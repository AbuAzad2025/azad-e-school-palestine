"""خدمات الواجبات والدرجات والحضور."""

from datetime import date

from sqlalchemy.orm import joinedload

from app.core.db import TxError, tx
from app.core.i18n import _
from app.core.uploads import save_upload
from app.extensions import db
from app.models.attendance import Attendance
from app.models.gradebook import Assignment, GradeCategory, GradeEntry, GradeItem, Submission


# ============ الواجبات ============
def create_assignment(
    class_id: int, title: str, body: str | None = None, due_at=None, max_mark=None, created_by=None
) -> tuple[Assignment | None, str | None]:
    title = (title or "").strip()
    if not title:
        return None, _("عنوان الواجب مطلوب.")

    def _create():
        a = Assignment(
            class_id=class_id,
            title=title,
            body=body,
            due_at=due_at,
            max_mark=max_mark,
            created_by=created_by,
        )
        db.session.add(a)
        return a

    return tx(_create), None


def list_assignments(class_id: int):
    return Assignment.query.filter_by(class_id=class_id).order_by(Assignment.created_at.desc()).all()


def submit_assignment(
    assignment: Assignment, student_id: int, body: str | None = None, file=None
) -> tuple[Submission | None, str | None]:
    """تسليم الطالب للواجب (نص و/أو ملف). يعيد (submission, error)."""
    if not body and not file:
        return None, _("أضف نصاً أو ملفاً للتسليم.")
    stored = None
    if file:
        try:
            stored = save_upload(file)
        except TxError as exc:
            return None, str(exc)

    def _submit():
        sub = Submission.query.filter_by(assignment_id=assignment.id, student_id=student_id).first()
        if sub:
            sub.body = body or sub.body
            sub.file = stored or sub.file
            sub.submitted_at = db.func.now()
            return sub
        return Submission(
            assignment_id=assignment.id,
            student_id=student_id,
            body=body,
            file=stored,
            submitted_at=db.func.now(),
        )

    return tx(_submit), None


def list_submissions(assignment: Assignment):
    return (
        Submission.query.filter_by(assignment_id=assignment.id)
        .options(joinedload(Submission.student))
        .order_by(Submission.submitted_at.desc())
        .all()
    )


def grade_submission(submission: Submission, mark, feedback: str | None = None, graded_by=None) -> None:
    def _grade():
        submission.mark = mark
        submission.feedback = feedback
        submission.graded_by = graded_by
        submission.graded_at = db.func.now()

    tx(_grade)


# ============ دفتر الدرجات ============
def create_category(class_id: int, name: str, weight=None) -> GradeCategory:
    def _create():
        c = GradeCategory(class_id=class_id, name=name.strip(), weight=weight)
        db.session.add(c)
        return c

    return tx(_create)


def list_categories(class_id: int):
    return GradeCategory.query.filter_by(class_id=class_id).order_by(GradeCategory.id.asc()).all()


def create_grade_item(category: GradeCategory, title: str, max_mark=None, kind: str = "exam") -> GradeItem:
    def _create():
        i = GradeItem(
            class_id=category.class_id, category_id=category.id, title=title.strip(), max_mark=max_mark, kind=kind
        )
        db.session.add(i)
        return i

    return tx(_create)


def set_grade(student_id: int, item: GradeItem, mark, recorded_by=None, note: str | None = None) -> None:
    def _set():
        entry = GradeEntry.query.filter_by(student_id=student_id, grade_item_id=item.id).first()
        if entry:
            entry.mark = mark
            entry.note = note
        else:
            db.session.add(
                GradeEntry(student_id=student_id, grade_item_id=item.id, mark=mark, recorded_by=recorded_by, note=note)
            )

    tx(_set)


def student_gradebook(student_id: int, class_id: int):
    """دفتر درجات طالب داخل صف: البنود + الدرجات."""
    categories = list_categories(class_id)
    items = GradeItem.query.filter_by(class_id=class_id).order_by(GradeItem.id.asc()).all()
    entries = {
        e.grade_item_id: e
        for e in GradeEntry.query.filter_by(student_id=student_id)
        .filter(GradeEntry.grade_item_id.in_([i.id for i in items] or [0]))
        .all()
    }
    return categories, items, entries


# ============ الحضور ============
def get_attendance(class_id: int, day: date):
    rows = Attendance.query.filter_by(class_id=class_id, date=day).all()
    return {r.student_id: r for r in rows}


def record_attendance(
    class_id: int, day: date, records: dict[int, str], recorded_by=None, note: str | None = None
) -> None:
    """records: {student_id: status}. upsert لكل طالب."""

    def _record():
        for student_id, status in records.items():
            row = Attendance.query.filter_by(class_id=class_id, student_id=student_id, date=day).first()
            if row:
                row.status = status
            else:
                db.session.add(
                    Attendance(
                        class_id=class_id,
                        student_id=student_id,
                        date=day,
                        status=status,
                        note=note,
                        recorded_by=recorded_by,
                    )
                )

    tx(_record)


def attendance_days(class_id: int):
    return [
        d[0]
        for d in db.session.query(Attendance.date)
        .filter_by(class_id=class_id)
        .distinct()
        .order_by(Attendance.date.desc())
        .limit(30)
        .all()
    ]


def attendance_summary(class_id: int, student_id: int):
    rows = Attendance.query.filter_by(class_id=class_id, student_id=student_id).all()
    return rows
