# Azad E-School v2.0 — System Specification & Capability Inventory

> **Audience:** Principal Systems Architect / Code Auditor / Enterprise ERP Analyst
> **Stack:** Python 3.11 · Flask · SQLAlchemy · Alembic · PostgreSQL (RLS) · Jinja2 · Vanilla JS (ES modules) · Vitest · Playwright
> **Locale:** Arabic (RTL) primary / English · Multi-tenant SaaS · Palestinian curriculum
> **Version:** Azad First Edition — Azad Smart Systems · Ahmad Ghanam

---

## 1. Core Module & Business Logic Inventory

### 1.1 Authentication & RBAC (`app/modules/auth`, `app/services/auth.py`, `app/core/permissions.py`)
- **Implemented:** Setup wizard (first-run super_admin), registration, login (session + Bearer PAT), logout, forgot/reset password (tokenised), individual-subscriber registration, dashboard redirect by role.
- **RBAC:** `role_required(UserRole...)` decorator; composite guards `class_access_required`, `class_teach_required`, `parent_of_required` (`app/core/permissions.py`). Roles: `super_admin`, `school_admin`, `teacher`, `student`, `parent`.
- **Security:** argon2id password hashing (`hash_password`/`verify_password`), password-change audit stamp, email verification tokens, rate limiting (5/min on auth endpoints), CSRF, session cookie hardening (Talisman).
- **Data flow:** `User` ↔ `UserRoleLink` (multi-school membership) ↔ `School`.

### 1.2 Multi-Tenancy & RLS (`app/core/tenancy.py`, `app/core/rls.py`, migration `g1h2i3j4k5l6`…)
- **Tenant root:** `School` (no `school_id`). Every tenant-scoped table carries `school_id`.
- **Application layer:** `scope_by_school` / `tenant_scope` filters every query; hidden resources return 404 (not 403) to avoid existence leaks.
- **DB layer:** PostgreSQL Row-Level Security policies (`USING` + `WITH CHECK`), null-safe when GUC unset (`n7o8p9q0r1s2`), composite indexes for indirect-policy subqueries (`i3j4k5l6m7n8`), class-scoped/wallet/role-link coverage gap closed (`l5m6n7o8p9q0`).
- **Hybrid tenancy:** `UserRoleLink` allows one user in multiple schools; access constrained by session scope, not identity alone.
- **Platform scope:** `platform_scope()` context manager (`app/core/rls.py`) elevates for cross-tenant system writes (e.g. publishing subscription plans) inside a single transaction; rollback + GUC restore on exit. Depth tracking for nested scopes.
- **Transaction safety:** all writes via `tx(...)` (`app/core/db.py`) — single commit, rollback on error.

### 1.3 Wallets & Financial Ledger (`app/services/wallet_service.py`, `app/models/wallet.py`, `app/modules/wallet_api`, `wallet_ui`)
- **Double-entry** ledger with `Decimal`, immutable movements (corrections via counter-entries, never edits).
- **Idempotency keys** on every external flow (gateway payments, tutoring commission).
- **Rounding:** `ROUND_HALF_UP` to 2 decimals before transfer.
- **Tables:** `wallets` (school_id, user_id, currency, status), `wallet_transactions` (source/destination wallet, school_id, type, status, idempotency_key, transaction_hash, metadata JSONB), `wallet_topup_requests`.
- **Constraints:** unique `uq_wallet_school_user_currency`, `ck_wallet_tx_amount_nonneg`, `ck_wallet_tx_status`.

### 1.4 Billing & Subscriptions (`app/modules/billing`, `app/services/billing.py`, `app/models/billing.py`)
- **Implemented:** Subscription plans (per school or platform-wide with `school_id IS NULL` global coupons `w6x7y8z9a0b1`), subscriptions (student/parent payer, status lifecycle), manual payments (pending→approved/rejected/expired), payment receipts, discount codes, expiry cron (`expire-subscriptions`, `expire-pending-payments`), family payer billing (payer identity on subscriptions/manual payments `r1s2t3u4v5w6`), pending-payment TTL 24h (`AZ-P1-09`).
- **Tutoring payment dual confirmation** (`u4v5w6x7y8z9`): both parties must agree.
- **CLI:** `flask expire-subscriptions`, `flask expire-pending-payments`.

