"""اختبارات بنك الأسئلة — نموذج + خدمة + مسارات."""

from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

# ═══════════════════════════════════════════════════════════════════
# خدمة: create, list, update, delete, import_to_quiz
# ═══════════════════════════════════════════════════════════════════


def test_create_bank_question(app):
    from app.services.question_bank import create_bank_question

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        q, err = create_bank_question(
            teacher_id=teacher_id,
            school_id=school_id,
            question_text="ما هو 2+2؟",
            question_type="mcq",
            options={"items": [{"label": "أ", "text": "3"}, {"label": "ب", "text": "4"}]},
            correct_answer={"index": 1},
            difficulty=2,
        )
        assert q is not None
        assert err is None
        assert q.question_text == "ما هو 2+2؟"
        assert q.question_type == "mcq"
        assert q.difficulty == 2


def test_create_bank_question_empty_text(app):
    from app.services.question_bank import create_bank_question

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        q, err = create_bank_question(teacher_id, school_id, "", "mcq")
        assert q is None
        assert err is not None


def test_create_bank_question_invalid_type(app):
    from app.services.question_bank import create_bank_question

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        q, err = create_bank_question(teacher_id, school_id, "سؤال", "invalid")
        assert q is None
        assert err is not None


def test_create_bank_question_difficulty_out_of_range(app):
    from app.services.question_bank import create_bank_question

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        q, err = create_bank_question(teacher_id, school_id, "سؤال", "essay", difficulty=99)
        assert q is None
        assert err is not None


def test_list_bank_questions(app):
    from app.services.question_bank import create_bank_question, list_bank_questions

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        create_bank_question(teacher_id, school_id, "سؤال 1", "mcq")
        create_bank_question(teacher_id, school_id, "سؤال 2", "true_false")
        create_bank_question(teacher_id, school_id, "سؤال 3", "essay")
        all_q = list_bank_questions(teacher_id)
        assert len(all_q) == 3
        mcq_only = list_bank_questions(teacher_id, question_type="mcq")
        assert len(mcq_only) == 1
        diff2 = list_bank_questions(teacher_id, difficulty=2)
        assert len(diff2) == 0


def test_delete_bank_question(app):
    from app.services.question_bank import create_bank_question, delete_bank_question

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        q, _ = create_bank_question(teacher_id, school_id, "حذفني", "mcq")
        ok, err = delete_bank_question(q.id, teacher_id)
        assert ok is True
        assert err is None


def test_delete_bank_question_not_found(app):
    from app.services.question_bank import delete_bank_question

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        ok, err = delete_bank_question(99999, teacher_id)
        assert ok is False
        assert err is not None


def test_delete_bank_question_unauthorized(app):
    from app.services.question_bank import create_bank_question, delete_bank_question

    school_id = make_school(app)
    t1 = make_user(app, role="teacher", school_id=school_id)
    t2 = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        q, _ = create_bank_question(t1, school_id, "سؤال", "mcq")
        ok, err = delete_bank_question(q.id, t2)
        assert ok is False
        assert err is not None


def test_update_bank_question(app):
    from app.services.question_bank import create_bank_question, update_bank_question

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        q, _ = create_bank_question(teacher_id, school_id, "أصلي", "mcq")
        updated, err = update_bank_question(q.id, teacher_id, question_text="جديد", difficulty=5)
        assert updated is not None
        assert err is None
        assert updated.question_text == "جديد"
        assert updated.difficulty == 5


def test_import_to_quiz(app):
    from app.services.assessment import create_quiz
    from app.services.question_bank import create_bank_question, import_to_quiz

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)
    with app.app_context():
        quiz, _ = create_quiz(class_id, "اختبار", created_by=teacher_id)
        q1, _ = create_bank_question(teacher_id, school_id, "س1", "mcq")
        q2, _ = create_bank_question(teacher_id, school_id, "س2", "true_false")
        count, err = import_to_quiz(quiz, [q1.id, q2.id], teacher_id)
        assert err is None
        assert count == 2


def test_import_to_quiz_empty_ids(app):
    from app.services.question_bank import import_to_quiz

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)
    with app.app_context():
        from app.services.assessment import create_quiz

        quiz, _ = create_quiz(class_id, "اختبار", created_by=teacher_id)
        count, err = import_to_quiz(quiz, [], teacher_id)
        assert count == 0
        assert err is not None


# ═══════════════════════════════════════════════════════════════════
# مسارات الويب
# ═══════════════════════════════════════════════════════════════════


def test_question_bank_list_page(client, app):
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        pass
    with client.session_transaction() as s:
        s["_user_id"] = str(teacher_id)
    resp = client.get("/classes/question-bank")
    assert resp.status_code == 200


def test_question_bank_create_route(client, app):
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    subject_id = make_subject(app)
    with client.session_transaction() as s:
        s["_user_id"] = str(teacher_id)
    resp = client.post(
        "/classes/question-bank/new",
        data={
            "question_text": "اختبار route",
            "question_type": "mcq",
            "subject_id": str(subject_id),
            "difficulty": "3",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 200)


def test_question_bank_delete_route(client, app):
    from app.services.question_bank import create_bank_question

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        q, _ = create_bank_question(teacher_id, school_id, "حذف", "mcq")
        q_id = q.id
    with client.session_transaction() as s:
        s["_user_id"] = str(teacher_id)
    resp = client.post(f"/classes/question-bank/{q_id}/delete", follow_redirects=False)
    assert resp.status_code in (302, 200)
