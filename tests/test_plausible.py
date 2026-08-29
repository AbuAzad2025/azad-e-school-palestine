"""اختبارات Plausible Analytics"""


def test_plausible_script_renders_when_configured(client, app):
    """يظهر سكريبت Plausible عند ضبط الإعداد"""
    app.config["PLAUSIBLE_SCRIPT_URL"] = "azad-school.ps"
    # Use a page that uses base.html (like login)
    response = client.get("/auth/login")
    assert b"plausible.io/js/script.js" in response.data
    assert b'data-domain="azad-school.ps"' in response.data


def test_plausible_script_hidden_when_empty(client, app):
    """لا يظهر السكريبت بدون الإعداد"""
    app.config["PLAUSIBLE_SCRIPT_URL"] = ""
    response = client.get("/auth/login")
    assert b"plausible.io" not in response.data
