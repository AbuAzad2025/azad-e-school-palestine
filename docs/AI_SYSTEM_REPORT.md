# 🧠 AI System Report — Azad E-School Platform

**Scope:** `app/services/ai.py`, `app/services/rag_service.py`, `app/services/quiz_ai_service.py`, `app/models/ai.py`, `app/models/tenant.py`, `app/modules/ai/`
**Generated:** 2026-09-10 · Audit method: direct code inspection (no assumptions)

---

## 1. Executive Overview of AI Architecture

The platform ships **three independent AI services** plus one governance model. They share no base class; each has its own client strategy, config surface, and fallback doctrine. All are **offline-safe by design** — every external call is wrapped so that missing keys, missing libraries, or network failure degrade to a deterministic local path instead of a 500.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        HTTP Layer (app/modules/ai/)                 │
│   /ai/chat · /ai/chat/stream (SSE) · /ai/grade/suggest              │
│   /ai/questions/generate · /ai/usage/stats                          │
└──────────────┬──────────────────────────────┬───────────────────────┘
               │                              │
   ┌───────────▼───────────┐      ┌───────────▼────────────┐
   │  AiService (ai.py)    │      │  RAG engine            │
   │  singleton, async     │      │  (rag_service.py)      │
   │  OpenAI SDK (Async)   │      │  library-only, sync    │
   │  + SSE streaming      │      │  requests-based LLM    │
   │  + RateLimiter        │      │  + hybrid embeddings   │
   │  + BudgetTracker      │      │  + TF-Cosine fallback  │
   └───────────┬───────────┘      └───────────┬────────────┘
               │                              │
   ┌───────────▼───────────┐      ┌───────────▼────────────┐
   │ quiz_ai_service.py    │      │  Governance            │
   │ library-only, sync    │      │  RateLimiter · Budget  │
   │ requests-based LLM    │      │  AiUsageLog · TenantQu │
   │ + offline quiz gen    │      │  (partial enforcement) │
   └───────────────────────┘      └────────────────────────┘
```

### Provider integration matrix

| Service | Client library | Default base URL | Default model | Transport | Async? |
|---|---|---|---|---|---|
| `AiService` | `openai.AsyncOpenAI` (soft import, `OPENAI_AVAILABLE` flag) | api.openai.com (SDK default) | `gpt-4o-mini` (`AI_MODEL`) | SDK | ✅ async generators |
| RAG embeddings + LLM | `openai.OpenAI` → **fallback to raw `requests`** on ImportError | `https://openrouter.ai/api/v1` (`OPENAI_API_BASE`) | `deepseek/deepseek-chat` (`AI_MODEL`) | SDK or REST | ❌ sync |
| `quiz_ai_service` | raw `requests` | `https://openrouter.ai/api/v1` | `deepseek/deepseek-chat` | REST | ❌ sync |

### Configuration parameters

| Variable | Consumer | Default | Purpose |
|---|---|---|---|
| `AI_API_KEY` | `AiConfig.api_key` (ai.py) | `""` | Master switch for the real LLM in `AiService` |
| `AI_MODEL` | `AiConfig.model`, RAG `_call_llm_with_context`, quiz `_call_llm` | `gpt-4o-mini` / `deepseek/deepseek-chat` | Model selection |
| `AI_MAX_TOKENS` | `AiConfig.max_tokens` | `4000` | Per-completion cap (chat) |
| `AI_TEMPERATURE` | `AiConfig.temperature` | `0.3` | Sampling temperature |
| `AI_MAX_RPM` | `RateLimiter.max_rpm` | `60` | Requests/minute sliding window |
| `AI_MAX_TPM` | `RateLimiter.max_tpm` | `100000` | Tokens/minute sliding window |
| `AI_MONTHLY_BUDGET_USD` | `BudgetTracker.monthly_budget` | `100.0` | Hard monthly USD cap |
| `OPENAI_API_KEY` | RAG + quiz services (`current_app.config` → env) | `""` | Gate for OpenRouter-compatible calls |
| `OPENAI_API_BASE` | RAG + quiz services | `https://openrouter.ai/api/v1` | OpenAI-compatible endpoint |
| `RAG_EMBEDDING_MODEL` | `_embed_texts_remote` | `text-embedding-3-small` | Dense embedding model |
| `RAG_DISABLE_EMBEDDINGS` | `_embeddings_enabled()` | `"0"` | Kill-switch for the dense path |
| `_EMBED_DIM` (const) | rag_service.py | `1536` | Expected embedding dimensionality |

