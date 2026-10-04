from app.extensions import csrf
from flask import Blueprint

bp = Blueprint("whatsapp", __name__, url_prefix="/api/whatsapp")

# مزوّد الخدمة يتصل من خادم Meta ولا يملك رمز CSRF (لا جلسة ولا نموذج)، فحماية
# CSRF تُرفض كل ويب هوك بـ400. التحقق هنا هو توقيع HMAC على الجسم الخام — وهو
# أقوى من CSRF لهذه المسارات，因为它 يثبت مصدر الرسالة لا مجرد وجود الجلسة.
csrf.exempt(bp)

from . import routes  # noqa
