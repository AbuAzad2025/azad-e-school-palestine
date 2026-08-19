"""خدمات التقييم بالمعيار (Rubric Grading)."""

from app.core.db import tx
from app.extensions import db
from app.models.gradebook import RubricCriterion, RubricGrade, RubricTemplate


def create_rubric_template(
    teacher_id: int,
    school_id: int,
    title: str,
    description: str | None = None,
    criteria: list[dict] | None = None,
) -> RubricTemplate:
    def _create():
        t = RubricTemplate(
            teacher_id=teacher_id,
            school_id=school_id,
            title=title.strip(),
            description=description,
        )
        db.session.add(t)
        db.session.flush()
        if criteria:
            for i, c in enumerate(criteria):
                db.session.add(
                    RubricCriterion(
                        template_id=t.id,
                        title=c["title"].strip(),
                        description=c.get("description"),
                        max_score=c["max_score"],
                        sort_order=i + 1,
                    )
                )
        return t

    return tx(_create)


def get_rubric_template(template_id: int) -> RubricTemplate | None:
    return RubricTemplate.query.filter_by(id=template_id).first()


def list_rubric_templates(teacher_id: int) -> list[RubricTemplate]:
    return RubricTemplate.query.filter_by(teacher_id=teacher_id).order_by(RubricTemplate.created_at.desc()).all()


def grade_with_rubric(submission_id: int, grades: list[dict], graded_by: int) -> list[RubricGrade]:
    """grades: [{"criterion_id": int, "score": float, "comment": str|None}]"""

    def _grade():
        results = []
        for g in grades:
            existing = RubricGrade.query.filter_by(submission_id=submission_id, criterion_id=g["criterion_id"]).first()
            if existing:
                existing.score = g["score"]
                existing.comment = g.get("comment")
                existing.graded_by = graded_by
                results.append(existing)
            else:
                rg = RubricGrade(
                    submission_id=submission_id,
                    criterion_id=g["criterion_id"],
                    score=g["score"],
                    comment=g.get("comment"),
                    graded_by=graded_by,
                )
                db.session.add(rg)
                results.append(rg)
        return results

    return tx(_grade)


def get_rubric_grades(submission_id: int) -> list[RubricGrade]:
    return RubricGrade.query.filter_by(submission_id=submission_id).all()


def rubric_total_score(submission_id: int) -> float:
    grades = get_rubric_grades(submission_id)
    return sum(float(g.score) for g in grades)
