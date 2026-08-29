"""اختبار M0: إنشاء التطبيق + الاتصال بقاعدة البيانات"""

import pytest
from app import create_app
from app.extensions import db


@pytest.fixture()
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


def test_app_created(app):
    assert app.name == "app"


def test_db_connect(app):
    with app.app_context():
        db.engine.connect()
        assert True


def test_health_route(app):
    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] in ("ok", "healthy", "degraded")


def test_404(app):
    client = app.test_client()
    resp = client.get("/no-such-page")
    assert resp.status_code == 404
