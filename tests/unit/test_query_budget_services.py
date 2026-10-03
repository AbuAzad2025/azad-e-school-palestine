"""ميزانيات استعلامات لخدمات الإصلاح — N+1 صفر في المسارات الحرجة.

كل اختبار يحصي عبارات SQL التي ينفّذها الكود فعلياً ويضع سقفاً صارماً،
فيتحوّل أي انحدار لاحق إلى فشل اختبار مباشر بدل اكتشافه في الإنتاج.

يعتمد على ``QueryCounter`` القائم في tests/test_query_performance.py.
"""

from __future__ import annotations

from datetime import date, timedelta

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


@pytest.fixture
def class_with_students(app):
    """صف فيه عدد من الطلاب —_baseline لتحوّل N إلى 1."""
    school = make_school(app)
    grade = make_grade(app, school)
    subject_id = make_subject(app)
    teacher = make_user(app, role="teacher", school_id=school)
    class_id = make_class(app, school, grade, subject_id, teacher_id=teacher)
    students = [make_user(app, role="student", school_id=school) for _ in range(8)]
    for sid in students:
        make_class_member(app, class_id, sid)
    return class_id, teacher, students


class TestAttendanceQueryBudget:
    """تسجيل حضور صف كامل يجب أن يبقى استعلامين مهما زاد عدد الطلاب."""

    def test_record_attendance_is_constant_queries(self, app, class_with_students):
        from app.extensions import db
        from app.services.gradebook import record_attendance

        class_id, _teacher, students = class_with_students
        day = date(2026, 3, 1)
        records = {sid: ("present" if i % 2 else "absent") for i, sid in enumerate(students)}

        with app.app_context():
            with QueryCounter(db.engine) as qc:
                record_attendance(class_id, day, records, recorded_by=None)
            assert qc.count <= 2, f"record_attendance استهلك {qc.count} استعلامات (السقف 2)"

    def test_record_attendance_updates_existing_rows(self, app, class_with_students):
        """التسجيل الثاني يجب أن يحدّث لا يكرّر — سلوك الـ upsert محفوظ."""
        from app.models.attendance import Attendance
        from app.services.gradebook import record_attendance

        class_id, _teacher, students = class_with_students
        day = date(2026, 3, 1)
        records = {sid: "present" for sid in students}

        with app.app_context():
            record_attendance(class_id, day, records)
            record_attendance(class_id, day, {students[0]: "absent"})
            rows = Attendance.query.filter_by(class_id=class_id, date=day).all()
            by_student = {r.student_id: r.status for r in rows}
            assert len(rows) == len(students), "لم تُنشأ صفوف مكررة"
            assert by_student[students[0]] == "absent"
            assert by_student[students[1]] == "present"

    def test_record_attendance_empty_is_noop(self, app, class_with_students):
        from app.extensions import db
        from app.services.gradebook import record_attendance

        class_id, _teacher, _students = class_with_students
        with app.app_context():
            with QueryCounter(db.engine) as qc:
                record_attendance(class_id, date(2026, 3, 1), {})
            assert qc.count == 0, "سجل فارغ لا يستحق فتح معاملة أصلاً"

    def test_attendance_summary_is_bounded_and_ordered(self, app, class_with_students):
        from app.services.gradebook import attendance_summary, record_attendance

        class_id, _teacher, students = class_with_students
        with app.app_context():
            for offset in range(5):
                record_attendance(
                    class_id,
                    date(2026, 1, 1) + timedelta(days=offset),
                    {students[0]: "present"},
                )
            rows = attendance_summary(class_id, students[0])
            assert len(rows) == 5
            days = [r.date for r in rows]
            assert days == sorted(days, reverse=True), "الترتيب تنازلي بالتاريخ"

    def test_attendance_summary_respects_limit(self, app, class_with_students):
        from app.services.gradebook import attendance_summary, record_attendance

        class_id, _teacher, students = class_with_students
        with app.app_context():
            for offset in range(4):
                record_attendance(
                    class_id,
                    date(2026, 1, 1) + timedelta(days=offset),
                    {students[0]: "present"},
                )
            assert len(attendance_summary(class_id, students[0], limit=2)) == 2


