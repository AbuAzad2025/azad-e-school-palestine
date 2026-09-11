# تقرير تغطية الاختبارات — منصة مدرسة أزاد

> تقرير استكشافي (لا يتضمن تعديلات). مصدر البيانات: ملف `.coverage` الناتج عن `pytest` مع إعداد الفرع (branch) في `.coveragerc`.

## ملخص عام

| المقياس | القيمة |
|---|---|
| إجمالي الأسطر (statements) | 9,161 |
| الأسطر المغطاة | 6,937 |
| **نسبة تغطية الأسطر** | **75.7%** |
| **نسبة التغطية الكلية (branch-aware)** | **71.5%** |
| تغطية الفروع | 54.6% (1,257 من 2,302) |
| الأسطر الناقصة | 2,224 |
| الحد الأدنى المطلوب (`.coveragerc`) | 70% |

النسبة الحالية **71.5%** تفي بالحد الأدنى المطلوب (70%) لكن بهامش ضيق.

## نطاق التغطية حسب الطبقة

| الطبقة | التغطية | ملاحظات |
|---|---|---|
| `app/models/*` | ~100% | نماذج SQLAlchemy مغطاة بالكامل تقريبًا |
| `app/core/*` | متباينة | tenancy/security/i18n/db 100%، لكن api_auth 4% و permissions 37% و rls 44% |
| `app/services/*` | ~75–96% | الأغلب الساحق عالٍ؛ الاستثناءات: ai 54%، rag_service 46%، quiz_ai 57%، payments 61% |
| `app/modules/*/routes` | ~50–97% | الأعلى: contact/export/notifications 100%؛ الأدنى: media 22%، ai 33%، payments 55% |
| `app/tasks/*` | منخفض جدًا | grading 10%، notifications 13%، `__init__` 17%، video 52% |

## ثغرات حرجة (أقل من 30%)

1. **`app/core/api_auth.py` — 4.3% (2/46)**: مصادقة API شبه غير مغطاة. منطقة أمنية عالية الخطورة.
2. **`app/tasks/grading.py` — 9.6% (11/114)**: مهام التصحيح التلقائي غير مغطاة.
3. **`app/tasks/notifications.py` — 13.0% (9/69)**: إرسال الإشعارات الخلفية.
4. **`app/core/openapi.py` — 21.4% (3/14)**: توليد وثائق OpenAPI.
5. **`app/modules/media/routes.py` — 22.0% (11/50)**: رفع/خدمة الوسائط.

## ثغرات متوسطة (30–60%)

| الملف | التغطية | ملاحظات |
|---|---|---|
| `app/modules/ai/routes.py` | 32.6% | مسارات الـ AI |
| `app/core/permissions.py` | 37.0% | فحوص الأدوار — قلب نظام الصلاحيات |
| `app/core/rls.py` | 43.8% | row-level security (تعدد المستأجرين) |
| `app/services/rag_service.py` | 46.2% | خدمة الاسترجاع RAG |
| `app/tasks/video.py` | 51.8% | معالجة الفيديو |
| `app/tasks/reports.py` | 52.8% | تقارير مجدولة |
| `app/services/ai.py` | 54.0% | |
| `app/modules/payments/routes.py` | 54.9% | مسارات الدفع |
| `app/modules/tutoring/routes.py` | 55.9% | |
| `app/modules/schools/routes.py` | 56.9% | |
| `app/services/quiz_ai_service.py` | 57.0% | |
| `app/modules/admin/routes.py` | 58.0% | أكبر ملف routes (614 سطرًا) |
| `app/services/payments.py` | 61.5% | أكبر خدمة دفع (325 سطرًا) |

## ملاحظات إضافية

- **`app/modules/admin/routes.py`** و**`app/services/payments.py`** يمثلان أكبر كتلتين من الأسطر غير المغطاة (258 و125 سطرًا على التوالي). رفع تغطيتهما سيعطي أكبر أثر عددي على النسبة الإجمالية.
- طبقة **`tasks`** (مهام Celery/الخلفية) شبه مهجورة تغطويًا؛ تتطلب اختبارات بعزلة للمهمات أو عبر mocking لجدولة الوظائف.
- **`models`** و**`services` الأساسية** في حالة ممتازة، مما يعكس التزامًا قويًا بمنهجية الطبقات.
- نسبة **الفروع (branch) 54.6%** تشير إلى أن كثيرًا من المسارات الشرطية (حالات الخطأ/edge cases) لا تزال غير مختبرة رغم تغطية الأسطر الجيدة.

## التوصيات (ترتيب بالأثر)

1. تحويل `core/permissions.py` و`core/rls.py` إلى تغطية >80% (أمن النظام كله يعتمد عليهما).
2. رفع `core/api_auth.py` و`modules/media` و`modules/ai` فوق 60%.
3. كتابة اختبارات لعزل مهام `tasks/` (grading, notifications).
4. استهداف `admin/routes.py` و`services/payments.py` لدفع النسبة الإجمالية فوق 80%.
