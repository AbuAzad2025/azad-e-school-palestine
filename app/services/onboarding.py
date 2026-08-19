"""خدمات معالج الإعداد الأولي للمدارس."""

from datetime import UTC, datetime

from app.core.db import tx
from app.extensions import db
from app.models.system import OnboardingProgress

WIZARD_STEPS = [
    {"step": 1, "title": "معلومات المدرسة", "description": "اسم المدرسة والمنطقة"},
    {"step": 2, "title": "المراحل الدراسية", "description": "تحديد المراحل (ابتدائي/متوسط/ثانوي)"},
    {"step": 3, "title": "المواد الدراسية", "description": "إضافة المواد المتاحة"},
    {"step": 4, "title": "المعلمون", "description": "دعوة المعلمين"},
    {"step": 5, "title": "الصفوف الدراسية", "description": "إنشاء الصفوف وربط المعلمين"},
]


def get_wizard_steps() -> list[dict]:
    return WIZARD_STEPS


def get_onboarding(school_id: int) -> OnboardingProgress | None:
    return OnboardingProgress.query.filter_by(school_id=school_id).first()


def start_onboarding(school_id: int) -> OnboardingProgress:
    existing = OnboardingProgress.query.filter_by(school_id=school_id).first()
    if existing:
        return existing

    def _start():
        p = OnboardingProgress(school_id=school_id, current_step=1, total_steps=5, completed_steps={})
        db.session.add(p)
        return p

    return tx(_start)


def complete_step(school_id: int, step: int, data: dict | None = None) -> OnboardingProgress | None:
    if step < 1 or step > 5:
        return None
    progress = OnboardingProgress.query.filter_by(school_id=school_id).first()
    if not progress:
        return None
    if progress.is_complete:
        return progress

    def _complete():
        steps_done = dict(progress.completed_steps or {})
        steps_done[str(step)] = data or {"completed": True}
        progress.completed_steps = steps_done
        if step >= progress.current_step:
            progress.current_step = min(step + 1, progress.total_steps)
        all_done = all(str(i) in steps_done for i in range(1, progress.total_steps + 1))
        if all_done:
            progress.is_complete = True
            progress.completed_at = datetime.now(UTC)
        return progress

    return tx(_complete)


def get_onboarding_status(school_id: int) -> dict:
    progress = OnboardingProgress.query.filter_by(school_id=school_id).first()
    if not progress:
        return {"started": False, "current_step": 0, "is_complete": False, "completed_steps": {}}
    return {
        "started": True,
        "current_step": progress.current_step,
        "is_complete": progress.is_complete,
        "completed_steps": progress.completed_steps or {},
    }
