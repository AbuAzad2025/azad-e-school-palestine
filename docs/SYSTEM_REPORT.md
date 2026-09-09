# 📋 التقرير الشامل لمنصة مدرسة أزاد الإلكترونية
### Azad E-School (Palestine) — Full System Architecture & Functional Report
> **الغرض:** مرجع كامل يشرح المنصة برمجياً ووظيفياً ومنطقياً — يمكن لأي مطوّر أو مساعد ذكي فهم النظام بالكامل من هذا الملف.
> **تاريخ التقرير:** 2026-09-09 | **حجم الكود:** ~19,500 سطر Python | 110 قالب HTML | 223 مسار HTTP | 60 جدول قاعدة بيانات | 116 ملف اختبار

---

## 1) نظرة تنفيذية — ما هذه المنصة؟

**منصة تعليم إلكتروني SaaS متعددة المستأجرين (Multi-Tenant)** للمناهج الفلسطينية، تدعم نموذجين تجاريين في نفس الوقت:

| النموذج | الوصف | الوحدات المسؤولة |
|---|---|---|
| **مدارس (Tenant)** | مدرسة تُسجَّل ككيان مستأجر، تدير معلميها وطلابها وصفوفها، وتدفع اشتراكات حسب الخطة | `schools`, `school_approvals`, `billing`, `tenant` (حصص Quotas) |
| **طلاب أفراد (Individual)** | طالب يسجّل بلا مدرسة، ينتسب لصفوف عامة مدفوعة/مجانية مباشرة | `individual`, `payments` |

**الأدوار الستة:** `super_admin` (مالك المنصة — فوق التينانتس) • `school_admin` • `teacher` • `student` • `parent`

**نقاط القوة المعمارية:**
1. عزل مستأجرين بثلاث طبقات: Python (`scope_by_school`) + RLS على PostgreSQL + سياق جلسة (`SET LOCAL app.current_school_id`).
2. صرامة مالية: `Decimal(10,2)` + `ROUND_HALF_UP` + قفل صفوف `.with_for_update()` + Idempotency عبر `processed_events`.
3. كل كتابة قاعدة بيانات عبر غلاف `tx()` واحد مع hooks بعد الـ commit.
4. أمان كلمات مرور argon2id + سجل كلمات + سياسة قوة + فحص إعادة استخدام.
5. رفع ملفات بتحقق ثلاثي (امتداد + MIME + Magic bytes) وأسماء UUID خارج المسارات العامة.

---

## 2) المكدس التقني (Stack)

| الطبقة | التقنية |
|---|---|
| Backend | Python 3.12 + Flask 3.1 (App Factory pattern) |
| ORM / DB | SQLAlchemy 2 (Mapped style) + PostgreSQL (psycopg2) + Alembic migrations (9 ملفات) |
| Auth | Flask-Login + argon2-cffi + itsdangerous tokens |
| Forms/CSRF | Flask-WTF + CSRF حسب الطلب |
| i18n | Flask-Babel (ar مصدر، en ترجمة) |
| Rate limiting | Flask-Limiter (fixed-window، memory أو Redis) |
| Email | Flask-Mail (قابل للتعطيل بـ `EMAIL_ENABLED`) |
| PDF / Excel | xhtml2pdf + openpyxl |
| Sanitization | bleach + BeautifulSoup4 (تنظيف HTML الدروس) |
| AI | OpenAI SDK (async، اختياري — مع fallback أوفلاين كامل) |
| Celery | اختياري (soft-import) — مهام خلفية مع Redis |
| Monitoring | structlog + Sentry (اختياري) + flasgger (Swagger UI) |
| Frontend | Jinja2 + CSS custom (design tokens) + vanilla JS modules + HLS.js |
| Tests | pytest + pytest-cov (>70% gate، حالياً ~77.5% lines / ~62.6% branches) |
| Lint/Types | ruff (check+format) + mypy |
| JS Lint | Biome |
| CI/CD | GitHub Actions (7 jobs) → Docker image → GHCR |
| Deploy | Gunicorn + Nginx + systemd + docker-compose |

---

## 3) نقطة الدخول ومصنع التطبيق

### `run.py`
مشغّل التطوير (`flask run` equivalent) — يستدعي `create_app(Config)`.

