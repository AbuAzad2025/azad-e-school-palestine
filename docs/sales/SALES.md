# Azad E-School Palestine — وصف تسويقي للبيع

## العنوان
**نظام إدارة تعليمي ومدرسي متكامل وجاهز للتشغيل** — Azad First Edition

## المشكلة التي يحلها
كل مدرسة أو معهد تعليمي يريد إطلاق منصته الرقمية يواجه تحديين: تكلفة التطوير (أشهر من العمل) وصعوبة الصيانة. هذا النظام يختصر الطريق — كود مصدر كامل (Full Source) جاهز للتشغيل الفوري، مع دعم متعدد المدارس (SaaS Multi-Tenant)، صلاحيات متدرجة، وواجهة عربية RTL احترافية.

## الفئة المستهدفة
- مستثمرو القطاع التعليمي.
- شبكات المدارس الخاصة والمعاهد.
- مطورو البرمجيات الراغبون في إطلاق منتجات SaaS تعليمية دون البدء من الصفر.

## أبرز المميزات التنافسية (مؤكدة من الكود المصدر)
- **أمان مالي ذرّي (Verified):** كل القيم `Decimal(10,2)` مع `ROUND_HALF_UP` (`services/billing.py`:22) — لا Float إطلاقاً. قفل `FOR UPDATE` على صفوف الدفع والاشتراك (`billing.py`:81,188,229) لمنع اعتماد مزدوج تحت التزامن.
- **ذكاء اصطناعي متكامل حقيقي (Verified):** خدمة `AiService` (`services/ai.py`:618 سطر) مع `AsyncOpenAI` حقيقي، تدفق `SSE` (`routes/ai.py`:42-103)، `RateLimiter` (60 RPM)، `BudgetTracker` شهري بالدولار، تسجيل `AiUsageLog` مع التكلفة التقديرية. `quiz_ai_service.py` (321 سطر): توليد اختبار من درس عبر LLM مع حفظ كمسودة (`status=draft`). `rag_service.py`: استرجاع مقيّد بمحتوى المدرسة (`school_id`).
- **نظام درجات متقدم مع اعتراضات رسمية (Verified):** متوسطات مرجّحة (`grade_calc.py`:231 سطر) مع خطابات عربية (`ممتاز`/`جيد جداً`). اعتراضات (`grade_appeals.py`:65 سطر) مع تتبع المشرف.
- **دفع كامل — يدوي وآلي (Verified):** خطط (`SubscriptionPlan`)، اشتراكات (`Subscription`: `pending` → `active` عبر اعتماد بشري)، أكواد خصم (`DiscountCode`) مع قفل ذري (`update(...).where(...)` — `billing.py`:424)، فواتير (`invoice_pdf` — `routes/billing.py`:285-303)، بوابات (`Stripe`/`PayTabs`/`CashU`/`WhatsApp`) مع Webhooks (`routes/payments.py`:14-58) + واجهة دفع (`payments_ui` — `routes/payments.py`:60-153).
- **إدارة مدارس متعددة حقيقية (Verified):** `scope_by_school` (`core/tenancy.py`) + `tenant_scope`. إدارة كاملة (`schools/routes.py`:281 سطر): مدارس، صفوف (`ClassRoom` مع معلم وأسعار فصلية/سنوية)، مستويات (`Grade`)، رموز انضمام، إعداد مدرسي (`onboarding` 5 خطوات).
- **صحة ومراقبة + نسخ احتياطي (Verified):** `health.py` (`check_database` مع `latency_ms`، `check_disk`)، نسخ احتياطي يدوي (`pg_dump` + `psql` مع تأكيد مزدوج — `admin/routes.py`:672-744).
- **بوابة أولياء أمور + دروس خصوصية مستقلة (Verified):** `family/routes.py` (ربط عبر `FamilyLinkCode`، تقدم/درجات أطفال). `tutoring/routes.py` (393 سطر: ملفات معلم، حجز مع نطاق سعر 80%–150%، جلسات مباشرة `Jitsi`، تقييم، أرباح، سحب).
- **محتوى تعليمي آمن (Verified):** `content/routes.py` + `services/content.py` (259 سطر — تنظيف HTML عبر `bleach` مع `CSSSanitizer`، رفع آمن بقائمة بيضاء، استيراد درس مشترك).
- **ترجمة ثنائية RTL حقيقية (Verified):** `core/i18n.py` (`lazy_gettext`) + `translations/ar` و `en` عبر Babel (`_()` في القوالب). المصدر عربي (`msgid`).
- **صلاحيات دقيقة (Verified):** `role_required` (`core/permissions.py`) حصرياً — لا فحص متفرق. أدوار: `super_admin`, `school_admin`, `teacher`, `student`, `parent`.
- **أمان رفع الملفات (Verified):** `core/uploads.py` (قائمة بيضاء + حد حجم + أسماء عشوائية خارج المجلد العام).
- **اختبارات شاملة (Verified):** `tests/` (pytest + Playwright E2E + Biome JS) — تغطية حقيقية لكل طبقة (`tests/security/`، `tests/unit/`).

## طريقة التسليم
- كود مصدر كامل عبر مستودع خاص (GitHub Private Repo) أو أرشيف ZIP.
- عقد نقل ملكية (Exclusive) أو ترخيص استخدام (Non-Exclusive) حسب الاتفاق.
- دعم فني محدود لفترة ما بعد البيع (اختياري).

## السعر المقترح (إرشادي)
- **بيع حصري (Exclusive):** 15,000 – 30,000 دولار أمريكي (حسب السوق المستهدف).
- **ترخيص غير حصري (Non-Exclusive):** 2,500 – 5,000 دولار أمريكي لكل مشترٍ عبر Gumroad / Sellix.

---
*المشروع مطور بواسطة أحمد غنام — أزاد للأنظمة الذكية.*
