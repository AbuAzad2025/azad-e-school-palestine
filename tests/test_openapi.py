"""اختبارات OpenAPI/Swagger"""

import json


def test_swagger_ui_reachable(client, app):
    """Swagger UI يمكن الوصول إليه عبر /api/v1/docs/"""
    resp = client.get("/api/v1/docs/")
    assert resp.status_code == 200
    assert b"swagger" in resp.data.lower() or b"Swagger" in resp.data


def test_apispec_json_reachable(client, app):
    """ملف apispec.json متاح عبر /api/v1/apispec.json"""
    resp = client.get("/api/v1/apispec.json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "paths" in data or "swagger" in data


def test_all_v1_endpoints_documented(client, app):
    """جميع نقاط النهاية في /api/v1/ موجودة في apispec"""
    resp = client.get("/api/v1/apispec.json")
    assert resp.status_code == 200
    data = resp.get_json()
    paths = data.get("paths", {})
    expected = ["/health", "/version", "/me", "/lessons", "/tutoring/sessions"]
    for ep in expected:
        assert ep in paths, f"{ep} not found in apispec paths: {list(paths.keys())}"


def test_schemas_defined_for_core_models(client, app):
    """تعريفات الموديلات الأساسية موجودة في apispec"""
    resp = client.get("/api/v1/apispec.json")
    assert resp.status_code == 200
    data = resp.get_json()
    defs = data.get("definitions", {})
    required_schemas = ["User", "Lesson", "TutoringSession", "Error", "HealthResponse"]
    for name in required_schemas:
        assert name in defs, f"Schema '{name}' not found in definitions: {list(defs.keys())}"
