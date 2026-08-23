# تقرير مراجعة UI/UX — منصة مدرسة أزاد الإلكترونية

**التاريخ:** 2026-08-23
**المراجع:** أزاد ERP (Flask-based)
**نطاق المراجعة:** الواجهات الرسومية، تجربة المستخدم، سير العمل، إمكانية الوصول

---

## 1. الهوية البصرية والتصميم (Visual Design Audit)

### ✅ ما هو قوي

| البند | التقييم | ملاحظات |
|-------|:-------:|---------|
| **Palette** | A- | هوية فلسطينية واضحة (navy #014e7c + green #009535 + red #c90f2a) — متسقة ومميزة |
| **Typography** | A | خط Cairo لجميع الأوزان (400-900) — مثالي للعربية، حجم base مناسب (0.9375rem) |
| **Design Tokens** | A | spacing + radius + shadow + z-index موحدّة في `brand.css` — نظام متكامل |
| **Dark Mode** | A | تبديل مظهر كامل عبر `data-theme` مع semantic colors متكاملة |
| **Micro-interactions** | B+ | hover states على البطاقات والأزرار، page-enter animation |
| **Loading States** | B+ | أزرار مع spinner و`aria-busy` — لكن لا يوجد skeleton للصفحات |

### ⚠️ نقاط الضعف

| البند | الخطورة | المشكلة | الحل المقترح |
|-------|:-------:|---------|-------------|
| **Gradient Overuse** | متوسطة | `azad-title` و`azad-btn` يستخدمان gradient دائماً — يُرهق العين عند تكراره | استخدام gradient للعناوين الرئيسية فقط، أزرار بلون ثابت |
| **Card Nesting** | منخفضة | بطاقات stat داخل بطاقات أخرى في بعض الأماكن | تبسيط الهيكل، الاعتماد على المسافة بدلاً من الإطارات |
| **CSS Legacy** | متوسطة | وجود `.form-group` + `.azad-field` — أنماط مكررة | توحيد تحت `.azad-field` وإزالة Legacy |
| **Inline Styles** | متوسطة | `style=` متناثر في القوالب (class_detail.html, auth/dashboard.html) | نقل كل الأنماط إلى CSS classes |
| **Footer Minimal** | منخفضة | Footer 4 أسطر فقط — يفتقر إلى روابط مهمة | إضافة روابط قانونية، دعم، وسائل تواصل |

---

## 2. بنية المعلومات والتنقل (Information Architecture & Navigation)

### ✅ ما هو قوي

- **Bottom Navigation** للموبايل — 4-5 عناصر حسب الدور (student/teacher/admin/parent)
- **Breadcrumb** macro موحد (`azad_breadcrumb`) — يظهر في معظم الصفحات الداخلية
- **Admin Sidebar** — تصنيف واضح (الرئيسية → الإدارة → الاشتراكات → AI → النظام)
- **Skip Link** — `sr-only` link لتخطي المحتوى (accessibility)

### ⚠️ مشاكل التنقل

| # | المشكلة | الخطورة | الحل |
|:-:|---------|:-------:|------|
| 1 | **لا يوجد Global Search في Navbar** للزوار غير المسجلين | متوسطة | إظهار حقل بحث مصغر للجميع |
| 2 | **Mobile Hamburger** يعكس نفس الروابط في Bottom Nav — تكرار | متوسطة | تبسيط Hamburger ليحتوي على الإعدادات واللغة فقط |
| 3 | **User Dropdown** لا يحتوي على "لوحتي" للمستخدم العادي | منخفضة | إضافة رابط سريع للوحة التحكم |
| 4 | **Active State** في Bottom Nav يعتمد على `request.endpoint` — قد يفشل مع URL params | منخفضة | استخدام regex أو data attribute |
| 5 | **لا يوجد You Are Here** في الصفحات المعمقة | منخفضة | تمييز Breadcrumb item النشط بشكل أوضح |

---

## 3. سير عمل المستخدم (User Flows)

### 3.1 تسجيل الدخول / التسجيل

| الخطوة | التقييم | ملاحظات |
|--------|:-------:|---------|
| صفحة Login | B+ | بسيطة، لكن لا تحتوي على "تذكّرني" أو تسجيل دخول اجتماعي |
| صفحة Register | B | فردي vs مدرسي واضح، لكن لا يوجد توضيح للفرق |
| Forgot Password | غير مراجع | يجب التحقق من وضوح الرسائل |
| Form Validation | B | أخطاء تظهر أسفل كل حقل، لكن لا يوجد inline validation |

**🔴 توصية حرجة:** إضافة **Password Strength Indicator** أثناء الكتابة — الطلاب يميلون لكلمات ضعيفة.

### 3.2 لوحة التحكم (Dashboard)

| الدور | التقييم | ملاحظات |
|-------|:-------:|---------|
| **Super Admin** | A- | 12 stat card + charts — غني بالمعلومات، لكن قد يكون مُرهقاً |
| **School Admin** | B+ | 4 stats + إجراءات سريعة — مناسب |
| **Teacher** | B+ | قائمة صفوف + سوق الدروس — واضح |
| **Student** | B+ | صفوفي + دروس خصوصية — مناسب |
| **Parent** | B | صفوف الأبناء — يفتقر إلى تفاصيل التقدم |

**⚠️ مشكلة:** `stats-grid` يستخدم `auto-fit` مع `minmax(140px, 1fr)` — في شاشات ضيقة قد يصبح النص غير قابل للقراءة. يُنصح بـ `minmax(200px, 1fr)`.

### 3.3 إدارة الصفوف (Class Management)

**Flow:** Teacher → Class Detail → Lessons / Quizzes / Assignments / Attendance

| الخطوة | التقييم | ملاحظات |
|--------|:-------:|---------|
| Class Detail | B | جدول أعضاء بسيط، لكن لا يوجد tabs للتنقل |
| Teacher Tools | B+ | 4 أزرار + توليد رمز — واضحة |
| Join Code | B | يُعرض بوضوح، لكن لا يوجد "نسخ" بنقرة واحدة |

**🔴 توصية:** إضافة **Copy-to-Clipboard** button بجانب رمز الانضمام — المعلمون يحتاجون مشاركته بسرعة.

### 3.4 سير عمل الموافقة (Approval Workflow)

**Flow:** Super Admin → Pending Registrations → Approve/Reject

| الخطوة | التقييم | ملاحظات |
|--------|:-------:|---------|
| Pending List | B+ | pagination + search — جيد |
| Approve Action | B | flash message فقط — لا يوجد toast أو animation |
| Email Notification | غير مراجع | يجب التحقق من وضوح رسائل البريد |

---

## 4. تصميم النماذج (Form Design)

### ✅ ما هو قوي

- **Label + Input** مترابطان دائماً
- **Placeholder** يوفر أمثلة (example@mail.com)
- **Autocomplete** attributes موجودة (email, current-password, new-password)
- **Error Messages** أسفل كل حقل — واضحة

### ⚠️ مشاكل النماذج

| # | المشكلة | الخطورة | الحل |
|:-:|---------|:-------:|------|
| 1 | **لا يوجد Inline Validation** — الأخطاء تظهر فقط بعد Submit | متوسطة | التحقق المباشر أثناء blur/typing |
| 2 | **Form Hints** نادرة — فقط في register_individual | منخفضة | إضافة tooltip أو helper text لكل حقل |
| 3 | **Password Toggle** (إظهار/إخفاء) — غير مؤكد وجوده في كل النماذج | منخفضة | التأكد من تطبيقه على كل حقول كلمة المرور |
| 4 | **Required Indicator** (*) غير موجود | منخفضة | إضافة نجمة حمراء للحقول الإلزامية |
| 5 | **Date Pickers** — غير واضح إذا كانت native أم مكتبة | منخفضة | استخدام مكتبة متسقة (flatpickr) |

---

## 5. التحليلات البيانية (Dashboards & Data Viz)

### ✅ ما هو قوي

- **Charts** عبر `<canvas data-chart="...">` — نظام مرن
- **Color Coding** للحالات (success/warning/danger/info)
- **Stat Cards** مع أيقونات ملونة وبار جانبي

### ⚠️ مشاكل التحليلات

| # | المشكلة | الخطورة | الحل |
|:-:|---------|:-------:|------|
| 1 | **لا يوجد Empty States** للcharts عندما تكون البيانات فارغة | متوسطة | إظهار رسالة "لا توجد بيانات كافية" مع illustration |
| 2 | **Chart Colors** — تكرار في palette (azad-navy/azad-blue متشابهان) | منخفضة | زيادة التباين بين الألوان |
| 3 | **لا يوجد Date Range Picker** — الإحصائيات دائماً 30 يوم | متوسطة | إضافة تحديد نطاق زمني |
| 4 | **AI Usage Stats** — لا توجد trend line | منخفضة | إضافة sparkline صغير لكل stat card |
| 5 | **Super Admin Dashboard** — 12 بطاقة في صف واحد | متوسطة | تجميع في أقسام قابلة للطي |

---

## 6. تجربة الموبايل (Mobile/Tablet Experience)

### ✅ ما هو قوي

- **Bottom Navigation** — native-like experience
- **Safe Area Insets** — `env(safe-area-inset-*)` للأجهزة الحديثة
- **Touch Targets** — 48px minimum للأزرار والروابط
- **Responsive Tables** — `overflow-x: auto` للجداول
- **Admin Sidebar** — drawer منزلق في الموبايل

### ⚠️ مشاكل الموبايل

| # | المشكلة | الخطورة | الحل |
|:-:|---------|:-------:|------|
| 1 | **Stats Grid** — `minmax(140px, 1fr)` يسبب بطاقات ضيقة جداً | متوسطة | `minmax(160px, 1fr)` + `gap: 12px` |
| 2 | **PWA Banner** — يظهر دائماً حتى لو مثبت | منخفضة | التحقق من `beforeinstallprompt` |
| 3 | **Landscape Mode** — Bottom Nav يستهلك مساحة | منخفضة | إخفاء Bottom Nav في landscape |
| 4 | **WhatsApp Float** — قد يغطي Bottom Nav | منخفضة | تعديل `bottom` position |
| 5 | **Tables in Mobile** — `white-space: nowrap` يسبب تمرير أفقي مُرهق | متوسطة | Card View للجداول في الموبايل |

---

## 7. إمكانية الوصول (Accessibility & Inclusivity)

### ✅ ما هو قوي

| البند | الحالة | ملاحظات |
|-------|:------:|---------|
| **Skip Link** | ✅ | موجود ويعمل |
| **ARIA Labels** | ✅ | على الأيقونات، الأزرار، والتنقل |
| **Focus Visible** | ✅ | `box-shadow` واضح عند التنقل بالكيبورد |
| **Semantic HTML** | ✅ | `<nav>`, `<main>`, `<aside>`, `role="alert"` |
| **Live Regions** | ✅ | `aria-live="polite"` للـ toasts |
| **Color Contrast** | B+ | `azad-navy` + `#fff` جيد، لكن `text-muted` (#64748b) قد يكون ضعيفاً على `surface` |
| **RTL Support** | ✅ | `[dir="rtl"]` + `inset-inline` — دعم كامل |

### ⚠️ مشاكل Accessibility

| # | المشكلة | الخطورة | الحل |
|:-:|---------|:-------:|------|
| 1 | **Flash Messages** — `role="status"` صحيح لكن لا تُقرأ تلقائياً | متوسطة | إضافة `aria-live="polite"` للحاوية |
| 2 | **Tour Component** — `aria-modal="true"` لكن لا يوجد `aria-describedby` | منخفضة | ربط النص بالعنوان |
| 3 | **Icons Only** — بعض الأزرار تعتمد على icon فقط | منخفضة | إضافة `aria-label` واضح |
| 4 | **Form Errors** — `aria-describedby` غير مستخدم | متوسطة | ربط الحقل برسالة الخطأ |
| 5 | **Reduced Motion** — لا يوجد `prefers-reduced-motion` | متوسطة | `animation: none` للمستخدمين الحساسين |

---

## 8. استدلالات نيلسن (Nielsen's 10 Heuristics)

| # | الاستدلال | التقييم | ملاحظات |
|:-:|-----------|:-------:|---------|
| 1 | Visibility of System Status | B+ | Flash messages + loading states — لكن لا يوجد progress bar للعمليات الطويلة |
| 2 | Match Between System & Real World | A | مصطلحات عربية واضحة (صفوف، دروس، واجبات) |
| 3 | User Control & Freedom | B+ | Undo غير متاح في معظم العمليات |
| 4 | Consistency & Standards | A- | Design System موحد، لكن بعض Legacy styles باقية |
| 5 | Error Prevention | B | Confirmation dialogs موجودة، لكن inline validation مفقود |
| 6 | Recognition Rather Than Recall | B+ | Quick Actions + Dashboard stats — جيد |
| 7 | Flexibility & Efficiency of Use | B | Shortcuts (Ctrl+K للبحث) — محدودة |
| 8 | Aesthetic & Minimalist Design | B+ | Hero + stats + cards — قد يكون مُرهقاً للمستخدم الجديد |
| 9 | Help Users Recognize, Diagnose, Recover | B | رسائل خطأ واضحة، لكن لا يوجد documentation |
| 10 | Help & Documentation | C | Tour موجود لكن محدود، لا يوجد Help Center |

---

## 9. التوصيات التصميمية (Redesign Recommendations)

### 🔴 حرجة — يجب تنفيذها فوراً

1. **Inline Form Validation** — التحقق المباشر أثناء الكتابة
2. **Password Strength Indicator** — شريط قوة كلمة المرور
3. **Copy-to-Clipboard** لرمز الانضمام — زر "نسخ" بجانب الكود
4. **Reduced Motion Support** — احترام `prefers-reduced-motion`

### 🟡 عالية — يُنصح بتنفيذها

5. **Global Search** في Navbar لجميع المستخدمين
6. **Card View for Mobile Tables** — تحويل الجداول إلى بطاقات في الموبايل
7. **Date Range Picker** في لوحات التحكم
8. **Skeleton Loaders** للصفحات الثقيلة
9. **Toast Notifications** بديلاً عن Flash Messages التقليدية

### 🟢 متوسطة — تحسينات مستقبلية

10. **Onboarding Wizard** — بدلاً من Tour خطوة واحدة
11. **Help Center** — صفحة FAQ أو chatbot
12. **Notification Preferences** — تحكم granular في الإشعارات
13. **Advanced Search** — فلترة متعددة المعايير
14. **Data Export** — تصدير الجداول إلى Excel/PDF

---

## 10. وصف Wireframes مقترحة

### Wireframe 1: Dashboard Mobile (Student)
```
┌─────────────────────────┐
│ ☰  أزاد  🔍  🔔  👤     │  ← Navbar (sticky)
├─────────────────────────┤
│ مرحباً، أحمد!           │  ← Greeting
├─────────────────────────┤
│ ┌─────┐  ┌─────┐       │
│ │📚   │  │🎓   │       │  ← 2 Stat Cards
│ │3 صفوف│  │85%  │       │
│ └─────┘  └─────┘       │
├─────────────────────────┤
│ 📋 صفوفي        [الكل] │  ← Section Header
├─────────────────────────┤
│ ┌─────────────────────┐ │
│ │ الرياضيات — الصف 9  │ │  ← Class Card
│ │ معلم: أ. خالد    →  │ │
│ └─────────────────────┘ │
│ ┌─────────────────────┐ │
│ │ العلوم — الصف 9     │ │
│ │ معلم: أ. سمر     →  │ │
│ └─────────────────────┘ │
├─────────────────────────┤
│ ⚡ وصول سريع           │
├─────────────────────────┤
│ [🔍] [📚] [🏠] [🔔] [✉️]│  ← Bottom Nav
└─────────────────────────┘
```

### Wireframe 2: Class Detail (Teacher — Mobile)
```
┌─────────────────────────┐
│ ← الرياضيات — الصف 9    │  ← Breadcrumb + Back
├─────────────────────────┤
│ ┌─────┐  ┌─────┐       │
│ │👥 25│  │🔑 ABC│      │  ← Members + Code (with 📋)
│ │طالب │  │رمز   │      │
│ └─────┘  └─────┘       │
├─────────────────────────┤
│ [📖 دروس] [📝 اختبارات] │  ← Horizontal Scroll Tabs
│ [📋 واجبات] [📅 حضور]  │
├─────────────────────────┤
│ 👥 الأعضاء              │
├─────────────────────────┤
│ ┌─────────────────────┐ │
│ │ أحمد غنام      طالب │ │  ← Member Row
│ └─────────────────────┘ │
│ ┌─────────────────────┐ │
│ │ سارة أحمد      طالبة│ │
│ └─────────────────────┘ │
└─────────────────────────┘
```

### Wireframe 3: Form with Inline Validation
```
┌─────────────────────────┐
│ تسجيل كطالب فردي        │
├─────────────────────────┤
│ الاسم الكامل *          │
│ ┌─────────────────────┐ │
│ │ أحمد غنام          │ │  ← Valid: green border + ✓
│ └─────────────────────┘ │
│                         │
│ البريد الإلكتروني *     │
│ ┌─────────────────────┐ │
│ │ ahmed@example.com  │ │  ← Valid
│ └─────────────────────┘ │
│                         │
│ كلمة المرور *           │
│ ┌─────────────────────┐ │
│ │ ••••••••           │ │  ← Typing...
│ └─────────────────────┘ │
│ ████████░░ ضعيفة        │  ← Strength Indicator
│ 8+ أحرف، رقم، رمز       │  ← Helper Text
│                         │
│ [ ✅ سجّل ]             │
└─────────────────────────┘
```

---

## الخلاصة

| المجال | الدرجة | الأولوية |
|--------|:------:|:--------:|
| الهوية البصرية | A- | مستقبلي |
| بنية المعلومات | B+ | مستقبلي |
| سير العمل | B+ | مستقبلي |
| تصميم النماذج | B | عالية |
| التحليلات البيانية | B+ | مستقبلي |
| تجربة الموبايل | B+ | عالية |
| إمكانية الوصول | B+ | عالية |
| الاستدلالات | B+ | عالية |

**الدرجة العامة: B+** — منصة متينة بصرياً ووظيفياً، مع بعض الفجوات في إمكانية الوصول وتجربة النماذج التي تستحق اهتماماً فورياً.