### `app/__init__.py` — `create_app(config_class=Config)`
ترتيب التهيئة:
1. تحميل dotenv + إعداد Flask (instance folder).
2. **الامتدادات:** `db` → `migrate` → `login_manager` (login_view=`auth.login`) → `csrf` → `babel` (اختيار لغة من الجلسة/Cookie) → `mail` → `limiter` (`get_remote_address`).
3. **Sentry** إن وُجد `SENTRY_DSN` + ربط user بعد الـ login.
4. **`login_manager.user_loader`** — تحميل مستخدم مع حماية من المحذوفين.
5. **Before-request hooks:** `set_tenant_for_request()` (RLS session vars) + health tracking + تسجيل بطيء للطلبات.
6. **After-request:** رؤوس أمان (Talisman-style يدوي: X-Frame-Options, CSP أساسي...).
7. **تسجيل 22 Blueprint** (انظر §7) + aliases قديمة (`assessment_alias`, `content_alias`, `grades_alias`, `api_health_legacy`).
8. **Context processors:** `admin_nav_context` (عداد الاشتراكات المعلّقة للإشعارات في الشريط — يهدم بأمان عند غياب الجداول)، `_()`، `get_locale`، شعار/إعدادات.
9. **Error handlers:** 403/404/500/429 بقوالب عربية + correlation_id.
10. **Jinja filters/helpers:** `icon()` (من `app/core/context.py` — SVG sprite)، تنسيق تواريخ/عملات.

### `config.py`
- `_BaseConfig`: UPLOAD_FOLDER داخل `instance/uploads` (خارج public)، Session آمنة (HttpOnly, SameSite=Lax, ساعة)، `RATELIMIT_DEFAULT=200/min`، MAIL إعدادات، `EMAIL_ENABLED=0` افتراضياً.
- `DevelopmentConfig` / `ProductionConfig` (Secure cookies +_PROXY aware) / `TestingConfig` (RATELIMIT معطّل، EMAIL معطّل — **هذا ما يستخدمه conftest للاختبارات**).
- مفاتيح AI: `AI_API_KEY`, `AI_MODEL`, `AI_MAX_RPM`, `AI_MAX_TPM`, `AI_MONTHLY_BUDGET_USD`.

---

## 4) الطبقة الأساسية `app/core/` (القوانين غير القابلة للتفاوض)

### 4.1 `db.py` (235 سطر) — إدارة المعاملات ⭐
- **`tx(fn, *args, **kwargs)`**: الغلاف الوحيد لأي كتابة — يفتح transaction، ينفّذ، **commit واحد**، rollback كامل عند أي استثناء، ثم يجري `_expire_committed_objects()`.
- **`TxError`**: استثناء منطقي مقصود لإلغاء المعاملة مع رسالة وجهها للمستخدم.
- **`tx_on_commit(fn)`**: جدولة تأثير خارجي (إيميل/إشعار/Celery) **بعد نجاح الـ commit فقط** — عبر post-commit hooks تُصرف بالترتيب.
- `_log_transaction_failure`: تسجيل منظم للفشل مع correlation_id.
> **القاعدة:** ممنوع `db.session.commit()` مباشرة في أي route/service.

### 4.2 `tenancy.py` (84 سطر) — العزل المنطقي
- `current_school_id()`: مدرسة المستخدم من `UserRoleLink` النشط الأول؛ `None` لـ super_admin وفوق التينانتس.
- `set_tenant_for_request()`: ينفّذ `SET LOCAL app.current_school_id / app.is_super_admin` لكل طلب (RLS يقرأها). آمن عند غياب transaction.
- `scope_by_school(model, school_id)` / `tenant_scope(...)`: إلزام فلتر `school_id` على كل استعلام للموديلات المؤجّرة.
- `get_school_or_404()`: جلب مدرسة بحماية.

### 4.3 `rls.py` (210 سطر) — العزل على مستوى قاعدة البيانات
- `enable_rls_on_table(table)`: ينشئ POLICY تُجبر `school_id = current_setting('app.current_school_id')` أو `is_super_admin='1'` — **FORCE ROW LEVEL SECURITY**.
- `enable_rls_on_indirect_table(table, subquery)`: للجداول بلا `school_id` مباشر (مثل `announcements` عبر class → school).
- Migration `g1h2i3j4k5l6` يطبق السياسات؛ الإنذار: الجداول بلا `school_id` عمود لا تُفعَّل إلا عبر subquery.
- `set_tenant_context()/reset_tenant_context()` للاستخدام اليدوي/السكربتات.

### 4.4 `permissions.py` (140 سطر) — RBAC المركزي (قاعدة C)
- `role_required(*roles)` — المفحص الأساسي؛ **super_admin يمرّ دائماً**.
- `any_role(*roles)` — نسخة صريحة بدون ترقية تلقائية.
- `class_access_required` — يفوض إلى `services/access.py:can_view_class`.
- `class_teach_required` — `can_teach_class` (معلم الصف أو أدارة).
- `parent_of_required` — وليّ أمر مرتبط بالطالب (FamilyLink أو عضوية).
- `student_only` — قفل دوري صارم.

### 4.5 `security.py` (72 سطر)
- `hash_password/verify_password` — **argon2id**.
- `validate_password_policy` — طول + تعقيد.
- `check_password_reuse` — ضد آخر 5 كلمات في `password_history`.

