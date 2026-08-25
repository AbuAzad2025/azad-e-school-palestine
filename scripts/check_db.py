"""فحص سريع لقاعدة البيانات"""
import os
import sys

# إضافة مجلد المشروع
sys.path.insert(0, r"D:\recovers\data\مشاريع أزاد الربحية للإعلانات\14-e-school-palestine")
os.chdir(r"D:\recovers\data\مشاريع أزاد الربحية للإعلانات\14-e-school-palestine")

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://postgres:123@localhost:5432/azad_e_school")
os.environ.setdefault("FLASK_ENV", "development")

from app import create_app
from app.extensions import db
from app.models import User, TutorProfile, School

app = create_app()
with app.app_context():
    print(f"Users: {User.query.count()}")
    print(f"TutorProfiles: {TutorProfile.query.count()}")
    print(f"Schools: {School.query.count()}")
    
    print("\n=== Users ===")
    for u in User.query.all():
        print(f"  ID={u.id} | {u.email} | role={u.role}")
    
    print("\n=== TutorProfiles ===")
    for t in TutorProfile.query.all():
        print(f"  ID={t.id} | user_id={t.user_id} | status={t.status}")
