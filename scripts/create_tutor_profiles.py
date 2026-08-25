"""إنشاء TutorProfile للمعلمين التجريبيين"""
import os
import sys

sys.path.insert(0, r"D:\recovers\data\مشاريع أزاد الربحية للإعلانات\14-e-school-palestine")
os.chdir(r"D:\recovers\data\مشاريع أزاد الربحية للإعلانات\14-e-school-palestine")

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://postgres:123@localhost:5432/azad_e_school")
os.environ.setdefault("FLASK_ENV", "development")

from app import create_app
from app.extensions import db
from app.models import User, TutorProfile, School
import secrets

app = create_app()
with app.app_context():
    school = School.query.first()
    if not school:
        print("No school found!")
        sys.exit(1)
    
    # البحث عن المعلمين التجريبيين
    arabic_teacher = User.query.filter_by(email="arabic-teacher@azad.edu.ps").first()
    math_teacher = User.query.filter_by(email="math-teacher@azad.edu.ps").first()
    
    created = []
    
    for teacher in [arabic_teacher, math_teacher]:
        if not teacher:
            continue
        # التحقق من عدم وجود TutorProfile مسبقاً
        existing = TutorProfile.query.filter_by(tutor_id=teacher.id).first()
        if existing:
            print(f"TutorProfile already exists for {teacher.email} (id={existing.id})")
            continue
        
        invite_code = f"TUTOR{teacher.id}{secrets.token_hex(4).upper()}"
        teacher_name = teacher.name_ar or teacher.name_en or "معلم"
        
        profile = TutorProfile(
            tutor_id=teacher.id,
            subject="عربي, لغة عربية" if "arabic" in teacher.email else "رياضيات",
            grade_levels=[5, 6, 7, 8, 9],
            price_hour=50.0,
            price_session=120.0,
            mode="both",
            availability={
                "sunday": ["16:00", "17:00", "18:00"],
                "monday": ["16:00", "17:00", "18:00"],
                "tuesday": ["16:00", "17:00", "18:00"],
                "wednesday": ["16:00", "17:00", "18:00"],
                "thursday": ["16:00", "17:00", "18:00"],
            },
            bio=f"معلم {teacher_name} ذو خبرة واسعة في التدريس. متخصص في تبسيط المفاهيم للطلاب.",
            invite_code=invite_code,
            is_active=True,
            video_provider="jitsi",
        )
        db.session.add(profile)
        created.append((teacher.email, profile))
        print(f"Created TutorProfile for {teacher.email} (invite_code={invite_code})")
    
    if created:
        db.session.commit()
        print(f"\nCommitted {len(created)} TutorProfile(s)")
    else:
        print("\nNo new TutorProfiles created")
    
    # التحقق النهائي
    print("\n=== All TutorProfiles ===")
    for t in TutorProfile.query.all():
        user = User.query.get(t.tutor_id)
        print(f"  ID={t.id} | tutor={user.email if user else '?'} | active={t.is_active} | rate={t.price_hour}/hr | invite={t.invite_code}")
