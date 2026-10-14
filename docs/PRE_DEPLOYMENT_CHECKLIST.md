# Pre-Deployment & Migration Checklist — خطة الإطلاق الإنتاجي

منصة مدرسة أزاد الإلكترونية — v2.0
**الجمهور:** Release Master / مهندس النشر. تُنفَّذ البنود **بالترتيب**، ولا يُنتقل من قسم لآخر قبل تحقّقه.
**الوثائق المرتبطة:** [`runbook.md`](runbook.md) (الاستجابة للحوادث) · [`production_checklist.md`](production_checklist.md) (فحص عام) · [`ACTIONABLE_WORK_ITEMS.md`](ACTIONABLE_WORK_ITEMS.md) (بنود P0 المتبقية).

> **قاعدة حاكمة:** إذا فشل أي بند تحقّق، **لا استمرار**. أوقف النشر واتبع قسم الرجوع (§6). نشر «بحسن نية» مع بند فاشل هو أسرع طريق لـ SEV-1.

---

## 0. نطاق الإصدار وشروط الدخول

| البند | الحالة المطلوبة | التحقق |
|---|---|---|
| CI أخضر على الـ commit المنشور | pytest + ruff + ruff format + mypy + biome + vitest + playwright | `.github/workflows/ci.yml` |
| شجرة العمل نظيفة | `git status --porcelain` فارغ | لا تعديلات غير مُودَعة |
| وسم الإصدار مُنشأ | `git tag -s v2.0.0 -m "Azad E-School v2.0.0"` | `git describe --tags` |
| حزمة الاختبارات العدائية تمر | `pytest tests/unit/test_cross_tenant_adversarial.py -q` | صفر فشل |
| اختبارات D-series تمر | `pytest tests/unit/test_hotfix_d_series.py -q` | صفر فشل |
| بنود P0 الحاجبة مغلقة | كل `AZ-P0-*` في `docs/ACTIONABLE_WORK_ITEMS.md` مُنجَز | مراجعة المالك |

**تحذير صريح — ينشر هذا الإصدار مع فجوات P0؟** حكم [`docs/STAKEHOLDER_GAP_ANALYSIS.md`](STAKEHOLDER_GAP_ANALYSIS.md) أن خمس فجوات P0 **حاجبة للإطلاق** (طريق مسدود للطالب الفردي المدفوع، ولي الأمر لا يدفع، واجهة `/payments` وهمية، ربط صفحة اشتراك الصفوف، إبراز شاشة أرباح المدرس). قرار النشر معها قرار مالك منتج لا قرار هندسي — ويُكتب في سجل الإصدار أيّها بقي مفتوحاً ولماذا.

---

## 1. التحضير والنسخ الاحتياطي (قبل أي لمس للإنتاج)

- [ ] **لقطة قاعدة البيانات** قبل الترقية، والتحقق من سلامتها لا من مجرد إنشائها:
      ```bash
      python scripts/backup.py
      python scripts/restore_verify.py --latest   # الاستعادة الفعلية على قاعدة مؤقتة
      ```
      نسخة لم تُختبر استعادتها ليست نسخة احتياطية.
- [ ] تأكيد المساحة الحرة: `df -h` (قاعدة البيانات قد تُضاعف حجمها أثناء الترقية).
- [ ] تسجيل نقطة الرجوع: `git rev-parse HEAD` و`flask db current` في سجل النشر.
- [ ] إخطار نافذة صيانة (إن كان الإصدار غير متوافق للخلف).
- [ ] **لا تُشغَّل أوامر الاختبار على قاعدة الإنتاج.** `tests/conftest.py:407` يمنع تفريغ قاعدة تحتوي بيانات، وتجاوزه بـ `ALLOW_TEST_DB_WIPE=1` على الإنتاج = حذف كل البيانات.

---

## 2. تسلسل ترقيات Alembic

**الوضع الحالي:** سلسلة **خطّية واحدة** بلا نقاط دمج — 18 ترقية، الرأس واحد:

