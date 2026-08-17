"""محرك حساب الدرجات — المتوسطات المرجّحة من سجل الدرجات."""

from sqlalchemy.orm import selectinload

from app.models.gradebook import GradeCategory, GradeEntry, GradeItem

ARABIC_GRADES = [
    (90, "ممتاز"),
    (80, "جيد جداً"),
    (70, "جيد"),
    (60, "مقبول"),
    (0, "راسب"),
]


def _letter_grade(score: float) -> str:
    for threshold, label in ARABIC_GRADES:
        if score >= threshold:
            return label
    return "راسب"


def calculate_student_grade(student_id: int, class_id: int) -> dict:
    """
    حساب الدرجة النهائية للطالب في صف معين.

    Returns:
        {
            "categories": [
                {
                    "name": "الفصل الأول",
                    "weight": 0.40,
                    "items": [
                        {"title": "...", "max_mark": 20, "earned": 16, "pct": 80.0},
                    ],
                    "category_pct": 75.0,
                    "weighted_score": 30.0,
                },
            ],
            "total_weighted_score": 82.5,
            "total_weight": 1.0,
            "final_grade": 82.5,
            "letter_grade": "جيد جداً",
        }
    """
    categories = (
        GradeCategory.query.filter_by(class_id=class_id)
        .options(selectinload(GradeCategory.items).selectinload(GradeItem.entries))
        .all()
    )

    entries_map = {}
    items = GradeItem.query.filter_by(class_id=class_id).all()
    if items:
        rows = GradeEntry.query.filter(
            GradeEntry.grade_item_id.in_([i.id for i in items]),
            GradeEntry.student_id == student_id,
        ).all()
        entries_map = {r.grade_item_id: r for r in rows}

    result_categories = []
    total_weighted = 0.0
    total_weight = 0.0

    for cat in categories:
        cat_weight = float(cat.weight) if cat.weight else 0
        cat_items = []
        cat_total_marks = 0.0
        cat_earned_marks = 0.0

        for item in cat.items:
            entry = entries_map.get(item.id)
            max_mark = float(item.max_mark) if item.max_mark else 0
            earned = float(entry.mark) if entry and entry.mark is not None else None
            pct = round((earned / max_mark * 100), 1) if max_mark > 0 and earned is not None else None

            cat_items.append(
                {
                    "id": item.id,
                    "title": item.title,
                    "max_mark": max_mark,
                    "earned": earned,
                    "pct": pct,
                }
            )

            if earned is not None and max_mark > 0:
                cat_total_marks += max_mark
                cat_earned_marks += earned

        category_pct = round((cat_earned_marks / cat_total_marks * 100), 1) if cat_total_marks > 0 else 0
        weighted_score = round(category_pct * cat_weight, 2)

        result_categories.append(
            {
                "id": cat.id,
                "name": cat.name,
                "weight": cat_weight,
                "items": cat_items,
                "category_pct": category_pct,
                "weighted_score": weighted_score,
            }
        )

        total_weighted += weighted_score
        total_weight += cat_weight

    final_grade = round(total_weighted / total_weight, 1) if total_weight > 0 else 0
    return {
        "categories": result_categories,
        "total_weighted_score": round(total_weighted, 2),
        "total_weight": total_weight,
        "final_grade": final_grade,
        "letter_grade": _letter_grade(final_grade),
    }


def class_grades_summary(class_id: int) -> list[dict]:
    """ملخص درجات جميع الطلاب في صف معين."""
    from app.models.class_room import ClassMember

    members = ClassMember.query.filter_by(class_id=class_id, status="active").all()
    results = []
    for member in members:
        grade_data = calculate_student_grade(member.user_id, class_id)
        results.append(
            {
                "student_id": member.user_id,
                "student": member.user,
                **grade_data,
            }
        )
    results.sort(key=lambda x: x["final_grade"], reverse=True)
    return results
