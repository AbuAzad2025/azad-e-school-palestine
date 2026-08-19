"""اختبارات صفحة الأسعار"""

import pytest


def test_pricing_route_returns_200(client):
    """صفحة الأسعار تعمل وتعيد 200"""
    response = client.get("/pricing")
    assert response.status_code == 200


def test_pricing_page_has_4_plans(client):
    """صفحة الأسعار تحتوي على 4 خطط"""
    response = client.get("/pricing")
    assert response.status_code == 200
    # Check for all 4 plan names
    assert b"29" in response.data  # Basic
    assert b"59" in response.data  # Pro
    assert b"499" in response.data  # School Pro
    assert b"999" in response.data  # School Premium


def test_pricing_page_no_auth_required(client):
    """صفحة الأسعار لا تحتاج تسجيل دخول"""
    response = client.get("/pricing")
    assert response.status_code == 200
    # Should not redirect to login
    assert "login" not in response.request.path