# إعداد API الذكاء الاصطناعي

القالب: `.env` (منسوخ من `.env.example`)

المتغيرات المطلوبة (من الكود الفعلي):
- `AI_API_KEY` → `services/ai.py` سطر 53 (`AiConfig.api_key`)
- `AI_MODEL` → `services/ai.py` سطر 54 (افتراضي `gpt-4o-mini`)
- `AI_MAX_TOKENS`, `AI_TEMPERATURE`, `AI_MAX_RPM`, `AI_MAX_TPM`, `AI_MONTHLY_BUDGET_USD`
- `OPENAI_API_KEY` أو نفس `AI_API_KEY` → `rag_service.py` سطر 77-78 (`_get_embedding_client` لـ `text-embedding-3-small`, 1536 بُعد)
- `RAG_EMBEDDING_MODEL` (اختياري، افتراضي `text-embedding-3-small`)
- `RAG_DISABLE_EMBEDDINGS=1` (اختياري — لتعطيل embeddings الكثيفة والاعتماد على TF-IDF فقط)

مثال `.env` مُحدَّث:
AI_API_KEY=sk-your-real-key-here
AI_MODEL=gpt-4o-mini
OPENAI_API_KEY=%AI_API_KEY%
RAG_EMBEDDING_MODEL=text-embedding-3-small
