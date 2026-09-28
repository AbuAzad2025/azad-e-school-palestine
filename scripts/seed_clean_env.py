#!/usr/bin/env python3
"""Clean environment seed for Azad E-School v2.0 (development).

Creates:
- Super admin user (approved + active).
- Initial school tenant (azad-model.azad.ps).
- Grades 1..12 for that school (via existing schools service logic).

All DB mutations run inside the project's tx() transaction context.
Password is hashed via app.core.security.hash_password (Argon2id).

The initial super-admin password is read from the environment
(``AZAD_SEED_ADMIN_PASSWORD``) and is never hardcoded in the repository (D4).
"""

from __future__ import annotations

import os
import sys

# Ensure repository root is in sys.path so `app` is importable when
# the script is executed directly (sys.path[0] would otherwise be scripts/).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.core.db import tx
from app.core.security import hash_password
from app.extensions import db
from app.models.school import Grade, School
from app.models.user import User, UserApprovalStatus, UserRole

SUPER_ADMIN_EMAIL = os.environ.get("AZAD_SEED_ADMIN_EMAIL", "admin@azad.ps")
SUPER_ADMIN_PASSWORD = os.environ.get("AZAD_SEED_ADMIN_PASSWORD", "")
SCHOOL_NAME_AR = "مدرسة أزاد النموذجية"
SCHOOL_NAME_EN = "Azad Model School"
SCHOOL_DOMAIN = "azad-model.azad.ps"


def _seed() -> dict:
    existing_user = db.session.execute(db.select(User).where(User.email == SUPER_ADMIN_EMAIL)).scalar_one_or_none()

    existing_school = db.session.execute(db.select(School).where(School.domain == SCHOOL_DOMAIN)).scalar_one_or_none()

    if existing_user is not None and existing_school is not None:
        grades_count = db.session.execute(
            db.select(db.func.count(Grade.id)).where(Grade.school_id == existing_school.id)
        ).scalar_one()
        db.session.flush()
        return {
            "status": "skipped",
            "reason": "clean seed already present",
            "user_id": existing_user.id,
            "school_id": existing_school.id,
            "grades_count": grades_count,
        }

    if existing_user is not None or existing_school is not None:
        raise RuntimeError(
            "Clean seed is partially present and cannot be safely completed in-place. "
            "Use a fresh database or remove the partial seed first."
        )

    if not SUPER_ADMIN_PASSWORD:
        raise RuntimeError(
            "AZAD_SEED_ADMIN_PASSWORD is not set. Pass the initial super-admin "
            "password via the environment; credentials are never committed (D4)."
        )

    password_hash = hash_password(SUPER_ADMIN_PASSWORD)

    def _seed_transaction():
        user = User(
            email=SUPER_ADMIN_EMAIL,
            password_hash=password_hash,
            role=UserRole.super_admin,
            name_ar="أحمد غنام",
            name_en="Ahmad Ghannam",
            locale="ar",
            is_active=True,
            is_verified=True,
            approval_status=UserApprovalStatus.approved,
        )
        db.session.add(user)
        db.session.flush()

        school = School(
            name_ar=SCHOOL_NAME_AR,
            name_en=SCHOOL_NAME_EN,
            domain=SCHOOL_DOMAIN,
            is_system=False,
        )
        db.session.add(school)
        db.session.flush()

        for level in range(1, 13):
            db.session.add(
                Grade(
                    school_id=school.id,
                    grade_level=level,
                    name_ar=f"صف {level}",
                )
            )

        return user, school

    user, school = tx(_seed_transaction)
    db.session.flush()

    return {
        "status": "ok",
        "user_id": user.id,
        "school_id": school.id,
        "grades_count": db.session.execute(
            db.select(db.func.count(Grade.id)).where(Grade.school_id == school.id)
        ).scalar_one(),
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        result = _seed()
        db.session.flush()
    print("SEED_RESULT:", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