> ⚠️ **Config split:** `AiService` reads `AI_API_KEY`, while RAG/quiz read `OPENAI_API_KEY`. Setting only one key leaves two of the three services on their offline paths. Recommended: unify on one variable (see §7).

---

## 2. Local Hybrid RAG Engine (`app/services/rag_service.py`)

### 2.1 Ingestion pipeline — `ingest_lesson_for_rag(lesson_id: int, school_id: int) -> tuple[int, str | None]`

```
Lesson (body_html)
  → strip HTML tags (re.sub(r"<[^>]+>", " "))
  → prepend "Title: {lesson.title}"
  → _chunk_text(): 500-char chunks, 50-char overlap
  → [optional] _embed_texts_remote(chunks)  ← one batched call
  → RAGChunk(text, lesson_id, school_id, chunk_index, source="lesson", embedding)
  → _chunk_store[school_id]  (old chunks for this lesson_id evicted, new appended)
```

- Chunk store: **in-process dict** `_chunk_store: dict[int, list[RAGChunk]]` keyed by `school_id`. The module docstring explicitly marks pgvector as the production target.
- Partial-embedding tolerance: if the batch call succeeds but returns fewer vectors than chunks, the tail chunks store `embedding=None` and only those fall back to TF scoring.

### 2.2 Retrieval mechanics — `retrieve_relevant_chunks(school_id, question, top_k=5)`

**Hybrid scoring** (dense + lexical blend), strictly inside one school's partition:

| Path | Condition | Score |
|---|---|---|
| **Hybrid dense** | *all* school chunks carry embeddings **and** the question vector was obtained | `0.7 × cosine_dense(question_vec, chunk.embedding) + 0.3 × cosine_lexical(question_tf, chunk_tf)` |
| **TF-Cosine only** | no embeddings anywhere, or the question-vector call failed | `cosine_lexical(question_tf, chunk_tf)` |

- Tokenizer `_tokenize()`: lowercase, strip punctuation, drop 1-char tokens — works for Arabic and English alike.
- `_cosine_similarity()` operates on `Counter`-normalized term-frequency dicts; `_cosine_dense()` on float vectors with dimension-mismatch guard (returns 0.0).
- Relevance floor: `similarity > 0.01` to enter the ranked list; results sorted descending, truncated to `top_k`.

### 2.3 Multi-tenant isolation

Isolation is **structural, not filter-based**: chunks are stored in per-school lists (`_chunk_store[school_id]`), and every retrieval begins with `_chunk_store.get(school_id, [])`. A query from school B can never even *see* school A's vectors — there is no global pool to filter down from. Verified by tests in `tests/unit/test_branch_coverage_gaps.py` (school2 → 0 hits against school1 content).

### 2.4 Tutor workflow — `query_school_rag_tutor(school_id, student_id, question) -> tuple[dict | None, str | None]`

```
1. retrieve_relevant_chunks(school_id, question, top_k=5)
2. if chunks:
     context = "\n\n---\n\n".join(chunk texts)
     sources = [{lesson_id, chunk_index, preview[:100]}, ...]
     answer  = _call_llm_with_context(question, context, school_id)
     return {answer, sources, confidence: "high" if ≥3 chunks else "medium", method: "rag"}
3. else:
     _fallback_llm_query() → direct LLM, sources=[], confidence="low", method="direct_llm"
4. LLM failure at any step → (None, "AI query failed: …")
```

`_call_llm_with_context()` posts to `{OPENAI_API_BASE}/chat/completions` with a Palestinian K-12 tutor system prompt (Arabic primary), `max_tokens=1000`, `temperature=0.7`, 30s timeout. Failure lands in `_generate_offline_response()`, which returns the top-500-chars of retrieved context as a study pointer, or an apology directing the student to their teacher.

### 2.5 Introspection — `get_rag_stats(school_id) -> dict`

Returns `{school_id, total_chunks, lessons_indexed, lesson_ids}` — per-tenant index health for dashboards.

---

## 3. Automated Content & Quiz Generation (`app/services/quiz_ai_service.py`)

