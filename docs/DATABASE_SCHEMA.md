# تصميم قاعدة البيانات — منصة مدرسة أزاد الإلكترونية
## وثيقة معمارية للاعتماد (تُنفَّذ بعد موافقتك فقط — D1)

**محرك:** PostgreSQL 18. **نوع المفاتيح:** `BIGINT GENERATED ALWAYS AS IDENTITY`.
**المبادئ:** علاقات مقيّدة بـ FK دائماً، JSONB للمرونة الديناميكية، فهارس لكل FK وعمود بحث، soft delete `deleted_at` لكل كيان قابل للحذف، حقول زمن `created_at/updated_at` للكل، وتقسيم (schema) نظيف عبر `public`.

---

## 1. مبادئ التصميم (تُطبق على كل جدول)
1. كل جدول له `id` (identity) + `created_at` + `updated_at` (تحديث تلقائي).
2. الكيانات القابلة للحذف تحمل `deleted_at` (حذف ناعم) — لا حذف فيزيائي للمحاضر/الدرجات.
3. **كل عمود يخزن قيماً بسيطة**؛ التعقيد/التغيّر في `jsonb` (`settings`, `meta`, `benefits`, `options`, `answers`) — مرونة دون هجرات.
4. الحقول النصية العربية تُخزَّن `TEXT` مع إسقاط Unicode عادي (لا collation حساس للعربية)؛ البحث عبر `ILIKE` أو `pg_trgm` (فهرس `gin_trgm_ops`) عند الحاجة.
5. **المدرسة هي حاجز العزل (tenancy)**: كل جدول أعمال يبدأ بمفتاح `school_id` — لا تداخل بين المدارس مهما توسّعنا.
   > **استثناء وحيد مقصود — الدروس الخصوصية (§3.15):** جداول T **بلا** `school_id` لأنها سوق حر خارج المدارس. حاجز العزل فيها هو المنصة نفسها، والوصول بصلاحية: طرفا الجلسة فقط + super_admin. لا يُضاف أي جدول خارج عزل المدرسة إلا بقرار صريح كهذا.
6. لا جداول خلفية صامتة: كل العلاقات `ON DELETE RESTRICT` (منع حذف بيانات محاسبية/درجات) إلا حيث صُمِّم النشر بوعي.

---

## 2. الفئات/الأنواع الثابتة (ENUM عبر PostgreSQL)
```sql
user_role        : super_admin | school_admin | teacher | student | parent
subscription_plan: first_term | second_term | annual
sub_status       : pending | active | expired | cancelled
payment_status   : pending | approved | rejected
content_status   : draft | published | archived
attempt_status   : in_progress | submitted | graded
question_type    : mcq | true_false | essay | matching
attendance_status: present | absent | late | excused
```
> تُنشأ كـ `CREATE TYPE` وتُستخدم كنوع عمود — صرامة بلا نصية.

---

## 3. الجداول (بترتيب الاعتماد)

### 3.1 المستخدمون والهوية
**users** — حساب واحد متعدد الأدوار (مدرّس في مدرسة، ولي في أخرى).
| عمود | النوع | ملاحظات |
|---|---|---|
| id | identity | PK |
| email | citext UNIQUE NOT NULL | تسجيل دخول |
| password_hash | text NOT NULL | argon2id/bcrypt |
| role | user_role NOT NULL | الدور الرئيسي |
| name_ar / name_en | text | أسماء ثنائية اللغة |
| avatar | text | URL مختزن خارج المجلد العام |
| locale | text DEFAULT 'ar' | RTL افتراضياً |
| is_active | boolean DEFAULT true | |
| is_verified | boolean DEFAULT false | تفعيل بريد |
| last_login_at | timestamptz | |
| deleted_at | timestamptz NULL | حذف ناعم |
| created_at / updated_at | timestamptz | |

**user_role_links** — الأدوار المتعددة عبر المدارس (المفتاح للمرونة).
| عمود | النوع |
|---|---|
| id | PK |
| user_id | FK→users |
| school_id | FK→schools |
| role | user_role |
| is_active | boolean |
| UNIQUE (user_id, school_id, role) |