### 4.6 `uploads.py` (142 سطر) — رفع آمن (قاعدة E)
- قوائم بيضاء للامتدادات + MIME + **MAGIC_SIGNATURES** (فحص بايتات حقيقية، مع خاص لـ OFFICE zip-based).
- `save_upload()`: UUID filename + تخزين في `instance/uploads` (غير مُخدَم مباشرة) + رفض أي شيء غير مطابق.
- الصور المسموحة: jpg/png/webp/gif، ومستندات: pdf/docx/xlsx/pptx.

### 4.7 `api.py` + `api_auth.py` — معيار REST
- **مغلف موحّد**: نجاح `{data, meta{version, request_id, ...page/per_page/total/pages}}`، خطأ `{error{code, message, details}, meta}`.
- `api_response / api_error / api_paginated`.
- `api_auth_required` — حارس للـ `/api/v1/*` (session-based، 401 JSON موحّد).

### 4.8 `logging.py` — structlog مع `correlation_id` لكل طلب + مستويات منضبطة.

### 4.9 `tokens.py` — itsdangerous URLSafe tokens (تأكيد إيميل، reset password) بصلاحية زمنية.

### 4.10 `context.py` — `icon(name)` من sprite واحد (`icons.svg`) + مساعدات قوالب.

### 4.11 `openapi.py` — flasgger/Swagger UI على `/api/docs` + `openapi.json`.

### 4.12 `sentry.py` — تهيئة اختيارية + `set_sentry_user`.

---

## 5) نموذج البيانات — 60 جدولاً حسب المجال

### 5.1 الهوية والأمان
| الجدول | الوصف |
|---|---|
| `users` | مستخدم واحد بكل الأدوار: `role` (StrEnum)، `approval_status` (pending/approved/rejected)، `is_individual`، `failed_login_attempts` + `locked_until` (قفل تدريجي)، `password_history` (JSON، آخر 5)، `password_changed_at`، `deleted_at` (soft delete) |
| `user_role_links` | **قلب التينانتس الهجين**: (user, school, role) مع `is_active` و`approved_by/at` — نفس الشخص معلّم في مدرسة ووليّ في أخرى. `User.school_id` خاصية محسوبة من أول رابط نشط |
| `audit_logs` | من/فعل ماذا/على أي كيان/تفاصيل/IP — يكتبه `communication.audit()` |
| `processed_events` | Idempotency للويبهوكات (event_id + gateway فريدان) |

### 5.2 هيكل المدرسة الأكاديمي
| الجدول | الوصف |
|---|---|
| `schools` | جذر التينانتس — `join_code` للانضمام، `stages` (JSON)، `settings` (JSON)، `is_system` |
| `grades` | الصفوف الدراسية (مرحلة + مستوى) |
| `subjects` | المواد (كود MoE اختياري `moe_code`) |
| `subject_grade_links` | ربط M:N مادة↔صف |
| `classes` (ClassRoom) | صف دراسي: school/subject/grade/teacher + فصول دراسية (`semester`) + **3 أسعار** (فصل1/فصل2/سنوي) + `join_code` + `is_public` (للأفراد) + `max_students` + `currency` |
| `class_members` | العضوية: (class, user, status active/pending/…) — تُستخدم للطلاب **وللربط أولياء الأمور بصفوف أبنائهم** |
| `academic_events` | تقويم أكاديمي (بداية فصل، إجازات...) |
| `announcements` | إعلانات على مستوى صف (عبر RLS indirect) |
| `school_settings` | key/value لكل مدرسة |

### 5.3 المحتوى التعليمي
| الجدول | الوصف |
|---|---|
| `units` | وحدات الصف |
| `lessons` | درس (HTML مُنقّى بـ bleach) + `version` + `published_at` + **`is_shared` + `original_lesson_id`** (استيراد درس بين صفوف مع حفظ الأصل) + `is_offline_available` |
| `lesson_attachments` | ملف/يوتيوب لكل درس (`kind`, mime, size, position) |
| `question_bank` | بنك أسئلة المدرس (صعوبة، وسوم، `is_shared` داخل المدرسة) |

### 5.4 التقييم والاختبارات
| الجدول | الوصف |
|---|---|
| `quizzes` | اختبار: مدة، محاولات، نافذة فتح/إغلاق، خلط أسئلة، **مراقبة (proctoring): `enable_proctoring` + `max_tab_switches` + `fullscreen_required`** |
| `questions` | أنواع: MCY/true-false/essay (options JSON، correct_answer، mark) |
| `quiz_attempts` | محاولة طالب: رقم، بداية/تسليم، score، status |
| `answers` | إجابة سؤال داخل محاولة (+ `awarded_mark` للتصحيح اليدوي) |
| `proctoring_logs` | أحداث مراقبة (tab switch, exit fullscreen) بطابع زمني |
| `assignments` | واجبات (max_mark, due_at) |
| `submissions` | تسليم الطالب + mark/feedback/graded_by |
| `grade_appeals` | اعتراض طالب على علامة → مراجعة معلم |
| `grade_categories` / `grade_items` / `grade_entries` | دفتر علامات مرجّح (فئات بأوزان، بنود، علامات) — **CHECK constraint يمنع سالب أو تجاوز الحد** |
| `rubric_templates` / `rubric_criteria` / `rubric_grades` | تقييم بالمعايير (rubric) |