```
5c63f56be2b2 (initial) → a1b2c3d4e5f6 → b2c3d4e5f6g7 → c1d2e3f4a5b6
  → d2e3f4a5b6c7 → e3f4a5b6c7d8 → f4a5b6c7d8e9 → a7b8c9d0e1f2
  → g1h2i3j4k5l6 → h2i3j4k5l6m7 → i3j4k5l6m7n8 → j4k5l6m7n8o9
  → k5l6m7n8o9p0 → l5m6n7o8p9q0 → m6n7o8p9q0r1 → n7o8p9q0r1s2
  → o8p9q0r1s2t3 → p9q0r1s2t3u4   ← HEAD
```

| # | المراجعة | ما تُنفّذه |
|---|---|---|
| 1 | `5c63f56be2b2` | المخطط الابتدائي من النماذج |
| 2 | `a1b2c3d4e5f6` | فهارس جزئية + طابع كلمة المرور (audit hardening) |
| 3 | `b2c3d4e5f6g7` | `schools.join_code` |
| 4 | `c1d2e3f4a5b6` | إصلاح طول `student_progress.status` |
| 5 | `d2e3f4a5b6c7` | إصلاحات تدقيق المخطط |
| 6 | `e3f4a5b6c7d8` | فهارس أداء |
| 7 | `f4a5b6c7d8e9` | فهارس أداء ناقصة (v2) |
| 8 | `a7b8c9d0e1f2` | تحقّق نزاهة المخطط (v3) |
| 9 | `g1h2i3j4k5l6` | **سياسات RLS لعزل المستأجرين** |
| 10 | `h2i3j4k5l6m7` | جداول المحفظة |
| 11 | `i3j4k5l6m7n8` | فهارس أداء RLS |
| 12 | `j4k5l6m7n8o9` | فهارس النطاقات الزمنية |
| 13 | `k5l6m7n8o9p0` | روابط واتساب |
| 14 | `l5m6n7o8p9q0` | **تغطية RLS الكاملة لكل المستأجرين** |
| 15 | `m6n7o8p9q0r1` | **`quiz_attempts.display_order`** — مزامنة عمود موجود في النماذج وغير موجود في القاعدة (مصدر 500 متقطّع سابق: العمود يُطلب في استعلام الاختبار) |
| 16 | `n7o8p9q0r1s2` | GUC المدرسة بصيغة تتحمّل NULL |
| 17 | `o8p9q0r1s2t3` | ربط أدوار المستخدم بـ `UserRoleLink` (تسليح التينانت) |
| 18 | `p9q0r1s2t3u4` | RLS عضوية الكورسات الفردية (**HEAD**) |

### خطوات التنفيذ

```bash
# 2.1 توليد القائمة المرتقبة وتأكيد رأس واحد فقط
flask db heads                 # يجب: p9q0r1s2t3u4  — رأس واحد، لا أكثر
flask db current               # ما هو مُطبَّق فعلاً على الإنتاج
flask db history --verbose | head -30   # القائمة المرتقبة

# 2.2 فحص الفرق · لا تُشغَّل ترقية لم تُقرأ
flask db upgrade --sql > migrations/to_apply.sql   # SQL مُولَّد للمراجعة
less migrations/to_apply.sql                       # اقرأ كل DROP/ALTER قبل التنفيذ

# 2.3 التنفيذ داخل مهلة (statement_timeout مضبوط على 30 ثانية في config.py —
#     للترقيات الثقيلة ارفعه للجلسة فقط، ولا تعدّل الإعداد العام)
flask db upgrade

# 2.4 التحقق بعد الترقية
flask db current               # يجب أن يساوي الرأس p9q0r1s2t3u4
```

### تحقّقات ما بعد الترقية (إلزامية)

