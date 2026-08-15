"""المستخدمون والأدوار — حساب واحد، أدوار متعددة عبر المدارس"""

from enum import StrEnum

from flask_login import UserMixin
from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin, SoftDeleteMixin


class UserRole(StrEnum):
    super_admin = "super_admin"
    school_admin = "school_admin"
    teacher = "teacher"
    student = "student"
    parent = "parent"


class User(PKMixin, SoftDeleteMixin, UserMixin, db.Model):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(db.Enum(UserRole, name="user_role"), nullable=False)
    name_ar: Mapped[str | None] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    avatar: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(5), default="ar", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True))

    role_links: Mapped[list["UserRoleLink"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def is_authenticated_prop(self):
        return self.is_active

    @property
    def school_id(self) -> int | None:
        """أول مدرسة نشطة للمستخدم (من user_role_links). None للمشرف الكلي."""
        for link in self.role_links:
            if link.is_active:
                return link.school_id
        return None

    def __repr__(self):
        return f"<User {self.id} {self.email} {self.role}>"


class UserRoleLink(PKMixin, db.Model):
    """أدوار متعددة لكل مستخدم عبر المدارس (مدرّس في مدرسة، ولي في أخرى)."""

    __tablename__ = "user_role_links"
    __table_args__ = (UniqueConstraint("user_id", "school_id", "role", name="uq_user_role_link"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    role: Mapped[UserRole] = mapped_column(db.Enum(UserRole, name="user_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="role_links")