### 3.2 المدارس والسنوات
**schools**
| عمود | النوع | ملاحظات |
|---|---|---|
| id | PK | |
| name_ar / name_en | text NOT NULL | |
| domain | citext UNIQUE NULL | نطاق فرعي مستقبلاً |
| academic_year | text | مثل 2025-2026 |
| stages | jsonb | ["primary","prep","secondary"] |
| settings | jsonb DEFAULT '{}' | إعدادات ديناميكية (الدفع، الإشعارات) |
| is_active | boolean | |

**school_settings** — جدول إعدادات ديناميكي (مفتاح/قيمة JSONB) بدل أعمدة متصلبة.
| عمود | النوع |
|---|---|
| id | PK |
| school_id | FK→schools NOT NULL |
| key | text NOT NULL |
| value | jsonb |
| UNIQUE (school_id, key) |

### 3.3 المنهاج: الصفوف الدراسية والمواد
**grades** (المستوى الدراسي 1..12 + مرحلة)
| عمود | النوع |
|---|---|
| id | PK |
| school_id | FK |
| grade_level | smallint NOT NULL | 1..12 |
| stage | text | primary/prep/secondary |
| name_ar / name_en | text |
| sort_order | smallint |
| UNIQUE (school_id, grade_level) |

**subjects** — مادة عامة (رياضيات/علوم/عربي...) قابلة للمشاركة.
| عمود | النوع |
|---|---|
| id | PK |
| code | text UNIQUE | مثل MATH7 |
| name_ar / name_en | text NOT NULL |
| is_elective | boolean DEFAULT false | **مادة اختيارية** |
| icon | text | |

**subject_grade_links** — أي مادة تدرس لأي صف (يربط "كل المواد لكل الصفوف" + الاختياري).
| عمود | النوع |
|---|---|
| id | PK |
| subject_id | FK→subjects |
| grade_id | FK→grades |
| UNIQUE (subject_id, grade_id) |

### 3.4 الصفوف (classes) والانضمام
**classes**
| عمود | النوع | ملاحظات |
|---|---|---|
| id | PK | |
| school_id | FK NOT NULL | حاجز العزل |
| subject_id | FK→subjects NOT NULL | |
| grade_id | FK→grades NOT NULL | |
| teacher_id | FK→users (teacher) | |
| semester | text | first/second (يُحسب السنوي منهما) |
| name | text | اسم اختياري للصف |
| join_code | citext UNIQUE NOT NULL | رمز انضمام 8 خانات |
| is_active | boolean DEFAULT true | |
| price_first_term / price_second_term / price_annual | numeric(10,2) | أسعار الخطط (دينار/دولار) |
| currency | text DEFAULT 'ILS' | |
| UNIQUE (school_id, subject_id, grade_id, semester) | | منع تكرار الصف |

**class_members** — عضوية الطالب في الصف.
| عمود | النوع |
|---|---|
| id | PK |
| class_id | FK→classes |
| user_id | FK→users (student) |
| status | text (active/removed/pending) |
| joined_at | timestamptz |
| UNIQUE (class_id, user_id) |

### 3.5 المحتوى (دروس + وحدات + مرفقات)
**units** — تقسيم المنهاج (وحدة/فصل).
| عمود | النوع |
|---|---|
| id | PK |
| class_id | FK |
| title | text |
| sort_order | smallint |

**lessons**
| عمود | النوع | ملاحظات |
|---|---|---|
| id | PK | |
| class_id | FK NOT NULL | |
| unit_id | FK→units NULL | |
| title | text NOT NULL | |
| body_html | text | نص منسّق (المحتوى النصي) |
| sort_order | smallint | |
| status | content_status DEFAULT 'draft' | |
| version | int DEFAULT 1 | إصدار المحتوى |
| published_at | timestamptz NULL | |
| created_by | FK→users | |
| deleted_at | timestamptz NULL | |

**lesson_attachments** — فيديو/PDF/صورة/رسم.
| عمود | النوع |
|---|---|
| id | PK |
| lesson_id | FK |
| kind | text (video/pdf/image/graph/audio) |
| title | text |
| stored_name | text NOT NULL | اسم عشوائي |
| original_name | text | |
| mime | text | |
| size_bytes | bigint | |
| youtube_url | text NULL | فيديو يوتيوب خارجي |
| position | smallint | |

