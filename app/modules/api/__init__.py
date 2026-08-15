"""Blueprint API — لتطبيق الجوال مستقبلاً (نسخة 1: قراءة بيانات فقط).

الهدف: من M1، كل منطق الأعمال في app/services، وستُعرَّض
نقاط JSON هنا لاحقاً لتغذية تطبيق الجوال دون إعادة بناء.
"""

from flask import Blueprint, jsonify

bp = Blueprint("api", __name__, url_prefix="/api/v1")


@bp.get("/health")
def api_health():
    return jsonify(status="ok", api="v1", app="azad-e-school")
