"""تجميع كل النماذج — تستورده SQLAlchemy وAlembic ليكتشف الجداول.

تُستورَد هنا صراحةً كل الوحدات حتى تُسجَّل الجداول لدى قاعدة البيانات.
"""

from .ai import AiMessage, AiSession
from .assessment import Answer, ProctoringLog, Question, Quiz, QuizAttempt
from .attendance import Attendance
from .billing import DiscountCode, ManualPayment, PaymentReceipt, ReminderLog, Subscription, SubscriptionPlan
from .calendar import AcademicEvent
from .class_room import ClassMember, ClassRoom
from .communication import Announcement, Notification
from .content import Lesson, LessonAttachment, Unit
from .family import FamilyLink, FamilyLinkCode
from .gradebook import Assignment, GradeCategory, GradeEntry, GradeItem, Submission
from .message import Message
from .mixins import PKMixin, SoftDeleteMixin
from .progress import StudentProgress, VideoProgress
from .question_bank import QuestionBank
from .school import Grade, School, SchoolSetting, Subject, SubjectGradeLink
from .system import AuditLog, Setting
from .tenant import TenantQuota
from .tutoring import TutoringRequest, TutoringSession, TutorProfile, TutorReview
from .user import User, UserRole, UserRoleLink

__all__ = [
    "AcademicEvent",
    "AiMessage",
    "AiSession",
    "Answer",
    "Assignment",
    "Attendance",
    "AuditLog",
    "ClassMember",
    "ClassRoom",
    "DiscountCode",
    "FamilyLink",
    "FamilyLinkCode",
    "Grade",
    "GradeCategory",
    "GradeEntry",
    "GradeItem",
    "Lesson",
    "LessonAttachment",
    "ManualPayment",
    "Message",
    "Notification",
    "PKMixin",
    "PaymentReceipt",
    "ProctoringLog",
    "Question",
    "QuestionBank",
    "Quiz",
    "QuizAttempt",
    "ReminderLog",
    "School",
    "SchoolSetting",
    "Setting",
    "SoftDeleteMixin",
    "StudentProgress",
    "Subject",
    "SubjectGradeLink",
    "Submission",
    "Subscription",
    "SubscriptionPlan",
    "TenantQuota",
    "TutorProfile",
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
