# Integration & tenant isolation audit — 2026-10-19

Scope: every frontend binding (`url_for`, form actions, `fetch`) against the Flask
route table, tenant scoping of ID-bearing endpoints, RBAC parity between UI and
`role_required`/guards, and an adversarial pass over the endpoints the existing
cross-tenant suite did not cover.

## Method

1. Built the live route table from `create_app().url_map`: **245 rules / 243
   endpoints**.
2. Parsed every `url_for(...)` in `app/templates/**` and `app/static/js/**`
   (**156 distinct endpoints**) and every Python `url_for` in `app/**`.
3. Matched `<form method=…>` against each target rule's allowed methods; checked
   `url_for` keyword arguments against rule arguments.
4. Probed every GET rule anonymously and checked that guarded endpoints answer
   401/403/302 — never 500.
5. Reviewed ID-bearing handlers (`db.get_or_404`, `db.session.get`) for an
   explicit tenant/participant check, since tests run with RLS bypassed
   (`tests/conftest.py`), so Python scoping is the only guard under test.

## Findings and fixes

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | High | `grades.appeal_detail` did not exist. `appeals_queue.html` called `url_for` on it, so the queue returned **500** as soon as one appeal existed. The grade column also read `appeal.current_mark`, which the model does not define (silently blank). | Added `GET /classes/appeals/<id>` with teacher-of-class / owning-student authorization and a review form; column now reads `appeal.submission.mark`. |
| 2 | High | `billing.payment_file` did not exist. `admin/pending_payments.html` called `url_for` on it, so the pending-payments page returned **500** whenever a payment had a receipt, and receipt files were unreachable. | Added `GET /billing/payments/receipts/<filename>`. The URL name is looked up as `PaymentReceipt.stored_name` (a random upload name), never joined into a path; access limited to super admin, school admin of that payment's school, subscription owner/payer, and a linked parent. |
| 3 | High | `wallet_api` GET `/balance` and `/transactions` had no auth decorator. Anonymous requests raised `AttributeError: 'AnonymousUserMixin' has no attribute 'id'` → **500**. | `role_required(student, teacher, parent, school_admin, super_admin)` → 401 JSON for anonymous, 403 for a role without a wallet. |
| 4 | High | `billing.admin` and `billing.review` are open to `school_admin` without school scoping: the list was global and a tampered `payment_id` could approve/reject another school's payment. | `pending_payments(school_id=…)` now joins payment → subscription → class and filters by `class.school_id`; `review()` refuses a foreign payment with 403. The admin-blueprint list/approve/reject got the same guard as defense in depth. |
| 5 | High | `schools.index` is reachable by `school_admin` but `list_schools()` returned **every active school** (name/domain/join code). | `list_schools(school_id=…)`; the route passes `current_school_id()` for non-super-admins. |
| 6 | Medium | `billing.subscribe_route` checked the payee but not `can_pay_class`. A parent could POST an arbitrary `class_id` (with a linked child id) and create a subscription for a class the child never joined or was eligible for. | Added the `can_pay_class` gate for parents only; students keep the existing membership gate in `_resolve_payee` (applying the page gate to students would block their first-ever purchase, which the CI suite caught). |
| 7 | Medium | `schools.class_assign_teacher` accepted any user with the `teacher` role by id — including a teacher with no active role link in the class's school. | Assignment now requires an active `UserRoleLink` in `class_room.school_id`. |
| 8 | Medium | `billing.discount_list` returned every school's discount codes to `school_admin`. | Non-super-admins are filtered to their own `school_id`. |
| 9 | Medium | Admin nav (`admin/base.html`) and the school-admin dashboard quick actions linked to endpoints the admin blueprint's `before_request` refuses for school admins (`/admin/users`, `/admin/payments/pending`, `/admin/backups`, …). | Nav is split by `is_super_admin()`; school admins get their dashboard link. Quick actions now point only to pages they can open (`schools.index`, `schools.manage`, `schools.my_classes`, `calendar.index`). |
| 10 | Low | `admin.wallet_topup_review` redirected school admins to `/admin/wallet`, which they cannot open (403 after a successful approval). | School admins return to `/admin/school-admin`; super admins keep the filtered ledger URL. |

Contract checks that came back clean: every form method matches its route's
allowed methods; no `url_for` keyword mismatch beyond optional query parameters;
the only root-relative `fetch` target (`/profile/badges/check`) is a POST route
and is called with POST; every Python `url_for` resolves.

## Regression tests

`tests/integration/test_ui_contract_and_tenant_scope.py` (16 tests) pins each
finding, including negative cases: foreign teacher on an appeal (403/404),
foreign school admin on a receipt (403/404, no bytes), cross-school payment
review (403/404 + row unchanged), parent subscribing a child to an unrelated
class (403 + no row), foreign teacher assignment (class teacher unchanged), and
a static scan that fails if any template `url_for` points at a missing
endpoint. Two coverage tests that previously accepted `500` for the appeals
queue now require 200/302.

## Verification (run locally, 2026-10-19)

| Command | Result |
|---|---|
| `ruff check app config.py run.py` | pass |
| `ruff format --check app config.py run.py` | 161 files formatted |
| `mypy app config.py run.py` | no issues in 161 source files |
| `pytest tests/unit/test_cross_tenant_adversarial.py -q` | 36 passed |
| `pytest tests/integration/test_subscription_flows.py -q` | 31 passed |
| `pytest tests/integration/test_ui_contract_and_tenant_scope.py -q` | 16 passed |
| `pytest tests/test_cov_module_routes.py tests/unit/test_admin_routes_gaps.py tests/test_erp_ux_sprint1.py -q` | 127 passed |
| `pytest tests/security/test_school_admin_tenant.py tests/test_security.py -q` | 91 passed, 1 skipped |
| `pytest tests/security/test_parent_child_boundary.py -q` | 16 passed |
| `pytest tests/security/test_student_subscription_guard.py -q` | 16 passed |
| `pytest tests/security/test_teacher_class_boundary.py -q` | 17 passed |
| `pytest ... -k "appeals_list"` | 2 passed |

The full `pytest tests` run was started locally but stopped: on this Windows
machine it progressed ~1% in five minutes (several minutes per percentage
point), which would take hours. The CI workflow remains the authority for the
full-suite result; the targeted suites above cover every module touched by this
audit.

## Residual notes (not changed)

* `messages.compose` limits the recipient picker to the sender's school but the
  POST handler accepts any existing `recipient_id`. `messages` has no
  `school_id`, so it is outside the tenant-table rule; tightening it is a
  product decision (platform-wide messaging vs intra-school only).
* `billing.discount_create` still falls back to `school_id = … or 1` for a
  super admin. Codes are school-scoped by RLS, so a platform-wide code needs a
  product decision before the fallback can be removed.
* `admin.payments`/nav counters are global, but the pages that consume them are
  now super-admin-only, and tenant pages no longer render that nav.
