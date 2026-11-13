"""إغلاق فجوات الفروع القابلة للاختبار من تدقيق التغطية.

كل اختبار هنا يستهدف فرعاً محدداً رصده تقرير CI (run 43470926246) ويثبت
سلوكاً حقيقياً — لا استدعاء شكلياً لرفع النسبة:

* ``platform_scope`` المتداخل يجب ألّا يُلغي المعاملة عند الخروج الداخلي.
* ولي أمر مرتبط بابنه يرى حركات محفظته (الفرع الناجح لفحص الرابط العائلي).
* فهرس إجابة خارج مدى التقليب لا يُترجم ولا يُسقط الطلب.
* ``update_bank_question`` يتجاهل مفتاحاً غير مسموح بدل رفعه.
* ``get_or_create_system_school`` idempotent: نداء ثانٍ لا يضاعف الصفوف.
* ``class_grades_summary`` لا يتأثر ببنود صف آخر (ثابت الاستعلام المقيَّد).
"""

from __future__ import annotations

from sqlalchemy import text
from tests.conftest import (
    make_class,
    make_class_member,
    make_family_link,
    make_grade,
    make_grade_category,
    make_grade_entry,
    make_grade_item,
    make_school,
    make_subject,
    make_user,
)

RLS_PASSWORD = "TestPass123!"


def test_nested_platform_scope_keeps_transaction_and_elevation(app):
    """الخروج من النطاق الداخلي لا ينهي المعاملة التي رفعها النطاق الخارجي.

    ``platform_scope`` يرفع GUC بمقدار ``SET LOCAL`` داخل المعاملة المفتوحة.
    لو ألغى الخروج الداخلي المعاملة (depth == 0 خطأً) لضاعت الترقية وظهرت
    الكتابات التالية مقيَّدة بالتينانت — وهو عطل تينانتس حقيقي.
    """
    from app.core.rls import _platform_scope, platform_scope
    from app.extensions import db

    with app.app_context():
        with platform_scope():
            db.session.execute(text("SELECT 1"))
            with platform_scope():
                db.session.execute(text("SELECT 1"))
                assert getattr(_platform_scope, "depth", 0) == 2
            # بعد الخروج الداخلي: العمق عاد والمعاملة والترقية باقيتان.
            assert getattr(_platform_scope, "depth", 0) == 1
            from app.core.rls import _session_in_transaction

            assert _session_in_transaction()
            elevated = db.session.execute(text("SELECT current_setting('app.is_super_admin', true)")).scalar()
            assert elevated == "1"

        assert getattr(_platform_scope, "depth", 0) == 0


def _logged_in_client(app, user_id: int):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    return client


def test_parent_can_read_linked_child_wallet_history(app):
    """ولي أمر مرتبط بابنه نشطاً يمرّ من فحص الرابط بدل 403."""
    from app.models.family import FamilyLink

    school_id = make_school(app)
    parent_id = make_user(app, role="parent", school_id=school_id)
    child_id = make_user(app, role="student", school_id=school_id)
    make_family_link(app, parent_id, child_id)
    with app.app_context():
        assert FamilyLink.query.filter_by(parent_id=parent_id, student_id=child_id, status="active").count() == 1

    response = _logged_in_client(app, parent_id).get(f"/api/v1/wallet/transactions?user_id={child_id}")

    assert response.status_code == 200
    assert response.get_json()["data"] == []


def test_parent_cannot_read_unlinked_child_wallet_history(app):
    """الضابط المقابل: نفس الطلب لطفل غير مرتبط يبقى 403."""
    school_id = make_school(app)
    parent_id = make_user(app, role="parent", school_id=school_id)
    stranger_id = make_user(app, role="student", school_id=school_id)

    response = _logged_in_client(app, parent_id).get(f"/api/v1/wallet/transactions?user_id={stranger_id}")

    assert response.status_code == 403


