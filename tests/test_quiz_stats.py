"""اختبارات إحصائيات الاختبارات."""

from app.services.quiz_stats import get_quiz_stats
from tests.conftest import make_class, make_grade, make_school, make_subject, make_user


def test_quiz_stats_empty(app):
    """إحصائيات اختبار بلا محاولات ترجع أصفاراً."""
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

    with app.app_context():
        from app.services.assessment import create_quiz

        quiz, _ = create_quiz(class_id, "اختبار تجريبي", created_by=teacher_id)
        quiz_id = quiz.id

    with app.app_context():
        stats = get_quiz_stats(quiz_id)

    assert stats is not None
    assert stats.total_attempts == 0
    assert stats.avg_score == 0.0
    assert stats.highest_score == 0.0
    assert stats.lowest_score == 0.0
    assert stats.completion_rate == 0.0
    assert stats.std_deviation == 0.0
    assert stats.question_stats == []


def test_quiz_stats_with_attempts(app):
    """إحصائيات اختبار مع محاولات تحسب بشكل صحيح."""
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    student1_id = make_user(app, role="student", school_id=school_id)
    student2_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

    with app.app_context():
        from app.extensions import db
        from app.models.assessment import Question
        from app.models.class_room import ClassMember
        from app.services.assessment import create_quiz, save_answer, start_attempt, submit_attempt

        # إضافة الطالبين للصف
        cm1 = ClassMember(class_id=class_id, user_id=student1_id, status="active")
        cm2 = ClassMember(class_id=class_id, user_id=student2_id, status="active")
        db.session.add_all([cm1, cm2])
        db.session.commit()

        quiz, _ = create_quiz(class_id, "اختبار إحصائي", created_by=teacher_id)
        q1 = Question(
            quiz_id=quiz.id,
            type="mcq",
            prompt="2+2=?",
            options={"items": [{"label": "أ", "text": "3"}, {"label": "ب", "text": "4"}]},
            correct_answer={"index": 1},
            mark=2.0,
        )
        q2 = Question(
            quiz_id=quiz.id,
            type="mcq",
            prompt="3+3=?",
            options={"items": [{"label": "أ", "text": "5"}, {"label": "ب", "text": "6"}]},
            correct_answer={"index": 1},
            mark=2.0,
        )
        q3 = Question(
            quiz_id=quiz.id, type="true_false", prompt="الشمس تشرق من الغرب", correct_answer={"value": False}, mark=1.0
        )
        db.session.add_all([q1, q2, q3])
        db.session.commit()

        # محاولة الطالب 1 - إجابتين صحيحتين، واحدة خاطئة
        attempt1, _ = start_attempt(quiz, student1_id)
        save_answer(attempt1, q1.id, {"index": 1})
        save_answer(attempt1, q2.id, {"index": 1})
        save_answer(attempt1, q3.id, {"value": True})  # خاطئة
        submit_attempt(attempt1)

        # محاولة الطالب 2 - ثلاث إجابات صحيحة
        attempt2, _ = start_attempt(quiz, student2_id)
        save_answer(attempt2, q1.id, {"index": 1})
        save_answer(attempt2, q2.id, {"index": 1})
        save_answer(attempt2, q3.id, {"value": False})
        submit_attempt(attempt2)

        quiz_id = quiz.id
        q1_id = q1.id
        q3_id = q3.id

    with app.app_context():
        stats = get_quiz_stats(quiz_id)

    assert stats is not None
    assert stats.total_attempts == 2
    # Student 1: 2+2+0 = 4, Student 2: 2+2+1 = 5, avg = 4.5
    assert stats.avg_score == 4.5
    assert stats.highest_score == 5.0
    assert stats.lowest_score == 4.0
    assert stats.question_stats is not None
    assert len(stats.question_stats) == 3

    # سؤال 1: كلاهما صحيح -> difficulty 1.0
    q1_stat = next(s for s in stats.question_stats if s.question_id == q1_id)
    assert q1_stat.difficulty_index == 1.0

    # سؤال 3: واحد صحيح من اثنين -> difficulty 0.5
    q3_stat = next(s for s in stats.question_stats if s.question_id == q3_id)
    assert q3_stat.difficulty_index == 0.5


