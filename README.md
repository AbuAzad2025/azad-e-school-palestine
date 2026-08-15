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

## التشغيل محلياً
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env    # ثم عبّئ القيم
flask db upgrade
flask run
```

## الضوابط (خلاصة من PLAN.md — يُقرأ كاملاً قبل أي مساهمة)
- D1 لا كود وظيفي خارج إطار خطة المراحل المعتمدة.
- D3 لا انتقال لمرحلة دون فحص وموافقة.
- D4 لا أسرار في الكود — كلها في .env.
- D5 الوصول للقاعدة عبر ORM فقط، لا SQL مكتوب يدوياً.
- D6 فحص الصلاحيات على كل route.
- D7 المرفوعات: قائمة بيضاء + حد حجم + خارج المجلد العام + أسماء عشوائية.
- D9 اختبارات pytest لكل مرحلة.
- D10 commits صغيرة وواضحة، لا ملفات كبيرة في الريبو.