- [ ] **مزامنة `quiz_attempts.display_order`** (الترقية 15): تأكيد وجود العمود فعلاً — هي الترقية التي كانت تسبّب خللاً متقطّعاً:
      ```sql
      SELECT column_name, data_type, is_nullable FROM information_schema.columns
       WHERE table_name = 'quiz_attempts' AND column_name = 'display_order';
      ```
- [ ] **RLS مفعّلة على كل جدول مستأجر** (الترقيات 9 و14):
      ```sql
      SELECT tablename FROM pg_tables WHERE rowsecurity = false AND schemaname='public';
      ```
      الناتج يجب أن يكون الجداول غير المستأجرة فقط (`schools`, `alembic_version`, جداول النظام). ظهور جدول يحمل `school_id` = **توقف فوري**.
- [ ] **فهارس الأداء** (الترقيات 6, 7, 11, 12):
      ```sql
      SELECT indexname FROM pg_indexes WHERE schemaname='public' AND indexname LIKE 'ix_%' ORDER BY 1;
      ```
      قارن العدد بما قبل الترقية لتأكيد أن الفهارس أُنشئت لا تُخطّيت.
- [ ] **تحقق من الـ GUC بعد الترقية 16**: تسجيل دخول لمستخدم مدرسة وقراءة صف من مدرسته — نجاح القراءة يعني أن `current_setting('app.school_id', true)` يعالج NULL كما هو مقصود.
- [ ] تصفير الـ plan cache ليس مطلوباً، لكن **أعد تشغيل الاتصالات**: `pool_pre_ping` مضبوط، ومع ذلك `sudo systemctl restart azad-e-school` بعد الترقية (§5).

### مصفوفة الرفض

| حالة | الإجراء |
|---|---|
| `flask db heads` يعيد أكثر من رأس | **توقف** — حلّل الفروع قبل أي ترقية |
| ترقية فشلت في المنتصف | **توقف** — تقرير `alembic_version` عبر `flask db current`؛ لا `upgrade` ثانياً قبل فحص القاعدة |
| جداول مستأجرة بلا RLS | **توقف** — هذا تسريب بيانات لا خلل عرض |
| `downgrade` يُفقد بيانات (`DROP COLUMN`) | الاستعادة من النسخة الاحتياطية (§1)، لا تراجع Alembic |

---

## 3. تدقيق متغيرات البيئة

`.env` على الخادم فقط (غير مرفوع لـ git). المصدر المرجعي: `.env.production.example` + `config.py`.

### إلزامية — الخدمة لا تعمل أو تعمل بشروط خاطئة بدونها

| المتغير | القيمة الإنتاجية | الافتراضي عند الغياب | الأثر عند الخطأ |
|---|---|---|---|
| `SECRET_KEY` | عشوائي 48 بايت+ | `None` | تعطّل الجلسات والتوقيعات — **حاجب مطلق** |
| `DATABASE_URL` | `postgresql+psycopg2://…` | `None` | **حاجب مطلق** (لا اتصال) |
| `FLASK_ENV` | `production` | `production` (احتياط) | ضبط صريح يمنع الانزلاق لبيئة تطوير |
| `TESTING` | **`0` أو غير موجود** | `0` | `1` يعني `TESTING=True` في الإنتاج |
| `ALLOW_TEST_DB_WIPE` | **غير موجود إطلاقاً** | — | `1` يزيل مانع حذف قاعدة الإنتاج (انظر `tests/conftest.py:407`). **يُضبط في بيئة اختبار مؤقتة فقط، ولا يُضبط في الإنتاج أبداً** |
| `SESSION_COOKIE_SECURE` | `1` | `1` | `0` يُرسل الكوكي بلا TLS |
| `TALISMAN_ENABLED` | `1` | `1` | `0` يُعطّل CSP/HSTS |
| `TALISMAN_FORCE_HTTPS` | `1` | `1` | `0` يسمح بـ HTTP |
| `WTF_CSRF_ENABLED` | `True` (افتراضي) | `True` | تعطيله يُلغي حماية CSRF |
| `CORS_ORIGINS` | نطاقات محدّدة | `[]` | **لا يجوز `*`** — مع `CORS_SUPPORTS_CREDENTIALS=1` يعني تسريب جلسات |
| `SWAGGER_ENABLED` | `0` | `0` | `1` ينشر واجهة API التوثيقية علناً |
| `LOG_JSON` | `1` | `0` | `0` يُصعّب التجميع الآلي في الإنتاج |