### 5.5 المالية والاشتراكات
| الجدول | الوصف |
|---|---|
| `subscription_plans` | خطة لصف/مدرسة: `plan` (annual/term1/term2...)، price، duration_days، benefits JSON |
| `subscriptions` | اشتراك المستخدم: status (pending→active→expired/cancelled)، `source`، `auto_activated_at` |
| `manual_payments` | إيصال تحويل يدوي: reference، amount، status (pending/approved/rejected)، reviewed_by/at |
| `payment_receipts` | صور الإيصالات (stored_name UUID) |
| `discount_codes` | كود خصم (نسبة/مبلغ، حد استخدام، تاريخ انتهاء، خطط مسموحة) |
| `reminder_logs` | سجل تذكيرات الدفع المرسلة |
| `wallets` / `wallet_transactions` | **محفظة مزدوجة القيد**: source/destination wallet، `transaction_hash`، `idempotency_key` فريد، metadata JSON، status |
| `tutor_commissions` / `tutor_payouts` | عمولة المنصة من الدروس الخصوصية + دفعات المستحقات |

### 5.6 الدروس الخصوصية (Tutoring)
`tutor_profiles` (أسعار/وضع/availability/invite_code/video_provider) • `tutoring_requests` • `tutoring_sessions` (حالة + payment_status + Zoom/Jitsi metadata) • `tutor_reviews`

### 5.7 التقدم والتفاعل
`student_progress` (حالة الدرس + ثوانٍ + نسبة) • `video_progress` (ثوانٍ مشاهدة لكل مرفق) • `offline_downloads` (انتهاء صلاحية) • `attendance` (حضور يومي) • `badges` + `student_badges` (Gamification) • `messages` (رسائل داخلية بثريدينج) • `notifications` + `notification_preferences` • `family_links` + `family_link_codes` (ربط وليّ↔طالب بكود مؤقت)

### 5.8 النظام (Platform)
`tenant_quotas` (tier: max students/teachers/classes/storage + AI tokens) • `onboarding_progress` • `certificate_templates` • `health_checks` • `settings` (عام) • `ai_sessions` + `ai_messages` + `ai_usage_logs` (تتبع استهلاك AI وتكلفة تقديرية)

---

## 6) طبقة الخدمات `app/services/` — 41 وحدة (كل منطق العمل هنا)

### الأمان والوصول
- **`access.py`** — بوابة المحتوى المدفوع: `can_view_class` (فحص دور + عضوية نشطة + اشتراك صالح غير منتهٍ + صف مجاني + فرع وليّ أمر) و`can_teach_class`. **العضوية وحدها لا تكفي للصف المدفوع.**
- **`auth.py`** — تسجيل (school/individual)، `authenticate` (قفل بعد محاولات فاشلة)، تأكيد إيميل، reset password.
- **`impersonation.py`** — انتحال صفة (super_admin فقط): `start/stop/clear` + سجل تدقيق؛ بعد الانتحال الحارس يفحص دور المنتحَل، والخروج يُعتم على دور المنتحِل الأصلي.
- **`school_approvals.py`** — قائمة انتظار الموافقات (مستخدم↔مدرسة) بموافقة school_admin أو super_admin.

### المالية
- **`billing.py` (440 سطر)** — `money()` (Decimal/ROUND_HALF_UP)، خطط، `subscribe` (ينشئ pending ولا يفعّل إلا بالدفع/مجاني)، `record_manual_payment`، `approve_payment/reject_payment` (تفعيل + عضوية + تدقيق + إيميل)، `expire_subscriptions`، أكواد خصم، ملخصات سداد.
- **`payments.py`** — بوابات: **Stripe** (PaymentIntent + webhook signature verification + refunds) و**PayTabs**، كلها عبر `processed_events` لمنع المعالجة المزدوجة.
- **`wallet_service.py`** — محفظة مزدوجة القيد: `process_transfer` (أقفال صفوف مرتّبة بالـ ID لمنع deadlock، فحص رصيد، idempotency_key)، `process_tutor_commission`، تاريخ وملخص.
- **`invoice.py`**, **`finance.py`** (إيرادات مدرسة/مديونية طلاب)، **`revenue.py`** (لوحة إيرادات المنصة: حسب بوابة/مدرسة/شهر/نمو).

