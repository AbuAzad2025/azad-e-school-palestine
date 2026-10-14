# تحليل الفجوات الوظيفية والتشغيلية والتجربة — قبل الإطلاق الرسمي

منصة مدرسة أزاد الإلكترونية — v2.0
نطاق التحليل: الجاهزية الوظيفية والتشغيلية وتجربة الاستخدام للأدوار الأربعة (مالك المنصة، المدرس، الطالب، ولي الأمر).

## منهجية التحقق

هذا التحليل **ليس استعراضاً نظرياً**: كل حكم فيه مبني على قراءة الكود الفعلي (مسارات، قوالب، خدمات، ملفات نشر)، ومعه مرجع الملف والسطر. النقاط التي لا يوجد لها أثر في الكود صُنِّفت فجوة، وليست "ميزة قيد التطوير".

ما تم التحقق منه فعلياً:

| البند | النتيجة |
|---|---|
| الأدوار والصلاحيات | `app/models/user.py:17` — `super_admin/school_admin/teacher/student/parent` (ولي الأمر دور كامل لا مجرد تسمية) |
| عزل التينانتس | `app/core/rls.py` + `app/services/access.py` — نطاقات قراءة مرفوعة مقيّدة |
| الذرّية المالية | `app/services/wallet_service.py` (قيد مزدوج Decimal) + `app/services/tutoring.py:579` `_append_commission_ledger` |
| دفع الاشتراكات | `app/modules/billing/routes.py` (خطط → اشتراك → دفع يدوي → اعتماد) |
| سوق الدروس الخصوصية | `app/modules/tutoring/routes.py` (ملف، طلبات، جلسات، تقييم، أرباح، طلب سحب) |
| المدفوعات الإلكترونية | `app/modules/payments/routes.py` + `app/templates/payments_ui/index.html` |
| الإشعارات | `app/services/communication.py`، `app/services/email.py`، `app/services/whatsapp.py` |
| المهام الدورية | `app/__init__.py:322` (CLI)، `scripts/cron_jobs.sh`، `scripts/daily_reminders.py` |

## الحكم التنفيذي

الطبقات التقنية والمالية **سليمة فعلاً** كما ورد في الوصف: القيد المزدوج يُكتب على إتمام الجلسة، الطلب المزدوج/الاعتماد المزدوج يفشلان برسالة مستخدم لا انهيار، والانتهاء يُفرض عند الوصول لا بالاعتماد على cron.

لكن أمام الإطلاق الرسمي هناك **5 فجوات حاجبة**، أربع منها تجعل تدفقات مالية أو تعليمية **غير قابلة للتنفيذ من واجهة المستخدم أصلاً** (وليست مزعجة فقط):

1. **الطالب الفردي المدفوع يقع في طريق مسدود**: الاشتراك يُنشأ `pending` ثم يُحوَّل لصفحة لا تحتوي أي طريقة للدفع ولا تعرض الطلب المعلّق.
2. **صفحة اشتراك صفوف المدرسة غير مُربوطة من أي مكان** — الطالب يُطالب بالاشتراك عبر رابط لا وجود له في الواجهة.
3. **ولي الأمر لا يستطيع الدفع لابنه** — كل مسارات الدفع مقيّدة بدور الطالب وبملكية الاشتراك.
4. **صفحة أرباح/سحب المدرس غير مُربوطة** — أهم شاشة للمعلم (المال) غير قابلة للاكتشاف إلا بكتابة الرابط يدوياً.
5. **لا توجد واجهة محفظة على الإطلاق** — المحفظة REST API فقط، ولا صفحة رصيد أو سجل أو شحن.

---

## 1. مالك المنصة (مالك المنصة)

### ✅ جاهز