### 1.5 Academics & Grades (`app/modules/grades`, `app/services/gradebook.py`, `grade_calc.py`, `grade_appeals.py`, `report_card.py`, `rubric.py`)
- **Implemented:** Classes (`class_room`), subjects, grade categories/items/entries, grade appeals (pending-created index), rubrics (`rubric_criteria`, `rubric_grades`, `rubric_templates`), report cards, class grades summary, grade entry mark-range CHECK.
- **Tenant isolation:** `class_members` status, `grade_entries` item-id RLS index.

### 1.6 Assessments & Quizzes (`app/modules/assessment`, `app/services/assessment.py`, `question_bank.py`, `quiz_ai_service.py`, `quiz_stats.py`)
- **Implemented:** Quizzes with per-attempt question/option shuffling (`display_order` `m6n7o8p9q0r1`), quiz attempts, answers, proctoring logs, question bank (teacher/school scoped), AI-assisted quiz generation, quiz stats/analytics, absence-alert dedup log (`t3u4v5w6x7y8`).
- **Constraints:** `ck_rubric_grade_score_range`, `ck_student_progress_*`, quiz attempt indexes.

### 1.7 Attendance (`app/services/attendance.py`)
- **Implemented:** Attendance records (class/student/date), status CHECK, recorded_by tracking, absence alerts to parents (`send-absence-alerts` CLI), dedup log.

### 1.8 Tutoring (`app/modules/tutoring`, `app/services/tutoring.py`)
- **Implemented:** Tutor profiles (mode/video provider CHECKs), tutoring requests (mode/status CHECKs), sessions (payment status, video provider), commissions, payouts (tutor/status), auto-timeout of unconfirmed sessions (`tutoring-auto-timeout` CLI), dual confirmation.
- **Financial integration:** session completion writes tutor payout + platform commission in one transaction with idempotency.

### 1.9 Content & Lessons (`app/modules/content`, `app/services/content.py`)
- **Implemented:** Units, lessons, lesson attachments (kind CHECK), video progress (class/student/lesson indexes), offline downloads, announcements, assignments, submissions (assignment/student indexes).

### 1.10 Family (`app/modules/family`, `app/services/family.py`)
- **Implemented:** Family links (parent↔student), family link codes (unique code CITEXT, used_by), family payer billing.

### 1.11 Gamification (`app/modules/gamification`, `app/services/gamification.py`)
- **Implemented:** Gamification points/badges/leaderboards (module present).

### 1.12 AI (`app/modules/ai`, `app/services/ai.py`, `ai_usage.py`, `rag_service.py`, `quiz_ai_service.py`)
- **Implemented:** AI chat (streaming), usage logging (user/created_at indexes), budget tracking, RAG service, AI usage report CLI (`ai-usage-report` with budget threshold exit code).

### 1.13 Notifications & Messages (`app/modules/notifications`, `messages`, `app/services/messages.py`, `notification_preferences.py`)
- **Implemented:** In-app messages (parent/recipient/read indexes), notification preferences, email (Flask-Mail).

### 1.14 Calendar (`app/modules/calendar`, `app/services/calendar.py`)
- **Implemented:** Calendar events.

### 1.15 Individual Subscribers (`app/modules/individual`, `app/services/individual.py`)
- **Implemented:** Individual (non-school) subscriber flow, access to paid class.

### 1.16 Schools & Approvals (`app/modules/schools`, `school_approvals`, `app/services/schools.py`, `school_approvals.py`)
- **Implemented:** School CRUD, join codes (`b2c3d4e5f6g7`), school approvals workflow, system school bootstrap (`ensure_system_school`), onboarding.

### 1.17 Progress & Analytics (`app/modules/progress`, `app/services/progress.py`, `analytics.py`, `revenue.py`)
- **Implemented:** Student progress tracking (class/student/status/created_at indexes, pct range CHECK), admin analytics, revenue analytics.

### 1.18 Media & Export (`app/modules/media`, `export`, `app/services/export.py`, `video_service.py`, `offline.py`)
- **Implemented:** File uploads (whitelisted extensions, size limits, random names, outside public dir — D7), PDF generation (Arabic TTF font readiness), offline downloads, video progress, export.

### 1.19 WhatsApp (`app/modules/whatsapp`, `app/services/whatsapp.py`)
- **Implemented:** WhatsApp links (verified phone↔account).

### 1.20 Contact (`app/modules/contact`)
- **Implemented:** Contact form.

### 1.21 Admin (`app/modules/admin`)
- **Implemented:** Dashboard, users (list/detail/toggle/bulk/impersonate), schools, subscriptions (cancel/detail), pending payments (approve/reject), AI usage, backups (create), admin audit log (`_audit_admin_action`).

