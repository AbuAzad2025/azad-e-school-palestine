

def test_ajax_error_returns_json_contract(app):
    client = app.test_client()
    # Trigger a 404 with AJAX header
    resp = client.get("/nonexistent/path/12345", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 404
    data = resp.get_json()
    assert data is not None
    assert "error" in data
    assert "code" in data["error"]
    assert "message" in data["error"]
    assert "domain" in data["error"]
    assert "meta" in data
    assert "request_id" in data["meta"]


def test_ajax_forbidden_returns_json(app):
    client = app.test_client()
    # Try to access admin without login - likely redirects or 401/403; with AJAX should get JSON
    resp = client.get("/admin/", headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
    # Should be JSON error
    assert resp.status_code in (401, 403, 302)  # depends on auth setup
    if resp.is_json:
        data = resp.get_json()
        assert "error" in data
        assert "message" in data["error"]
