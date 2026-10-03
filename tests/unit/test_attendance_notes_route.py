"""ملاحظات الحضور من النموذج إلى قاعدة البيانات — اختبارات تكامل كاملة.

تغطي سلسلة: ``attendance_save`` (المسار) ← ``record_attendance`` (الخدمة)
← صف ``attendance``. تركيز الاختبارات على **دلالة الفراغ**، لأن المتصفح
يرسل ``note_<id>=""`` لكل صف لم يلمسه المعلم: إرسالها كما هي يمسح كل
الملاحظات المحفوظة، وتجاهلها دائماً يمنع المسح الصريح.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from tests.conftest import (
    QueryCounter,
    make_class,
    make_class_member,
    make_grade,
    make_school,
    make_subject,
    make_user,
)

PASSWORD = "TestPass123!"
DAY = date(2026, 3, 4)


def _email(tag: str) -> str:
    return f"att-{tag}-{uuid.uuid4().hex[:8]}@test.com"


@pytest.fixture
def class_with_teacher(app):
    """صف + معلّم + طالبان — groundwork لمسار حفظ الحضور."""
    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    teacher_email = _email("t")
    teacher_id = make_user(app, role="teacher", school_id=school_id, email=teacher_email)
    students = [make_user(app, role="student", school_id=school_id, email=_email("s")) for _ in range(2)]
    for student_id in students:
        make_class_member(app, class_id, student_id)

    from app.models.class_room import ClassRoom
    from tests.conftest import _db

    with app.app_context():
        _db.session.get(ClassRoom, class_id).teacher_id = teacher_id
        _db.session.commit()
    return school_id, class_id, teacher_id, teacher_email, students


def _client(app, email: str):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return client


def _stored(app, class_id: int, student_id: int):
    """قيمة ملاحظة الصف المخزَّنة — تُقرأ داخل السياق (لا كائن منفصل)."""
    from app.models.attendance import Attendance

    with app.app_context():
        row = Attendance.query.filter_by(class_id=class_id, student_id=student_id, date=DAY).first()
        return None if row is None else (row.status, row.note)


class TestAttendanceNoteFlow:
    """INSERT ثم UPDATE عبر المسار الحقيقي."""

    def test_note_persisted_on_first_submit(self, app, class_with_teacher):
        _school, class_id, _tid, teacher_email, students = class_with_teacher
        client = _client(app, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/attendance?date={DAY.isoformat()}",
            data={f"status_{students[0]}": "absent", f"note_{students[0]}": "لم يحضر مع عذر"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert _stored(app, class_id, students[0]) == ("absent", "لم يحضر مع عذر")

    def test_note_overwritten_on_second_submit(self, app, class_with_teacher):
        _school, class_id, _tid, teacher_email, students = class_with_teacher
        client = _client(app, teacher_email)
        sid = students[0]
        url = f"/classes/{class_id}/attendance?date={DAY.isoformat()}"
        client.post(url, data={f"status_{sid}": "absent", f"note_{sid}": "ملاحظة أولى"})
        client.post(url, data={f"status_{sid}": "excused", f"note_{sid}": "تغيّر السبب"})
        assert _stored(app, class_id, sid) == ("excused", "تغيّر السبب"), "الملاحظة الجديدة لم تكتب"

    def test_untouched_empty_field_keeps_note(self, app, class_with_teacher):
        """حقل فارغ لم يلمسه المعلم = "لم يُمرَّر" — لا يمسح الملاحظة.

        هذا هو الحالة الشائعة في الواجهة: المتصفح يرسل ``note_x=""`` لكل
        صف، ولو مرّرناه كما هو لضاعت كل الملاحظات المحفوظة عند كل حفظ.
        """
        _school, class_id, _tid, teacher_email, students = class_with_teacher
        client = _client(app, teacher_email)
        sid = students[0]
        url = f"/classes/{class_id}/attendance?date={DAY.isoformat()}"
        client.post(url, data={f"status_{sid}": "absent", f"note_{sid}": "ملاحظة محفوظة"})
        client.post(url, data={f"status_{sid}": "late", f"note_{sid}": ""})
        assert _stored(app, class_id, sid) == ("late", "ملاحظة محفوظة")

    def test_absent_note_field_keeps_note(self, app, class_with_teacher):
        """حقل غير مُرسل إطلاقاً — المسار الأقدم بلا ملاحظات."""
        _school, class_id, _tid, teacher_email, students = class_with_teacher
        client = _client(app, teacher_email)
        sid = students[0]
        url = f"/classes/{class_id}/attendance?date={DAY.isoformat()}"
        client.post(url, data={f"status_{sid}": "absent", f"note_{sid}": "محفوظة"})
        client.post(url, data={f"status_{sid}": "present"})
        assert _stored(app, class_id, sid) == ("present", "محفوظة")

    def test_explicit_clear_is_supported(self, app, class_with_teacher):
        """المسح الصريح عبر خانة الاختيار — لا بالحقل الفارغ."""
        _school, class_id, _tid, teacher_email, students = class_with_teacher
        client = _client(app, teacher_email)
        sid = students[0]
        url = f"/classes/{class_id}/attendance?date={DAY.isoformat()}"
        client.post(url, data={f"status_{sid}": "absent", f"note_{sid}": "سأمسحها"})
        client.post(
            url,
            data={f"status_{sid}": "absent", f"note_{sid}": "", f"clear_note_{sid}": "1"},
        )
        assert _stored(app, class_id, sid) == ("absent", "")

    def test_notes_are_isolated_per_student(self, app, class_with_teacher):
        _school, class_id, _tid, teacher_email, students = class_with_teacher
        client = _client(app, teacher_email)
        a, b = students
        client.post(
            f"/classes/{class_id}/attendance?date={DAY.isoformat()}",
            data={
                f"status_{a}": "absent",
                f"note_{a}": "للطالب الأول",
                f"status_{b}": "late",
                f"note_{b}": "للطالب الثاني",
            },
        )
        assert _stored(app, class_id, a) == ("absent", "للطالب الأول")
        assert _stored(app, class_id, b) == ("late", "للطالب الثاني")

    def test_whitespace_is_normalized(self, app, class_with_teacher):
        """المسافات تُقصّ فلا تختلف عن المخزَّن بلا فائدة."""
        _school, class_id, _tid, teacher_email, students = class_with_teacher
        client = _client(app, teacher_email)
        sid = students[0]
        client.post(
            f"/classes/{class_id}/attendance?date={DAY.isoformat()}",
            data={f"status_{sid}": "absent", f"note_{sid}": "  مُنظَّفة  "},
        )
        assert _stored(app, class_id, sid) == ("absent", "مُنظَّفة")

    def test_invalid_status_only_post_writes_nothing(self, app, class_with_teacher):
        """لا حالة صالحة ⇒ لا كتابة ولا ملاحظات (حارس المسار)."""
        _school, class_id, _tid, teacher_email, students = class_with_teacher
        client = _client(app, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/attendance?date={DAY.isoformat()}",
            data={f"status_{students[0]}": "مشترك", f"note_{students[0]}": "ملاحظة يتيمة"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert _stored(app, class_id, students[0]) is None, "كُتب صف بلا حالة صالحة"

    def test_overlong_note_is_rejected_atomically(self, app, class_with_teacher):
        """ملاحظة أطول من الحد: تُرفض الدفعة كاملة ولا تُكتب نصفها."""
        from app.config.constants import ATTENDANCE_NOTE_MAX_LEN

        _school, class_id, _tid, teacher_email, students = class_with_teacher
        client = _client(app, teacher_email)
        a, b = students
        resp = client.post(
            f"/classes/{class_id}/attendance?date={DAY.isoformat()}",
            data={
                f"status_{a}": "present",
                f"status_{b}": "absent",
                f"note_{b}": "س" * (ATTENDANCE_NOTE_MAX_LEN + 1),
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert _stored(app, class_id, a) is None, "كُتب صف من دفعة مرفوضة"


class TestAttendanceNoteQueryBudget:
    """ميزانية الاستعلامات: O(1) لا تتغيّر مع حجم الصف."""

    def test_post_query_count_does_not_scale_with_class_size(self, app, class_with_teacher):
        from app.extensions import db

        school_id, class_id, _tid, teacher_email, students = class_with_teacher
        # نوسّع الصف إلى 8 طلاب: أي N+1 في المسار يظهر فرقاً في العدّ.
        extra = [make_user(app, role="student", school_id=school_id, email=_email("x")) for _ in range(6)]
        for student_id in extra:
            make_class_member(app, class_id, student_id)
        client = _client(app, teacher_email)
        everyone = list(students) + list(extra)

        counts = []
        for size in (2, len(everyone)):
            data = {f"status_{s}": "present" for s in everyone[:size]}
            data.update({f"note_{s}": f"ملاحظة {s}" for s in everyone[:size]})
            with app.app_context():
                with QueryCounter(db.engine) as qc:
                    client.post(
                        f"/classes/{class_id}/attendance?date={DAY.isoformat()}",
                        data=data,
                        follow_redirects=False,
                    )
            counts.append(qc.count)
        assert counts[0] == counts[1], f"عدد استعلامات المسار تغيّر مع حجم الصف: {counts} — عائد إلى O(N)"

    def test_service_note_path_is_bounded(self, app, class_with_teacher):
        """سقف صريح على الخدمة نفسها مع تمرير ملاحظة لكل طالب."""
        from app.extensions import db
        from app.services.gradebook import record_attendance

        _school, class_id, _tid, _mail, students = class_with_teacher
        with app.app_context():
            with QueryCounter(db.engine) as qc:
                record_attendance(
                    class_id,
                    DAY,
                    {s: "present" for s in students},
                    notes={s: f"ملاحظة {s}" for s in students},
                )
            assert qc.count <= 2, f"الخدمة استهلكت {qc.count} استعلامات (السقف 2)"


class TestAttendanceNoteAccessAndTemplate:
    """الصلاحيات وقالب العرض."""

    def test_student_cannot_write_attendance_notes(self, app, class_with_teacher):
        school_id, class_id, _tid, _teacher_email, students = class_with_teacher
        intruder = make_user(app, role="student", school_id=school_id, email=_email("stu"))
        client = _client(app, _email_of(app, intruder))
        resp = client.post(
            f"/classes/{class_id}/attendance?date={DAY.isoformat()}",
            data={f"status_{students[0]}": "absent", f"note_{students[0]}": "تخريب"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 403)
        assert _stored(app, class_id, students[0]) is None, "طالب كتب في الحضور"

    def test_template_renders_note_field_for_teacher(self, app, class_with_teacher):
        _school, class_id, _tid, teacher_email, students = class_with_teacher
        client = _client(app, teacher_email)
        html = client.get(f"/classes/{class_id}/attendance?date={DAY.isoformat()}").get_data(as_text=True)
        assert f'name="note_{students[0]}"' in html, "حقل الملاحظة غائب عن القالب"
        assert "maxlength=" in html

    def test_template_is_readonly_without_teach_right(self, app, class_with_teacher):
        from app.services.gradebook import record_attendance

        school_id, class_id, _tid, _teacher_email, students = class_with_teacher
        with app.app_context():
            record_attendance(class_id, DAY, {students[0]: "absent"}, notes={students[0]: "ملاحظة مقروءة"})
        viewer = make_user(app, role="student", school_id=school_id, email=_email("v"))
        make_class_member(app, class_id, viewer)  # يعرض الصف ولا يدرّسه
        client = _client(app, _email_of(app, viewer))
        html = client.get(f"/classes/{class_id}/attendance?date={DAY.isoformat()}").get_data(as_text=True)
        assert f'name="note_{students[0]}"' not in html, "لا حقل إدخال لمن لا يدرّس"
        assert "ملاحظة مقروءة" in html, "الملاحظة المقروءة يجب أن تظهر"


def _email_of(app, user_id: int) -> str:
    from app.extensions import db
    from app.models.user import User

    with app.app_context():
        return db.session.get(User, user_id).email