### التعليم
- **`content.py`** — وحدات ودروس (sanitize HTML بـ bleach)، مرفقات، نشر/سحب، **استيراد درس مشترك** بين صفوف، مشاركة داخل مدرسة.
- **`assessment.py`** — دورة حياة الاختبار: إنشاء/بدء محاولة (فحص النافذة والمحاولات) / حفظ إجابة / تصحيح آلي (MCQ/TF) + يدوي للمقالي / `submit_attempt` مع فرض المدة.
- **`gradebook.py`** — واجبات وتسليمات وتصحيح + دفتر علامات مرجّح + حضور (سجل/ملخص).
- **`grade_calc.py`** — حساب علامة طالب من الأوزان + تقدير حرفي + ملخص صف.
- **`grade_appeals.py`**, **`rubric.py`**, **`report_card.py`** (GPA + كشف علامات HTML→PDF عبر xhtml2pdf), **`quiz_stats.py`** (إحصاء صف: صعوبة، معامل تمييز).
- **`progress.py`** — تتبع مشاهدات الدروس/فيديو/وقت/نِسب + آخر أيام نشاط.
- **`question_bank.py`** — CRUD بنك الأسئلة + استيراد إلى اختبار.
- **`gamification.py`** — شارات (تحقق streaks/إكمال مساق) ومنح آلي عند الأحداث.
- **`offline.py`** — طلبات تحميل أوفلاين مع انتهاء صلاحية.

### التواصل
- **`communication.py`** — `notify()` (إشعار داخلي)، `audit()`، `mark_all_read`.
- **`email.py`** — 9 قوالب إيميل ثنائية اللغة (ترحيب/موافقة/رفض/علامة/نتيجة اختبار/غياب/تذكير دفع/رد تواصل) — تُرسل عبر `tx_on_commit` وتُعطّل بـ `EMAIL_ENABLED`.
- **`messages.py`** — رسائل خاصة + ثريدينج.
- **`family.py`** — كود ربط وليّ↔طالب (ينتهي) + `is_parent_of`.

### المنصة
- **`schools.py`** — إنشاء/إدارة مدارس، انضمام بكود (class أو school)، `is_member`.
- **`individual.py`** — كتالوج الصفوف العامة + `subscribe_to_class` (**P-SEC-07/08/09**: يبدأ pending، الفعّال فقط بعد الدفع، المجاني يُفعّل فوراً).
- **`tenant.py`** — حصص Quotas حسب tier + `set_tier`.
- **`onboarding.py`** — معالج تهيئة مدرسة جديدة خطوة-بخطوة.
- **`health.py`** — فحوص DB/قرص/أداء + تسجيل في `health_checks` + حالة عامة.
- **`calendar.py`**, **`export.py`** (Excel للطلاب/العلامات/التقدم + صيغة MoE), **`analytics.py`**, **`notification_preferences.py`**.
- **`tutoring.py` (589 سطر)** — ملفات مدرّسين، بحث، طلبات، جلسات (Jitsi/Zoom عبر `generate_zoom_meeting`)، تقييم، عمولات.

### الذكاء الاصطناعي
- **`ai.py` (618 سطر)** — `AiService` كامل: RateLimiter (RPM/TPM) + BudgetTracker (سقف شهري USD) + استخدام async OpenAI مع اختيار موديل من env + تسكل `ai_usage_logs`. يعمل حتى بدون openai مثبّتًا (fallback).
- **`rag_service.py` (371 سطر)** — RAG محلي **بلا اعتماديات خارجية**: chunking + TF-Cosine retrieval **مقيّد بـ school_id**، `query_school_rag_tutor` (يستخدم LLM إن توفر وإلا إجابة مركّبة من المقاطع).
- **`quiz_ai_service.py`** — توليد اختبار من نص الدرس (prompt منظم → JSON parsing → إنشاء Quiz+Questions داخل `tx()`، مع مولّد أوفلاين احتياطي).
- **`video_service.py`** — توكنات بث HMAC-SHA256 (15 دقيقة، مربوطة بـ user+school+lesson) + تحقق + presigned paths.

### أساس معماري
- **`base.py`** — `BaseService[T]` + `PaginatedResult` + إعادة تصدير `tx` (كل الخدمات تستورد من هنا أو من core).

---

## 7) طبقة الوحدات `app/modules/` — 22 Blueprint، 223 مساراً

