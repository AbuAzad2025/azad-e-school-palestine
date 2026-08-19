"""تجميع كل النماذج — تستورده SQLAlchemy وAlembic ليكتشف الجداول.

تُستورَد هنا صراحةً كل الوحدات حتى تُسجَّل الجداول لدى قاعدة البيانات.
"""

from .ai import AiMessage, AiSession
from .assessment import Answer, ProctoringLog, Question, Quiz, QuizAttempt
from .attendance import Attendance
from .billing import DiscountCode, ManualPayment, PaymentReceipt, ReminderLog, Subscription, SubscriptionPlan
from .calendar import AcademicEvent
from .class_room import ClassMember, ClassRoom
from .communication import Announcement, ContactMessage, Notification, NotificationPreference
from .content import Lesson, LessonAttachment, Unit
from .family import FamilyLink, FamilyLinkCode
from .gamification import Badge, StudentBadge
from .gradebook import (
    Assignment,
    GradeAppeal,
    GradeCategory,
    GradeEntry,
    GradeItem,
    RubricCriterion,
    RubricGrade,
    RubricTemplate,
    Submission,
)
from .message import Message
from .mixins import PKMixin, SoftDeleteMixin
from .offline import OfflineDownload
from .progress import StudentProgress, VideoProgress
from .question_bank import QuestionBank
from .school import Grade, School, SchoolSetting, Subject, SubjectGradeLink
from .system import AuditLog, CertificateTemplate, HealthCheck, OnboardingProgress, Setting
from .tenant import TenantQuota
from .tutoring import TutorCommission, TutoringRequest, TutoringSession, TutorPayout, TutorProfile, TutorReview
from .user import User, UserRole, UserRoleLink

__all__ = [
    "AcademicEvent",
    "AiMessage",
    "AiSession",
    "Answer",
    "Assignment",
    "Attendance",
    "AuditLog",
    "Badge",
    "ClassMember",
    "ClassRoom",
    "ContactMessage",
    "DiscountCode",
    "FamilyLink",
    "FamilyLinkCode",
    "Grade",
    "GradeAppeal",
    "GradeCategory",
    "GradeEntry",
    "GradeItem",
    "CertificateTemplate",
    "HealthCheck",
    "Lesson",
    "LessonAttachment",
    "ManualPayment",
    "Message",
    "Notification",
    "NotificationPreference",
    "OfflineDownload",
    "OnboardingProgress",
    "PKMixin",
    "PaymentReceipt",
    "ProctoringLog",
    "Question",
    "QuestionBank",
    "RubricCriterion",
    "RubricGrade",
    "RubricTemplate",
    "Quiz",
    "QuizAttempt",
    "ReminderLog",
    "School",
    "SchoolSetting",
    "Setting",
    "SoftDeleteMixin",
    "StudentBadge",
    "StudentProgress",
    "Subject",
    "SubjectGradeLink",
    "Submission",
    "Subscription",
    "SubscriptionPlan",
    "TenantQuota",
    "TutorCommission",
    "TutorProfile",
    "TutorPayout",
    "TutoringRequest",
    "TutoringSession",
    "TutorReview",
    "Unit",
    "User",
    "UserRole",
    "UserRoleLink",
    "VideoProgress",
    "Announcement",
]
