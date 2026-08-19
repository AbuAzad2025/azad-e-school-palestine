"""اختبارات اعتراضات الدرجات."""

from datetime import UTC, datetime

from app.extensions import db
from app.models.gradebook import Assignment, GradeAppeal, Submission
from app.services import grade_appeals as svc
from tests.conftest import make_class, make_grade, make_school, make_subject, make_user


def _setup_submission(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        tid = make_user(app, role="teacher", school_id=sid)
        cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
        stid = make_user(app, role="student", school_id=sid)
        a = Assignment(class_id=cid, title="واجب اختبار", max_mark=100, created_by=tid)
        db.session.add(a)
        db.session.commit()
        s = Submission(assignment_id=a.id, student_id=stid, body="تسليمي", submitted_at=datetime.now(UTC))
        db.session.add(s)
        db.session.commit()
        return stid, tid, s.id, a.id


def test_submit_appeal(app):
    stid, tid, sub_id, aid = _setup_submission(app)
    with app.app_context():
        result = svc.submit_appeal(sub_id, stid, "الدرجة غير صحيحة")
        assert result is not None
        assert result.status == "pending"
        assert result.reason == "الدرجة غير صحيحة"


def test_submit_appeal_duplicate_prevention(app):
    stid, tid, sub_id, aid = _setup_submission(app)
    with app.app_context():
        svc.submit_appeal(sub_id, stid, "أول اعتراض")
        dup = svc.submit_appeal(sub_id, stid, "اعتراض مكرر")
        assert dup is None


def test_submit_appeal_empty_reason_rejected(app):
    stid, tid, sub_id, aid = _setup_submission(app)
    with app.app_context():
        assert svc.submit_appeal(sub_id, stid, "") is None
        assert svc.submit_appeal(sub_id, stid, "   ") is None
        assert svc.submit_appeal(sub_id, stid, None) is None


def test_review_appeal_approve(app):
    stid, tid, sub_id, aid = _setup_submission(app)
    with app.app_context():
        appeal = svc.submit_appeal(sub_id, stid, "أطلب إعادة التقييم")
        result = svc.review_appeal(appeal.id, "approved", "تمت الموافقة", tid)
        assert result.status == "approved"
        assert result.reviewed_by == tid
        assert result.reviewed_at is not None


def test_review_appeal_reject(app):
    stid, tid, sub_id, aid = _setup_submission(app)
    with app.app_context():
        appeal = svc.submit_appeal(sub_id, stid, "الدرجة صحيحة")
        result = svc.review_appeal(appeal.id, "rejected", "الدرجة م纩اة", tid)
        assert result.status == "rejected"
        assert result.teacher_response == "الدرجة م纩اة"


def test_review_appeal_invalid_status(app):
    stid, tid, sub_id, aid = _setup_submission(app)
    with app.app_context():
        appeal = svc.submit_appeal(sub_id, stid, "اختبار")
        result = svc.review_appeal(appeal.id, "invalid", None, tid)
        assert result is None
        appeal_obj = db.session.get(GradeAppeal, appeal.id)
        assert appeal_obj.status == "pending"


def test_get_student_appeals(app):
    stid, tid, sub_id, aid = _setup_submission(app)
    with app.app_context():
        svc.submit_appeal(sub_id, stid, "اعتراض 1")
        appeals = svc.get_student_appeals(stid)
        assert len(appeals) == 1
        assert appeals[0].student_id == stid


def test_get_pending_appeals(app):
    stid, tid, sub_id, aid = _setup_submission(app)
    with app.app_context():
        svc.submit_appeal(sub_id, stid, "انتظار")
        pending = svc.get_pending_appeals()
        assert any(a.submission_id == sub_id for a in pending)