### 3.6 التقييم: اختبارات وأسئلة ومحاولات
**quizzes**
| عمود | النوع |
|---|---|
| id | PK |
| class_id | FK |
| title | text |
| duration_min | int | مؤقّت (عشوائية+مؤقّت ضد الغش) |
| attempts_allowed | smallint DEFAULT 1 |
| open_at / close_at | timestamptz NULL |
| shuffle | boolean DEFAULT false |
| show_answers_after | boolean |
| total_mark | numeric(6,2) | يُحسب من الأسئلة |
| status | content_status |
| created_by | FK |

**questions**
| عمود | النوع |
|---|---|
| id | PK |
| quiz_id | FK |
| type | question_type NOT NULL |
| prompt | text NOT NULL |
| options | jsonb | خيارات MCQ بصيغة JSON |
| correct_answer | jsonb | الجواب الصحيح (JSON يتحمل التوصيل/مقالي) |
| mark | numeric(5,2) |
| sort_order | smallint |

**quiz_attempts** — محاولة الطالب (مع منع التكرار فوق الحد).
| عمود | النوع |
|---|---|
| id | PK |
| quiz_id | FK |
| student_id | FK |
| started_at / submitted_at | timestamptz |
| score | numeric(6,2) |
| status | attempt_status |
| UNIQUE (quiz_id, student_id, attempt_no) | | attempt_no متسلسل |

**answers** — إجابة كل سؤال داخل المحاولة.
| عمود | النوع |
|---|---|
| id | PK |
| attempt_id | FK |
| question_id | FK |
| answer | jsonb |
| is_correct | boolean NULL | يملؤه المعلم للمقالي |
| awarded_mark | numeric(5,2) |

### 3.7 الواجبات والتسليمات
**assignments**
| عمود | النوع |
|---|---|
| id | PK |
| class_id | FK |
| title | text |
| body | text |
| due_at | timestamptz |
| max_mark | numeric(5,2) |
| created_by | FK |

**submissions**
| عمود | النوع |
|---|---|
| id | PK |
| assignment_id | FK |
| student_id | FK |
| body | text |
| file | text NULL | stored_name |
| submitted_at | timestamptz |
| mark / max_mark | numeric |
| feedback | text |
| graded_by / graded_at | FK / timestamptz |
| UNIQUE (assignment_id, student_id) |

### 3.8 الدرجات ودفتر الدرجات
**grade_categories** — أقسام الدفتر (فصل أول/ثاني، شهري، نهائي) بوزن.
| عمود | النوع |
|---|---|
| id | PK |
| class_id | FK |
| name | text |
| weight | numeric(3,2) | نسبي |
| UNIQUE (class_id, name) |

**grade_items** — بند تقييم (اختبار/واجب/حضور) تحت قسم.
| عمود | النوع |
|---|---|
| id | PK |
| class_id | FK |
| category_id | FK→grade_categories |
| title | text |
| max_mark | numeric(5,2) |
| due_at | timestamptz NULL |
| kind | text (quiz/assignment/exam/project) |

**grade_entries** — درجة الطالب في بند واحد (لا تتكرر).
| عمود | النوع |
|---|---|
| id | PK |
| student_id | FK |
| grade_item_id | FK |
| mark | numeric(5,2) |
| recorded_by | FK |
| note | text |
| UNIQUE (student_id, grade_item_id) |

### 3.9 الحضور
**attendance**
| عمود | النوع |
|---|---|
| id | PK |
| class_id | FK |
| student_id | FK |
| date | date |
| status | attendance_status |
| note | text |
| recorded_by | FK |
| UNIQUE (class_id, student_id, date) |

### 3.10 الاشتراك والدفع (حقيبة Billing معزولة — درس OpenEduCat)
**subscription_plans** — خطط قابلة لإعادة الاستخدام لكل صف.
| عمود | النوع |
|---|---|
| id | PK |
| school_id | FK |
| class_id | FK→classes NULL | NULL = خطة عامة للمدرسة |
| name | text | "فصل أول" / "فصل ثاني" / "سنوي" |
| plan | subscription_plan NOT NULL |
| price | numeric(10,2) |
| currency | text |
| duration_days | int | |
| benefits | jsonb | **مزايا المواد الاختيارية** (F-الاشتراك) |
| is_active | boolean |