### وظيفية — تُعطّل ميزة كاملة بصمت

| المتغير | عند الغياب |
|---|---|
| `REDIS_URL` | المهام تُنفَّذ inline بمهلة 10 ثوانٍ؛ الترميز الطويل يُسجَّل `task_dispatch_skipped_no_celery` |
| `RATELIMIT_STORAGE_URL` | `memory://` → حدود الطلبات **لكل عملية** لا للنظام كله (تجاوز فعلي للحد) |
| `EMAIL_ENABLED` | `0` → لا بريد: لا تنبيه غياب ولا إشعار اعتماد دفع |
| `MAIL_SERVER` + `MAIL_USERNAME` + `MAIL_PASSWORD` + `MAIL_DEFAULT_SENDER` | فشل إرسال صامت في السجل |
| `WHATSAPP_APP_SECRET` | **فارغ = رفض كل webhook (fail-closed)** — سلوك مقصود في `config.py`، أي غيابه يحجب القناة لا يفتحها |
| `WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` | لا إرسال واتساب |
| `SENTRY_DSN` | لا مراقبة أخطاء في الإنتاج |
| `ALERT_EMAIL` | لا تنبيهات تشغيلية |
| `BACKUP_ENABLED=1` + `BACKUP_DIR` | لا نسخ احتياطي مجدول |
| `BACKUP_S3_*` | النسخ محلية فقط (تفقد مع فقد الخادم) |
| `PDF_FONT_DIR` | الافتراضي `deploy/fonts` — غياب الخط يُنتج `pdf_font_fallback` في السجل وPDF بخط بديل |
| `STRIPE_SECRET_KEY` | مفاتيح اختبار في الإنتاج = مدفوعات وهمية |

### HMAC وتوقيع الـ webhooks

- [ ] `WHATSAPP_APP_SECRET` = App Secret الإنتاجي (من لوحة Meta) ومُطابق للقيمة في بيئة الويب؛ غيابه يحجب كل webhook بصمت.
- [ ] التحقق من التوقيع مُختبَر على `raw body` لا على JSON مُعاد تسلسله — الانحدار يظهر كـ `403` على كل webhook صامتاً:
      `pytest tests/unit/test_webhook_signature_hardening.py -q`
- [ ] لا سطر سرّ في git: `git grep -nE "sk_live|APP_SECRET=.+|SECRET_KEY=.+" -- ':!.env.example' ':!*.po'` → صفر نتائج.
- [ ] `STRIPE_PUBLISHABLE_KEY` إنتاجي ومطابق للسرّي (خلط الاثنين = فشل صامت في الواجهة).

### فحص آلي قبل النشر

```bash
# 3.i لا ALLOW_TEST_DB_WIPE ولا أسرار مكشوفة في ملف البيئة الإنتاجي
grep -nE "ALLOW_TEST_DB_WIPE|^TESTING=1" .env && echo "❌ STOP" || echo "✅ ok"

# 3.ii تأكيد أن التطبيق يُقلع بإعدادات الإنتاج فعلاً
FLASK_ENV=production python -c "
from app import create_app
app = create_app()
assert app.config['DEBUG'] is False
assert app.config['SECRET_KEY'], 'SECRET_KEY missing'
assert app.config['WTF_CSRF_ENABLED'] is True
assert '*' not in app.config['CORS_ORIGINS'], 'wildcard CORS in production'
assert app.config['SWAGGER_ENABLED'] is False
print('config ok:', app.config['ENV'] if 'ENV' in app.config else 'production')
"
```

---

