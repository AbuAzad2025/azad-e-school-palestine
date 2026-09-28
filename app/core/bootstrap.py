"""
Idempotent, production-grade application bootstrap.

This module centralizes the mandatory runtime system initialization so that
Azad E-School can guarantee a clean production-ready state without relying
on standalone/external seed scripts such as scripts/seed_clean_env.py.

Design rules:
- Zero dummy data: only creates missing core system entities required by the
  runtime.
- Idempotent: safe to run on every app startup / deployment.
- Transactional: all mutations run through the project's `tx()` context.
- Deterministic: does not invent super admins or tenants unless explicitly
  configured via explicit app config values.
"""

from __future__ import annotations

from typing import Any

from app.core.db import tx
from app.extensions import db
from app.models.school import School
from app.models.user import User, UserApprovalStatus, UserRole


def _existing_user(email: str) -> User | None:
    return db.session.execute(db.select(User).where(User.email == email)).scalar_one_or_none()


def _existing_school(domain: str) -> School | None:
    return db.session.execute(db.select(School).where(School.domain == domain)).scalar_one_or_none()


def ensure_system_school_exists() -> School:
    """Ensure the system school exists.

    This is the application-internal equivalent of the legacy
    get_or_create_system_school() behavior, but it is intentionally
    referenced from the app lifecycle rather than from ad-hoc scripts.
    """
    from app.services.schools import get_or_create_system_school

    return get_or_create_system_school()


def ensure_super_admin_exists(email: str, password: str) -> User:
    """Ensure a super admin user exists with the given credentials.

    This is intentionally explicit rather than magical: the application
    does not invent a super admin by default unless this function is
    called with explicit credentials.
    """
    from app.core.security import hash_password

    existing = _existing_user(email)
    if existing is not None:
        return existing

    def _create():
        user = User(
            email=email,
            password_hash=hash_password(password),
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
        return user

    return tx(_create)


def bootstrap_system(
    app: Any,
    *,
    super_admin_email: str | None = None,
    super_admin_password: str | None = None,
) -> dict[str, Any]:
    """Idempotent bootstrap of mandatory runtime system entities.

    Args:
        app: The Flask application instance (used for context and config).
        super_admin_email: If provided, ensures a super admin with this email
            exists using `super_admin_password`. If omitted, no super admin
            is created automatically.
        super_admin_password: Required when super_admin_email is provided.

    Returns:
        A structured bootstrap report suitable for logging or CLI output.
    """
    system_school = ensure_system_school_exists()

    super_admin = None
    if super_admin_email and super_admin_password:
        super_admin = ensure_super_admin_exists(super_admin_email, super_admin_password)

    return {
        "system_school": {
            "domain": system_school.domain,
            "id": system_school.id,
            "exists": True,
        },
        "super_admin": (
            {
                "email": super_admin.email,
                "id": super_admin.id,
                "exists": True,
            }
            if super_admin is not None
            else None
        ),
    }
