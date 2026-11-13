# Azad E-School v2.0 — "The Future Frontier" Roadmap

Vision: transform Azad into an autonomous, hyper-scalable, AI-native educational ecosystem
without compromising stability, RLS multi-tenancy, double-entry ledger immutability, or 100% coverage.

## Phase A — ORM Scalability (N+1 Zero Tolerance)
- [x] Query counter utility: `app/core/query_counter.py` (before_cursor_execute event counter)
- [ ] Audit admin/analytics/grading list endpoints → `selectinload`/`joinedload`
- [ ] Query-count regression tests per endpoint (threshold assertions)
- [ ] Redis-backed cache (already memory+Redis in `app/core/cache.py`); event-driven invalidation hooks on writes

## Phase B — AI-Native Pedagogy
- [x] Multi-model AI router: `app/services/ai_router.py` (fallback, budget cap, semantic cache)
- [ ] Adaptive learning engine: student profiling from quiz performance → difficulty adjustment + RAG remedial content
- [ ] Comprehension & sentiment analytics: engagement/submission processing → early-warning metrics

## Phase C — Offline-First PWA
- [x] Versioned service worker `app/static/sw.js` (offline fallback + static cache)
- [ ] Background sync queue for offline quiz submissions
- [ ] Optimistic UI updates + conflict resolution on reconnect

## Phase D — Global Scale
- [ ] Read/write DB splitting via SQLAlchemy bind keys (analytics → read replica)
- [ ] Materialized views + scheduled ETL aggregations for executive dashboards
- [ ] Backward-compatible Alembic patterns for zero-downtime rolling deploys

## Phase E — A11y & I18n Parity
- [ ] axe-core integration in Playwright E2E (RTL Arabic views)
- [ ] Complete en Babel translations (extract/update/compile + fill)

## Execution order
A → B → C → D → E. Each phase must land with unit/integration/branch tests and pass
ruff/mypy/biome before merge. PG-dependent verification requires a stable PostgreSQL instance.
EOF