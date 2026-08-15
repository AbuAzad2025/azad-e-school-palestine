"""تجميع كل النماذج — تستورده SQLAlchemy وAlembic ليكتشف الجداول.

تُستورَد هنا صراحةً كل الوحدات حتى تُسجَّل الجداول لدى قاعدة البيانات.
"""
from .ai import AiMessage, AiSession
from .assessment import Answer, Question, Quiz, QuizAttempt
from .attendance import Attendance
from .billing import ManualPayment, PaymentReceipt, Subscription, SubscriptionPlan
from .class_room import ClassMember, ClassRoom
from .communication import Announcement, Notification
from .content import Lesson, LessonAttachment, Unit
from .gradebook import Assignment, GradeCategory, GradeEntry, GradeItem, Submission
from .mixins import PKMixin, SoftDeleteMixin
from .school import Grade, School, SchoolSetting, Subject, SubjectGradeLink
from .system import AuditLog, Setting
from .user import User, UserRole, UserRoleLink

__all__ = [
    "AiMessage",
    "AiSession",
    "Answer",
    "Assignment",
    "Attendance",
    "AuditLog",
    "ClassMember",
    "ClassRoom",
    "Grade",
    "GradeCategory",
    "GradeEntry",
    "GradeItem",
    "Lesson",
    "LessonAttachment",
    "ManualPayment",
    "Notification",
    "PKMixin",
    "PaymentReceipt",
    "Question",
    "Quiz",
    "QuizAttempt",
    "School",
    "SchoolSetting",
    "Setting",
    "SoftDeleteMixin",
    "Subject",
    "SubjectGradeLink",
    "Submission",
    "Subscription",
    "SubscriptionPlan",
    "Unit",
    "User",
    "UserRole",
    "UserRoleLink",
    "Announcement",
]