**subscriptions** — اشتراك الطالب.
| عمود | النوع |
|---|---|
| id | PK |
| user_id | FK (student) |
| plan_id | FK→subscription_plans |
| class_id | FK |
| price / currency | |
| start_at / end_at | timestamptz |
| status | sub_status |
| source | text (manual/gateway) |
| UNIQUE (user_id, plan_id, class_id) | قيد نشاط منطقي |

**manual_payments** — الطلبات اليدوية (تحويل/واتساب).
| عمود | النوع |
|---|---|
| id | PK |
| subscription_id | FK |
| reference | text | رقم مرجع التحويل |
| amount | numeric(10,2) |
| note | text |
| status | payment_status |
| reviewed_by / reviewed_at | FK / timestamptz |

**payment_receipts** — صورة الإيصال.
| عمود | النوع |
|---|---|
| id | PK |
| manual_payment_id | FK |
| stored_name / original_name / mime | text |
| size_bytes | bigint |

### 3.11 التواصل
**announcements** — إعلان صف.
| عمود | النوع |
|---|---|
| id | PK |
| class_id | FK |
| author_id | FK |
| title / body | text |
| pinned | boolean |
| created_at | timestamptz |

**notifications**
| عمود | النوع |
|---|---|
| id | PK |
| user_id | FK |
| type | text (result/new_assignment/subscription...) |
| title / body | text |
| link | text |
| is_read | boolean DEFAULT false |
| created_at | timestamptz |

### 3.12 الذكاء الاصطناعي (F27-F30 — جاهز مسبقاً)
**ai_sessions** — جلسة معلم افتراضي/مولد أسئلة (مقيّد بمنهاج صف).
| عمود | النوع |
|---|---|
| id | PK |
| user_id | FK |
| class_id | FK |
| lesson_id | FK NULL | سياق الشرح |
| session_type | text (tutor/question_generator/grading_assist) |
| meta | jsonb | إعدادات النموذج |
| created_at | timestamptz |

**ai_messages**
| عمود | النوع |
|---|---|
| id | PK |
| session_id | FK |
| role | text (user/assistant) |
| content | text |
| model | text |
| tokens | int |
| created_at | timestamptz |

### 3.15 الدروس الخصوصية (سوق حر — استثناء تينانتس مقصود)
> بلا `school_id` — الحاجز هو المنصة، والوصول: طرفا الجلسة فقط + super_admin. انظر المبدأ 5.

**tutor_profiles** — ملف المعلم الخصوصي (صفحة عامة قابلة للبحث).
| عمود | النوع | ملاحظات |
|---|---|---|
| id | PK | |
| tutor_id | FK→users NOT NULL | UNIQUE — معلم واحد لكل ملف |
| subject | text NOT NULL | مادة التدريس |
| grade_levels | jsonb | [7,8,9] الصفوف التي يدرّسها |
| price_hour | numeric(10,2) | سعر الساعة |
| price_session | numeric(10,2) | سعر الجلسة الثابتة |
| mode | text | online/offline/both |
| availability | jsonb | أوقات/أيام التوفر |
| bio | text | نبذة للمعلم |
| invite_code | citext UNIQUE | مفتاح دعوة مباشر |
| is_active | boolean DEFAULT true | |
| created_at / updated_at | timestamptz | |

**tutoring_requests** — طلب حجز من طالب لمعلم.
| عمود | النوع | ملاحظات |
|---|---|---|
| id | PK | |
| tutor_id | FK→users NOT NULL | |
| student_id | FK→users NOT NULL | |
| subject | text | |
| preferred_time | timestamptz | |
| mode | text | online/offline |
| price_quote | numeric(10,2) | سعر مقترح |
| note | text | |
| status | text | pending/accepted/rejected/cancelled |
| UNIQUE (tutor_id, student_id, status) | | قيد نشاط منطقي للطلبات المفتوحة |