| القدرة | المرجع |
|---|---|
| إدارة مدارس متعددة (قائمة، تفاصيل، إدارة) | `app/modules/admin/routes.py` → `schools_list` / `school_detail` + `app/templates/admin/` |
| اعتماد تسجيل مدارس جديدة دون تدخل يدوي في قاعدة البيانات | `app/modules/school_approvals/routes.py` + `app/services/school_approvals.py` + `admin/pending_registrations.html` |
| نظرة مالية للمدرسة: صفوف/طلاب/معلمين/اشتراكات/متأخرات | `admin/school_admin_dashboard.html` (يستدعي `app/services/finance.py`) |
| الإيرادات والنمو | `app/templates/admin/revenue.html` (إجمالي الإيرادات، عدد المعاملات، معدل النمو) |
| الاعتماد المالي اليدوي للمدفوعات | `admin/pending_payments.html` + `billing.review` (اعتماد/رفض + قفل صف + إشعار + بريد) |
| أكواد الخصم مع قفل ذرّي (`update … where used_count < max_uses`) | `billing.discount_*` + `app/services/billing.py:428` |
| الفواتير وPDF | `billing.invoice_view` / `invoice_pdf` + `app/services/invoice.py` |
| قائمة سحب أرباح المعلمين مع قفل وتدقيق | `admin.payouts_queue` / `admin.review_payout` `app/modules/admin/routes.py:1253` و`:1269` |
| قوائم تدقيق، نسخ احتياطي، صحة النظام، استخدام AI، تصدير MoE | `admin/audit_logs.html`، `admin/backups.html`، `admin/health.html`، `admin/ai_usage.html`، `admin/moe_export.html` |
| فرض الاشتراك | **لا يعتمد على cron**: `app/services/access.py:_has_valid_subscription` يرفض `end_at < now` عند الوصول |

### ⚠️ فجوات