---

## 2. API & Routing Architecture

- **27 Blueprints** registered in `app/__init__.py` (`main`, `admin`, `auth`, `api`, `schools`, `tutoring`, `content`, `assessment`, `grades`, `billing`, `notifications`, `ai`, `payments` + `payments_ui` + `payments_webhook`, `family`, `progress`, `calendar`, `export`, `gamification`, `media`, `messages`, `school_approvals`, `individual`, `contact`, `wallet_api`, `wallet_ui`, `whatsapp`).
- **~202 route handlers** using `@bp.get/post/put/delete/patch`.
- **API versioning:** `/api/v1/*` with negotiation middleware (`negotiate_api_version`), CORS for mobile clients, rate limit 100/min on api blueprint.
- **Auth methods:** Session cookie (web) + Bearer PAT (mobile) via `request_loader`.
- **Security decorators:** `role_required`, `class_access_required`, `class_teach_required`, `parent_of_required`; rate limiting per sensitive endpoint; CSRF on web forms.
- **Error handling:** centralized in `app/core/errors.py` (Arabic messages, trace ID, JSON for API vs HTML for web).
- **OpenAPI/Swagger:** `app/core/openapi.py`, docstrings on `/me`, `/lessons`, `/tutoring/sessions`; `SWAGGER_ENABLED` env toggle.
- **Health:** `/health`, `/health/deep` (super_admin), `/api/health` (legacy redirect).

---

## 3. Database & Multi-Tenancy Architecture

- **ORM:** SQLAlchemy 3.1 (`db = SQLAlchemy()`), Flask-Migrate/Alembic.
- **Models:** 23 model modules, ~68 model classes (`app/models/`).
- **Migrations:** 25 revisions, chain `5c63f56be2b2` → `w6x7y8z9a0b1 (head)`, all applied cleanly.
- **RLS:** policies from `g1h2i3j4k5l6` onward; `USING` (read) and `WITH CHECK` (write) separated; null-safe GUC handling; platform_scope for cross-tenant writes.
- **Tenant scoping:** every `school_id`-bearing table queried via `scope_by_school`/`tenant_scope`.
- **Audit:** `audit_logs` table (entity/entity_id indexes).
- **System bootstrap:** `flask init-system` (idempotent), `ensure_system_school`, super_admin creation.
- **CLI commands:** expire-subscriptions, expire-pending-payments, ai-usage-report, backup-health, send-absence-alerts, tutoring-auto-timeout, init-system.

---

## 4. Frontend Integration & UI Components

- **Templates:** 119 Jinja2 HTML files under `app/templates/` (RTL Arabic default, D8), organized by module; `base.html` layout; macros.
- **i18n:** Babel (ar source msgid, en translated), `pybabel` extract/update/compile pipeline; `_()` in templates, `lazy_gettext` in forms.
- **JS:** 13 ES modules under `app/static/js/` — core (`api.js`, `theme.js`), components (`charts.js`, `forms.js`, `toast.js`, `tour.js`, `ui.js`), pages (`bulk.js`, `quiz.js`, `search.js`), `ai-chat.js`, `index.js`, `video_player.js`.
- **CSS:** modular under `app/static/css/` — base, brand, theme, app, components, pages, landing, polish, admin, ai-chat; dist build.
- **Security:** CSP with per-request nonce, Talisman headers, no `unsafe-inline`.
- **Bidi:** Arabic RTL default; Babel locale selection from cookie/preferences.
- **Testing:** Vitest (jsdom) — 28 test files, 579 tests; Playwright E2E.

---

## 5. Architectural Gap Analysis & Future Recommendations

### 5.1 Scaling & Performance
- **N+1 remediation** partially addressed (performance indexes v1/v2); remaining: ensure eager loading (`joinedload`/`selectinload`) audit across list endpoints.
- **Connection pooling / read replicas** not configured; single PG instance.
- **Celery** optional (import-guarded); background tasks may run in-process in dev.
- **Caching:** `app/core/cache.py` present but coverage of hot paths (grade summaries, analytics) to verify.