| الوحدة | Endpoints | أبرز المسارات | الحارس |
|---|---|---|---|
| `admin` | 37 | `/admin/dashboard`, `/admin/users` (+impersonate/exit)، `/admin/schools`، `/admin/subscriptions` (approve/reject)، `/admin/payments`، `/admin/analytics`، `/admin/revenue`، `/admin/audit-logs`، `/admin/settings`، `/admin/health`، `/admin/quotas` | `role_required(super_admin)` / school_admin مسارات منفصلة |
| `grades` | 21 | دفتر علامات، واجبات، تسليم، اعتراضات، rubrics، كشف علامات PDF | `class_teach_required` / `class_access_required` |
| `assessment` | 19 | إنشاء اختبار/أسئلة، بدء/حفظ/تسليم محاولة، مراقبة (proctoring events) | `class_teach_required` للتحضير، `class_access_required` للتقديم |
| `tutoring` | 18 | ملف مدرّس، بحث، طلبات، جلسات، تقييم، Zoom | ملكية طرفي الجلسة |
| `content` | 15 | وحدات/دروس/مرفقات/نشر/استيراد | `class_teach_required` |
| `api` (v1) | 14 | `/api/v1/{me,schools,classes,lessons,quizzes,subscriptions,users,notifications,search}` + 404/401/403/429 handlers | `api_auth_required` + scoping حسب الدور (طالب ← اشتراكاته فقط) |
| `schools` | 13 | `/schools/join` (كود مدرسة/صف)، قائمة صفواطي، **تفاصيل صف عبر `can_view_class`** | مختلط حسب المسار |
| `billing` | 11 | خطط، اشتراك، إيصالات، فواتير | `login_required` + ملكية |
| `auth` | 8 | login/logout/register/confirm/reset + dashboard موحّد لكل الأدوار | عام + مفحوصات داخلية |
| `payments` (UI) | 8 | رفع إيصال، متابعة حالة | ملكية الاشتراك |
| `ai` | 6 | جلسة شات تعليمية + توليد اختبار | أدوار + حصص AI |
| `messages`, `notifications`, `family`, `progress`, `calendar`, `export`, `individual`, `school_approvals`, `contact`, `gamification`, `media` | 1–7 | رسائل/إشعارات/ربط أبناء/تقدم/تقويم/تصدير Excel/كتالوج الأفراد/موافقات/تواصل/شارات/**بث فيديو محمي بتوكن HMAC** | كلٌ حسب دوره |

> `main` — الصفحة الرئيسية/Landing + health endpoints (`/health`, `/health/deep`).

---

## 8) المهام الخلفية `app/tasks/` (Celery اختياري)

- **`__init__.py`** — مصنع `celery_app` (Redis broker، acks_late، time limits، worker recycle كل 100 مهمة) + `FlaskTask` يفتح app context لكل مهمة + **fallback كامل عند غياب Celery** (`.delay()` يعمل sync).
- **`notifications.py`** — إشعارات جماعية بالدفعات.
- **`reports.py`** — توليد كشوف PDF خلفياً.
- **`grading.py`** — تصحيح آلي لاختبارات كبيرة.
- **`video.py`** — transcode HLS (محمي بـ `_HAS_CELERY` + فحص ffmpeg).

---

## 9) الواجهة الأمامية

### قوالب (110 ملف، ~40 مجلداً)
- `base.html` (هيكل عام + شريط علوي + RTL/LTR) و`admin/base.html` (لوحة جانبية ERP-style).
- `partials/` (navbar, footer, toasts) + `macros/ui.html` (بطاقات إحصاء، breadcrumbs `azad_breadcrumb`، أزرار، جداول، pagination، modal).
- أقسام كاملة لكل دور: admin (22 قالب)، grades (10)، schools (9)، assessment (9)، tutoring (8)، auth (6)، billing (5)، family، progress، ai، gamification، emails (قوالب البريد)، errors (403/404/500/429).

### CSS (بنية Design Tokens)
- `brand.css` — المتغيرات (ألوان/مسافات/خطوط) + أزرار `azad-btn-*`.
- `app.css` — المكونات + **طبقة توافق** أضيفت لكل الأصناف المستخدمة سابقاً بلا تنسيق.
- `components/_tables.css`, `_gradebook.css`, `admin.css`, `ai-chat.css`.
- **dist/** — `app.min.css` (88KB مضغوط عبر `scripts/build_css.py` + manifest).
- دعم RTL كامل (`inset-inline`, `margin-inline`) + وضع داكن (tokens).

### JS (13 ملف ES modules)
- `core/api.js` (fetch wrapper)، `core/theme.js`، `index.js` (bootstrap الوحدات)، `components/` (toast, forms, charts, tour, ui)، `pages/` (quiz, bulk, search)، `ai-chat.js`، `video_player.js` (HLS.js + watermark متحرك).
- مُفحوص بـ **Biome** + اختبارات Vitest في CI (`test-js` job).

---

## 10) التدويل i18n
- **العربية هي المصدر** (msgid) و`en` تُترجم فقط — `babel.cfg` + `messages.pot` + `.po/.mo` للغتين.
- `_()` في القوالب/الخدمات، `lazy_gettext` في النماذج.
- سكربتات مساعدة: `scan_translations.py`, `dump_untranslated.py`.

---

## 11) قاعدة البيانات والهجرات
- **9 ملفات migration** حتى `g1h2i3j4k5l6`:
  1. `5c63f56be2b2` المخطط الأولي من الموديلات
  2. `a1b2c3d4e5f6` تدقيق أمني (password stamp + فهارس جزئية فريدة)
  3. `b2c3d4e5f6g7` كود انضمام المدرسة
  4. `c1d2e3f4a5b6` إصلاح طول `student_progress.status`
  5. `d2e3f4a5b6c7` تدقيق مخطط (دقة أوزان + FK ondelete)
  6. `e3f4a5b6c7d8` + `f4a5b6c7d8e9` فهارس أداء (علاج N+1)
  7. `a7b8c9d0e1f2` CHECK constraints + فهارس
  8. `g1h2i3j4k5l6` **سياسات RLS لعزل التينانتس**
- **قيود CHECK حاسمة:** `ck_grade_entry_mark_range` (0 ≤ mark ≤ max)، `ck_tutoring_session_status`، وحالات الأدوار.
- **بيئة التطوير:** قاعدة `azad_school` جديدة نظيفة (هاجرت من الصفر + RLS ناجح)؛ قاعدة `azad_test` للاختبارات؛ حارس في conftest يمنع pytest من لمس قاعدة فيها بيانات (29 مستخدماً) إلا بـ `ALLOW_TEST_DB_WIPE=1`.

---

## 12) الاختبارات — 116 ملفاً (organized squads)

| الفئة | أمثلة | ما يغطيه |
|---|---|---|
| **الأمان (security/)** | `test_superadmin_routes`, `test_school_admin_tenant`, `test_teacher_class_boundary`, `test_student_subscription_guard`, `test_parent_child_boundary`, `test_unauthenticated_attacker` | مصفوفة RBAC كاملة بشخصيات حقيقية (6 personas) — 403/404 للجميع خارج نطاقه |
| **تكامل (integration/)** | `test_subscription_flows` | مجاني→وصول فوري، مدفوع→pending→موافقة→وصول، رفض→حجب، انتهاء→إلغاء وصول، عزل بين مدرستين |
| **RBAC/tenancy أساسية** | `test_squad1_rbac/tenancy/security/tokens/auth_session/uploads`, `test_zero_trust_auth`, `test_security_parent_idor`, `test_hybrid_tenancy` | الحرس والنطاقات وهجرة الأدوار |
| **مالية** | `test_financial_integrity`, `test_squad2_billing`, `test_integration_billing_ledger`, `test_discount_system`, `test_teacher_commission`, `test_payment_reminders`, `test_coverage_payments_ai` | دقة Decimal، أقفال، idempotency، دورة الموافقات |
| **API** | `test_api_v1_routes` (51 اختبار — كل النهايات + أصحاب الحدود)، `test_squad3_*_api`, `test_mobile_api`, `test_openapi`, `test_api_versioning` | العقود والمغلفات والتقسيم |
| **خدمات** | `test_squad2_all_services`, `test_unit_*` (14 ملف), `test_cov_*` | تغطية عميقة للـ 41 خدمة |
| **جودة/أداء** | `test_query_performance` (N+1 bounds), `test_performance`, `test_load_testing`, `test_css_architecture` (أصول/تكرارات/أيتام + 4 فحوص أصول جديدة), `test_wcag_aa`, `test_frontend_critical`, `test_js_modernization` | انضباط غير وظيفي |
| **ميزات** | `test_proctoring`, `test_gamification`, `test_rubric`, `test_grade_appeals`, `test_offline*`, `test_onboarding`, `test_health`, `test_monitoring`, `test_m0/m1`, `test_phase8/9`, `test_erp_ux_sprint1-4` | كل دورة وظيفية |
| **CI نفسها** | `test_cicd_pipeline`, `test_production_deployment` | صحة الأنابيب |

- **conftest.py**: `app` fixture بـ TestingConfig (RATELIMIT off) + حارس قاعدة البيانات + **~35 مصنع بيانات** (`make_school/user/class/lesson/quiz/subscription/payment/...`) + `_clean_db` autouse (TRUNCATE CASCADE) + `pg_trgm` extension.
- **التشغيل:** `DATABASE_URL=...azad_test pytest tests -q` — CI يشغّل الكل مع `--cov` وGate ≥70% (الحالي: **77.5% سطور / 62.6% فروع** للأكواد البايثونية؛ إجمالي مع JS: 77.5% / 67.6%).

---

## 13) CI/CD — `.github/workflows/ci.yml` (7 jobs)

| Job | الوظيفة |
|---|---|
| `lint` | ruff check + ruff format --check + mypy + biome + gitleaks (No leaks) |
| `frontend-asset-quality` | pytest على `test_css_architecture.py` + `test_wcag_aa` + `test_frontend_critical` (بPostgres مستقلة سريعة) |
| `test` | pytest كامل + PostgreSQL 16 service + `pg_trgm` + coverage gate |
| `test-js` | Vitest |
| `build` | Docker build (no push) |
| `coverage` | دمج coverage (Python+JS) → تقرير موحّد في Job Summary |
| `deploy` | بناء ودفع صورة إلى **GHCR** (`azad-e-school:latest` + `main-<sha>`) عند push على main |

- **آخر حالة:** إصلاح تنسيق ruff (`787d9a7`) — التشغيل قيد المتابعة.
- الإعدادات: concurrency group (إلغاء القديم)، permissions read-only.

---

## 14) النشر والتشغيل
- `deploy/Dockerfile` (python:3.12-slim + gunicorn) • `docker-compose.production.yml` • `deploy/nginx.conf` (TLS + static + proxy) • `azad-e-school.service` (systemd) • `gunicorn.conf.py`.
- **سكربتات تشغيلية:** `backup.py` + `backup_encrypt.py` + `restore.py` + `restore_verify.py` + `cron_backup.sh`/`cron_jobs.sh` (تذكيرات دفع يومية + انتهاء اشتراكات) • `daily_reminders.py` • `check_db.py` • `build_css.py` • `create_tutor_profiles.py` • `lighthouse.sh`.
- **Seed:** `scripts/seed_data.py` (idempotent) — 29 مستخدماً/مدرستين/صفوف واختبارات كاملة، كلمة المرور `Azad@2026`، **والحسابات تُنشأ `pending` فتُعتمد يدوياً أو بسكربت**.
- `docs/`: `runbook.md`, `production_checklist.md`, `DATABASE_SCHEMA.md`, `mobile_api_integration.md`, `postgresql.conf.production`.

---

## 15) ملخص النموذج المالي-المنطقي (كيف تُمنع التسريبات)

1. **الانضمام بكود صف ≠ عضوية فعّالة** — الحالة `pending` حتى دفع/موافقة (P-SEC-07/08).
2. **الصف المجاني** (بلا خطة أو سعر 0) هو الحالة الوحيدة للتفعيل الفوري (P-SEC-09).
3. **`can_view_class`** = الدور مناسب **و** (عضوية نشطة على صف مجاني **أو** اشتراك active غير منتهٍ) — العضوية وحدها لا تفتح محتوى مدفوعاً.
4. موافقة الأدمن (يدوي/بوابة): تحديث الإيصال → تفعيل الاشتراك بتواريخ دقيقة → `ClassMember` نشط idempotent → AuditLog → إيميل `tx_on_commit`.
5. كل المدفوعات عبر بوابة تمر بـ `processed_events` (Stripe webhook signature + idempotency)، واليدوية بإيصال + موافقة بشرية.
6. المحفظة: مزدوجة القيد + قفل صفين مرتّب + idempotency_key فريد → مستحيل الازدواج أو السالب.

---

## 16) الحالات المعروفة ونقاط الانتباه (لأي مطوّر قادم)

- **CI يجب أن يكون أخضر** — آخر إصلاحات: بحث الاشتراكات في `/api/v1/search` (join بلا ON كان يُرجع صفر نتائج) + تسريب نطاق الطالب في نفس المسار (أُصلحا في `4aa796c`/`787d9a7`).
- **قاعدة الاختبار:** لا تشغّل pytest على `azad_school` — الحارس سيوقفك (بالتصميم). استخدم `azad_test`.
- **AI وCelery اختياريان بالكامل** — الكود يعمل بلا openai/celery مثبّتين (fallbacks مدمجة).
- **الترميز:** استخدم `query_string={"q": ...}` وليس تضمين العربية في URL نصياً عند اختبار werkzeug client.
- **البحث العالمي** يشمل: مدارس/مستخدمين/صفوف/اشتراكات — الطالب يرى اشتراكاته فقط (فُصل الدور قبل فلتر المدرسة عمداً).

---

## 17) أرقام سريعة (Quick Facts)

| المقياس | القيمة |
|---|---|
| أسطر Python (app/) | ~19,450 |
| قوالب Jinja | 110 |
| مسارات HTTP | 223 |
| Blueprints | 22 + aliases |
| جداول DB | 60 |
| ملفات migration | 9 |
| خدمات (services) | 41 وحدة |
| وحدات core | 15 |
| ملفات اختبار | 116 (integration/ + security/ + unit-style) |
| تغطية Python | 77.5% سطور / 62.6% فروع (هدف CI ≥70% سطور) |
| jobs في CI | 7 |
| مستخدمو الديمو | 29 (كلمة `Azad@2026`) |
