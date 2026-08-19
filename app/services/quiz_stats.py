"""إحصائيات الاختبارات — حسابات بحتة بدون جداول جديدة."""

import math
from dataclasses import dataclass


@dataclass
class QuestionStats:
    question_id: int
    prompt: str
    total_answers: int
    correct_count: int
    wrong_count: int
    difficulty_index: float
    discrimination_index: float | None


@dataclass
class QuizStats:
    quiz_id: int
    total_attempts: int
    avg_score: float
    highest_score: float
    lowest_score: float
    completion_rate: float
    std_deviation: float
    score_distribution: dict[str, int]
    question_stats: list[QuestionStats]


def get_quiz_stats(quiz_id: int) -> QuizStats | None:
    from sqlalchemy.orm import selectinload

    from app.extensions import db
    from app.models.assessment import Quiz, QuizAttempt

    quiz = db.session.execute(
        db.select(Quiz).options(selectinload(Quiz.questions)).where(Quiz.id == quiz_id)
    ).scalar_one_or_none()
    if not quiz:
        return None

    attempts = list(
        db.session.execute(
            db.select(QuizAttempt)
            .options(selectinload(QuizAttempt.answers))
            .where(QuizAttempt.quiz_id == quiz_id, QuizAttempt.status == "submitted")
        )
        .scalars()
        .all()
    )

    total_attempts = len(attempts)

    if total_attempts == 0:
        return QuizStats(
            quiz_id=quiz_id,
            total_attempts=0,
            avg_score=0.0,
            highest_score=0.0,
            lowest_score=0.0,
            completion_rate=0.0,
            std_deviation=0.0,
            score_distribution={},
            question_stats=[],
        )

    scores = [float(a.score or 0) for a in attempts]
    avg_score = sum(scores) / total_attempts
    highest_score = max(scores)
    lowest_score = min(scores)

    total_possible = sum(float(q.mark or 1) for q in quiz.questions) or 1.0
    completion_rate = round(total_attempts / max(total_possible, 1) * 100, 1) if total_possible else 0.0

    variance = sum((s - avg_score) ** 2 for s in scores) / total_attempts
    std_deviation = round(math.sqrt(variance), 2)

    bins = ["0-20", "20-40", "40-60", "60-80", "80-100"]
    score_distribution = {b: 0 for b in bins}
    for s in scores:
        pct = (s / total_possible * 100) if total_possible else 0
        if pct < 20:
            score_distribution["0-20"] += 1
        elif pct < 40:
            score_distribution["20-40"] += 1
        elif pct < 60:
            score_distribution["40-60"] += 1
        elif pct < 80:
            score_distribution["60-80"] += 1
        else:
            score_distribution["80-100"] += 1

    question_stats = []
    if attempts:
        sorted_attempts = sorted(attempts, key=lambda a: float(a.score or 0), reverse=True)
        top_n = max(1, int(len(sorted_attempts) * 0.27))
        bottom_n = max(1, int(len(sorted_attempts) * 0.27))
        top_students = {a.student_id for a in sorted_attempts[:top_n]}
        bottom_students = {a.student_id for a in sorted_attempts[-bottom_n:]}

    for question in quiz.questions:
        q_answers = []
        for attempt in attempts:
            for ans in attempt.answers:
                if ans.question_id == question.id:
                    q_answers.append(ans)

        total_answers = len(q_answers)
        correct_count = sum(1 for a in q_answers if a.is_correct is True)
        wrong_count = sum(1 for a in q_answers if a.is_correct is False)
        difficulty_index = round(correct_count / total_answers, 2) if total_answers else 0.0

        top_correct = 0
        top_total = 0
        bottom_correct = 0
        bottom_total = 0
        if attempts and top_students and bottom_students:
            for attempt in attempts:
                for ans in attempt.answers:
                    if ans.question_id == question.id:
                        if attempt.student_id in top_students:
                            top_total += 1
                            if ans.is_correct is True:
                                top_correct += 1
                        if attempt.student_id in bottom_students:
                            bottom_total += 1
                            if ans.is_correct is True:
                                bottom_correct += 1

        top_pct = top_correct / top_total if top_total else 0.0
        bottom_pct = bottom_correct / bottom_total if bottom_total else 0.0
        discrimination_index = round(top_pct - bottom_pct, 2) if (top_total and bottom_total) else None

        question_stats.append(
            QuestionStats(
                question_id=question.id,
                prompt=question.prompt,
                total_answers=total_answers,
                correct_count=correct_count,
                wrong_count=wrong_count,
                difficulty_index=difficulty_index,
                discrimination_index=discrimination_index,
            )
        )

    return QuizStats(
        quiz_id=quiz_id,
        total_attempts=total_attempts,
        avg_score=round(avg_score, 2),
        highest_score=round(highest_score, 2),
        lowest_score=round(lowest_score, 2),
        completion_rate=completion_rate,
        std_deviation=std_deviation,
        score_distribution=score_distribution,
        question_stats=question_stats,
    )