### 5.2 Multi-Tenancy Edge Cases
- **Cross-tenant adversarial tests** exist (`test_cross_tenant_adversarial.py`); RLS coverage gap on some tables closed in `l5m6n7o8p9q0` but `[rls] tables without a policy` warnings indicate ~18 tables still lack RLS policies (announcements, assignments, attendance, audit_logs, class_members, grade_categories, grade_items, lesson_attachments, lessons, manual_payments, offline_downloads, payment_receipts, rubric_criteria, student_progress, subscriptions, units, video_progress, wallet_topup_requests). **Gap:** extend RLS to these or document intentional exclusion.
- **`platform_scope` rollback** relies on scoped session; `_session_in_transaction` now correctly reflects state (fixed).

### 5.3 Financial Integrity
- **Reconciliation:** no automated reconciliation job between wallet ledger and gateway settlements.
- **FX/multi-currency:** currency stored as 3-char; no conversion service.
- **Refunds/partial refunds** flow not evident.

### 5.4 Frontend
- **Bundle/build:** CSS `dist` exists but JS has no bundler (vanilla ES modules); consider Vite for tree-shaking.
- **Offline:** `offline_downloads` + `offline.html` present; service worker not evident.
- **Accessibility:** no a11y audit tooling in CI.

### 5.5 Observability
- **Sentry** optional (DSN-gated); structured logging (structlog) + correlation IDs present.
- **Metrics:** response-time deque (in-memory, 1000 samples) only; no Prometheus/OpenTelemetry.
- **Backup freshness** check exists (`backup-health` CLI) but no automated restore drill.

### 5.6 Testing Coverage
- Backend branch coverage ~99.44% (18 partial branches); frontend ~96.64% (27 branches); 13 previously-deselected tests now passing.
- **Gap:** load tests (`tests/load/`) present but not in default CI gate; security tests (`tests/security/`) extensive.

### 5.7 Data & Compliance
- **GDPR/privacy:** no data-export/deletion tooling for student records.
- **Audit log** present but no retention policy.
- **PII in logs:** structlog may include user IDs; review needed.

### 5.8 Recommended Next Modules
1. **RLS completion** — add policies to the 18 uncovered tables.
2. **Payment reconciliation & refunds** service.
3. **Notification channels** (push/SMS) beyond email/WhatsApp.
4. **Analytics warehouse** (materialized views / read replica).
5. **Mobile API** hardening (OpenAPI complete, rate limits per client).
6. **Accessibility & i18n coverage** (full en translation audit).

---

## Appendix — Key Paths
| Concern | Path |
|---|---|
| App factory | `app/__init__.py` |
| DB/tx | `app/core/db.py` |
| Tenancy/RLS | `app/core/tenancy.py`, `app/core/rls.py` |
| Permissions | `app/core/permissions.py` |
| Models | `app/models/` (23 modules) |
| Services | `app/services/` (43 modules) |
| Blueprints | `app/modules/` (27) |
| Migrations | `migrations/versions/` (25) |
| Tests | `tests/` (197 files) |
| Frontend | `app/static/js/`, `app/static/css/`, `app/templates/` |
| Docs | `docs/` (STAKEHOLDER_GAP_ANALYSIS, ACTIONABLE_WORK_ITEMS, etc.) |

---

## 6. Gap Closure Sprint (Phases 1–5) — Status

| Gap (§5) | Status | Deliverable |
|---|---|---|
| RLS on 18 uncovered tables | Migration created | `migrations/versions/x7y8z9a0b1c2_rls_completion_phase1.py` |
| Refunds / partial refunds | Implemented | `process_refund()` in `app/services/wallet_service.py` |
| Payment reconciliation | Implemented | `app/services/reconciliation.py` + CLI `reconcile-payments` |
| Multi-currency / FX | Implemented + tested | `app/services/fx_service.py` (8 manual cases) |
| Tenant-aware cache | Implemented | `tenant_key()`, `invalidate_prefix()` in `app/core/cache.py` |
| GDPR export/erasure | Implemented | `app/services/privacy.py` |
| Audit log retention | Implemented | CLI `purge-expired-logs` + `AUDIT_LOG_RETENTION_DAYS` |
| Observability | Implemented | `app/core/metrics.py` + `/metrics` endpoint |
| Offline service worker | Implemented | `app/static/sw.js` |
| N+1 eager-loading audit | Not done (requires broad audit + query-count tests) | — |
| a11y automation + en translations | Not done (requires pybabel + Playwright axe) | — |

**Blocker:** PostgreSQL environment unstable in this sandbox (server crashes between commands), preventing migration apply, smoke tests and pytest runs. Static gates (ruff, mypy) pass on all new/modified files.
