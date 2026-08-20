"""اختبارات API Versioning — /api/v1/ endpoints"""

import pytest


def _login_as(client, email, password="TestPass123!"):
    client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=True)


def test_v1_prefix_exists(client, app):
    """نقطة /api/v1/health تعمل بشكل صحيح"""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["api"] == "v1"


def test_v1_response_has_meta_version(client, app):
    """الاستجابة تحتوي meta.version = v1"""
    resp = client.get("/api/v1/health")
    data = resp.get_json()
    assert resp.headers["X-API-Version"] == "v1"
    assert resp.headers["X-API-Versions"] == "v1"


def test_v1_me_requires_auth(client, app):
    """نقطة /api/v1/me تتطلب مصادقة"""
    resp = client.get("/api/v1/me")
    assert resp.status_code == 401
    data = resp.get_json()
    assert "error" in data
    assert data["error"]["code"] == "UNAUTHORIZED"


def test_v1_me_returns_user_profile(client, app, admin_user):
    """نقطة /api/v1/me تُعيد ملف المستخدم"""
    _login_as(client, admin_user)
    resp = client.get("/api/v1/me")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["data"]["email"] == admin_user
    assert data["meta"]["version"] == "v1"
    assert "request_id" in data["meta"]


def test_v1_error_format_consistent(client, app):
    """صيغة الأخطاء موحّدة في /api/v1/ — عدم المصادقة يُعيد JSON"""
    resp = client.get("/api/v1/me")
    assert resp.status_code == 401
    data = resp.get_json()
    assert "error" in data
    assert "message" in data["error"]
    assert "code" in data["error"]
    assert data["error"]["code"] == "UNAUTHORIZED"
    assert "meta" in data
    assert data["meta"]["version"] == "v1"
    assert "request_id" in data["meta"]


def test_rate_limiting_applied_to_v1(client, app):
    """Rate limiting مفعّل على /api/v1/"""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200


def test_v1_lessons_returns_paginated(client, app, admin_user):
    """نقطة /api/v1/lessons تُعيد قائمة مُ الصفحة"""
    _login_as(client, admin_user)
    resp = client.get("/api/v1/lessons")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "data" in data
    assert "meta" in data
    assert "page" in data["meta"]
    assert "total" in data["meta"]
    assert isinstance(data["data"], list)
