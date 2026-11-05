# -*- coding: utf-8 -*-
"""Round-11: final 4 backend gaps."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import patch

PASSWORD = "TestPass123!"


def _email():
    return f"r11-{uuid.uuid4().hex[:10]}@test.com"


# access.py line 201: parent's child is member but has no subscription
def test_parent_can_pay_child_member_no_subscription(app):
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    from app.extensions import db
    from app.models.class_room import ClassRoom
    from app.models.family import FamilyLink
    from app.models.user import User
    from app.services import access

    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    tid = make_user(app, role="teacher", school_id=sid)
    cid = make_class(app, sid, gid, subj, teacher_id=tid)
    parent = make_user(app, role="parent", school_id=sid)
    student = make_user(app, role="student", school_id=sid)

    with app.app_context():
        link = FamilyLink(parent_id=parent, student_id=student, status="active")
        db.session.add(link)
        cm = __import__("app.models.class_room", fromlist=["ClassMember"]).ClassMember(
            class_id=cid, user_id=student, status="active"
        )
        db.session.add(cm)
        db.session.commit()

        cls = db.session.get(ClassRoom, cid)
        user = db.session.get(User, parent)
        # child is member but has no subscription -> falls through to ClassMember check -> True
        assert access.can_pay_class(cls, user) is True


# gradebook.py line 149: mark exceeds max_mark
def test_gradebook_mark_exceeds_max_raises(app):
    from tests.conftest import make_class, make_grade, make_grade_category, make_grade_item, make_school, make_subject, make_user

    from app.extensions import db
    from app.models.gradebook import GradeItem
    from app.services.gradebook import set_grade

    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    tid = make_user(app, role="teacher", school_id=sid)
    cid = make_class(app, sid, gid, subj, teacher_id=tid)
    stud = make_user(app, role="student", school_id=sid)
    cat = make_grade_category(app, cid, "Exam", 1.0)
    item = make_grade_item(app, cid, cat, "Midterm", 100)

    with app.app_context():
        from app.extensions import db
        from app.models.gradebook import GradeItem
        from app.services.gradebook import GradeOutOfRange

        item_obj = db.session.get(GradeItem, item)
        try:
            set_grade(stud, item_obj, 150, recorded_by=tid)
            assert False, "should have raised"
        except GradeOutOfRange:
            pass
