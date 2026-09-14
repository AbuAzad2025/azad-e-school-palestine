# Runbook — دليل الاستجابة للحوادث

منصة مدرسة أزاد الإلكترونية — إجراءات التشغيل عند الأعطال

## تصنيف الخطورة

| المستوى | الوصف | أمثلة | زمن الاستجابة |
|---|---|---|---|
| **SEV-1** | المنصة متوقفة كلياً أو بيانات معرضة للخطر | 500 على كل الطلبات، تسريب قاعدة بيانات، RLS معطّل | فوري |
| **SEV-2** | ميزة أساسية معطّلة | تسجيل الدخول يفشل، رفع الفيديو يفشل للجميع | ≤ 30 دقيقة |
| **SEV-3** | خلل جزئي مع بديل | بطء الاستجابة، فشل إرسال بريد فردي | ≤ يوم العمل |

## الفحص الأولي

```bash
# 1. فحص صحة الخدمة
curl -fsS https://<domain>/health || echo "HEALTH FAILED"
curl -fsS https://<domain>/health/deep   # يفحص قاعدة البيانات أيضاً

# 2. سجلات الخدمة (systemd)
sudo journalctl -u azad-e-school -n 200 --no-pager

# 3. حالة الحاويات (إن كنت على Docker)
docker ps
docker logs --tail 200 azad-e-school
```

## سيناريو: المنصة لا تستجيب (SEV-1)

1. تأكيد من `/health` ومن مزوّد الاستضافة (حالة الـ VM/الحاوية).
2. `sudo journalctl -u azad-e-school -n 500` — ابحث عن أول traceback.
3. إذا كانت القاعدة تعمل والخطأ من التطبيق:
   ```bash
   sudo systemctl restart azad-e-school
   curl -fsS https://<domain>/health
   ```
4. إذا كان الهجوم سبباً (rate-limit مفعّل): راجع سجلات الـ proxy وفعّل الحجب المؤقت.

## سيناريو: فشل ترقية قاعدة البيانات (SEV-1)

1. أوقف النشر فوراً (لا تُكمل `flask db upgrade`).
2. راجع `migrations/versions/` آخر ملف وأصلح الترقية قبل إعادة المحاولة.
3. الرجوع للنسخة السابقة عند تلف البيانات:
   ```bash
   flask db downgrade -1
   ```
4. الاستعادة من نسخة احتياطية (آخر مورد):
   ```bash
   psql "$DATABASE_URL" -f backups/<latest>.sql
   ```
   انظر لوحة الأدمن `/admin/backups` لإنشاء واستعادة النسخ.

## rollback التطبيق

```bash
# الرجوع لإصدار سابق من الصورة (Docker)
docker pull ghcr.io/abuazad2025/azad-e-school-palestine/azad-e-school:<previous-tag>
docker compose -f deploy/docker-compose.production.yml up -d

# أو Git (مع مزامنة الترقيات)
git checkout <previous-tag>
flask db downgrade -1   # فقط إذا رافق الترقية تغيير مخطط
sudo systemctl restart azad-e-school
```

## سيناريو: انقطاع Redis / Celery

- النظام مصمّم للعمل بوضع sync fallback — المهام تُنفَّذ inline مع مهلة 10 ثوانٍ.
- الفحص: `redis-cli ping` → إن فشل أعد تشغيل Redis ثم راقب `/health`.
- ترميز الفيديو الطويل لا يُنفَّذ inline — سيُسجّل `task_dispatch_skipped_no_celery` ويعاد المحاولة عند عودة Redis.

## ما بعد الحادث

- سجّل ملخصاً: الزمن، السبب الجذري، الإجراء، الوقاية.
- افتح issue بقسم `postmortem` إن كان SEV-1/SEV-2.
