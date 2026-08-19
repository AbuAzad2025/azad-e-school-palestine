"""اختبارات وضع عدم الاتصال — Offline Mode."""

from app.extensions import db
from app.models.offline import OfflineDownload
from app.services.offline import (
    expire_old_downloads,
    get_offline_items,
    mark_downloaded,
    mark_for_download,
    remove_offline,
)
from tests.conftest import (
    make_attachment,
    make_class,
    make_grade,
    make_lesson,
    make_school,
    make_subject,
    make_user,
)


def _setup(app):
    with app.app_context():
        sid = make_user(app, role="student")
        school = make_school(app)
        grade = make_grade(app, school)
        subject = make_subject(app)
        teacher = make_user(app, role="teacher")
        cid = make_class(app, school, grade, subject, teacher)
        lid = make_lesson(app, cid)
        aid = make_attachment(app, lid)
    return sid, school, grade, subject, teacher, cid, lid, aid


def test_offline_model(app):
    sid, school, grade, subject, teacher, cid, lid, aid = _setup(app)
    with app.app_context():
        d = OfflineDownload(student_id=sid, attachment_id=aid, lesson_id=lid, status="pending")
        db.session.add(d)
        db.session.commit()
        assert d.id is not None


def test_mark_for_download(app):
    sid, school, grade, subject, teacher, cid, lid, aid = _setup(app)
    with app.app_context():
        result = mark_for_download(sid, aid, lid)
        assert result is not None
        assert result.status == "ready"


def test_mark_for_download_duplicate(app):
    sid, school, grade, subject, teacher, cid, lid, aid = _setup(app)
    with app.app_context():
        mark_for_download(sid, aid, lid)
        result2 = mark_for_download(sid, aid, lid)
        assert result2 is None


def test_get_offline_items(app):
    sid, school, grade, subject, teacher, cid, lid, aid = _setup(app)
    with app.app_context():
        mark_for_download(sid, aid, lid)
        items = get_offline_items(sid)
        assert len(items) == 1


def test_remove_offline(app):
    sid, school, grade, subject, teacher, cid, lid, aid = _setup(app)
    with app.app_context():
        d = mark_for_download(sid, aid, lid)
        remove_offline(d.id)
        items = get_offline_items(sid)
        assert len(items) == 0


def test_mark_downloaded(app):
    sid, school, grade, subject, teacher, cid, lid, aid = _setup(app)
    with app.app_context():
        d = mark_for_download(sid, aid, lid)
        mark_downloaded(d.id)
        d2 = db.session.get(OfflineDownload, d.id)
        assert d2.status == "ready"
        assert d2.downloaded_at is not None


def test_expire_old_downloads(app):
    sid, school, grade, subject, teacher, cid, lid, aid = _setup(app)
    with app.app_context():
        from datetime import UTC, datetime, timedelta

        d = OfflineDownload(
            student_id=sid,
            attachment_id=aid,
            lesson_id=lid,
            status="ready",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        db.session.add(d)
        db.session.commit()
        expired = expire_old_downloads()
        assert expired >= 1
        d2 = db.session.get(OfflineDownload, d.id)
        assert d2.status == "expired"


def test_empty_offline_list(app):
    sid, school, grade, subject, teacher, cid, lid, aid = _setup(app)
    with app.app_context():
        items = get_offline_items(sid)
        assert items == []


def test_offline_requires_unique_student_attachment(app):
    sid, school, grade, subject, teacher, cid, lid, aid = _setup(app)
    with app.app_context():
        s2 = make_user(app, role="student")
        mark_for_download(sid, aid, lid)
        r2 = mark_for_download(s2, aid, lid)
        assert r2 is not None
