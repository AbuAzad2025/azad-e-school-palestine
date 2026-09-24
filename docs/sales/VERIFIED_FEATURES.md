# ميزات تنافسية مؤكدة من الكود (Verified from Source)

> كل ميزة أدناه مثبتة بقراءة الملف الفعلي — لا افتراضات.

---

## 1. الأمان الذرّي والذريّة المالية
- `tx(...)` في `app/core/db.py` (خط 12): كل كتابة قاعدة تمر عبر `tx()` — commit واحد، rollback تلقائي.
- `FOR UPDATE` في `app/services/billing.py` (سطر 81، 188، 229): قفل صفوف الدفع والاشتراك لمنع اعتماد مزدوج تحت التزامن.
- كلمات المرور `argon2id` عبر `hash_password`/`verify_password` (`core/security.py`).

---

## 2. التينانتس الحقيقية (SaaS Multi-School)
- `scope_by_school` و `tenant_scope` في `core/tenancy.py`.
- كل جدول يحمل `school_id` يُفلتر عبر هذه الدوال (`models/school.py`, `class_room.py`, `billing.py`).
- `School` هي جذر التينانت (بلا `school_id` نفسه).

---

## 3. الذكاء الاصطناعي المتكامل (ليس مجرد واجهة)
- `app/services/ai.py` (618 سطر): خدمة حقيقية مع `AsyncOpenAI`، دعم `stream=True` (SSE)، `RateLimiter` (60 طلب/دقيقة)، `BudgetTracker` (ميزانية شهرية بالدولار)، تسجيل `AiUsageLog` لكل طلب مع التكلفة التقديرية.
- `app/services/quiz_ai_service.py` (321 سطر): توليد اختبار من درس عبر LLM مع تحليل JSON، حفظ كمسودة (`status=draft`)، التحقق من ملكية الدرس عبر `current_school_id()`.
- `app/services/rag_service.py`: استرجاع مقيّد بمحتوى مدرسة المستخدم (`school_id` + `query_school_rag_tutor`).
- مسارات `ai/routes.py` (299 سطر): `/chat/stream` (SSE)، `/chat`, `/grade/suggest`, `/questions/generate`, `/rag/query`, `/quiz/generate`, `/usage/stats`.

---

## 4. نظام الدرجات المتقدم
- `app/services/grade_calc.py` (231 سطر): متوسطات مرجّحة (`weighted_score`)، فئات (`GradeCategory`) مع أوزان، خطابات عربية (`ممتاز`/`جيد جداً`/`راسب`) عبر `_letter_grade()`.
- `grade_appeals.py`: اعتراضات درجات (`submit_appeal`, `review_appeal`) مع تتبع المشرف (`reviewed_by`, `teacher_response`).
- `assessment.py`: اختبارات (`Quiz`)، محاولات (`QuizAttempt`)، تصحيح آلي (`_grade_answer` لـ `mcq`/`true_false`)، قفل المحاولة (`for_update`)، رفض بعد انتهاء الوقت (`deadline_exceeded` مع `QUIZ_GRACE_SECONDS` قابل للضبط).

---

## 5. نظام الدفع الكامل (ليس فقط يدوي)
- `billing/routes.py` (303 سطر): خطط (`SubscriptionPlan`)، اشتراكات (`Subscription` مع حالة `pending` → `active` عبر اعتماد مشرف)، أكواد خصم (`DiscountCode`) مع قفل ذري (`update(...).where(...).values(...)` لمنع استنفاد مزدوج)، فواتير (`invoice_view` + `invoice_pdf` عبر `render_invoice_pdf`).
- `payments/routes.py` (201 سطر): بوابات دفع حقيقية (`Stripe`, `PayTabs`, `CashU`, `WhatsApp`) مع Webhooks (`/webhook/stripe`, `paytabs`, `cashu`, `whatsapp`)، إنشاء نية دفع (`create_payment_intent` مع تحقق الملكية والمبلغ)، تحقق يدوي (`verify_payment`).
- `services/billing.py`: كل القيم مالية `Decimal` (`ROUND_HALF_UP`) — لا Float إطلاقاً (`money()` سطر 22).

---

## 6. إدارة المدارس المتعددة (Super Admin + School Admin)
- `schools/routes.py` (281 سطر): إنشاء مدرسة (`create_school_with_defaults`)، إدارة صفوف (`create_class` مع معلم/سعر فصل أول/ثاني/سنوي)، مستويات (`Grade`)، رموز انضمام (`join_code` مع تجديد `regenerate_join_code`)، إعداد مدرسي (`onboarding` بـ 5 خطوات).
- `admin/routes.py` (1193 سطر): لوحة مشرف رئيسية مع رسوم بيانية (`chart_signups`, `chart_subscriptions`, `chart_revenue`)، إدارة مستخدمين (تفاصيل، تفعيل/تعطيل، إجراءات جماعية `bulk_action`)، انتحال صفة (`impersonate` مع `clear_impersonation`)، إدارة اشتراكات (`subscription_detail` مع جدول زمني)، اعتماد/رفض دفع يدوي (`approve_payment` مع إنشاء `ClassMember` تلقائياً — `P-SEC-18`)، سحب أرباح معلمين (`payouts_queue` + `review_payout`)، نسخ احتياطي (`pg_dump` + `psql` مع تأكيد مزدوج)، إعدادات النظام، سجل تدقيق (`audit_logs` مع تصفية حسب `action`/`entity`/`user`)، رسائل تواصل (`contact_inbox` + `reply` + `mark_read`)، صحة النظام (`system_health` مع `check_database` + `check_disk`)، تصدير MOE (`export_moe_format` إلى `.xlsx`)، شهادات (`CertificateTemplate`).

