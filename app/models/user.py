"""المستخدمون والأدوار — حساب واحد، أدوار متعددة عبر المدارس"""

from datetime import datetime, timedelta
from enum import StrEnum

from flask_login import UserMixin
from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin, SoftDeleteMixin
from .school import School


class UserRole(StrEnum):
    super_admin = "super_admin"
    school_admin = "school_admin"
    teacher = "teacher"
    student = "student"
    parent = "parent"


class UserApprovalStatus(StrEnum):
    """حالة موافقة تسجيل المستخدم."""

    pending = "pending"  # في انتظار موافقة السوبر أدمن
    approved = "approved"  # مقبول - يمكنه تسجيل الدخول
    rejected = "rejected"  # مرفوض - لا يمكنه تسجيل الدخول


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
    approval_status: Mapped[UserApprovalStatus] = mapped_column(
        db.Enum(UserApprovalStatus, name="user_approval_status"), default=UserApprovalStatus.pending, nullable=False
    )
    is_individual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True))
    # حماية من brute force
    failed_login_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until = db.Column(db.DateTime(timezone=True))
    # تاريخ كلمات المرور (لتجنب إعادة الاستخدام)
    password_history: Mapped[list[str]] = mapped_column(db.JSON, default=list, nullable=False)

    role_links: Mapped[list["UserRoleLink"]] = relationship(
        back_populates="user", foreign_keys="UserRoleLink.user_id", cascade="all, delete-orphan"
    )

    @property
    def is_authenticated_prop(self):
        return self.is_active

    @property
    def is_approved(self) -> bool:
        """تحقق مما إذا كان الحساب مقبولاً ومفعّلاً."""
        return self.is_active and self.approval_status == UserApprovalStatus.approved

    @property
    def belongs_to_school(self) -> bool:
        """True if user has an active role link to a non-system school."""
        for link in self.role_links:
            if link.is_active and not link.school.is_system:
                return True
        return False

    @property
    def school_id(self) -> int | None:
        """أول مدرسة نشطة للمستخدم (من user_role_links). None للمشرف الكلي."""
        for link in self.role_links:
            if link.is_active:
                return link.school_id
        return None

    def is_locked(self) -> bool:
        """تحقق مما إذا كان الحساب مقفلاً."""
        if self.locked_until and self.locked_until > datetime.utcnow():
            return True
        return False

    def increment_failed_login(self, max_attempts: int = 5, lockout_minutes: int = 15) -> None:
        """يزيد المحاولات الفاشلة ويقفل الحساب إذا تجاوز الحد."""
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= max_attempts:
            self.locked_until = datetime.utcnow() + timedelta(minutes=lockout_minutes)

    def reset_failed_login(self) -> None:
        """يعيد تعيين المحاولات الفاشلة عند نجاح الدخول."""
        self.failed_login_attempts = 0
        self.locked_until = None

    def add_password_to_history(self, password_hash: str, history_count: int = 5) -> None:
        """يضيف الهاش للتاريخ ويمنع إعادة الاستخدام."""
        if self.password_history is None:
            self.password_history = []
        if password_hash in self.password_history:
            return
        self.password_history.append(password_hash)
        if len(self.password_history) > history_count:
            self.password_history = self.password_history[-history_count:]

    def __repr__(self):
        return f"<User {self.id} {self.email} {self.role} {self.approval_status}>"


class UserRoleLink(PKMixin, db.Model):
    """أدوار متعددة لكل مستخدم عبر المدارس (مدرّس في مدرسة، ولي في أخرى)."""

    __tablename__ = "user_role_links"
    __table_args__ = (UniqueConstraint("user_id", "school_id", "role", name="uq_user_role_link"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    role: Mapped[UserRole] = mapped_column(db.Enum(UserRole, name="user_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="role_links", foreign_keys=[user_id])
    school: Mapped[School] = relationship("School")
    approver: Mapped[User | None] = relationship("User", foreign_keys=[approved_by])
