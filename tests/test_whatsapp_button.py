"""اختبارات WhatsApp Floating Button"""


def test_whatsapp_button_renders_when_configured(client, app):
    """يظهر الزر عند ضبط الرقم"""
    app.config["WHATSAPP_BUSINESS_NUMBER"] = "972599123456"
    # Use a page that uses base.html (like login)
    response = client.get("/auth/login")
    assert b"wa.me/972599123456" in response.data
    assert b"whatsapp-float" in response.data


def test_whatsapp_button_hidden_when_empty(client, app):
    """لا يظهر الزر بدون إعداد"""
    app.config["WHATSAPP_BUSINESS_NUMBER"] = ""
    response = client.get("/auth/login")
    assert b"whatsapp-float" not in response.data