def test_quiz_stats_discrimination_index(app):
    """مؤشر التمييز يحسب بشكل صحيح مع المجموعات العليا والدنيا."""
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    students = [make_user(app, role="student", school_id=school_id) for _ in range(10)]
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

    with app.app_context():
        from app.extensions import db
        from app.models.assessment import Question
        from app.models.class_room import ClassMember
        from app.services.assessment import create_quiz, save_answer, start_attempt, submit_attempt

        for sid in students:
            db.session.add(ClassMember(class_id=class_id, user_id=sid, status="active"))
        db.session.commit()

        quiz, _ = create_quiz(class_id, "اختبار تمييز", created_by=teacher_id)
        q = Question(
            quiz_id=quiz.id,
            type="mcq",
            prompt="سؤال للتمييز",
            options={"items": [{"label": "أ", "text": "خاطئ"}, {"label": "ب", "text": "صحيح"}]},
            correct_answer={"index": 1},
            mark=1.0,
        )
        db.session.add(q)
        db.session.commit()

        # أعلى 3 طلاب يجيبون بشكل صحيح، أدنى 3 يجيبون خاطئاً
        for i, sid in enumerate(students):
            attempt, _ = start_attempt(quiz, sid)
            save_answer(attempt, q.id, {"index": 1 if i < 3 else 0})
            submit_attempt(attempt)

        quiz_id = quiz.id
        q_id = q.id

    with app.app_context():
        stats = get_quiz_stats(quiz_id)

    assert stats is not None
    q_stat = stats.question_stats[0]
    # المجموعات العليا 100% صحيحة، المجموعات الدنيا 0% صحيحة -> discrimination = 1.0
    assert q_stat.discrimination_index == 1.0


def test_quiz_stats_nonexistent_quiz(app):
    """اختبار غير موجود يرجع None."""
    with app.app_context():
        stats = get_quiz_stats(99999)
    assert stats is None


# Route tests
def test_quiz_stats_route_teacher_access(app, client):
    """المعلم يمكنه الوصول لإحصائيات الاختبار."""
    school_id = make_school(app)
    teacher_email = f"teacher_{school_id}@test.com"
    teacher_id = make_user(app, role="teacher", school_id=school_id, email=teacher_email)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

    with app.app_context():
        from app.services.assessment import create_quiz

        quiz, _ = create_quiz(class_id, "اختبار", created_by=teacher_id)
        quiz_id = quiz.id

    with client:
        client.post("/auth/login", data={"email": teacher_email, "password": "TestPass123!"})
        resp = client.get(f"/classes/quiz/{quiz_id}/stats")
        assert resp.status_code == 200
        data = resp.get_data(as_text=True)
        assert "إحصائيات الاختبار" in data


def test_quiz_stats_route_student_forbidden(app, client):
    """الطالب لا يمكنه الوصول للإحصائيات."""
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    student_email = f"student_{school_id}@test.com"
    student_id = make_user(app, role="student", school_id=school_id, email=student_email)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

    with app.app_context():
        from app.services.assessment import create_quiz

        quiz, _ = create_quiz(class_id, "اختبار", created_by=teacher_id)
        quiz_id = quiz.id

    with client:
        client.post("/auth/login", data={"email": student_email, "password": "TestPass123!"})
        resp = client.get(f"/classes/quiz/{quiz_id}/stats")
        assert resp.status_code == 403


def test_quiz_stats_route_school_admin_access(app, client):
    """مشرف المدرسة يمكنه الوصول للإحصائيات."""
    school_id = make_school(app)
    admin_email = f"admin_{school_id}@test.com"
    admin_id = make_user(app, role="school_admin", school_id=school_id, email=admin_email)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

    with app.app_context():
        from app.services.assessment import create_quiz

        quiz, _ = create_quiz(class_id, "اختبار", created_by=teacher_id)
        quiz_id = quiz.id

    with client:
        client.post("/auth/login", data={"email": admin_email, "password": "TestPass123!"})
        resp = client.get(f"/classes/quiz/{quiz_id}/stats")
        assert resp.status_code == 200