class TestAttendanceNoteSemantics:
    """دلالة ``note`` في التسجيل: تُكتب عند الإنشاء وعند التحديث.

     الخلل المُصلَح: الصف الموجود كان يُحدَّث في ``status`` وحده فتسقط
     ``note`` — أي أن ملاحظة المعلّم تضيع عند تعديل الحالة لنفس اليوم.
    التفريق: ``None`` تعني "لم تُمرَّر" (تُحفظ الملاحظة القائمة)، و``""`` تعني
     "امسح الملاحظة" صراحةً.
    """

    day = date(2026, 3, 1)

    def _note_of(self, class_id, student_id, day=None):
        from app.models.attendance import Attendance

        row = Attendance.query.filter_by(class_id=class_id, student_id=student_id, date=day or self.day).one()
        return row.note

    def test_note_is_stored_on_insert(self, app, class_with_students):
        """مسار INSERT: الملاحظة تُحفظ عند إنشاء الصف."""
        from app.services.gradebook import record_attendance

        class_id, _teacher, students = class_with_students
        with app.app_context():
            record_attendance(class_id, self.day, {students[0]: "present"}, note="سجلته إدارة المدرسة")
            assert self._note_of(class_id, students[0]) == "سجلته إدارة المدرسة"

    def test_note_overwrites_existing_on_update(self, app, class_with_students):
        """مسار UPDATE: الملاحظة الجديدة تُكتب فوق القديمة مع تحديث الحالة."""
        from app.services.gradebook import record_attendance

        class_id, _teacher, students = class_with_students
        student = students[0]
        with app.app_context():
            record_attendance(class_id, self.day, {student: "present"}, note="ملاحظة أولى")
            record_attendance(class_id, self.day, {student: "absent"}, note="تصحيح: تأخّر في الوصول")
            assert self._note_of(class_id, student) == "تصحيح: تأخّر في الوصول"

    def test_none_note_preserves_existing(self, app, class_with_students):
        """``note=None`` تعني "لم تُمرَّر" — لا تمسح الملاحظة المحفوظة."""
        from app.services.gradebook import record_attendance

        class_id, _teacher, students = class_with_students
        student = students[0]
        with app.app_context():
            record_attendance(class_id, self.day, {student: "present"}, note="تأخّر عن الدخول")
            record_attendance(class_id, self.day, {student: "late"})
            assert self._note_of(class_id, student) == "تأخّر عن الدخول"

    def test_empty_note_clears_existing(self, app, class_with_students):
        """السلسلة الفارغة مسحٌ صريح للملاحظة (تختلف عن None)."""
        from app.services.gradebook import record_attendance

        class_id, _teacher, students = class_with_students
        student = students[0]
        with app.app_context():
            record_attendance(class_id, self.day, {student: "present"}, note="ملاحظة قديمة")
            record_attendance(class_id, self.day, {student: "excused"}, note="")
            assert self._note_of(class_id, student) == ""

    def test_none_note_keeps_null_on_insert(self, app, class_with_students):
        """INSERT بلا ملاحظة يبقى NULL — لا تُكتب قيمة فارغة."""
        from app.services.gradebook import record_attendance

        class_id, _teacher, students = class_with_students
        with app.app_context():
            record_attendance(class_id, self.day, {students[0]: "present"})
            assert self._note_of(class_id, students[0]) is None

    def test_mixed_batch_writes_note_everywhere(self, app, class_with_students):
        """دفعة واحدة تضم صفوفاً موجودة وأخرى جديدة: الملاحظة تُكتب على كلها."""
        from app.extensions import db
        from app.models.attendance import Attendance
        from app.services.gradebook import record_attendance

        class_id, _teacher, students = class_with_students
        existing, fresh = students[0], students[1]
        with app.app_context():
            record_attendance(class_id, self.day, {existing: "present"}, note="قبل")
            with QueryCounter(db.engine) as qc:
                record_attendance(
                    class_id,
                    self.day,
                    {existing: "absent", fresh: "late"},
                    note="دفعة مختلطة",
                )
            # SELECT + UPDATE + INSERT = 3 عبارات ثابتة. السقف وحده لا يثبت
            # O(1) — انظر الاختبار التالي الذي يقارن دفعتين مختلفتَي الحجم.
            assert qc.count <= 3, f"الدفعة المختلطة استهلكت {qc.count} استعلامات (السقف 3)"
            rows = {r.student_id: r for r in Attendance.query.filter_by(class_id=class_id, date=self.day).all()}
            assert set(rows) == {existing, fresh}
            assert rows[existing].status == "absent"
            assert rows[existing].note == "دفعة مختلطة"
            assert rows[fresh].status == "late"
            assert rows[fresh].note == "دفعة مختلطة"

    def test_note_path_does_not_scale_with_class_size(self, app, class_with_students):
        """دليل O(1): نفس عدد الاستعلامات لدفعة بـ 2 طالب وآخر بـ 8.

        السقف الثابت وحده لا يمنع انحدار O(N) خفياً (استعلام لكل صف ضمن
        الحد الأقصى)، فالمقارنة بين دفعتين مختلفتَي الحجم هي الدليل.
        """
        from app.extensions import db
        from app.services.gradebook import record_attendance

        class_id, _teacher, students = class_with_students
        counts = []
        with app.app_context():
            for size in (2, len(students)):
                day = self.day + timedelta(days=size)
                record_attendance(class_id, day, {s: "present" for s in students[:size]}, note="بداية")
                with QueryCounter(db.engine) as qc:
                    record_attendance(
                        class_id,
                        day,
                        {s: "absent" for s in students[:size]},
                        note="تعديل",
                    )
                counts.append(qc.count)
        assert counts[0] == counts[1], f"عدد الاستعلامات تغيّر مع حجم الصف: {counts} — عائد إلى O(N)"
        assert counts[0] <= 2

    def test_batch_is_atomic_on_failure(self, app, class_with_students):
        """فشل في الدفعة يتراجع عنها بالكامل — لا كتابة نصفية."""
        from app.extensions import db
        from app.models.attendance import Attendance
        from app.services.gradebook import record_attendance
        from sqlalchemy.exc import DataError

        class_id, _teacher, students = class_with_students
        with app.app_context():
            with pytest.raises(DataError):
                record_attendance(
                    class_id,
                    self.day,
                    {students[0]: "present", students[1]: "x" * 50},  # يتجاوز varchar(10)
                    note="لن تُحفظ",
                )
            # الجلسة تحتاج تراجعاً صريحاً بعد فشل flush (service رجّع فعلاً).
            db.session.rollback()
            assert Attendance.query.filter_by(class_id=class_id, date=self.day).count() == 0