| الفجوة | الأثر | المرجع |
|---|---|---|
| **لا واجهة لعرض عمولات المنصة** — صفر مطابقة لكلمة عمولة/commission في قوالب الأدمن، بينما القيود تُكتب فعلاً | المالك لا يرى إيراد العمولات (20%) رغم أنه مُسجَّل في الدفتر | `grep -rn "عمولة\|commission" app/templates/admin/` → لا نتائج؛ الكتابة في `app/services/tutoring.py:579` |
| **لا مستكشف دفتر محفظة للأدمن** — سجل الحركات متاح فقط عبر API لمستخدم محدّد | لا مراجعة عيّنة ولا مطابقة (reconciliation) من الواجهة | `app/modules/wallet_api.py` → `/api/v1/wallet/transactions` (يتطلب `user_id`) |
| **لا مسار لعكس/إبطال حركة مالية** مع أن الحالة `reversed` معرّفة | أي خطأ مالي يُصحَّح بقيد إداري يدوي فقط | `app/models/wallet.py` (`status` completed/reversed/pending`) |
| **لا واجهة إيداع** — الإيداع الإداري متاح فقط عبر `POST /api/v1/wallet/deposits` | لا شحن محفظة لطالب بدل عن طالب عبر الواجهة | `app/modules/wallet_api.py:wallet_deposit` |
| **لا جدولة تشغيلية حقيقية** — `deploy/docker-compose.production.yml` بلا خدمة cron/worker؛ المهام في `scripts/cron_jobs.sh` بمسارات `/path/to/...` | تذكيرات التجديد والنسخ الاحتياطي تعتمد على خطوة يدوية على الخادم | `scripts/cron_jobs.sh`، `deploy/docker-compose.production.yml` |
| **مهمة معالجة المدفوعات المعلّقة معطوبة**: تستخدم `datetime`/`timedelta` بلا استيرادها | الوظيفة تفشل بـ `NameError` كل 5 دقائق بلا أثر ظاهر | `scripts/cron_jobs.sh` (مهمة `*/5`) |
| `pg_cron` مُفعَّل في إعدادات postgres لكن بلا أي مهمة مسجّلة | إعداد ميت يوهم بوجود جدولة | `deploy/postgresql.conf.production:130` |

---

## 2. المدرس (المدرس)

### ✅ جاهز

| القدرة | المرجع |
|---|---|
| إدارة الصفوف والدروس | `app/modules/schools/routes.py`، `app/modules/content/routes.py` |
| الاختبارات والواجبات والتصحيح والتقييم بالسلّم (rubric) | `app/modules/assessment/routes.py`، `app/modules/grades/routes.py`، `grades/rubric_*` |
| الحضور اليومي (حاضر/غائب/متأخر/بعذر + ملاحظة) | `grades.attendance` + `app/templates/grades/attendance.html` |
| سجل الدرجات وتقارير الطلاب والتقدم | `grades.gradebook`، `progress.class_overview`، `report_card` |
| هيكل الدروس الخصوصية: ملف، طلبات، جلسات، بث مباشر، تقييم | `app/modules/tutoring/routes.py` |
| **دفتر P7 مزدوج القيد يعمل فعلاً** على إتمام الجلسة (ساقان: قبض المعلم + عمولة المنصة) بمفاتيح idempotency | `app/services/tutoring.py:579` `_append_commission_ledger` |
| أرباح المعلم + طلب سحب (حد أدنى 200₪، قفل على العمولات المعلّقة) | `tutoring.tutor_earnings`، `tutoring.payout_request`، `app/services/tutoring.py:659` |

### ⚠️ فجوات

| الفجوة | الأثر | المرجع |
|---|---|---|
| **شاشة الأرباح وطلب السحب غير مُربوطة من أي مكان** (صفر روابط في القوالب وJS) | المدرس لا يعرف أن ماله متاح للسحب؛ الوصول يتطلب حفظ الرابط يدوياً | `grep -rn "tutor_earnings" app/templates app/static` → لا نتائج؛ الداشبورد يعرض "ملفي كمعلم" و"طلباتي وجلساتي" فقط |
| **الرصيد في المحفظة قد يتباعد عن سجل العمولة**: إن لم يوجد صف محفظة للمعلم تُتخطى ساقا الدفتر بلا رسالة | سجل المحفظة/الرصيد ناقص بينما "المتاح للسحب" صحيح — مصدر ارتباك عند المطابقة | `app/services/tutoring.py` → `commission_ledger_skipped_no_wallet` (تسجيل فقط) |
| **تصحيح الواجب يُشعر الطالب ولا يُشعر ولي الأمر** | المدرس يظن أن التقييم وصل البيت | `app/modules/grades/routes.py:188` (إشعار للطالب فقط) |
| لا توجد شاشة "محفظتي" بمعنى الرصيد والسجل للمعلم | لا يقدر المعلم ربط سجل الجلسات بسجل المحفظة | لا وجود لقوالب محفظة (`grep -i wallet app/templates` → نتائج غير ذات صلة) |

---

## 3. الطالب (الطالب)

### ✅ جاهز

| القدرة | المرجع |
|---|---|
| الانضمام بالرمز + كشف الصفوف | `schools.class_join`، `schools.my_classes` |
| الدروس والمواد والتنزيل للاستخدام بلا اتصال (PWA) | `content.class_lessons`، `content.offline_downloads`، `app/static/sw.js`، `manifest.json` |
| الاختبارات والواجبات والتسليم | `app/modules/assessment/routes.py`، `grades.assignment_submit` |
| التقدم والتقارير والشارات | `progress.my_progress`، `report_card`، `app/modules/gamification` |
| المساعد الذكي (عادي + بثّ) مع حصص | `app/modules/ai/routes.py` |
| الإشعارات الداخلية والبريدية وتفضيلاتها | `notifications.index`، `app/services/notification_preferences.py` |
| العربية هي المصدر والنصوص كلها عبر `_()` | كل القوالب + `app/translations/*` مُجمَّعة |
| الكورسات الفردية العامة | `individual.catalog` / `individual.my_courses` |

### ❌ فجوات (الأخطر)

| الفجوة | الأثر | المرجع |
|---|---|---|
| **الطالب الفردي المدفوع في طريق مسدود**: الاشتراك يُنشأ `pending` بلا عضوية، ثم يُحوَّل إلى "كورساتي" التي تعرض **العضويات الفعّالة فقط** — فلا يرى الطلب ولا يوجد أي زر دفع | الطالب لا يمكنه إكمال الشراء، ولا يفهم لماذا لم يُفتح الكورس. القناة الذاتية **لا تجمّع إيراداً** | `app/services/individual.py:subscribe_to_class` (P-SEC-07) + `app/modules/individual/routes.py:subscribe` + `app/templates/individual/dashboard.html` |
| **صفحة اشتراك صفوف المدرسة (`/billing/<class_id>`) غير مُربوطة من أي قالب** | رسالة `join_class` تقول "اشترك عبر صفحة الاشتراك" بلا رابط؛ الطالب يواجه 403 بلا مخرج واضح | `grep -rn "class_billing" app --include=*.html` → صفر نتائج؛ المصدر الوحيد للرابط `app/services/email.py:210` (أي: من البريد فقط) |
| **`/payments` صفحة تجريبية**: زر "اختيار" يُنفّذ `alert()` و`console.log` فقط، وغير مُربوطة من القائمة | واجهة "طرق الدفع" تبدو ميزة قائمة وهي غير عاملة | `app/templates/payments_ui/index.html` (بلوك `scripts`) |
| **لا واجهة محفظة**: لا رصيد، لا سجل، لا تعبئة. الإيداع لأدمن فقط | الطالب لا يمكنه تجهيز رصيد لأي خدمة داخلية | `app/modules/wallet_api.py` (API فقط) |
| **دفع الجلسة الخصوصية بتصريح ذاتي**: زر "تأكيد استلام الدفع (يدوي)" يُعلّم الجلسة مدفوعة بلا حركة مال ولا تأكيد من المدرس | ثقب أمانة/إساءة استخدام في مسار مالي حقيقي | `app/modules/tutoring/routes.py:session_pay` |

---

## 4. ولي الأمر (ولي الأمر)

### ✅ جاهز

| القدرة | المرجع |
|---|---|
| دور كامل + ربط الأسرة بالرمز (الطالب يولّد، ولي الأمر يربط/يفك) | `app/modules/family/routes.py`، `app/services/family.py`، `family/generate_code.html` |
| إشراف قراءة فقط على صفوف الأبناء | `app/services/access.py:can_view_class` (فرع الدور `parent`) |
| صفحات الدرجات والتقدم للابن | `family.child_grades`، `family.child_progress` (`@parent_of_required`) |
| استعلامات واتساب لأولياء الأمور (حضور/متابعة الأبناء) | `app/services/whatsapp.py` (`_children_ids`، خريطة حالات الحضور) |
| قالب بريد تنبيه غياب جاهز بالعربية | `app/services/email.py:170` |

### ❌ فجوات

| الفجوة | الأثر | المرجع |
|---|---|---|
| **لا يستطيع الدفع لابنه**: كل مسارات الدفع مقيّدة `role != student → 403`، و`payment_create` تشترط `sub.user_id == current_user.id` | السؤال الأساسي "حالة رسوم ابني" بلا جواب في المنصة | `app/modules/billing/routes.py:subscribe_route` و`payment_create` |
| **لا شاشة رسوم/كشف حساب لولي الأمر** (اشتراكات الأبناء، المتبقي، حالة الدفع، الإيصالات) | لا شفافية مالية للأسرة إطلاقاً | `app/templates/family/` = 4 قوالب فقط: `index`، `generate_code`، `child_grades`، `child_progress` |
| **`child_progress.html` لا يعرض تقدماً**: قائمة صفوف + شريحة ثابتة "نشط" بلا نسبة إنجاز أو معدل أو حضور | التبويب الوحيد المخصص للمتابعة شكلي | `app/templates/family/child_progress.html` |
| **لا عرض حضور لولي الأمر**: الحضور أداة معلم فقط؛ الاستعلام الوحيد عبر واتساب | ولي الأمر لا يرى سجل غياب ابنه في المنصة | `app/templates/grades/attendance.html` مقيّد بـ `can_teach` |
| **تنبيه الغياب "ميت"**: `send_absence_alert_email` معرّفة ومغطّاة باختبار وحدة لكن **لا يستدعيها أي مسار أو مهمة** | وعد التنبيه التلقائي غير مُنفَّذ | `grep -rn "send_absence_alert_email" app scripts` → التعريف فقط |
| **لا إشعار لولي الأمر عند رصد درجة** | يحتاج فتح المنصة يدوياً ليعرف | `app/modules/grades/routes.py:188` |
| قائمة ولي الأمر لا تتضمن رابط "أبنائي" (`family.index`) | لا يجد إدارة الربط إلا من الداشبورد | `app/templates/partials/navbar.html` (فرع `is_parent()`) |
| ولي الأمر خارج أدوار `wallet_api` | لا يمكنه شحن محفظة ابنه | `app/modules/wallet_api.py` decorators |

---

## التوصيات — بترتيب الأولوية

### الموجة P0 — حاجبة للإطلاق (المال والوصول)

1. **إغلاق حلقة الدفع للطالب الفردي المدفوع**
   - أضف شاشة/قسم "اشتراكات معلّقة" في `app/templates/individual/dashboard.html` يُمرَّر إليها الاشتراكات `pending` (عبر `list_subscriptions(user_id, status="pending")`)، مع زر انتقال مباشر إلى صفحة الدفع.
   - أعد التوجيه بعد `individual.subscribe` إلى تلك الشاشة بدل `individual.my_courses` عند وجود اشتراك مدفوع.
2. **ربط صفحة اشتراك الصفوف**
   - زر/بانر "اشترك الآن" في `app/templates/schools/class_detail.html` والبطاقة في `auth/dashboard.html` نحو `url_for('billing.class_billing', class_id=...)`، وحوّل رسالة `join_class` النصية إلى رابط فعلي.
3. **تمكين ولي الأمر من الدفع لابنه**
   - وسّع `_has_valid_subscription` / `payment_create` بمسار "الدافع" (`payer_id` على الاشتراك) مع فحص `is_parent_of`، وأضف قسم "الرسوم والاشتراكات" في `family/index.html` لكل ابن (الحالة، المتبقي، رفع الإيصال، تنزيل الفاتورة).
4. **إبراز شاشة الأرباح للمدرس**
   - رابط "أرباحي" في `partials/navbar.html` وفي إجراءات داشبورد المدرس (`auth/dashboard.html`) نحو `tutoring.tutor_earnings`، وبطاقة رصيد/متاح للسحب في الداشبورد.
5. **إزالة واجهة الدفع الوهمية**
   - إما تنفيذ `/payments` فعلياً (تحويل إلى بوابة عبر `payments_ui` + `create-intent`)، أو حذفها من التسجيل وإخفاؤها حتى تنفيذها — لا يجوز إطلاق صفحة زرّها `alert()`.

### الموجة P1 — ثقة مالية وشفافية

6. **تقرير عمولات المنصة للأدمن** (استعلام `tutor_commission` مجمّعاً بالشهر/المدرسة) وأضفه إلى `admin/revenue.html`.
7. **مستكشف دفتر محفظة للأدمن** مع واجهة عكس حركة (`status="reversed"`) وقيد مقابل، بدل الاعتماد على API يدوي.
8. **واجهة إيداع إداري** في لوحة الأدمن تغلّف `wallet_service.admin_credit` (بدلاً من استدعاء API من خارج المنصة).
9. **إصلاح مهمة المدفوعات المعلّقة** في `scripts/cron_jobs.sh` (استيراد `datetime`/`timedelta`) أو نقلها إلى CLI رسمي (`flask expire-pending-payments`) مثل `expire-subscriptions`.
10. **تشغيل الجدولة فعلياً**: خدمة cron/worker في `deploy/docker-compose.production.yml` أو timer في `deploy/azad-e-school.service`، وإزالة `pg_cron` إن لم تُستخدم.

### الموجة P2 — تجربة الأسر والتعليم

11. **تعميق `family/child_progress.html`**: نسبة إنجاز الدروس، متوسط الدرجات، سجل الحضور، وحدة زمنية (تلتقط `Attendance` الموجود: `app/models/attendance.py`).
12. **تشغيل تنبيهات الغياب**: مهمة يومية تستدعي `send_absence_alert_email` لغير الحاضر (وتُسجَّل في `ReminderLog`-نمط جدول لمنع التكرار)، وتوصيل `notify()` لولي الأمر عند رصد درجة.
13. **مسار الدفع الآمن للجلسات الخصوصية**: تأكيد مزدوج (طالب + مدرس) أو تسوية عبر المحفظة بدل التصريح الذاتي.

## قيود التحليل

- التحليل ساكن (قراءة كود وقوالب)، لا اختبار نقر حيّ في متصفح؛ الأحكام مبنية على عدم وجود مسار/رابط في الكود، وهو حكم قاطع على مستوى الكود لكنه لا يقيس الإرباك البصري.
- لم تُختبر تجربة الجوال/WCAG في هذا التحليل (مغطّاة جزئياً بـ `tests/test_wcag_aa.py`، `tests/e2e/app.spec.js`).
- أوامر الجودة (`ruff`/`mypy`/`pytest`) لم تُعَد لأن هذا التغيير **توثيقي فقط** ولا يمس كود التطبيق.