## 4. الأصول الساكنة والترجمات وإبطال المخزّن المؤقت

### 4.1 ملفات الترجمة (`.mo`)

مصدر النص **عربي**، و`en` تُترجم فقط. ملفات `.mo` الثنائية المُجمَّعة هي ما يقرأه التطبيق وقت التشغيل — `.po` بعد التعديل بلا `compile` = نصوص قديمة أو إنجليزية ناقصة.

```bash
# 4.1.1 التحديث من المصدر ثم التعبئة
pybabel extract -F babel.cfg -o messages.pot .
pybabel update -i messages.pot -d app/translations
#      → املأ ترجمات en في app/translations/en/LC_MESSAGES/messages.po

# 4.1.2 التحقق من عدم وجود نصوص غير مترجمة قبل الترجمة النهائية
python scripts/scan_translations.py      # (أو scripts/dump_untranslated.py للمعاينة)

# 4.1.3 التجميع الإلزامي
pybabel compile -d app/translations

# 4.1.4 تأكيد أن الـ .mo أحدث من الـ .po وفيه المحتوى الجديد
ls -l --time-style=+%s app/translations/{ar,en}/LC_MESSAGES/messages.{po,mo}
python - <<'PY'
import gettext, pathlib
for loc in ("ar", "en"):
    mo = pathlib.Path(f"app/translations/{loc}/LC_MESSAGES/messages.mo")
    t = gettext.GNUTranslations(open(mo, "rb"))
    print(loc, "entries:", len(t._catalog), "| sample:", t.gettext("حدث خطأ"))
PY
```

- [ ] رسائل الأخطاء الجديدة (`app/core/errors.py`) ظاهرة في `en`: الترجمة العربية موجودة، والإنجليزية مُعبّأة (`standard_message` تُرجع نصاً عربياً بلا ترجمة إن نقصت).

### 4.2 الأصول الساكنة

```bash
# 4.2.1 إعادة بناء الحزم المُصغّرة + الـ manifest
python scripts/build_css.py
git status --porcelain app/static/css/dist/       # يجب: تغيير متوقّع ومُراجَع
```

- [ ] `app/static/css/dist/manifest.txt` مُحدَّث (القيم فيه بصمات حزم المحتوى — عدم تحديثه = خدمة CSS قديم).
- [ ] **رفع إصدار الـ Service Worker** — `app/static/sw.js:1` `var CACHE_NAME = "azad-v5";` فيه تعليق صريح: `BUMP THIS VERSION on every deployment`. بدون الرفع، المستخدمون العائدون يخدمون أصولاً قديمة من مخزّن المتصفح.
      ```bash
      grep -n "CACHE_NAME" app/static/sw.js && ls -l --time-style=+%Y-%m-%d app/static/css/dist/*.min.css
      ```
- [ ] `app/static/js/index.js` وغيره حواجز أخطاء/استيرادات ES حديثة بلا `import` مكسور. تحقق عام: `npx biome check app/static/js` + `npx vitest run`.
- [ ] **إبطال المخزّن المؤقت على الحافة/nginx**: ضبط `Cache-Control` للأصول المُبصَّمة (`immutable, max-age=31536000`) وعداها (`no-cache`)؛ لا يُخدَم HTML من المخزّن المؤقت.
- [ ] إن كان Redis مستخدماً كذاكرة تخزين مؤقت: تفريغ المفاتيح المرتبطة بالأصول بعد البناء (المفاتيح المحسوبة بالبصمة تُبطَل تلقائياً، والمفاتيح الثابتة لا).
      ```bash
      redis-cli --scan --pattern "azad:*" | head   # فحص قبل أي مسح
      ```

### 4.3 مجلدات وقت التشغيل

- [ ] `instance/uploads` مملوك لمستخدم الخدمة (`azad`) وقابل للكتابة (وإلا: فشل رفع صامت).
- [ ] `backups/` موجود وقابل للكتابة، ومُثبَّت في compose/الخدمة.
- [ ] `deploy/fonts` مُدرَج في صورة النشر (وإلا: `pdf_font_fallback`).

