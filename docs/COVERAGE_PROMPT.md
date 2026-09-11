# Prompt: رفع تغطية الاختبارات إلى 90% — مهام المساعد

> إشارة دائمة للمساعد الآلي: عند بدء أي عمل على التغطية، اقرأ هذا الملف كاملاً أولاً ولا تتجاوز أي بند منه.

---

You are working on a Flask SaaS e-school platform ("azad-e-school-palestine"). The goal is to raise **real** test coverage to **90%** and enforce it. Current coverage is ~71.5% overall (lines 75.7%, branches 54.6%). Do NOT write superficial/placeholder tests — every test must exercise real code paths and assert real behavior.

## 1. Project facts you must respect
- Backend: Flask + SQLAlchemy (`app/`), modules under `app/modules/<name>/routes.py`, business logic under `app/services/`, shared logic under `app/core/`.
- Frontend JS: `app/static/js`, tested with **Vitest** (`tests/js/*.test.js`, `vitest.config.js`).
- E2E: Playwright (`tests/e2e/*.spec.js`, `playwright.config.js`).
- Load: Locust (`tests/load/locustfile.py`).
- Python tests: pytest (`tests/`).
- Quality gate (always run after changes, commands verbatim):
  ```
  .venv\Scripts\python.exe -m pytest tests -q
  .venv\Scripts\python.exe -m ruff check app config.py run.py
  .venv\Scripts\python.exe -m ruff format --check app config.py run.py
  .venv\Scripts\python.exe -m mypy app config.py run.py
  npx biome check app/static/js
  ```
- Architecture rules (non-negotiable): DB writes go through `tx(...)` in `app/core/db.py`; tenant queries go through `scope_by_school`/`tenant_scope`; role checks only via `role_required` (app/core/permissions.py). Read `AGENTS.md` fully before starting.

## 2. Raise the threshold
- Edit `.coveragerc`: change `fail_under = 70` to `fail_under = 90`.
- Remove the `omit` for `app/core/__init__.py` and `app/services/__init__.py` only if you can actually cover them; otherwise keep them omitted.
- Ensure the CI config (`.github/workflows/`) runs pytest with coverage AND fails the build on `< 90`. It must also still run ruff/mypy/biome and the JS/e2e suites.

## 3. Coverage targets (real tests, priority order)
Target the known low-coverage areas first — biggest impact on the total:
1. `app/core/api_auth.py` (4%) and `app/core/openapi.py` (21%) — security & API auth.
2. `app/core/permissions.py` (37%) and `app/core/rls.py` (44%) — role checks + tenant row-level security; cover every branch (allow/deny) for all roles.
3. `app/tasks/` (grading 10%, notifications 13%, `__init__` 17%, video 52%, reports 53%) — isolate tasks and test each with an in-memory/`EagerResult` Celery backend or direct function invocation with dependencies mocked at the boundary only.
4. `app/modules/media/routes.py` (22%) and `app/modules/ai/routes.py` (33%) — uploads and AI endpoints, both success and failure paths.
5. `app/modules/payments/routes.py` (55%), `app/services/payments.py` (61%), `app/services/invoice.py` (64%), `app/services/wallet_service.py` (74%).
6. `app/modules/tutoring`, `schools`, `grades`, `content`, `admin` routes — fill the uncovered branches (error handling, permission denials, not-found, invalid input).
7. `app/services/ai.py` (54%), `rag_service.py` (46%), `quiz_ai_service.py` (57%) — mock only the external LLM/embedding clients, assert the service logic itself.
8. Frontend: expand `tests/js/*.test.js` for all modules in `app/static/js` (charts, forms, quiz, search, tour, ai-chat, bulk, api, theme, ui, index). Add missing unit tests for pure functions, state handling, and DOM interactions (jsdom environment with `setup.js`).
9. Static/assert assets where relevant: add a lightweight sanity test that critical templates render expected elements and that shared macros are reused (no inline styles), matching the existing `test_css_architecture.py` / `test_content_reuse.py` conventions.
10. Keep branch coverage in mind: for every `if/elif/except` you touch, add a test for each branch. Current branch coverage (54.6%) must rise proportionally toward line coverage.

## 4. Split the work into small, self-contained GitHub batches (MOST IMPORTANT)
Do NOT create one giant dump. Break the entire effort into **separate logical units**, each delivered as its own focused PR/commit so CI stays fast and reviewable. Suggested split (adapt as needed):

- **Batch 1 — Core/security:** `api_auth`, `openapi`, `permissions`, `rls`. PR title: `test(core): cover api_auth/permissions/rls/openapi`
- **Batch 2 — Tasks layer:** `tasks/grading`, `tasks/notifications`, `tasks/__init__`, `tasks/video`, `tasks/reports`.
- **Batch 3 — Media/AI routes:** `media`, `ai` routes + `services/ai`.
- **Batch 4 — RAG & quiz AI:** `rag_service`, `quiz_ai_service`, `ai` service remainder.
- **Batch 5 — Payments/finance:** `payments` routes + `services/payments` + `invoice` + `wallet_service` + `revenue`.
- **Batch 6 — School modules routes:** `schools`, `tutoring`, `grades`, `content`, `family`, `progress`.
- **Batch 7 — Admin routes:** `admin` (largest file; split by feature area into sub-commits).
- **Batch 8 — Frontend JS:** one PR per JS feature area (charts, forms, quiz, search, tour, ai-chat, bulk, api, theme, ui).
- **Batch 9 — Threshold & CI:** bump `.coveragerc` to 90, wire CI coverage gate, and add the final assertion/template sanity tests.

Rules for every batch:
- Each PR must be green on its own (pytest + ruff + mypy + biome + vitest + playwright).
- Run the full coverage report (`coverage report`) after each batch and report the new overall % in the PR description.
- Do not merge a batch until it passes `fail_under` relative to its own added tests.
- Ensure no test is skipped/xfail unless there is a documented, real blocker with a tracking note.

## 5. Acceptance criteria (definition of done)
- `fail_under = 90` in `.coveragerc` and `coverage report` shows **≥ 90%** overall with branch coverage meaningfully improved.
- All quality commands above pass in CI.
- Work delivered as a sequence of small, independent PRs (not one monolith).
- Every test asserts real behavior; no assertion-less or tautological tests.

Start with Batch 1. Do not modify production code just to game coverage — if untestable dead code exists, flag it for a separate cleanup decision instead of adding throwaway tests.
