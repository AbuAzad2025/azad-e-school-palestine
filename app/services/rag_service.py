"""RAG (Retrieval-Augmented Generation) — School-scoped AI Tutor.

P6-01: Ingestion pipeline extracts, chunks, and embeds lesson content.
P6-02: Retrieval scoped strictly to school_id (no cross-tenant leakage).
P6-03: Simple TF-IDF + cosine similarity (no external vector DB required).
P6-04: Fallback to direct LLM when RAG context is insufficient.

Usage:
    # Ingest lesson content
    ingest_lesson_for_rag(lesson_id=10, school_id=1)

    # Query the RAG tutor
    answer, context = query_school_rag_tutor(school_id=1, student_id=42, question="What is photosynthesis?")
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter

from flask import current_app

from app.core.logging import get_logger
from app.extensions import db

logger = get_logger(__name__)

# Chunking parameters
_CHUNK_SIZE = 500  # characters per chunk
_CHUNK_OVERLAP = 50  # overlap between chunks


class RAGChunk:
    """A text chunk with metadata for retrieval."""

    __slots__ = ("text", "lesson_id", "school_id", "chunk_index", "source", "embedding")

    def __init__(
        self,
        text: str,
        lesson_id: int,
        school_id: int,
        chunk_index: int,
        source: str = "lesson",
        embedding: list[float] | None = None,
    ):
        self.text = text
        self.lesson_id = lesson_id
        self.school_id = school_id
        self.chunk_index = chunk_index
        self.source = source
        # P3-RAG-01: متجه كثيف اختياري — None يعني التراجع لـ TF-Cosine
        self.embedding = embedding


# In-memory chunk store (production: use pgvector or dedicated vector DB)
_chunk_store: dict[int, list[RAGChunk]] = {}  # school_id -> [chunks]

# ─── P3-RAG-01: Hybrid embeddings layer ──────────────────────────────
# عند توفر مفتاح API نستخدم embeddings كثيفة (دلالية)؛ عند الفشل أو
# غياب المفتاح يعمل المسترجع TF-Cosine القديم بدون أي تأثير وظيفي.
_EMBED_DIM = 1536  # text-embedding-3-small / default OpenAI-compatible
_embedder_cache: dict[str, object] = {}


def _embeddings_enabled() -> bool:
    """هل embeddings مفعّلة؟ (مفتاح + علم بيئي، تعطيل اختياري)."""
    if os.getenv("RAG_DISABLE_EMBEDDINGS", "0") == "1":
        return False
    return bool(current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", ""))


def _get_embedding_client():
    """عميل OpenAI-compatible واحد لكل عملية (يُخزّن لكل app)."""
    api_key = str(current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", ""))
    api_base = str(current_app.config.get("OPENAI_API_BASE") or "https://openrouter.ai/api/v1")
    key_id = f"{api_base}:{api_key[:8]}"
    if key_id in _embedder_cache:
        return _embedder_cache[key_id]
    try:
        from openai import OpenAI

        client: object = OpenAI(api_key=api_key, base_url=api_base, timeout=15)
    except ImportError:
        # openai غير مثبّت — استخدم requests مباشرة على /embeddings
        client = ("requests", api_key, api_base)
    _embedder_cache[key_id] = client
    return client


def _embed_texts_remote(texts: list[str]) -> list[list[float]] | None:
    """حساب متجهات عبر API — يعيد None عند أي فشل (fallback تلقائي)."""
    if not texts:
        return []
    model = os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-3-small")
    try:
        client = _get_embedding_client()
        if isinstance(client, tuple):  # requests path
            import requests

            _, api_key, api_base = client
            resp = requests.post(
                f"{api_base}/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "input": texts},
                timeout=15,
            )
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            return [d["embedding"] for d in data]
        result = client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in result.data]
    except Exception as exc:  # noqa: BLE001 — أي فشل → TF-Cosine
        logger.warning("rag_embeddings_failed_fallback_tf", error=str(exc)[:200])
        return None


def _tokenize(text: str) -> list[str]:
    """Simple Arabic/English tokenizer."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = text.split()
    # Remove very short tokens
    return [t for t in tokens if len(t) > 1]


