#!/usr/bin/env python3
"""Phase 1 Demo Seed — Azad E-School Palestine.

Creates focused demo data for all Phase 1 features:
  1 school with active term, 7 users, family links,
  2 subjects, 1 grade, 1 class with members,
  4 lessons (2 published + video, 2 draft),
  1 quiz (5 questions), 1 assignment (2 submissions),
  grade categories + items + entries for 3 students,
  3 subscriptions (paid/partial/pending) + manual payments,
  3 academic events.

Usage:
  .venv\\Scripts\\python.exe scripts\\seed_phase1.py
  .venv\\Scripts\\python.exe scripts\\seed_phase1.py --purge
"""

from __future__ import annotations

import argparse
import io
import secrets
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.core.db import tx  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.assessment import Question, Quiz  # noqa: E402
from app.models.billing import ManualPayment, Subscription, SubscriptionPlan  # noqa: E402
from app.models.calendar import AcademicEvent  # noqa: E402
from app.models.class_room import ClassMember, ClassRoom  # noqa: E402
from app.models.content import Lesson, LessonAttachment, Unit  # noqa: E402
from app.models.family import FamilyLink  # noqa: E402
from app.models.gradebook import (  # noqa: E402
    Assignment,
    GradeCategory,
    GradeEntry,
    GradeItem,
    Submission,
)
from app.models.school import Grade, School, Subject, SubjectGradeLink  # noqa: E402
from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink  # noqa: E402
from sqlalchemy import text  # noqa: E402

DEMO_PASSWORD = "Azad@2026"


def _out(msg: str) -> None:
    print(f"[seed-phase1] {msg}")


def _find_user(email: str) -> User | None:
    return User.query.filter_by(email=email).first()


# ─── Helpers ───────────────────────────────────────────────────────────


def _create_user(
    email: str,
    password: str,
    name_ar: str,
    name_en: str,
    role: str,
    school_id: int | None = None,
) -> User:
    user = _find_user(email)
    if user:
        _out(f"  skip (exists): {email}")
        return user

    def _add() -> User:
        u = User(
            email=email,
            password_hash=hash_password(password),
            role=UserRole(role),
            name_ar=name_ar,
            name_en=name_en,
            locale="ar",
            is_active=True,
            is_verified=True,
            approval_status=UserApprovalStatus.approved,
        )
        db.session.add(u)
        db.session.flush()
        if school_id is not None:
            db.session.add(UserRoleLink(user_id=u.id, school_id=school_id, role=UserRole(role), is_active=True))
        return u

    u = tx(_add)
    _out(f"  user: {name_ar} ({email})")
    return u


def _get_or_create_subject(code: str, name_ar: str, name_en: str) -> Subject:
    s = Subject.query.filter_by(code=code).first()
    if s:
        return s

    def _add() -> Subject:
        obj = Subject(code=code, name_ar=name_ar, name_en=name_en, is_elective=False)
        db.session.add(obj)
        db.session.flush()
        return obj

    return tx(_add)


def _get_or_create_grade(school: School, level: int) -> Grade:
    g = Grade.query.filter_by(school_id=school.id, grade_level=level).first()
    if g:
        return g
    stage = "primary" if level <= 4 else ("prep" if level <= 9 else "secondary")

    def _add() -> Grade:
        obj = Grade(
            school_id=school.id,
            grade_level=level,
            stage=stage,
            name_ar=f"الصف {level}",
            name_en=f"Grade {level}",
            sort_order=level,
        )
        db.session.add(obj)
        db.session.flush()
        return obj

    return tx(_add)


def _link_subject_grade(subject: Subject, grade: Grade) -> None:
    if SubjectGradeLink.query.filter_by(subject_id=subject.id, grade_id=grade.id).first():
        return

    def _add() -> None:
        db.session.add(SubjectGradeLink(subject_id=subject.id, grade_id=grade.id))

    tx(_add)


def _add_member(class_room: ClassRoom, user: User) -> None:
    if ClassMember.query.filter_by(class_id=class_room.id, user_id=user.id).first():
        return

    def _add() -> None:
        db.session.add(ClassMember(class_id=class_room.id, user_id=user.id, status="active"))

    tx(_add)


