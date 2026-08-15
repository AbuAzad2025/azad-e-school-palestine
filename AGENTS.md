# AGENTS.md — منصة مدرسة أزاد الإلكترونية

قواعد العمل الإلزامية لكل تعديل:

## أوامر الجودة (تُشغَّل دائماً بعد أي تعديل)
```powershell
# اختبارات
.venv\Scripts\python.exe -m pytest tests -q

# Python lint (ruff)
.venv\Scripts\python.exe -m ruff check app config.py run.py
.venv\Scripts\python.exe -m ruff format --check app config.py run.py

# Python types (mypy)
.venv\Scripts\python.exe -m mypy app config.py run.py

# JavaScript (biome)
npx biome check app/static/js
```

## قواعد البنية (غير قابلة للتفاوض)
- **لا تكرار (DRY):** كل منطق مشترك في `app/core/` ويُعاد تصديره من `app/core/__init__.py`. لا نسخ دومن في modules.
- **الذرّية:** كل كتابة قاعدة بيانات تمر عبر `tx(...)` (app/core/db.py) — commit واحد، rollback عند أي خطأ. ممنوع commit متناثر في routes.
- **التينانتس (SaaS):** أي استعلام على جدول يحمل `school_id` يمر عبر `scope_by_school` / `tenant_scope`. `School` هي جذر التينانتس (بلا school_id).
- **الصلاحيات:** فحص الأدوار حصراً عبر `role_required` (app/core/permissions.py). لا فحص متفرق.
- **قواميس عربي/إنجليزي:** كل نص ظاهر للمستخدم في `_()` (قوالب) أو `lazy_gettext` (نماذج). بعد إضافة نصوص:
  ```powershell
  .venv\Scripts\pybabel.exe extract -F babel.cfg -o messages.pot .
  .venv\Scripts\pybabel.exe update -i messages.pot -d app/translations
  # املأ ترجمات en في app/translations/en/LC_MESSAGES/messages.po ثم:
  .venv\Scripts\pybabel.exe compile -d app/translations
  ```
  المصدر عربي (msgid)، و`en` تُترجم فقط.
- **الأمان (D4):** لا أسرار في git (.env مستثنى). كلمات المرور argon2id عبر `hash_password`/`verify_password`.