---

## 5. النشر والتحقق البعدي

### 5.1 خطوات النشر

```bash
# systemd (نشر git مباشر)
cd /opt/azad-e-school
git fetch --tags && git checkout v2.0.0
source .venv/bin/activate
pip install -r requirements.txt
python scripts/build_css.py
pybabel compile -d app/translations
flask db upgrade                     # §2
sudo systemctl restart azad-e-school
sudo systemctl --no-pager status azad-e-school

# أو Docker
git checkout v2.0.0
docker compose -f deploy/docker-compose.production.yml up -d --build
docker compose -f deploy/docker-compose.production.yml ps
```

- [ ] كل الحاويات `running` لا `restarting` (خلاف ذلك: `docker logs --tail 200 <service>`).
- [ ] لا traceback في أول 100 سطر من السجل بعد الإقلاع.

### 5.2 فحوص الصحة

```bash
curl -fsS https://<domain>/health          || echo "HEALTH FAILED"
curl -fsS https://<domain>/health/deep     || echo "DEEP HEALTH FAILED"
curl -fsSI https://<domain>/ | grep -iE "strict-transport-security|content-security-policy"
```

- [ ] `/health` = 200 · `/health/deep` = 200 (يشمل فحص قاعدة البيانات).
- [ ] ترويسات الأمان حاضرة: HSTS + CSP (بـ nonce لا `unsafe-inline`).
- [ ] ترويسة `X-Request-ID` موجودة في الرد (من `app/core/logging.py`) — وهي عمود فقري التتبّع في §5.4.

### 5.3 دخان الوظائف الحرجة (بالترتيب)

| # | المسار | المتوقع |
|---|---|---|
| 1 | `GET /` | 200، صفحة عربية RTL، بلا 500 |
| 2 | `GET /auth/login` | 200 + نموذج + رمز CSRF |
| 3 | دخول طالب حقيقي (بيانات مُجهّزة، لا حساب مُنشأ حديثاً بلا بيانات) | 302 → `/dashboard` |
| 4 | `GET /dashboard` بدور مدرس | 200، يشمل «أطفالي» لدور ولي الأمر ورابط «أرباحي» للمدرس (حسب AZ-P0-04) |
| 5 | فحص الفصل بين المستأجرين: مستخدم مدرسة A يطلب مورد مدرسة B بمعرّف مُخمَّن | 403/404 **بلا أي بايت من بيانات B** |
| 6 | اختبار تلقائي بديل للخطوة 5 | `pytest tests/unit/test_cross_tenant_adversarial.py -q` |
| 7 | `GET /this-does-not-exist` | 404 **بصفحة عربية** من `errors/404.html` (لا صفحة Werkzeug إنجليزية) |
| 8 | `GET /payments` | حسب قرار AZ-P0-05: 404 عربية، أو صفحة دفع فعلية |
| 9 | رفض CSRF: `POST` بلا رمز من صفحة محمية | 400 برسالة عربية «انتهت صلاحية الجلسة…» لا 500 |
| 10 | رسالة خطأ API: `GET /api/v1/<محمي>` بلا جلسة | JSON بالشكل الموحّد `{"error": {"code","message","details"}, "meta": {"version","request_id"}}` |
| 11 | دورة مالية كاملة | تسجيل طالب → اشتراك → دفع يدوي → اعتماد أدمن → وصول للصف → قيد محفظة واحد |
| 12 | `/admin/pending_payments` | ظهور الدفعة المعلّقة، والاعتماد يفشل بصوت عالٍ لا بصمت |
| 13 | اختبار عمولة المدرس | `pytest tests/unit/test_hotfix_d_series.py -q` |

### 5.4 معرّف المتابعة (سلامة الأخطاء)

