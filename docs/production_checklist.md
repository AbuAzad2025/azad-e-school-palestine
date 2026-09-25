# Production Checklist — قائمة التحقق قبل الإطلاق

منصة مدرسة أزاد الإلكترونية — v2.0

## 1. الأسرار والبيئة

- [ ] `.env` على الخادم فقط (غير مرفوع لـ git) — راجع `.env.example`.
- [ ] `SECRET_KEY` قوي وعشوائي (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
- [ ] `DATABASE_URL` يشير لقاعدة الإنتاج (`postgresql+psycopg2://...`).
- [ ] `REDIS_URL` مضبوط (خلاف ذلك تعمل المهام inline بمهلة 10 ثوانٍ).
- [ ] `FLASK_ENV=production` و`DEBUG=False`.
- [ ] مفتاح PayTabs/CashU الإنتاجي في متغيرات البيئة — لا مفاتيح اختبار.

## 2. قاعدة البيانات

- [ ] ترقية المخطط: `flask db upgrade` (تحقق من رأس واحد فقط: `flask db heads`).
- [ ] سياسات RLS مفعّلة (ترقية `g1h2i3j4k5l6`):
      `SELECT tablename, rowsecurity FROM pg_tables WHERE rowsecurity = false AND schemaname='public';` يجب أن تعيد صفوف الجداول غير المستأجرة فقط.
- [ ] النسخ الاحتياطي التلقائي مُجدول (`/admin/backups` + cron لـ `pg_dump`).
- [ ] فهرس الأداء مثبّت (ترقيات `e3f4a5b6c7d8`, `f4a5b6c7d8e9`, `i3j4k5l6m7n8`).

## 3. التشغيل

- [ ] `deploy/Dockerfile` يبنى بنجاح و`deploy/docker-compose.production.yml` يضم postgres:15 وredis:7 وnginx.
- [ ] خدمة systemd (`deploy/azad-e-school.service`) مفعّلة: `systemctl enable --now azad-e-school`.
- [ ] nginx يُوجّه 80/443 → gunicorn، مع TLS سليم.
- [ ] توليد PDF: خط Amiri مضمّن في الصورة (`deploy/fonts`، رخصة OFL) مع `PDF_FONT_DIR=/app/deploy/fonts`
      (مضبوط في Dockerfile). لاستبداله بخط آخر اضبط `PDF_FONT_DIR`. العلامة في السجلات عند فقدان الخط: `pdf_font_fallback`.
- [ ] `/health` و`/health/deep` يعيدان 200 خلف البروكسي.
- [ ] Sentry / تسجيل الأخطاء يستقبل الأحداث (`SENTRY_DSN` مضبوط).

## 4. الأمان

- [ ] HTTPS إجباري + HSTS.
- [ ] `WTF_CSRF_ENABLED=True` في الإنتاج.
- [ ] كلمة مرور السوبر أدمن argon2id وليست الافتراضية من الـ seed.
- [ ] جدار نار يسمح بمنافذ 80/443 فقط من الخارج.
- [ ] مراجعة `CORS_ORIGINS` — لا تشمل `*` في الإنتاج.

## 5. التحقق النهائي

- [ ] دورة كاملة: تسجيل طالب → اشتراك → دفع يدوي → اعتماد → وصول للصف.
- [ ] فحص الفصل بين المستأجرين: مستخدم مدرسة A لا يرى محتوى مدرسة B.
- [ ] تشغيل الحزمة الكاملة على CI أخضر للـ commit المنشور.