### 3.1 Pipeline — `generate_quiz_from_lesson(lesson_id, question_count=5, difficulty="medium", created_by=None) -> tuple[Quiz | None, str | None]`

```
Step 1  Extract:  db.session.get(Lesson, lesson_id) → _extract_lesson_text()
                  (title + HTML-stripped body; empty → (None, "لا يوجد محتوى نصي في الدرس."))
Step 2  Prompt:   _QUIZ_PROMPT_TEMPLATE.format(count, difficulty, lesson_content[:3000])
                  Strict contract: ONLY a JSON array; per-item schema
                  question_text / question_type (mcq|true_false|fill_blank) /
                  options / correct_answer / marks / explanation
                  + difficulty guidelines (easy=recall, medium=comprehension, hard=application)
Step 3  LLM:      _call_llm() → POST {OPENAI_API_BASE}/chat/completions,
                  system "expert exam writer… ONLY valid JSON", max_tokens=2000,
                  temperature=0.8, timeout=60.  Exception → _generate_offline_quiz()
Step 4  Parse:    _parse_llm_response()
                    a) strip ``` fences
                    b) json.loads; if dict-not-list → reject
                    c) validate each item has question_text + correct_answer
                    d) on JSONDecodeError → regex r"\[.*\]" (DOTALL) salvage attempt
                    e) no valid items → None → (None, "فشل في تحليل استجابة الذكاء الاصطناعي.")
Step 5  Persist:  tx(_create_quiz)  ← ATOMIC
                    Quiz(class_id=lesson.class_id, title="اختبار تلقائي: {title}",
                         duration_min=count×2, attempts_allowed=3, shuffle=True,
                         show_answers_after=True, status="draft", created_by,
                         proctoring off, max_tab_switches=5)
                    + N × Question(quiz_id, …, difficulty=_map_difficulty())
                  TxError → (None, str); unexpected → (None, "Database error: …")
