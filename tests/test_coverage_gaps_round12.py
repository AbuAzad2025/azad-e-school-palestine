# -*- coding: utf-8 -*-
"""Round-12: final backend gap (access.py line 201)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

PASSWORD = "TestPass123!"


def _email():
    return f"r12-{uuid.uuid4().hex[:10]}@test.com"


def test_parent_can_pay_child_member_no_subscription_covered(app):
    """Parent's child is active member but has no subscription -> fallback return (line 201)."""
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    from app.extensions import db
    from app.models.class_room import ClassRoom, ClassMember
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
        cm = ClassMember(class_id=cid, user_id=student, status="active")
        db.session.add(cm)
        db.session.commit()

        cls = db.session.get(ClassRoom, cid)
        user = db.session.get(User, parent)
        # child is member but has no subscription -> falls through to ClassMember check -> True
        assert access.can_pay_class(cls, user) is True