```bash
# اطلب مورداً غير موجود واقرأ المعرّف المعروض، ثم ابحث عنه في السجل
curl -s -o /dev/null -D - https://<domain>/this-does-not-exist | grep -i x-request-id
sudo journalctl -u azad-e-school -n 500 --no-pager | grep -i "<المعرّف>"
```

- [ ] المعرّف في الصفحة/الرد موجود في السجل **ولم يحمل تفاصيل داخلية للعميل** (لا SQL ولا مسار ملف ولا أثر استثناء).
- [ ] `pytest tests/unit/test_error_handling_sanitization.py -q` أخضر.

### 5.5 الجدولة والمهام الخلفية

- [ ] مهمة الجدولة/الـ worker تعمل: `systemctl list-timers` (أو `docker compose ps`) وتشغيل يدوي ناجح بنفس الأمر.
- [ ] تشغيل يدوي لـ `flask expire-subscriptions` بلا خطأ، والبحث في السجل عن `NameError` في مهمة المدفوعات المعلّقة (`scripts/cron_jobs.sh` — فجوة AZ-P1-09).
- [ ] نسخة احتياطية دورية واحدة على الأقل أنتجت ملفاً بعد النشر، وحجمه معقول (> 1MB).

### 5.6 المراقبة بعد النشر (30 دقيقة)

- [ ] معدّل 5xx أقل من 0.1% (Sentry: لا نوع استثناء جديد يتصاعد).
- [ ] زمن الاستجابة p95 تحت الحد المقبول، وبلا ارتفاع بعد الترقية (الفهارس الجديدة تُستعمل).
- [ ] لا `ERROR` متكرّر جديد في السجل مقارنةً بساعة ما قبل النشر.
- [ ] تسجيل نتيجة الدخان كاملة في سجل النشر مع الـ commit والوسم والوقت.

---

## 6. الرجوع (Rollback)

**القاعدة:** الرجوع يعني **استعادة النظام** أولاً، ثم تشخيص السبب. لا `downgrade` على قاعدة فيها بيانات جديدة إلا بعد حصر ما يُفقَد.

```bash
# 6.1 رجوع التطبيق بلا لمس المخطط (الأكثر شيوعاً وآمناً)
git checkout <previous-tag>
pip install -r requirements.txt && python scripts/build_css.py && pybabel compile -d app/translations
sudo systemctl restart azad-e-school
curl -fsS https://<domain>/health

# أو Docker
docker compose -f deploy/docker-compose.production.yml up -d --build   # بعد checkout الوسم السابق

# 6.2 مخطط ترقية بلا فقد بيانات فقط (ADD COLUMN/ADD INDEX)
flask db downgrade -1        # ثم flask db current للتحقق

# 6.3 آخر مورد: استعادة كاملة
psql "$DATABASE_URL" -f backups/<latest>.sql
```

- [ ] **نشر متوافق للخلف مقدماً:** أفضل إجراء وقائي هو أن تكون الترقيات إضافية، فيكفي رجوع التطبيق (`6.1`) بلا لمس القاعدة.
- [ ] `ADD INDEX` لا يُتراجع فورياً: الفهرس المتبقي غير ضار؛ لا تستعمل `downgrade` لإزالته.
- [ ] `DROP COLUMN` في مرحلة الرفع = **لا تراجع Alembic**؛ استعادة (§6.3) أو إصلاح أمامي.
- [ ] بعد أي رجوع: أعد §5.2 و§5.3 كاملة، وأعد §4 إن تغيّرت الأصول الساكنة (رفع إصدار `sw.js` مرة أخرى).

---

## 7. قالب رسالة الـ commit للنشر

الرسالة المُقترَحة **للشجرة الحالية** (توحيد معالجة الأخطاء + تنقية الرسائل + الحزمة العدائية). ملاحظة: إصلاحات D-series وربط دفتر P7 مُودَعة سلفاً في `cbf686d` + `7e26d62`، فلا يُعاد وصفها كأنها في هذا الـ commit.