class TestParentAccessQueryBudget:
    """صلاحيات ولي الأمر: استعلام واحد مهما كان عدد طلاب الصف."""

    def test_parent_access_query_count_constant(self, app, class_with_students):
        """can_view_class لولي أمر: سقفان ثابتان مهما كثر طلاب الصف.

        الاختبار يمرّ على المسار الحقيقي المستدعى في كل طلب (@class_access_required)
        لا على الدالة المساعدة، وإلا لأفلت أي حلقة N+1 تُعاد لاحقاً.
        """
        from app.extensions import db
        from app.models.class_room import ClassRoom
        from app.models.family import FamilyLink
        from app.models.user import User
        from app.services.access import can_view_class

        class_id, _teacher, students = class_with_students
        parent_id = make_user(app, role="parent")

        with app.app_context():
            # أسوأ حالة واقعية: ولي أمر واحد فقط من بين طلاب الصف كلهم —
            # هنا يتوقف any() عند آخر عنصر، فأي فحص لكل طالب يظهر كاستعلامات.
            db.session.add(FamilyLink(parent_id=parent_id, student_id=students[-1], status="active"))
            db.session.commit()

            class_room = db.session.get(ClassRoom, class_id)
            parent = db.session.get(User, parent_id)
            # سياق طلب لازم: can_view_class يقرأ current_user عبر current_school_id
            with app.test_request_context():
                with QueryCounter(db.engine) as qc:
                    allowed = can_view_class(class_room, parent)
            assert allowed is True
            assert qc.count <= 2, f"فحص ولي الأمر استهلك {qc.count} استعلامات (السقف 2)"

    def test_parent_without_link_is_denied(self, app, class_with_students):
        from app.services.access import parent_has_active_member

        class_id, _teacher, _students = class_with_students
        stranger = make_user(app, role="parent")
        with app.app_context():
            assert parent_has_active_member(stranger, class_id) is False

    def test_inactive_link_is_denied(self, app, class_with_students):
        from app.extensions import db
        from app.models.family import FamilyLink
        from app.services.access import parent_has_active_member

        class_id, _teacher, students = class_with_students
        parent = make_user(app, role="parent")
        with app.app_context():
            db.session.add(FamilyLink(parent_id=parent, student_id=students[0], status="removed"))
            db.session.commit()
            assert parent_has_active_member(parent, class_id) is False

    def test_removed_membership_is_denied(self, app, class_with_students):
        from app.extensions import db
        from app.models.class_room import ClassMember
        from app.models.family import FamilyLink
        from app.services.access import parent_has_active_member

        class_id, _teacher, students = class_with_students
        parent = make_user(app, role="parent")
        with app.app_context():
            db.session.add(FamilyLink(parent_id=parent, student_id=students[0], status="active"))
            member = ClassMember.query.filter_by(class_id=class_id, user_id=students[0]).first()
            member.status = "removed"
            db.session.commit()
            assert parent_has_active_member(parent, class_id) is False