# ─── Main Seed ─────────────────────────────────────────────────────────


def seed_phase1() -> None:
    _out("=" * 50)
    _out("Phase 1 Seed — START")
    _out("=" * 50)

    # ── 1) School ──────────────────────────────────────────────────────
    _out("\n[1/9] School...")
    school = School.query.filter_by(domain="azad.edu.ps").first()
    if school is None:

        def _add_school() -> School:
            s = School(
                name_ar="مدرسة أزاد النموذجية",
                name_en="Azad Model School",
                domain="azad.edu.ps",
                academic_year="2026/2027",
                stages=["primary", "prep", "secondary"],
                settings={"currency": "ILS", "region": "Palestine"},
                is_active=True,
            )
            db.session.add(s)
            db.session.flush()
            return s

        school = tx(_add_school)
    _out(f"  school: {school.name_ar} (id={school.id})")

    # ── 2) Users ───────────────────────────────────────────────────────
    _out("\n[2/9] Users...")
    _create_user(
        "admin@azad.edu.ps",
        DEMO_PASSWORD,
        "أ. خالد أبو ريا",
        "Khaled Abu Raya",
        "school_admin",
        school_id=school.id,
    )
    teacher1 = _create_user(
        "arabic-teacher@azad.edu.ps",
        DEMO_PASSWORD,
        "أ. منى الشاعر",
        "Mona Al-Shaer",
        "teacher",
        school_id=school.id,
    )
    _create_user(
        "math-teacher@azad.edu.ps",
        DEMO_PASSWORD,
        "أ. سامي النتشة",
        "Sami Al-Natsheh",
        "teacher",
        school_id=school.id,
    )
    parent = _create_user(
        "parent@azad.edu.ps",
        DEMO_PASSWORD,
        "أحمد خليل أبو ريا",
        "Ahmad Khaleel Abu Raya",
        "parent",
        school_id=school.id,
    )
    student1 = _create_user(
        "student1@azad.edu.ps",
        DEMO_PASSWORD,
        "أحمد خليل",
        "Ahmad Khaleel",
        "student",
        school_id=school.id,
    )
    student2 = _create_user(
        "student2@azad.edu.ps",
        DEMO_PASSWORD,
        "سلمى عوض",
        "Salma Awad",
        "student",
        school_id=school.id,
    )
    student3 = _create_user(
        "student3@azad.edu.ps",
        DEMO_PASSWORD,
        "محمود الريماوي",
        "Mahmoud Al-Rimawi",
        "student",
        school_id=school.id,
    )
    students = [student1, student2, student3]

    # ── 3) Family links (student1 + student2 linked; student3 unlinked) ──
    _out("\n[3/9] Family links...")
    for s in (student1, student2):
        if FamilyLink.query.filter_by(parent_id=parent.id, student_id=s.id).first():
            continue

        def _add_link(sid: int = s.id) -> None:
            db.session.add(FamilyLink(parent_id=parent.id, student_id=sid, status="active"))

        tx(_add_link)
        _out(f"  linked: parent -> {s.name_ar}")

    # ── 4) Subjects + Grade ────────────────────────────────────────────
    _out("\n[4/9] Subjects + Grade...")
    subj_ar = _get_or_create_subject("ARAB", "اللغة العربية", "Arabic")
    subj_mth = _get_or_create_subject("MATH", "الرياضيات", "Mathematics")
    grade5 = _get_or_create_grade(school, 5)
    _link_subject_grade(subj_ar, grade5)
    _link_subject_grade(subj_mth, grade5)
    _out(f"  subjects: Arabic(id={subj_ar.id}), Math(id={subj_mth.id})")
    _out(f"  grade: {grade5.name_ar}(id={grade5.id})")

    # ── 5) ClassRoom + Members ─────────────────────────────────────────
    _out("\n[5/9] ClassRoom + Members...")
    existing_class = ClassRoom.query.filter_by(
        school_id=school.id,
        subject_id=subj_ar.id,
        grade_id=grade5.id,
        semester="first",
    ).first()

    if existing_class:
        class_room = existing_class
    else:
        code = secrets.token_urlsafe(6)
        while ClassRoom.query.filter_by(join_code=code).first():
            code = secrets.token_urlsafe(6)

        def _add_class() -> ClassRoom:
            c = ClassRoom(
                school_id=school.id,
                subject_id=subj_ar.id,
                grade_id=grade5.id,
                teacher_id=teacher1.id,
                semester="first",
                name="اللغة العربية — الصف 5 — الفصل الأول",
                join_code=code,
                is_active=True,
                currency="ILS",
                price_first_term=140,
                price_second_term=140,
                price_annual=240,
            )
            db.session.add(c)
            db.session.flush()
            return c

        class_room = tx(_add_class)

    _out(f"  class: {class_room.name} (id={class_room.id}, code={class_room.join_code})")

    for s in students:
        _add_member(class_room, s)
    _add_member(class_room, teacher1)
    _out(f"  members: {len(students)} students + teacher1")

    # ── 6) Units + Lessons (4: 2 published+video, 2 draft) ────────────
    _out("\n[6/9] Units + Lessons...")

    def _get_or_create_unit(title: str, order: int) -> Unit:
        u = Unit.query.filter_by(class_id=class_room.id, title=title).first()
        if u:
            return u

        def _add() -> Unit:
            obj = Unit(class_id=class_room.id, title=title, sort_order=order)
            db.session.add(obj)
            db.session.flush()
            return obj

        return tx(_add)

    unit1 = _get_or_create_unit("النحو والقواعد", 1)
    unit2 = _get_or_create_unit("القراءة والنصوص", 2)

    lessons_data = [
        {
            "unit": unit1,
            "title": "الإعراب وال Parsing الأساسي",
            "order": 1,
            "status": "published",
            "body": "<p>تعرّف على المبتدأ والخبر وقواعد الإعراب الأساسية.</p>"
            "<ul><li>المبتدأ: اسم مرفوع في أول الجملة</li>"
            "<li>الخبر: يكمل المعنى ويرفع مثل المبتدأ</li></ul>",
            "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
        {
            "unit": unit1,
            "title": "المفعول به والجار والمجرور",
            "order": 2,
            "status": "published",
            "body": "<p>المفعول به منصوب، والجار والمجرور يدلّان على الظرف أو الحالية.</p>"
            "<ul><li>مثال: قرأتُ الكتابَ</li>"
            "<li>مثال: مررتُ بالحديقةِ</li></ul>",
            "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
        {
            "unit": unit2,
            "title": "النصوص الأدبية",
            "order": 3,
            "status": "draft",
            "body": "<p>قراءة وتحليل نصوص أدبية فلسطينية مختارة.</p>",
            "video_url": None,
        },
        {
            "unit": unit2,
            "title": "البلاغة والتصوير",
            "order": 4,
            "status": "draft",
            "body": "<p>مقدمة في التشبيه والاستعارة والكناية.</p>",
            "video_url": None,
        },
    ]

    published_count = 0
    draft_count = 0
    for ld in lessons_data:
        existing = Lesson.query.filter_by(class_id=class_room.id, title=ld["title"]).first()
        if existing:
            _out(f"  lesson (exists): {ld['title']}")
            if ld["status"] == "published":
                published_count += 1
            else:
                draft_count += 1
            continue

        def _add_lesson(d: dict = ld) -> Lesson:
            lesson = Lesson(
                class_id=class_room.id,
                unit_id=d["unit"].id,
                title=d["title"],
                body_html=d["body"],
                sort_order=d["order"],
                status=d["status"],
                version=1,
                created_by=teacher1.id,
            )
            if d["status"] == "published":
                lesson.published_at = datetime.now(UTC)
            db.session.add(lesson)
            db.session.flush()
            if d["video_url"]:
                db.session.add(
                    LessonAttachment(
                        lesson_id=lesson.id,
                        kind="video",
                        title=f"فيديو: {d['title']}",
                        stored_name=f"seed_video_{lesson.id}.mp4",
                        original_name=f"{d['title']}.mp4",
                        mime="video/mp4",
                        youtube_url=d["video_url"],
                    )
                )
            return lesson

        tx(_add_lesson)
        if ld["status"] == "published":
            published_count += 1
        else:
            draft_count += 1
        _out(f"  lesson ({ld['status']}): {ld['title']}")

    _out(f"  total: {published_count} published, {draft_count} draft")

    # ── 7) Quiz + Questions (5 questions) ──────────────────────────────
    _out("\n[7/9] Quiz + Questions...")
    quiz_title = "اختبار عربية — الوحدة الأولى"
    quiz = Quiz.query.filter_by(class_id=class_room.id, title=quiz_title).first()

    if quiz:
        _out(f"  quiz (exists): {quiz_title}")
    else:
        questions_data = [
            (
                "mcq",
                "ما هو المبتدأ في جملة: الكتابُ جديدٌ؟",
                {"a": "الكتاب", "b": "جديد", "c": "في", "d": "هو"},
                "a",
                2.0,
            ),
            (
                "mcq",
                "ما نوع الكلمة: يكتبُ الطالبُ الدرسَ؟",
                {"a": "فعل مضارع", "b": "اسم", "c": "فعل أمر", "d": "حرف"},
                "a",
                2.0,
            ),
            ("true_false", "الخبر في الجملة الاسمية مرفوع دائماً.", None, "true", 1.0),
            (
                "mcq",
                "أكمل: مررتُ _____ الحديقةِ.",
                {"a": "في", "b": "على", "c": "بال", "d": "من"},
                "c",
                2.0,
            ),
            ("essay", "اكتب جملة اسماً تحتوي مبتدأ وخبراً وعلامتي إعراب.", None, None, 3.0),
        ]
        total_mark = sum(q[4] for q in questions_data)

        def _add_quiz() -> Quiz:
            q = Quiz(
                class_id=class_room.id,
                title=quiz_title,
                duration_min=20,
                attempts_allowed=1,
                shuffle=True,
                show_answers_after=True,
                total_mark=total_mark,
                status="published",
                created_by=teacher1.id,
            )
            db.session.add(q)
            db.session.flush()
            for i, (qtype, prompt, opts, correct, mark) in enumerate(questions_data, 1):
                db.session.add(
                    Question(
                        quiz_id=q.id,
                        type=qtype,
                        prompt=prompt,
                        options=opts,
                        correct_answer=correct,
                        mark=mark,
                        sort_order=i,
                    )
                )
            return q

        quiz = tx(_add_quiz)
        _out(f"  quiz: {quiz_title} (id={quiz.id}, 5 questions)")

    # ── 8) Assignment + Submissions ────────────────────────────────────
    _out("\n[8/9] Assignment + Submissions...")
    assign_title = "واجب: جمل اسمية"
    assignment = Assignment.query.filter_by(class_id=class_room.id, title=assign_title).first()

    if assignment:
        _out(f"  assignment (exists): {assign_title}")
    else:

        def _add_assign() -> Assignment:
            a = Assignment(
                class_id=class_room.id,
                title=assign_title,
                body="اكتب 5 جمل اسمية معربة مع ذكر المبتدأ والخبر.",
                due_at=datetime.now(UTC) + timedelta(days=7),
                max_mark=10.0,
                created_by=teacher1.id,
            )
            db.session.add(a)
            db.session.flush()
            return a

        assignment = tx(_add_assign)
        _out(f"  assignment: {assign_title} (id={assignment.id})")

    # 2 submissions: student1 graded, student2 pending
    for st, body_text, mark_val, fb in [
        (student1, "الكتابُ جديدٌ. الطالبُ مجتهدٌ. الشمسُ مشرقةٌ.", 9.0, "ممتاز، جمل مصيبة."),
        (student2, "القمرُ مضيء. الريحُ باردة.", None, None),
    ]:
        if Submission.query.filter_by(assignment_id=assignment.id, student_id=st.id).first():
            _out(f"  submission (exists): {st.name_ar}")
            continue

        def _add_sub(
            a_id: int = assignment.id,
            s_id: int = st.id,
            body_t: str = body_text,
            m_val: float | None = mark_val,
            fb_val: str | None = fb,
            grader: int = teacher1.id,
        ) -> None:
            sub = Submission(
                assignment_id=a_id,
                student_id=s_id,
                body=body_t,
                submitted_at=datetime.now(UTC),
            )
            if m_val is not None:
                sub.mark = m_val
                sub.feedback = fb_val
                sub.graded_by = grader
                sub.graded_at = datetime.now(UTC)
            db.session.add(sub)

        tx(_add_sub)
        status = f"graded ({mark_val})" if mark_val else "pending"
        _out(f"  submission ({status}): {st.name_ar}")

    # ── 9a) GradeCategories + Items + Entries ──────────────────────────
    _out("\n[9a] Gradebook...")
    cat_name = "الفصل الأول"
    grade_cat = GradeCategory.query.filter_by(class_id=class_room.id, name=cat_name).first()

    if grade_cat:
        _out(f"  category (exists): {cat_name}")
    else:

        def _add_cat() -> GradeCategory:
            c = GradeCategory(class_id=class_room.id, name=cat_name, weight=0.5)
            db.session.add(c)
            db.session.flush()
            return c

        grade_cat = tx(_add_cat)
        _out(f"  category: {cat_name} (id={grade_cat.id})")

    grade_items: list[GradeItem] = []
    for title, kind, max_mark in [("اختبار الكتابة", "exam", 10.0), ("واجب الجمل", "assignment", 10.0)]:
        item = GradeItem.query.filter_by(class_id=class_room.id, category_id=grade_cat.id, title=title).first()
        if item:
            grade_items.append(item)
            continue

        def _add_item(t: str = title, k: str = kind, mm: float = max_mark) -> GradeItem:
            obj = GradeItem(class_id=class_room.id, category_id=grade_cat.id, title=t, max_mark=mm, kind=k)
            db.session.add(obj)
            db.session.flush()
            return obj

        item = tx(_add_item)
        grade_items.append(item)
        _out(f"  item: {title} (id={item.id})")

    marks = [9.0, 8.5, 7.0]
    for st, mark in zip(students, marks, strict=True):
        for item in grade_items:
            if GradeEntry.query.filter_by(student_id=st.id, grade_item_id=item.id).first():
                continue

            def _add_entry(s_id: int = st.id, i_id: int = item.id, m: float = mark) -> None:
                db.session.add(GradeEntry(student_id=s_id, grade_item_id=i_id, mark=m, recorded_by=teacher1.id))

            tx(_add_entry)
        _out(f"  grades: {st.name_ar} = {mark}")

    # ── 9b) Subscriptions + Manual Payments ────────────────────────────
    _out("\n[9b] Subscriptions + Payments...")
    plan = SubscriptionPlan.query.filter_by(school_id=school.id).first()
    if plan is None:

        def _add_plan() -> SubscriptionPlan:
            p = SubscriptionPlan(
                school_id=school.id,
                class_id=class_room.id,
                name="فصل أول — عربية",
                plan="first_term",
                price=140.0,
                currency="ILS",
                is_active=True,
            )
            db.session.add(p)
            db.session.flush()
            return p

        plan = tx(_add_plan)
        _out(f"  plan: {plan.name} (id={plan.id})")

    # Subscription 1: active (paid in full) — student1
    if not Subscription.query.filter_by(user_id=student1.id, plan_id=plan.id, class_id=class_room.id).first():

        def _add_sub1() -> Subscription:
            s = Subscription(
                user_id=student1.id,
                plan_id=plan.id,
                class_id=class_room.id,
                price=140.0,
                currency="ILS",
                status="active",
                source="manual",
            )
            db.session.add(s)
            db.session.flush()
            db.session.add(
                ManualPayment(
                    subscription_id=s.id,
                    reference="TXN-001-FULL",
                    amount=140.0,
                    status="approved",
                )
            )
            return s

        tx(_add_sub1)
        _out("  subscription: active (full 140) — student1")

    # Subscription 2: active (partial payment) — student2
    if not Subscription.query.filter_by(user_id=student2.id, plan_id=plan.id, class_id=class_room.id).first():

        def _add_sub2() -> Subscription:
            s = Subscription(
                user_id=student2.id,
                plan_id=plan.id,
                class_id=class_room.id,
                price=140.0,
                currency="ILS",
                status="active",
                source="manual",
            )
            db.session.add(s)
            db.session.flush()
            db.session.add(
                ManualPayment(
                    subscription_id=s.id,
                    reference="TXN-002-PARTIAL",
                    amount=70.0,
                    status="approved",
                )
            )
            return s

        tx(_add_sub2)
        _out("  subscription: active (partial 70/140) — student2")

    # Subscription 3: pending (no payment) — student3
    if not Subscription.query.filter_by(user_id=student3.id, plan_id=plan.id, class_id=class_room.id).first():

        def _add_sub3() -> Subscription:
            return Subscription(
                user_id=student3.id,
                plan_id=plan.id,
                class_id=class_room.id,
                price=140.0,
                currency="ILS",
                status="pending",
                source="manual",
            )

        db.session.add(tx(_add_sub3))
        _out("  subscription: pending — student3")

    # ── 9c) Academic Events ────────────────────────────────────────────
    _out("\n[9c] Academic Events...")
    events = [
        ("بداية الفصل الأول", "term_start", date(2026, 9, 1), date(2026, 9, 1)),
        ("فترة الامتحانات النهائية", "exam_period", date(2027, 1, 15), date(2027, 1, 25)),
        ("نهاية الفصل الأول", "term_end", date(2027, 1, 25), date(2027, 1, 25)),
    ]
    for title, etype, start_d, end_d in events:
        if AcademicEvent.query.filter_by(school_id=school.id, title=title).first():
            continue

        def _add_event(
            t: str = title,
            et: str = etype,
            sd: date = start_d,
            ed: date = end_d,
        ) -> None:
            db.session.add(
                AcademicEvent(
                    school_id=school.id,
                    title=t,
                    event_type=et,
                    start_date=sd,
                    end_date=ed,
                    is_active=True,
                )
            )

        tx(_add_event)
        _out(f"  event: {title}")

    # ── Summary ────────────────────────────────────────────────────────
    _out("")
    _out("=" * 50)
    _out("Phase 1 Seed — DONE")
    _out("=" * 50)
    _out(f"School: {school.name_ar} (id={school.id})")
    _out(f"Admin:     admin@azad.edu.ps / {DEMO_PASSWORD}")
    _out(f"Teacher1:  arabic-teacher@azad.edu.ps / {DEMO_PASSWORD}")
    _out(f"Teacher2:  math-teacher@azad.edu.ps / {DEMO_PASSWORD}")
    _out(f"Parent:    parent@azad.edu.ps / {DEMO_PASSWORD}")
    _out(f"Student1:  student1@azad.edu.ps / {DEMO_PASSWORD}")
    _out(f"Student2:  student2@azad.edu.ps / {DEMO_PASSWORD}")
    _out(f"Student3:  student3@azad.edu.ps / {DEMO_PASSWORD}")
    _out("Family:    student1+student2 -> parent")
    _out(f"Class:     {class_room.name} (code={class_room.join_code})")
    _out(f"Quiz:      {quiz_title} (5 questions)")
    _out(f"Assignment:{assign_title} (2 submissions)")
    _out("Subs:      student1(full), student2(partial), student3(pending)")
    _out("Events:    3 academic events")
    _out("=" * 50)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1 seed data")
    parser.add_argument("--purge", action="store_true", help="purge all data first")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.purge:
            _out("Purging all data...")
            tables = [t.name for t in db.metadata.sorted_tables if t.name != "alembic_version"]
            db.session.execute(text("TRUNCATE TABLE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"))
            db.session.commit()
            _out("Purged.")

        seed_phase1()


if __name__ == "__main__":
    main()