```text
fix(core): centralize error handling and stop leaking internals to clients

The app had six scattered error handlers in the factory and mixed response
shapes: a route could answer HTML, another JSON, and Werkzeug served its
English page for every code without a template (400/405/415). Worse, an
unexpected exception inside an API route returned an HTML page, and
flash(str(exc)) in the billing review path echoed raw exception text to the
browser.

- app/core/errors.py (new): single source for error responses — Arabic
  per-status messages, JSON shape shared with api_error via error_payload,
  HTML template per known status plus errors/generic.html for the rest, and a
  correlation id on every error response so a user report maps to a log line
  and nothing else.
- Sanitisation: looks_technical/safe_message replace any SQL, driver, file
  path or Python object leak with the standard Arabic message; full detail
  stays in the log (log_error logs type, message and traceback for 5xx only).
- Classification stays narrow: TxError and unique-constraint violations map to
  409, OperationalError/DBAPIError to 503, CSRFError to 400 with the
  session-expiry message, everything else stays a generic 500 so real bugs are
  never softened into user-error replies.
- app/core/api.py now builds on error_payload, so a route error and a handler
  error cannot drift apart.
- Routes flash through flash_error instead of flash(str(exc)); AI/RAG
  endpoints pass service errors through safe_message.
- Tests: tests/unit/test_error_handling_sanitization.py (sanitisation,
  classification, JSON-vs-HTML shape, correlation id), plus
  tests/unit/test_cross_tenant_adversarial.py, a two-tenant adversarial suite
  asserting no cross-tenant byte ever reaches the other side.
- i18n: new Arabic strings extracted and compiled (ar/en .mo).
- 401 contract kept verbatim from the old handler: API/health paths get a
  JSON 401, browsers get the login redirect; clients without an Accept header
  (tools, test clients) keep the legacy JSON 401 instead of silently becoming
  a redirect.

Verified: ruff check, ruff format --check, mypy app config.py run.py, npx
biome check app/static/js, and pytest tests -q (4776 tests: 4762 passed,
12 skipped, 0 failures in CI-selected files; the only regression found by the
run, TestAdminGuard::test_anonymous_401, was fixed and its file re-run green —
the single remaining failure is in tests/test_erp_ux_sprint4.py, which CI
deselects by policy).

🤖 Generated with Codebuff
Co-Authored-By: Codebuff <noreply@codebuff.com>
```

**قوالب رسائل مصغّرة** (للـ commits الصغيرة أثناء تنفيذ بنود العمل):

```text
fix(AZ-P0-01): show pending subscriptions so a paid individual course can be paid
feat(AZ-P0-03): let a linked parent pay for a child's subscription
fix(AZ-P1-09): import datetime in the pending-payment cron job
chore(deploy): add real cron service to production compose
test(security): pin cross-tenant isolation with an adversarial suite
docs(release): add pre-deployment checklist and actionable work items
```

---

## 8. قيود هذا المستند

- **لم تُشغَّل الترقيات فعلاً** على قاعدة إنتاج أو نسخة منها في إعداد هذا المستند؛ تسلسل §2 مُشتقّ من قراءة `migrations/versions/` (سلسلة خطّية، رأس واحد `p9q0r1s2t3u4`) ومن `down_revision` لكل ملف — لا من تنفيذ.
- **بنود P0 الحاجبة مفتوحة** (`docs/ACTIONABLE_WORK_ITEMS.md`): لا ينبغي قراءة هذا المستند كإقرار بجهوزية وظيفية كاملة، بل كخطة نشر تقنية.
- **قيم متغيرات البيئة الفعلية لم تُقرأ** (`.env` مستثنى من git): الجدول في §3 يصف **المطلوب** والأثر عند الغياب استناداً إلى `config.py` و`.env.production.example`.
- **§5.6 أهداف المراقبة** (معدّل 5xx، p95) تحتاج ضبطاً على خط أساس حقيقي من الإنتاج؛ الأرقام هنا مبدئية للمقارنة النسبية لا مطلقة.