class TestStudentGradebookQueryBudget:
    """دفتر درجات الطالب: 3 استعلامات ثابتة مهما كثرت الأقسام والبنود (كانت 4)."""

    def test_student_gradebook_constant_queries(self, app, class_with_students):
        from app.extensions import db
        from app.services.gradebook import create_category, create_grade_item, student_gradebook

        class_id, _teacher, students = class_with_students
        with app.app_context():
            for ci in range(3):
                cat = create_category(class_id, f"قسم {ci}", weight=ci + 1)
                for ii in range(3):
                    create_grade_item(cat, f"بند {ci}-{ii}", max_mark=10)

            with QueryCounter(db.engine) as qc:
                categories, items, entries = student_gradebook(students[0], class_id)
            assert qc.count <= 3, f"دفتر الدرجات استهلك {qc.count} استعلامات (السقف 3)"
            assert len(categories) == 3
            assert len(items) == 9
            assert entries == {}

    def test_student_gradebook_items_are_sorted(self, app, class_with_students):
        from app.services.gradebook import create_category, create_grade_item, student_gradebook

        class_id, _teacher, students = class_with_students
        with app.app_context():
            cat_a = create_category(class_id, "أ")
            cat_b = create_category(class_id, "ب")
            create_grade_item(cat_b, "ب1", max_mark=5)
            create_grade_item(cat_a, "أ1", max_mark=5)
            _cats, items, _entries = student_gradebook(students[0], class_id)
            ids = [i.id for i in items]
            assert ids == sorted(ids), "البنود مرتّبة تصاعدياً كما كان السلوك السابق"


class TestReportCardProgressQueryBudget:
    """تقرير الطالب: تجميع التقدّم في استعلام واحد بدل ثلاثة."""

    def test_report_card_progress_queries_are_few(self, app, class_with_students):
        from app.extensions import db
        from app.services.progress import record_lesson_view, update_time_spent
        from app.services.report_card import generate_report_card
        from tests.conftest import make_lesson

        class_id, _teacher, students = class_with_students
        with app.app_context():
            for i in range(4):
                lesson_id = make_lesson(app, class_id, title=f"درس {i}")
                record_lesson_view(students[0], lesson_id, class_id)
            # 600 ثانية = 100% تقدّم ⇒ درس مكتمل واحد على الأقل
            first_lesson = make_lesson(app, class_id, title="درس مكتمل")
            record_lesson_view(students[0], first_lesson, class_id)
            update_time_spent(students[0], first_lesson, 600)

            with QueryCounter(db.engine) as qc:
                data = generate_report_card(students[0], class_id)
            assert qc.count <= 8, f"تقرير الطالب استهلك {qc.count} استعلامات (السقف 8)"
            assert data["completed_lessons"] >= 1
            assert data["total_lessons"] >= 1