def _compute_tf(tokens: list[str]) -> dict[str, float]:
    """Compute term frequency."""
    counts = Counter(tokens)
    total = len(tokens) if tokens else 1
    return {word: count / total for word, count in counts.items()}


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Compute cosine similarity between two term-frequency vectors."""
    common = set(vec_a.keys()) & set(vec_b.keys())
    if not common:
        return 0.0

    dot = sum(vec_a[k] * vec_b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _chunk_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start += chunk_size - overlap
    return chunks


def ingest_lesson_for_rag(lesson_id: int, school_id: int) -> tuple[int, str | None]:
    """Ingest a lesson's content into the RAG chunk store.

    Extracts text from lesson body_html and attachment metadata,
    chunks it, and stores it indexed by school_id.

    Args:
        lesson_id: Target lesson.
        school_id: School (for tenancy isolation).

    Returns:
        (chunk_count, error_or_none)
    """
    from app.models.content import Lesson

    lesson = db.session.get(Lesson, lesson_id)
    if not lesson:
        return 0, "Lesson not found"

    # Extract text content
    text_parts = []
    if lesson.title:
        text_parts.append(f"Title: {lesson.title}")
    if lesson.body_html:
        # Strip HTML tags for plain text extraction
        clean = re.sub(r"<[^>]+>", " ", lesson.body_html)
        clean = re.sub(r"\s+", " ", clean).strip()
        text_parts.append(clean)

    full_text = "\n".join(text_parts)
    if not full_text.strip():
        return 0, "No text content in lesson"

    # Chunk the text
    chunks = _chunk_text(full_text)

    # P3-RAG-01: حاول حساب embeddings دلالية لكل القطع دفعة واحدة؛
    # عند الفشل تبقى None فيعمل المسترجع TF-Cosine كالمعتاد.
    embeddings: list[list[float]] | None = None
    try:
        with current_app.app_context():
            if _embeddings_enabled():
                embeddings = _embed_texts_remote(chunks)
    except Exception:  # noqa: BLE001
        embeddings = None

    # Store chunks
    rag_chunks = [
        RAGChunk(
            text=chunk,
            lesson_id=lesson_id,
            school_id=school_id,
            chunk_index=i,
            source="lesson",
            embedding=embeddings[i] if embeddings and i < len(embeddings) else None,
        )
        for i, chunk in enumerate(chunks)
    ]

    # Add to chunk store (append, don't replace)
    if school_id not in _chunk_store:
        _chunk_store[school_id] = []

    # Remove old chunks for this lesson
    _chunk_store[school_id] = [c for c in _chunk_store[school_id] if c.lesson_id != lesson_id]
    _chunk_store[school_id].extend(rag_chunks)

    logger.info(
        "rag_ingestion_completed",
        lesson_id=lesson_id,
        school_id=school_id,
        chunk_count=len(rag_chunks),
    )

    return len(rag_chunks), None


def _cosine_dense(vec_a: list[float], vec_b: list[float]) -> float:
    """تشابه جيبي للمتجهات الكثيفة (embeddings)."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    na = math.sqrt(sum(a * a for a in vec_a))
    nb = math.sqrt(sum(b * b for b in vec_b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def retrieve_relevant_chunks(
    school_id: int,
    question: str,
    top_k: int = 5,
) -> list[RAGChunk]:
    """Retrieve the most relevant chunks for a question.

    P3-RAG-01: هجين — إن وُجدت embeddings مخزّنة للقطع تُستخدم (دلالية)،
    مع دمج درجة TF-Cosine كمرجح ثانوي؛ وإن لا فتُنفّذ TF-Cosine وحدها.
    كلا المسارين مقيّد بـ school_id (لا تسريب بين المستأجرين).

    Args:
        school_id: School (tenancy filter).
        question: User's question.
        top_k: Number of chunks to return.

    Returns:
        List of relevant chunks, ordered by relevance.
    """
    school_chunks = _chunk_store.get(school_id, [])
    if not school_chunks:
        return []

    # Tokenize the question (TF path)
    question_tokens = _tokenize(question)
    question_tf = _compute_tf(question_tokens)

    # P3-RAG-01: dense path — إن كانت كل القطع تحمل embeddings نحسب
    # متجه السؤال مرة واحدة ونستخدم التشابه الكثيف.
    dense_available = all(c.embedding for c in school_chunks)
    question_vec: list[float] | None = None
    if dense_available:
        try:
            with current_app.app_context():
                if _embeddings_enabled():
                    vecs = _embed_texts_remote([question])
                    question_vec = vecs[0] if vecs else None
        except Exception:  # noqa: BLE001
            question_vec = None

    # Score each chunk
    scored = []
    for chunk in school_chunks:
        if dense_available and question_vec is not None and chunk.embedding:
            similarity = _cosine_dense(question_vec, chunk.embedding)
            # مرجّح ثانوي معجمي لتحسين الاسترجاع للمصطلحات الدقيقة
            chunk_tf = _compute_tf(_tokenize(chunk.text))
            lexical = _cosine_similarity(question_tf, chunk_tf)
            similarity = (0.7 * similarity) + (0.3 * lexical)
        else:
            chunk_tf = _compute_tf(_tokenize(chunk.text))
            similarity = _cosine_similarity(question_tf, chunk_tf)
        if similarity > 0.01:  # Minimum threshold
            scored.append((similarity, chunk))

    # Sort by relevance (descending)
    scored.sort(key=lambda x: x[0], reverse=True)

    return [chunk for _, chunk in scored[:top_k]]


def query_school_rag_tutor(
    school_id: int,
    student_id: int,
    question: str,
) -> tuple[dict | None, str | None]:
    """Query the RAG tutor for a school-scoped answer.

    Pipeline:
        1. Retrieve relevant chunks from school's content
        2. Build context from top chunks
        3. Query LLM with context + question
        4. Return structured answer

    Args:
        school_id: School (tenancy enforced).
        student_id: Asking student.
        question: Student's question.

    Returns:
        ({answer, sources, confidence}, error_or_none)
    """
    from app.core.logging import get_correlation_id

    logger.info(
        "rag_query_started",
        school_id=school_id,
        student_id=student_id,
        question_length=len(question),
        correlation_id=get_correlation_id(),
    )

    # Retrieve relevant chunks
    chunks = retrieve_relevant_chunks(school_id, question, top_k=5)

    if not chunks:
        # No relevant content found — direct LLM fallback
        return _fallback_llm_query(question, school_id, student_id)

    # Build context
    context_parts = []
    sources = []
    for chunk in chunks:
        context_parts.append(chunk.text)
        sources.append(
            {
                "lesson_id": chunk.lesson_id,
                "chunk_index": chunk.chunk_index,
                "preview": chunk.text[:100],
            }
        )

    context = "\n\n---\n\n".join(context_parts)

    # Query LLM with context
    try:
        answer = _call_llm_with_context(question, context, school_id)
        return {
            "answer": answer,
            "sources": sources,
            "confidence": "high" if len(chunks) >= 3 else "medium",
            "method": "rag",
        }, None
    except Exception as exc:
        logger.exception("rag_llm_query_failed", school_id=school_id)
        return None, f"AI query failed: {exc}"


def _fallback_llm_query(
    question: str,
    school_id: int,
    student_id: int,
) -> tuple[dict | None, str | None]:
    """Fallback to direct LLM when no RAG context is available."""
    try:
        answer = _call_llm_with_context(question, "", school_id)
        return {
            "answer": answer,
            "sources": [],
            "confidence": "low",
            "method": "direct_llm",
        }, None
    except Exception as exc:
        return None, f"AI query failed: {exc}"


def _call_llm_with_context(question: str, context: str, school_id: int) -> str:
    """Call LLM API with question and context.

    Supports OpenAI-compatible APIs (OpenRouter, DeepSeek, etc.)
    """
    api_key = current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    api_base = current_app.config.get("OPENAI_API_BASE", "https://openrouter.ai/api/v1")
    model = current_app.config.get("AI_MODEL", "deepseek/deepseek-chat")

    if not api_key:
        return _generate_offline_response(question, context)

    try:
        import requests

        system_prompt = (
            "You are an AI tutor for Palestinian K-12 curriculum. "
            "Language: Arabic (primary) / English. "
            "Style: Encouraging, step-by-step, pedagogical. "
            "If the context contains relevant information, use it. "
            "If not, use your general knowledge but note it's not from the school's materials."
        )

        messages = [{"role": "system", "content": system_prompt}]
        if context:
            messages.append(
                {
                    "role": "user",
                    "content": f"Context from school materials:\n\n{context}\n\nQuestion: {question}",
                }
            )
        else:
            messages.append({"role": "user", "content": question})

        response = requests.post(
            f"{api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": 1000,
                "temperature": 0.7,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception:
        return _generate_offline_response(question, context)


def _generate_offline_response(question: str, context: str) -> str:
    """Generate a basic offline response when LLM is unavailable."""
    if context:
        return (
            f"بناءً على محتوى الدروس المتاح، وجدت معلومات قد تساعد:\n\n"
            f"{context[:500]}\n\n"
            f"يرجى مراجعة الدرس للتفاصيل الكاملة."
        )
    return "عذراً، لا يمكنني الإجابة على هذا السؤال حالياً. يرجى مراجعة معلمك أو المحاضرة المباشرة."


def get_rag_stats(school_id: int) -> dict:
    """Get RAG statistics for a school."""
    chunks = _chunk_store.get(school_id, [])
    lesson_ids = set(c.lesson_id for c in chunks)
    return {
        "school_id": school_id,
        "total_chunks": len(chunks),
        "lessons_indexed": len(lesson_ids),
        "lesson_ids": sorted(lesson_ids),
    }
