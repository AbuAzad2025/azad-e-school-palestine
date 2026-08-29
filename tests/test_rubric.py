"""اختبارات التقييم بالمعيار (Rubric Grading)."""

from app.extensions import db
from app.models.gradebook import (
    Assignment,
    Submission,
)
from app.services.rubric import (
    create_rubric_template,
    get_rubric_grades,
    get_rubric_template,
    grade_with_rubric,
    list_rubric_templates,
    rubric_total_score,
)
from tests.conftest import (
    make_class,
    make_grade,
    make_school,
    make_subject,
    make_user,
)


def _setup(app):
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)
    assignment_id = None
    submission_id = None
    with app.app_context():
        a = Assignment(
            class_id=class_id,
            title="essay 1",
            max_mark=100,
            created_by=teacher_id,
        )
        db.session.add(a)
        db.session.flush()
        assignment_id = a.id
        s = Submission(
            assignment_id=assignment_id,
            student_id=student_id,
            body="my essay",
        )
        db.session.add(s)
        db.session.flush()
        submission_id = s.id
        db.session.commit()
    return school_id, teacher_id, student_id, class_id, assignment_id, submission_id


def test_rubric_template_creation(app):
    school_id, teacher_id, *_ = _setup(app)
    with app.app_context():
        t = create_rubric_template(
            teacher_id=teacher_id,
            school_id=school_id,
            title="Essay Rubric",
            description="Grading rubric for essays",
            criteria=[
                {"title": "Content", "max_score": 30, "description": "Idea depth"},
                {"title": "Grammar", "max_score": 20, "description": "Language accuracy"},
            ],
        )
        assert t.id is not None
        assert t.title == "Essay Rubric"
        assert len(t.criteria) == 2


def test_rubric_criteria_ordering(app):
    school_id, teacher_id, *_ = _setup(app)
    with app.app_context():
        t = create_rubric_template(
            teacher_id=teacher_id,
            school_id=school_id,
            title="Ordered",
            criteria=[
                {"title": "C", "max_score": 10},
                {"title": "A", "max_score": 10},
                {"title": "B", "max_score": 10},
            ],
        )
        db.session.refresh(t)
        orders = [c.sort_order for c in t.criteria]
        assert orders == [1, 2, 3]


def test_grade_with_rubric(app):
    school_id, teacher_id, student_id, *_rest, submission_id = _setup(app)
    with app.app_context():
        t = create_rubric_template(
            teacher_id=teacher_id,
            school_id=school_id,
            title="R",
            criteria=[
                {"title": "Content", "max_score": 50},
                {"title": "Style", "max_score": 50},
            ],
        )
        db.session.refresh(t)
        c1, c2 = t.criteria[0], t.criteria[1]
        results = grade_with_rubric(
            submission_id=submission_id,
            grades=[
                {"criterion_id": c1.id, "score": 40, "comment": "Good"},
                {"criterion_id": c2.id, "score": 35},
            ],
            graded_by=teacher_id,
        )
        assert len(results) == 2
        assert float(results[0].score) == 40


def test_rubric_grades_are_upserted(app):
    school_id, teacher_id, student_id, *_rest, submission_id = _setup(app)
    with app.app_context():
        t = create_rubric_template(
            teacher_id=teacher_id,
            school_id=school_id,
            title="R",
            criteria=[{"title": "X", "max_score": 10}],
        )
        db.session.refresh(t)
        cid = t.criteria[0].id
        grade_with_rubric(
            submission_id=submission_id,
            grades=[{"criterion_id": cid, "score": 5}],
            graded_by=teacher_id,
        )
        grade_with_rubric(
            submission_id=submission_id,
            grades=[{"criterion_id": cid, "score": 8}],
            graded_by=teacher_id,
        )
        gs = get_rubric_grades(submission_id)
        assert len(gs) == 1
        assert float(gs[0].score) == 8


def test_get_rubric_grades(app):
    school_id, teacher_id, student_id, *_rest, submission_id = _setup(app)
    with app.app_context():
        t = create_rubric_template(
            teacher_id=teacher_id,
            school_id=school_id,
            title="R",
            criteria=[
                {"title": "A", "max_score": 20},
                {"title": "B", "max_score": 20},
            ],
        )
        db.session.refresh(t)
        grade_with_rubric(
            submission_id=submission_id,
            grades=[
                {"criterion_id": t.criteria[0].id, "score": 15},
                {"criterion_id": t.criteria[1].id, "score": 18},
            ],
            graded_by=teacher_id,
        )
        gs = get_rubric_grades(submission_id)
        assert len(gs) == 2


def test_rubric_total_score(app):
    school_id, teacher_id, student_id, *_rest, submission_id = _setup(app)
    with app.app_context():
        t = create_rubric_template(
            teacher_id=teacher_id,
            school_id=school_id,
            title="R",
            criteria=[
                {"title": "A", "max_score": 30},
                {"title": "B", "max_score": 30},
                {"title": "C", "max_score": 30},
            ],
        )
        db.session.refresh(t)
        grade_with_rubric(
            submission_id=submission_id,
            grades=[
                {"criterion_id": t.criteria[0].id, "score": 25},
                {"criterion_id": t.criteria[1].id, "score": 20},
                {"criterion_id": t.criteria[2].id, "score": 15},
            ],
            graded_by=teacher_id,
        )
        assert rubric_total_score(submission_id) == 60


def test_list_rubric_templates(app):
    school_id, teacher_id, *_ = _setup(app)
    with app.app_context():
        create_rubric_template(
            teacher_id=teacher_id,
            school_id=school_id,
            title="First",
        )
        create_rubric_template(
            teacher_id=teacher_id,
            school_id=school_id,
            title="Second",
        )
        templates = list_rubric_templates(teacher_id)
        assert len(templates) == 2
        assert templates[0].title == "Second"


def test_rubric_template_with_empty_criteria(app):
    school_id, teacher_id, *_ = _setup(app)
    with app.app_context():
        t = create_rubric_template(
            teacher_id=teacher_id,
            school_id=school_id,
            title="Empty",
        )
        assert t.id is not None
        fetched = get_rubric_template(t.id)
        assert fetched is not None
        assert len(fetched.criteria) == 0


def test_grade_with_rubric_empty_grades(app):
    """Grading with empty grades list should return empty list."""
    school_id, teacher_id, student_id, *_rest, submission_id = _setup(app)
    with app.app_context():
        create_rubric_template(
            teacher_id=teacher_id,
            school_id=school_id,
            title="R",
            criteria=[{"title": "X", "max_score": 10}],
        )
        results = grade_with_rubric(
            submission_id=submission_id,
            grades=[],
            graded_by=teacher_id,
        )
        assert results == []


def test_get_rubric_template_nonexistent(app):
    """Getting a nonexistent template returns None."""
    with app.app_context():
        result = get_rubric_template(999999)
        assert result is None


def test_get_rubric_grades_empty(app):
    """Getting grades for ungraded submission returns empty list."""
    school_id, teacher_id, student_id, *_rest, submission_id = _setup(app)
    with app.app_context():
        gs = get_rubric_grades(submission_id)
        assert gs == []


def test_rubric_total_score_no_grades(app):
    """Total score for ungraded submission returns 0."""
    school_id, teacher_id, student_id, *_rest, submission_id = _setup(app)
    with app.app_context():
        total = rubric_total_score(submission_id)
        assert total == 0