**tutoring_sessions** — الجلسة المؤكَّدة بين المعلم والطالب.
| عمود | النوع | ملاحظات |
|---|---|---|
| id | PK | |
| request_id | FK→tutoring_requests NULL | |
| tutor_id | FK→users NOT NULL | |
| student_id | FK→users NOT NULL | |
| subject | text NOT NULL | |
| scheduled_at | timestamptz NOT NULL | |
| duration_min | int | |
| price | numeric(10,2) | |
| currency | text DEFAULT 'ILS' | |
| mode | text | online/offline |
| online_link | text NULL | رابط الاجتماع |
| location | text NULL | المكان الحضوري |
| status | text | requested/accepted/completed/cancelled |
| payment_status | text | pending/approved/rejected (يدوي — D12) |
| created_at / updated_at | timestamptz | |

### 3.16 سجل التدقيق
**audit_logs**
| عمود | النوع |
|---|---|
| id | PK |
| user_id | FK NULL |
| action | text |
| entity / entity_id | text / bigint |
| detail | jsonb |
| ip | inet |
| created_at | timestamptz |
> فهرس (entity, entity_id) + (user_id, created_at) — تدقيق سريع.

### 3.14 النظام
**settings** — إعدادات عامة (مفتاح/قيمة JSONB).
| عمود | النوع |
|---|---|
| id | PK |
| key | text UNIQUE |
| value | jsonb |

---

## 4. الفهارس (Performance — N5)
- كل عمود FK يُفهرس تلقائياً بـ `CREATE INDEX ... ON ...(fk_id)`.
- `users(email)`، `classes(join_code)`، `subscriptions(user_id)`، `class_members(class_id, user_id)`.
- `lessons(class_id, sort_order)`، `quiz_attempts(quiz_id, student_id)`.
- `grade_entries(student_id)` لبطاقة الدرجات السريعة.
- `attendance(class_id, date)` للحضور اليومي.
- `audit_logs(entity, entity_id)`.
- `tutor_profiles(subject)`, `tutor_profiles(invite_code)`, `tutoring_sessions(tutor_id, scheduled_at)`, `tutoring_sessions(student_id)`.
- `pg_trgm` على `subjects.name_ar`, `lessons.title` للبحث المرن عند الحاجة لاحقاً.

## 5. الهجرات
- **Alembic (Flask-Migrate)** إلزامي: لا تعديل يدوي للجداول — كل تغيير هجرة مُرقّمة `alembic upgrade head`.
- كل ميزة مستقبلية تُضاف بهجرة جديدة (لا مساس بالجداول القائمة — أساس قابل للتطوير دون كسر).

## 6. ماذا يُغطى في M1..M6 من هذا المخطط؟
| المرحلة | الجداول |
|---|---|
| M1 المصادقة | users, user_role_links |
| M2 المدارس والصفوف | schools, school_settings, grades, subjects, subject_grade_links, classes, class_members |
| M3 الدروس | units, lessons, lesson_attachments |
| M4 الاختبارات | quizzes, questions, quiz_attempts, answers |
| M5 الواجبات والدرجات والحضور | assignments, submissions, grade_categories, grade_items, grade_entries, attendance |
| M6 الاشتراك والدفع | subscription_plans, subscriptions, manual_payments, payment_receipts |
| M2T الدروس الخصوصية (موازٍ) | tutor_profiles, tutoring_requests, tutoring_sessions |

> الجداول 3.11-3.16 تُنشأ في M0 كجزء من الهيكل الأساسي (لا كود بعد — schema فقط)، لتضمن أن التصميم مستقبلي بالكامل من أول يوم.

## 7. قرارات تحتاج تأكيدك قبل التنفيذ
1. **الرمز النقدي الافتراضي:** `ILS` (شيكل) أم `USD` أم `JOD`؟ (أُدرج `currency` كعمود مرن — لكن أفترض شيكلاً افتراضياً).
2. **تخزين كلمات المرور:** `argon2id` (الأقوى، لكن يحتاج حزمة إضافية `argon2-cffi`) أم `bcrypt`؟ (الخطة تقول bcrypt/argon2 — أختار **argon2id**).
3. **حجم الأكواد:** هل نقبل `requirements.txt` يثبّت `psycopg2-binary` أم نُفضّل `psycopg2` (يتطلب مترجم/بيئة)؟ — **الخيار الأول أسرع للتطوير المحلي**.