def test_out_of_range_answer_index_is_not_remapped(app):
    """فهرس عرض خارج مدى التقليب يُحفظ كما هو ولا يُترجم لفهرس أصلي شاذ."""
    from app.extensions import db
    from app.models.assessment import Answer, Question, Quiz
    from app.services.assessment import save_answer, start_attempt

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)
    make_class_member(app, class_id, student_id)

    with app.app_context():
        quiz = Quiz(class_id=class_id, title="shuffle", shuffle=True, attempts_allowed=1)
        db.session.add(quiz)
        db.session.flush()
        question = Question(
            quiz_id=quiz.id,
            type="mcq",
            prompt="q",
            options={"items": [{"label": "أ", "text": "1"}, {"label": "ب", "text": "2"}]},
            correct_answer={"index": 1},
            mark=1,
            sort_order=0,
        )
        sibling = Question(
            quiz_id=quiz.id,
            type="mcq",
            prompt="q2",
            options={"items": [{"label": "أ", "text": "1"}, {"label": "ب", "text": "2"}]},
            correct_answer={"index": 0},
            mark=1,
            sort_order=1,
        )
        db.session.add_all([question, sibling])
        db.session.commit()

        attempt, error = start_attempt(quiz, student_id=student_id)
        assert error is None
        assert attempt.display_order is not None
        permutation = attempt.display_order["options"][str(question.id)]
        assert permutation

        save_answer(attempt, question.id, {"index": len(permutation) + 5})
        db.session.commit()

        saved = Answer.query.filter_by(attempt_id=attempt.id, question_id=question.id).one()
        # الفهرس الشاذ يبقى على حاله بدل تحويله لفهرس "أصلي" خارج النطاق.
        assert saved.answer["index"] == len(permutation) + 5


def test_update_bank_question_ignores_disallowed_kwargs(app):
    """المفاتيح غير المسموحة تُتجاهل بأمان بدل setattr أعمى."""
    from app.models.question_bank import QuestionBank
    from app.services.question_bank import create_bank_question, update_bank_question

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    other_teacher_id = make_user(app, role="teacher", school_id=school_id)
    subject_id = make_subject(app)

    with app.app_context():
        from app.extensions import db

        bank, error = create_bank_question(
            teacher_id,
            school_id,
            "سؤال أصلي",
            "mcq",
            subject_id=subject_id,
            options={"items": [{"label": "أ", "text": "1"}]},
            correct_answer={"index": 0},
        )
        assert error is None
        assert bank is not None
        bank_id = bank.id

        updated, error = update_bank_question(
            bank_id,
            teacher_id,
            question_text="سؤال محدَّث",
            owner_id=other_teacher_id,  # غير مسموح — يجب أن يُتجاهل
            is_active=False,  # غير مسموح أيضاً
        )

        assert error is None
        assert updated is not None
        assert updated.question_text == "سؤال محدَّث"
        assert updated.teacher_id == teacher_id
        assert db.session.get(QuestionBank, bank_id).teacher_id == teacher_id


def test_system_school_creation_is_idempotent(app):
    """نداء ثانٍ يعيد نفس المدرسة ولا يضاعف الصفوف الاثني عشر."""
    from app.models.school import Grade, School
    from app.services.schools import get_or_create_system_school

    with app.app_context():
        first = get_or_create_system_school()
        second = get_or_create_system_school()

        assert first.id == second.id
        assert School.query.filter_by(is_system=True).count() == 1
        assert Grade.query.filter_by(school_id=first.id).count() == 12


def test_class_summary_ignores_other_class_grade_items(app):
    """ملخص الصف يُبنى من بنوده فقط، وبنود صف آخر لا تظهر ولا تُسقط الحساب."""
    from app.services.grade_calc import class_grades_summary

    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_a = make_class(app, school_id, grade_id, subject_id)
    class_b = make_class(app, school_id, grade_id, subject_id)
    student_id = make_user(app, role="student", school_id=school_id)
    make_class_member(app, class_a, student_id)

    cat_a = make_grade_category(app, class_a, "أعمال", 100)
    item_a = make_grade_item(app, class_a, cat_a, "واجب", 10)
    make_grade_entry(app, student_id, item_a, 8)

    cat_b = make_grade_category(app, class_b, "أعمال", 100)
    item_b = make_grade_item(app, class_b, cat_b, "واجب آخر", 10)
    make_grade_entry(app, student_id, item_b, 2)

    with app.app_context():
        summary = class_grades_summary(class_a)

    assert len(summary) == 1
    assert summary[0]["student_id"] == student_id
    assert summary[0]["final_grade"] == 80.0
    assert [c["id"] for c in summary[0]["categories"]] == [cat_a]
    assert [i["id"] for i in summary[0]["categories"][0]["items"]] == [item_a]