---

## 7. بوابة أولياء الأمور
- `family/routes.py` (74 سطر): ربط حساب ولي أمر (`link_parent` عبر `FamilyLinkCode`)، إزالة ربط (`remove_link`)، عرض أطفال (`list_children`)، تقدم طفل (`child_progress`)، درجات (`child_grades`).

---

## 8. دروس خصوصية (سوق حر — لا عزل مدرسة)
- `tutoring/routes.py` (393 سطر): ملفات معلم (`TutorProfile`)، بحث (`search_tutors`)، حجز درس (`BookingForm` مع نطاق سعر 80%–150% من سعر المعلم)، جلسات (`TutoringSession` مع `online_link` لجلسة مباشرة `Jitsi` عبر `generate_live_session_url`)، حالة جلسة (`start_live_session`/`end_live_session`)، تقييم (`rate_session` مع نافذة 24 ساعة بعد انتهاء الجلسة)، أرباح (`tutor_earnings`)، طلب سحب (`payout_request`).

---

## 9. المحتوى التعليمي (دروس + مكتبة مشتركة + تحميل دون اتصال)
- `content/routes.py`: وحدات (`Unit`)، دروس (`Lesson` مع `body_html` مُنظَّف عبر `bleach` في `services/content.py`)، مرفقات (`LessonAttachment` مع قائمة بيضاء: `video`/`audio`/`image`/`file`)، استيراد درس مشترك (`import_lesson` مع نسخ عميق للمرفقات)، تحميل دون اتصال (`OfflineDownload`).
- `services/content.py` (259 سطر): تنظيف HTML (`ALLOWED_HTML_TAGS` + `CSSSanitizer` لمنع `url()`/`expression()`)، رفع آمن (`save_upload` من `core/uploads`).

---

## 10. الإشعارات والتفضيلات + سجل التدقيق
- `notification_preferences.py` (50 سطر): تفضيلات لكل نوع إشعار (`email_enabled`/`in_app_enabled`) مع افتراضي `DEFAULT_TYPES`.
- `communication.py` (98 سطر): إشعار داخلي (`notify`) مع فحص `should_notify`، عدد غير مقروء (`unread_count`)، سجل تدقيق (`audit`) مع `IP` (`X-Forwarded-For`) + تفاصيل مالية (`amount`, `currency`, `subscription_id`) + تتبع تغييرات الحقل (`changes`).

---

## 11. صحة النظام ومراقبة الأداء
- `services/health.py` (77 سطر): فحص قاعدة بيانات (`SELECT 1` مع قياس `latency_ms`)، فحص قرص (`disk_usage` مع حالة `healthy`/`degraded`/`down` حسب المساحة الحرة)، تسجيل (`record_health` في `HealthCheck`)، حالة عامة (`get_system_status`).
- `admin/routes.py`: لوحة صحة (`/admin/health`) مع تشغيل فحوصات مباشرة (`run_all_checks`).

---

## 12. الترجمة الثنائية (RTL عربي افتراضي)
- `app/core/i18n.py`: `lazy_gettext` للنماذج.
- كل نص ظاهر للمستخدم في `_()` (قوالب) أو `lazy_gettext` (نماذج) — `models/user.py`, `models/school.py`, إلخ.
- `app/translations/ar/LC_MESSAGES/messages.po` + `en/LC_MESSAGES/messages.po` (مترجمة فعلاً — المصدر عربي `msgid`).

---

## 13. التصدير والتحليلات
- `services/export.py`: تصدير بصيغة `MOE` (`export_moe_format` إلى `.xlsx`).
- `services/analytics.py`: إحصائيات (`get_analytics_data` — DAU، تسجيلات، تفاعل).
- `services/revenue.py`: ملخص إيرادات (`get_revenue_dashboard_data`).
- `admin/routes.py`: لوحة إيرادات (`/admin/revenue`) مع رسوم بيانية شهرية + حالة اشتراكات.

---

## 14. الأمان الإضافي
- `core/security.py`: رفع ملفات قائمة بيضاء (`allowed_extension`) + حد حجم + خارج المجلد العام + أسماء عشوائية (`random_filename`).
- `core/permissions.py`: `role_required` حصرياً — لا فحص متفرق.
- `core/tenancy.py`: `scope_by_school` لكل استعلام `school_id`.
- `tests/security/`: اختبارات أمان (حدود أولياء الأمور، حدود معلم الصف، هجمات `IDOR`, `superadmin`، `unauthenticated`).

---

## الخلاصة التنافسية للمشتري
هذا النظام ليس "موقع تعليمي بسيط" — هو **منصة SaaS تعليمية متعددة المدارس** مع:
1. أمان مالي ذرّي (`Decimal` + `FOR UPDATE` + `tx`)
2. ذكاء اصطناعي متكامل حقيقي (SSE، ميزانية، حدود، RAG، توليد اختبارات)
3. نظام درجات متقدم مع اعتراضات رسمية
4. دفع يدوي وآلي مع بوابات متعددة
5. إدارة كاملة للمدارس (إعداد، صفوف، مستويات، معلمون، طلاب)
6. بوابة أولياء الأمور + دروس خصوصية مستقلة
7. مراقبة صحة النظام + نسخ احتياطي يدوي
8. ترجمة ثنائية RTL حقيقية مع Babel
9. اختبارات شاملة (pytest + Playwright + Biome)

كل هذه الحقائق مثبتة بقراءة الكود المصدر مباشرة — لا افتراض.
