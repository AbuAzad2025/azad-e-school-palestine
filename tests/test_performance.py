"""اختبارات الأداء — N+1 Detection + Benchmarks + Query Count"""

import time

from sqlalchemy import event as sa_event


def _track_queries(app):
    """Decorator to count queries during the wrapped operation."""
    from app.extensions import db

    counter = {"count": 0}

    def _before(conn, cursor, stmt, params, context, executemany):
        counter["count"] += 1

    with app.app_context():
        engine = db.engine
        sa_event.listen(engine, "before_cursor_execute", _before)

    yield counter

    with app.app_context():
        sa_event.remove(engine, "before_cursor_execute", _before)


def test_no_nplusone_in_lesson_list(client, app, admin_user):
    """لا يوجد N+1 في قائمة الدروس"""
    _login(client, admin_user)

    from app.extensions import db

    counter = {"count": 0}

    def _before(conn, cursor, stmt, params, context, executemany):
        counter["count"] += 1

    with app.app_context():
        eng = db.engine
        sa_event.listen(eng, "before_cursor_execute", _before)

    resp = client.get("/api/v1/lessons")
    assert resp.status_code == 200

    with app.app_context():
        sa_event.remove(eng, "before_cursor_execute", _before)

    assert counter["count"] <= 5, f"N+1 detected: {counter['count']} queries for lesson list"


def test_homepage_renders_under_threshold(client, app):
    """صفحة تسجيل الدخول تُحمّل تحت الحد المسموح"""
    start = time.perf_counter()
    resp = client.get("/auth/login")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert resp.status_code == 200
    assert elapsed_ms < 2000, f"Homepage took {elapsed_ms:.0f}ms (threshold: 2000ms)"


def test_db_query_count_capped(client, app, admin_user):
    """عدد الاستعلامات محدود في نقطة /api/v1/me"""
    _login(client, admin_user)

    from app.extensions import db

    counter = {"count": 0}

    def _before(conn, cursor, stmt, params, context, executemany):
        counter["count"] += 1

    with app.app_context():
        eng = db.engine
        sa_event.listen(eng, "before_cursor_execute", _before)

    resp = client.get("/api/v1/me")
    assert resp.status_code == 200

    with app.app_context():
        sa_event.remove(eng, "before_cursor_execute", _before)

    assert counter["count"] <= 3, f"Too many queries: {counter['count']} for /api/v1/me"


def test_api_lessons_response_time(client, app, admin_user):
    """API lessons يستجيب تحت 500ms"""
    _login(client, admin_user)

    start = time.perf_counter()
    resp = client.get("/api/v1/lessons")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert resp.status_code == 200
    assert elapsed_ms < 500, f"/api/v1/lessons took {elapsed_ms:.0f}ms (threshold: 500ms)"


def test_api_health_response_time(client, app):
    """API health يستجيب تحت 100ms"""
    start = time.perf_counter()
    resp = client.get("/api/v1/health")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert resp.status_code == 200
    assert elapsed_ms < 100, f"/api/v1/health took {elapsed_ms:.0f}ms (threshold: 100ms)"


def _login(client, email, password="TestPass123!"):
    client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=True)