```

Safety properties: the quiz is born as **`status="draft"`** (a human publishes it — AI cannot self-publish content to students), difficulty is whitelisted via `_map_difficulty()` (`easy→1, medium→2, hard→3`, default 2), and the whole Quiz+Questions write is one transaction — a malformed question can never leave an orphaned quiz row.

### 3.2 Offline fallback generator — `_generate_offline_quiz(prompt) -> str`

When `OPENAI_API_KEY` is unset **or the HTTP call raises**, the service synthesizes a deterministic 2-question quiz by extracting the lesson title from the prompt (`re.search(r"العنوان:\s*(.+)")`):

1. MCQ — "ما هو الموضوع الرئيسي في درس '{title}'؟" with 4 options, correct answer = the title-derived option, `marks=1`.
2. True/False — "هل درس '{title}' مفيد للطلاب؟" → "True", `marks=1`.

The returned JSON feeds the *same* parser and the same `tx()` persistence path as LLM output — so offline quizzes are indistinguishable to the persistence layer and always produce a usable draft.

### 3.3 Integration status (honest finding)

`generate_quiz_from_lesson` has **no HTTP route yet** — it is a library service ready to be wired into a teacher's quiz-builder action. `AiService.generate_questions()` (topic-based, not lesson-based) is the currently exposed generation endpoint.

---

## 4. Governance, Rate Limiting & Cost Tracking

### 4.1 Rate limiting — `RateLimiter` (ai.py)

- **Algorithm:** 60s sliding window over two deques: `request_times` (timestamps) and `token_usage` (`(timestamp, tokens)` tuples).
- `can_proceed(estimated_tokens=1000)`: prunes expired entries (`_clean_old()`), then rejects when `len(request_times) >= max_rpm` or `Σ token_usage + estimated > max_tpm`. Returns `(bool, reason)`.
- `record_request(tokens_used)`: appends `(now, tokens)` to both windows — called from `_record_usage()` **after** each successful real API call.
- Instantiated lazily as a **class-level singleton** (`AiService._rate_limiter`) on first `AiService()` construction — one budget window per process, not per request.

### 4.2 Monthly budget — `BudgetTracker` (ai.py)

- `_ensure_current_month()` auto-resets `_monthly_spent` when the calendar month rolls over (`datetime.utcnow()` month boundary).
- `can_spend(estimated_cost)` pre-flight check in `_check_limits()`; `record_spending(cost)` accrues after each call.
- `get_usage()` → `{spent_usd, budget_usd, remaining_usd, usage_percent}` — surfaced through `/ai/usage/stats` and `get_usage_stats()["budget"]`.
- Enforcement is **hard-cap**: `_check_limits()` blocks the call and returns `{"error": "Budget: Monthly budget exceeded: $100.00", "fallback": …}` — with the mock grade/questions attached so the UX degrades instead of dying.

### 4.3 Cost estimation — `MODEL_PRICING`

Per-1K-token USD table for 4 OpenAI models (`gpt-4o` 0.005/0.015, `gpt-4o-mini` 0.00015/0.0006, `gpt-4-turbo` 0.01/0.03, `gpt-3.5-turbo` 0.0005/0.0015, input/output). Unknown models fall back to `gpt-4o-mini` pricing. `_estimate_cost(prompt_tokens, completion_tokens)` = linear input+output cost.

### 4.4 Tier-based allowances — `TenantQuota` (app/models/tenant.py)

| Field | Type | Notes |
|---|---|---|
| `school_id` | FK schools.id, unique | one quota row per school |
| `tier` | String(20), default `free` | free / basic / pro / enterprise |
| `ai_enabled` | Boolean, default `False` | feature flag |
| `max_ai_tokens_monthly` | Integer, default `0` | token allowance |
| `max_students / max_teachers / max_classes / max_storage_mb` | Integer | non-AI resource caps |

Tier presets in `app/services/tenant.py` (`TIER_DEFAULTS`): `free`→0, `basic`→0, `pro`→100,000, `enterprise`→9,999,999 monthly AI tokens. Helpers: `get_quota(school_id)` (auto-provisions the default row), `set_tier(school_id, tier)`.

> ⚠️ **Governance gap (honest audit):** neither `ai_enabled` nor `max_ai_tokens_monthly` is consulted by `AiService._check_limits()` or any `/ai/*` route today. Platform-wide RPM/TPM/budget are enforced; **per-school AI gating is not yet wired**. Recommendation in §7.

### 4.5 Audit logging — `AiUsageLog` write path

`_record_usage(prompt_tokens, completion_tokens, user_id, action)` runs after every real API call:

1. records into the sliding windows (`record_request`),
2. accrues `BudgetTracker.record_spending(cost)`,
3. persists an `AiUsageLog` row via `tx()` with `user_id, model, prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd, action` (`chat` / `suggest_grade` / `generate_questions`).

Aggregation: `get_usage_stats(user_id=None, days=30)` computes totals, per-action and per-model breakdowns, plus live budget and rate-limit state.

---

## 5. Data Models & HTTP Endpoints

### 5.1 Tables (app/models/ai.py — all `PKMixin`: `id` PK, `created_at`, `updated_at`)

**`ai_sessions`**

| Column | Type | Constraints |
|---|---|---|
| `user_id` | FK `users.id` | NOT NULL, indexed |
| `class_id` | FK `classes.id` | nullable, indexed |
| `lesson_id` | FK `lessons.id` | nullable, indexed |
| `session_type` | Text | NOT NULL (e.g. `"student_helper"`) |
| `meta` | JSONB | nullable (stores model name for UI) |
| `messages` | relationship → `AiMessage` | `cascade="all, delete-orphan"`, `back_populates="session"` |

**`ai_messages`**

| Column | Type | Constraints |
|---|---|---|
| `session_id` | FK `ai_sessions.id` | NOT NULL, indexed |
| `role` | Text | NOT NULL (`user` / `assistant`) |
| `content` | Text | NOT NULL |
| `model` | Text | nullable |
| `tokens` | Integer | nullable |

**`ai_usage_logs`**

| Column | Type | Constraints |
|---|---|---|
| `user_id` | FK `users.id` `ON DELETE SET NULL` | nullable |
| `model` | Text | NOT NULL |
| `prompt_tokens` / `completion_tokens` / `total_tokens` | Integer | NOT NULL, default 0 |
| `estimated_cost_usd` | Float | NOT NULL, default 0.0 |
| `action` | Text | NOT NULL |
| `meta` | JSONB | nullable |

Relations: `users 1—N ai_sessions 1—N ai_messages`; `users 1—N ai_usage_logs` (SET NULL on user delete preserves cost history). `classes`/`lessons` optionally anchor a session to academic context.

> ⚠️ **Schema note:** none of the three tables carries `school_id`. Cost/usage is attributable per *user* only; per-school rollups require a join through `users.school_id`. Acceptable for user-level analytics, but a limitation for tenant billing (see §7).

### 5.2 HTTP endpoints (`app/modules/ai/`, blueprint `ai`, prefix `/ai`, registered in `app/__init__.py:226`)

| Method | Path | Guards | Purpose |
|---|---|---|---|
| GET | `/ai/chat` | `@login_required` | Chat page; loads all `student_helper` sessions with `selectinload(AiSession.messages)` (N+1-safe), renders `ai/chat.html` |
| POST | `/ai/chat/stream` | `@login_required` | **SSE streaming chat.** JSON body `{question, context?, class_id?, lesson_id?}`; empty question → 400. Bridges the async generator via a dedicated event loop inside `stream_with_context`; headers `Cache-Control: no-cache`, `X-Accel-Buffering: no` |
| POST | `/ai/chat` | `@login_required` | Non-streaming chat (`asyncio.run(ask_question)`) → `{question, answer, session_id}` |
| POST | `/ai/grade/suggest` | `@login_required` + `@role_required(teacher, school_admin)` | AI-suggested grading: `{student_answer, question_type, correct_answer?, rubric?}` → structured JSON (score/feedback/strengths) |
| POST | `/ai/questions/generate` | `@login_required` + `@role_required(teacher, school_admin)` | Topic-based exam generation; `count` clamped to 1–20 server-side → `{questions: [...]}` |
| GET | `/ai/usage/stats` | `@login_required` + `@role_required(school_admin)` | Usage/cost analytics, `?days=N` (default 30) |

RBAC posture: students can chat; only teachers/school-admins can generate content or request grade suggestions; only school-admins see cost analytics. `super_admin` passes `@role_required` via the standard hierarchy.

### 5.3 Internal service surface (non-HTTP)

| Call site | Signature |
|---|---|
| `AiService.start_session` | `(user_id, session_type, class_id=None, lesson_id=None) -> AiSession` (via `tx()`) |
| `AiService.log_message` | `(session_id, role, content) -> AiMessage` (via `tx()`) |
| `AiService.ask_question` / `ask_question_stream` | `(user_id, question, context, class_id, lesson_id)` → dict / SSE async generator |
| `AiService.suggest_grade` | `(student_answer, question_type, correct_answer=None, rubric=None, user_id=0) -> dict` |
| `AiService.generate_questions` | `(topic, count=5, question_types=None, difficulty="medium", user_id=0) -> list[dict]` |
| `ingest_lesson_for_rag` | `(lesson_id, school_id) -> tuple[int, str \| None]` |
| `retrieve_relevant_chunks` | `(school_id, question, top_k=5) -> list[RAGChunk]` |
| `query_school_rag_tutor` | `(school_id, student_id, question) -> tuple[dict \| None, str \| None]` |
| `generate_quiz_from_lesson` | `(lesson_id, question_count=5, difficulty="medium", created_by=None) -> tuple[Any, str \| None]` |

---

## 6. Resiliency & Offline Degradation Matrix

| Feature | API key set + healthy | Key missing | Library missing (`openai` not installed) | Network/API error | Rate-limited / over budget |
|---|---|---|---|---|---|
| **Chat (SSE)** | Real token-by-token stream from `AI_MODEL`; usage logged | `_mock_stream()` — keyword-routed Arabic tutor answers, chunked at 3 words / 20ms, same SSE protocol | Same mock path (`config.api_key` present but `OPENAI_AVAILABLE=False` → mock) | `except` in `ask_question_stream` → `{"error": …}` event + `[DONE]`; stream closes cleanly | `_check_limits()` inside `_real_stream` → error event; no tokens spent |
| **Chat (non-streaming)** | Full answer assembled from stream | Mock answer | Mock answer | Error event captured in answer stream | Error event |
| **Grade suggestion** | Real JSON grade (mcq/true_false/essay prompts, `response_format=json_object`) | `_mock_grade()` — randomized plausible scores + canned feedback | Mock path | `{"error": str(e), "fallback": mock}` | `{"error": msg, "fallback": mock}` |
| **Question generation** | Real questions from `AI_MODEL` | `_mock_generate_questions()` — deterministic typed questions (marks 2.0/1.0/5.0) | Mock path | `[{"error": …}] + mock list` | `[{"error": msg}] + mock list` |
| **RAG retrieval (dense)** | `text-embedding-3-small` via OpenAI-compatible endpoint; hybrid 0.7/0.3 scoring | TF-Cosine only | `requests`-based REST path instead of SDK | `_embed_texts_remote` → `None` → **TF-Cosine silently** (warn log) | n/a (embeddings bypass rate limiter — see §7) |
| **RAG retrieval (lexical)** | Always available — pure Python | ✅ works | ✅ works | ✅ works | ✅ works |
| **RAG tutor answer** | LLM answer with sources + confidence | `_generate_offline_response()` — returns retrieved context excerpt as study pointer | Same offline text | `_call_llm_with_context` catches → offline text | n/a |
| **RAG tutor (no context)** | Direct LLM, `confidence=low` | Apology text directing student to teacher | Same | Same | n/a |
| **Quiz generation** | Real parsed questions → draft Quiz | `_generate_offline_quiz()` → deterministic 2-question draft | REST path (no SDK dependency) | Same offline draft | n/a |
| **Usage stats** | Live DB aggregates + budget state | ✅ works (zeros for API usage) | ✅ works | ✅ works | ✅ works |

**Design invariants observed across the matrix:**
1. **No AI failure ever 500s a user-facing route** — every external boundary returns a typed fallback.
2. **SSE protocol is stable offline** — the mock emits identical `data: {"delta": …}` / `data: [DONE]` framing, so the frontend needs no mode switching.
3. **Writes never depend on the LLM** — mock/offline content still persists through the same `tx()` paths (sessions, messages, draft quizzes).
4. **Cost guards fire before network spend** — `_check_limits()` is a pre-flight, not a post-hoc audit.

---

## 7. Gaps & Recommendations (audit findings)

| # | Finding | Severity | Recommendation |
|---|---|---|---|
| 1 | `TenantQuota.ai_enabled` / `max_ai_tokens_monthly` never enforced on `/ai/*` | **High** | Add a per-school token check in `AiService._check_limits()`: resolve `school_id` from `current_user`, sum `AiUsageLog.total_tokens` for the current month, gate on quota; refuse when `ai_enabled=False` (403 or `fallback` payload) |
| 2 | `rag_service` and `quiz_ai_service` have zero production call sites | Medium | Wire `ingest_lesson_for_rag()` into lesson publish/save, expose `query_school_rag_tutor` in the chat stream (`context` already exists in the contract), add a teacher "Generate quiz from lesson" button |
| 3 | Config split: `AI_API_KEY` (ai.py) vs `OPENAI_API_KEY` (rag/quiz) | Medium | Single source of truth; deprecate one name or read both with fallback |
| 4 | `_chunk_store` is in-process memory — lost on restart, divergent across Gunicorn workers | Medium | Move to pgvector/Postgres table (already flagged in module docstring); embeddings are tenant-keyed and trivially persistable |
| 5 | `ai_sessions`/`ai_usage_logs` lack `school_id` | Medium | Add columns (migration) for direct tenant cost attribution and RLS alignment |
| 6 | RAG embeddings bypass `RateLimiter`/`BudgetTracker` (separate `requests` path) | Low | Route embedding + RAG LLM calls through the shared limiter or document the exclusion |
| 7 | `get_usage_stats` ignores `school_id` (user-level only) | Low | Join through `users.school_id` for admin-portal tenant rollups |

## 8. Test Coverage of AI Components

| Test file | Covers |
|---|---|
| `tests/test_pillars_3_4_5.py` | RAG ingestion/retrieval, tenancy isolation, quiz generation pipeline, offline fallbacks |
| `tests/unit/test_branch_coverage_gaps.py` | Embedding failure → TF fallback, LLM failure → offline answer, budget/limit branches |
| `tests/test_coverage_payments_ai.py` | `BudgetTracker.get_usage`, limit bounds, AI service paths |
| `tests/test_coverage_max.py`, `tests/test_coverage_services_massive.py`, `tests/test_squad2_all_services.py` | Service-level mocks of `AiService`, RAG helpers |

All listed suites green as of the latest full run (CI on `801ee67`).

---

*Report generated from source inspection; every behavioral claim above is traceable to the cited file and function. Line references drift with edits — trust file + symbol names.*
