# منصة مدرسة أزاد الإلكترونية

منصة تعليم إلكتروني لطلاب فلسطين (مناهج فلسطينية) — عربي (RTL) / إنجليزي.
صفوف، دروس، اختبارات، واجبات، درجات، حضور، اشتراكات.

**الإصدار:** Azad First Edition — أزاد للأنظمة الذكية | تطوير: أحمد غنام
**التقنية:** Python + Flask + Jinja2 + PostgreSQL

> الخطة المرجعية الكاملة والميزات والضوابط: [PLAN.md](PLAN.md)

## البنية
```
app/
  core/          # مشترك: صلاحيات، رفع ملفات، أدوات، جلسات
  models/        # نماذج SQLAlchemy (مقسمة حسب المجال)
  modules/       # Blueprints: auth, schools, classes, content,
                 #   assessment, attendance, billing, admin
  templates/     # قوالب Jinja2 (عربي RTL افتراضياً — D8)
  static/        # css/js/img/uploads
  translations/  # ترجمات Babel (ar/en)
tests/           # اختبارات pytest (D9)
docs/            # وثائق تصميم قاعدة البيانات والمعمارية
scripts/         # أدوات مساعدة (نسخ احتياطي، نشر)
instance/        # إعدادات وقت التشغيل (مستثنى من Git)
```

## المعمارية متعددة المستأجرين (SaaS)

المنصة تخدم **عدة مدارس على قاعدة بيانات واحدة**، والفصل بينها مفروض على طبقتين لا على طبقة واحدة:

- **جذر التينانتس:** `School` هي الجذر (وحدها بلا `school_id`)، وكل جدول يحمل `school_id` يمرّ استعلامه عبر `scope_by_school` / `tenant_scope` (`app/core/tenancy.py`). لا استعلام "غير مُقيَّد" على جدول مستأجر.
- **RLS على مستوى قاعدة البيانات:** سياسات Postgres مفعّلة بسلاسل ترقيات كاملة (`g1h2i3j4k5l6` → `l5m6n7o8p9q0` → `n7o8p9q0r1s2` → `o8p9q0r1s2t3` → `p9q0r1s2t3u4`). سياسة القراءة `USING` والكتابة `WITH CHECK` منفصلتان، فحتى الاستعلام الخام الذي لا يذكر `school_id` لا يخرج ببيانات مدرسة أخرى.
- **تينانتس هجين:** `UserRoleLink` يربط المستخدم بالمدارس، فالمستخدم الواحد قد ينتمي لأكثر من مدرسة — والوصول يُقيَّد بنطاق الجلسة الحالي لا بهويته وحدها.
- **نطاق المنصة:** الكتابات النظامية العابرة للتينانتس (مثل إنشاء خطة اشتراك من سعر صف منشور) تُنفَّذ داخل `platform_scope()` صراحةً (`app/core/rls.py`)، لا بتوسيع صلاحيات الكتابة للجميع.
- **الذرّية:** كل كتابة تمرّ عبر `tx(...)` (`app/core/db.py`) — commit واحد وrollback عند أي خطأ؛ لا commit متناثر في المسارات.
- **الصلاحيات:** فحص الأدوار حصراً عبر `role_required` (`app/core/permissions.py`) وحروسه المركّبة (`class_access_required`، `class_teach_required`، `parent_of_required`).
- **الموارد المخفية تُعيد 404 لا 403** حيث يكشف رمز الردّ وجود المورد في مدرسة أخرى.

### الدفتر المالي (P7)

- محفظة بقيد مزدوج بـ `Decimal` (`app/services/wallet_service.py`)، والحركات غير قابلة للتعديل: تصحيح الخطأ بقيد مقابل لا بتعديل سجل.
- إتمام جلسة دروس خصوصية يكتب ساقي الدفتر (قبض المعلم + عمولة المنصة) داخل معاملة واحدة بمفاتيح idempotency (`app/services/tutoring.py`).
- مدفوعات البوابة تُكتب كتدفّق خارجي بمفتاح idempotency، وكل مبلغ صادر يُقرَّب لمنزلتين بـ `ROUND_HALF_UP` قبل التحويل.

## التشغيل محلياً
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env    # ثم عبّئ القيم
flask db upgrade
flask run
```

## الاختبارات وبوابات الجودة

```bash
# حزمة الاختبارات كاملة
.venv\Scripts\python.exe -m pytest tests -q

# عزل المستأجرين — حزمة عدائية بمستأجرين كاملين: أي محاولة عبور تينانت
# يجب أن تنتهي بـ 403/404 وصفر بايت من بيانات الطرف الآخر
.venv\Scripts\python.exe -m pytest tests/unit/test_cross_tenant_adversarial.py -q

# نزاهة الدفتر المالي وidempotency الدفعة والعمولة
.venv\Scripts\python.exe -m pytest tests/unit/test_hotfix_d_series.py -q

# تنقية رسائل الأخطاء ومعرّف المتابعة
.venv\Scripts\python.exe -m pytest tests/unit/test_error_handling_sanitization.py -q

# بوابات الجودة
.venv\Scripts\python.exe -m ruff check app config.py run.py
.venv\Scripts\python.exe -m ruff format --check app config.py run.py
.venv\Scripts\python.exe -m mypy app config.py run.py
npx biome check app/static/js
```

> **تحذير:** اختبارات pytest تُفرِّغ الجداول. `tests/conftest.py` يرفض العمل على قاعدة فيها بيانات إلا بتجاوز صريح `ALLOW_TEST_DB_WIPE=1` — **ولا يُضبط هذا المتغير على الإنتاج مطلقاً**.

## ملفات مرجعية

| المستند | المحتوى |
|---|---|
| [`CHANGELOG.md`](CHANGELOG.md) | سجل التغييرات: العزل، النزاهة المالية، الدفتر، الأخطاء |
| [`docs/STAKEHOLDER_GAP_ANALYSIS.md`](docs/STAKEHOLDER_GAP_ANALYSIS.md) | تحليل الفجوات للأطراف الأربعة بأدلة ملف:سطر |
| [`docs/ACTIONABLE_WORK_ITEMS.md`](docs/ACTIONABLE_WORK_ITEMS.md) | بنود العمل P0/P1/P2 بمعايير قبول وقوالب تذاكر |
| [`docs/PRE_DEPLOYMENT_CHECKLIST.md`](docs/PRE_DEPLOYMENT_CHECKLIST.md) | تسلسل الترقيات، تدقيق البيئة، فحوص ما بعد النشر، الرجوع |
| [`docs/runbook.md`](docs/runbook.md) | الاستجابة للحوادث حسب الخطورة |

## الضوابط (خلاصة من PLAN.md — يُقرأ كاملاً قبل أي مساهمة)
- D1 لا كود وظيفي خارج إطار خطة المراحل المعتمدة.
- D3 لا انتقال لمرحلة دون فحص وموافقة.
- D4 لا أسرار في الكود — كلها في .env.
- D5 الوصول للقاعدة عبر ORM فقط، لا SQL مكتوب يدوياً.
- D6 فحص الصلاحيات على كل route.
- D7 المرفوعات: قائمة بيضاء + حد حجم + خارج المجلد العام + أسماء عشوائية.
- D9 اختبارات pytest لكل مرحلة.
- D10 commits صغيرة وواضحة، لا ملفات كبيرة في الريبو.
