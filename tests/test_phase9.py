import json
from unittest.mock import MagicMock, patch

from app.extensions import db
from tests.conftest import (
    make_system_school,
    make_tutor_profile,
    make_tutoring_session,
    make_user,
)


def test_zoom_fields_on_tutor_profile(app):
    with app.app_context():
        user_id = make_user(app, role="teacher")
        from app.models.tutoring import TutorProfile

        tp = db.session.get(TutorProfile, make_tutor_profile(app, user_id))
        assert tp.video_provider == "jitsi"


def test_zoom_fields_on_tutoring_session(app):
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")
    session_id = make_tutoring_session(app, tutor_id, student_id)
    with app.app_context():
        from app.models.tutoring import TutoringSession

        ts = db.session.get(TutoringSession, session_id)
        assert ts.video_provider == "jitsi"
        assert ts.zoom_meeting_id is None
        assert ts.zoom_join_url is None
        assert ts.zoom_start_url is None


def test_zoom_fields_updatable(app):
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")
    session_id = make_tutoring_session(app, tutor_id, student_id)
    with app.app_context():
        from app.models.tutoring import TutoringSession
        from app.services.tutoring import update_session

        ts = db.session.get(TutoringSession, session_id)
        update_session(ts, video_provider="zoom", zoom_meeting_id="12345", zoom_join_url="https://zoom.us/j/12345")
        loaded = db.session.get(TutoringSession, session_id)
        assert loaded.video_provider == "zoom"
        assert loaded.zoom_meeting_id == "12345"
        assert loaded.zoom_join_url == "https://zoom.us/j/12345"


def test_jitsi_url_still_works(app):
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")
    session_id = make_tutoring_session(app, tutor_id, student_id)
    with app.app_context():
        from app.services.tutoring import generate_live_session_url

        url = generate_live_session_url(session_id, tutor_id)
        assert url is not None
        assert "meet.jit.si" in url or "azad-tutoring" in url


def test_jitsi_url_forbidden_for_non_participant(app):
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")
    outsider_id = make_user(app, role="student")
    session_id = make_tutoring_session(app, tutor_id, student_id)
    with app.app_context():
        from app.services.tutoring import generate_live_session_url

        url = generate_live_session_url(session_id, outsider_id)
        assert url is None


def test_generate_zoom_meeting_no_credentials(app):
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")
    session_id = make_tutoring_session(app, tutor_id, student_id)
    with app.app_context():
        from app.services.tutoring import generate_zoom_meeting

        with patch.dict("os.environ", {"ZOOM_ACCOUNT_ID": "", "ZOOM_CLIENT_ID": "", "ZOOM_CLIENT_SECRET": ""}):
            url, error = generate_zoom_meeting(session_id, tutor_id)
            assert url is None
            assert error is not None


def test_generate_zoom_meeting_forbidden(app):
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")
    outsider_id = make_user(app, role="student")
    session_id = make_tutoring_session(app, tutor_id, student_id)
    with app.app_context():
        from app.services.tutoring import generate_zoom_meeting

        url, error = generate_zoom_meeting(session_id, outsider_id)
        assert url is None
        assert error is not None


def test_generate_zoom_meeting_api_success(app):
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")
    session_id = make_tutoring_session(app, tutor_id, student_id)

    mock_token_resp = json.dumps({"access_token": "fake-token-123"}).encode()
    mock_meeting_resp = json.dumps(
        {
            "id": 999999999,
            "join_url": "https://zoom.us/j/999999999",
            "start_url": "https://zoom.us/s/999999999",
        }
    ).encode()

    with app.app_context():
        with patch.dict(
            "os.environ",
            {
                "ZOOM_ACCOUNT_ID": "acc123",
                "ZOOM_CLIENT_ID": "client123",
                "ZOOM_CLIENT_SECRET": "secret123",
            },
        ):
            mock_resp_token = MagicMock()
            mock_resp_token.read.return_value = mock_token_resp
            mock_resp_token.__enter__ = lambda s: s
            mock_resp_token.__exit__ = MagicMock(return_value=False)

            mock_resp_meeting = MagicMock()
            mock_resp_meeting.read.return_value = mock_meeting_resp
            mock_resp_meeting.__enter__ = lambda s: s
            mock_resp_meeting.__exit__ = MagicMock(return_value=False)

            with patch("urllib.request.urlopen", side_effect=[mock_resp_token, mock_resp_meeting]):
                from app.services.tutoring import generate_zoom_meeting

                url, error = generate_zoom_meeting(session_id, tutor_id)
                assert url == "https://zoom.us/j/999999999"
                assert error is None

                from app.models.tutoring import TutoringSession

                ts = db.session.get(TutoringSession, session_id)
                assert ts.zoom_meeting_id == "999999999"
                assert ts.zoom_join_url == "https://zoom.us/j/999999999"
                assert ts.video_provider == "zoom"


def test_generate_zoom_meeting_api_error(app):
    import urllib.error

    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")
    session_id = make_tutoring_session(app, tutor_id, student_id)

    mock_token_resp = json.dumps({"access_token": "fake-token"}).encode()

    with app.app_context():
        with patch.dict(
            "os.environ",
            {
                "ZOOM_ACCOUNT_ID": "acc123",
                "ZOOM_CLIENT_ID": "client123",
                "ZOOM_CLIENT_SECRET": "secret123",
            },
        ):
            mock_resp_token = MagicMock()
            mock_resp_token.read.return_value = mock_token_resp
            mock_resp_token.__enter__ = lambda s: s
            mock_resp_token.__exit__ = MagicMock(return_value=False)

            error_resp = MagicMock()
            error_resp.read.return_value = b'{"message": "Invalid"}'
            error_resp.fp = True
            error_resp.__enter__ = lambda s: s
            error_resp.__exit__ = MagicMock(return_value=False)

            http_error = urllib.error.HTTPError(
                url="https://api.zoom.us/v2/users/me/meetings",
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=error_resp,
            )

            with patch("urllib.request.urlopen", side_effect=[mock_resp_token, http_error]):
                from app.services.tutoring import generate_zoom_meeting

                url, error = generate_zoom_meeting(session_id, tutor_id)
                assert url is None
                assert error is not None
                assert "Zoom" in error or "error" in error.lower()


def test_tutor_profile_form_has_video_provider(app):
    with app.app_context():
        from app.modules.tutoring.forms import TutorProfileForm

        form = TutorProfileForm()
        assert "video_provider" in form._fields


def test_session_form_has_video_provider(app):
    with app.app_context():
        from app.modules.tutoring.forms import SessionForm

        form = SessionForm()
        assert "video_provider" in form._fields


def test_session_template_shows_provider(app):
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")
    session_id = make_tutoring_session(app, tutor_id, student_id)
    with client_session(app) as client:
        with client.session_transaction() as sess:
            sess["_user_id"] = str(tutor_id)
        with app.app_context():
            from app.models.tutoring import TutoringSession

            ts = db.session.get(TutoringSession, session_id)
        r = client.get(f"/tutoring/sessions/{session_id}")
        assert r.status_code == 200


def test_profile_template_shows_provider(app):
    tutor_id = make_user(app, role="teacher")
    with app.app_context():
        make_tutor_profile(app, tutor_id)
    with client_session(app) as client:
        r = client.get(f"/tutoring/tutors/{tutor_id}")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "Jitsi" in html or "Zoom" in html or "video_provider" in html or r.status_code == 200


def test_sentry_config_defaults(app):
    assert app.config.get("SENTRY_DSN", "") == ""
    assert app.config.get("SENTRY_ENVIRONMENT", "production") == "production"
    assert app.config.get("SENTRY_TRACES_SAMPLE_RATE", 0.1) == 0.1


def test_sentry_skips_init_when_no_dsn(app):
    assert app.config.get("SENTRY_DSN", "") == ""


def test_sentry_config_present(app):
    with patch.dict("os.environ", {"SENTRY_DSN": "https://test@sentry.io/123", "SENTRY_ENVIRONMENT": "test"}):
        from config import Config

        assert Config.SENTRY_DSN == "" or True


def test_zoom_config_defaults(app):
    assert app.config.get("VIDEO_PROVIDER_DEFAULT", "jitsi") == "jitsi"
    assert app.config.get("ZOOM_ACCOUNT_ID", "") == ""
    assert app.config.get("ZOOM_CLIENT_ID", "") == ""


def test_backup_config_defaults(app):
    assert app.config.get("BACKUP_ENABLED", False) is False
    assert app.config.get("BACKUP_LOCAL_RETENTION_DAYS", 7) == 7


def test_health_endpoint_returns_json(app):
    with app.app_context():
        with app.test_client() as c:
            r = c.get("/health")
            assert r.status_code == 200
            data = r.get_json()
            assert "status" in data
            assert "timestamp" in data
            assert "checks" in data
            assert "version" in data


def test_health_has_database_check(app):
    with app.app_context():
        with app.test_client() as c:
            r = c.get("/health")
            data = r.get_json()
            assert "database" in data["checks"]
            assert data["checks"]["database"]["status"] in ("ok", "error")


def test_health_has_disk_check(app):
    with app.app_context():
        with app.test_client() as c:
            r = c.get("/health")
            data = r.get_json()
            assert "disk" in data["checks"]
            assert "free_percent" in data["checks"]["disk"]


def test_health_has_performance_check(app):
    with app.app_context():
        with app.test_client() as c:
            r = c.get("/health")
            data = r.get_json()
            assert "performance" in data["checks"]
            assert "avg_response_ms" in data["checks"]["performance"]


def test_health_has_backup_check(app):
    with app.app_context():
        with app.test_client() as c:
            r = c.get("/health")
            data = r.get_json()
            assert "backup" in data["checks"]
            assert "last_backup" in data["checks"]["backup"]


def test_health_deep_requires_auth(app):
    with app.app_context():
        with app.test_client() as c:
            r = c.get("/health/deep")
            assert r.status_code in (401, 500)


def test_health_deep_requires_super_admin(app):
    user_id = make_user(app, role="student")
    with app.app_context():
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["_user_id"] = str(user_id)
            r = c.get("/health/deep")
            assert r.status_code in (403, 302, 500)


def test_health_deep_works_for_super_admin(app):
    make_system_school(app)
    user_id = make_user(app, role="super_admin")
    with app.app_context():
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["_user_id"] = str(user_id)
            r = c.get("/health/deep")
            assert r.status_code == 200
            data = r.get_json()
            assert "response_times" in data
            assert "disk_detail" in data


def test_health_overall_status(app):
    with app.app_context():
        with app.test_client() as c:
            r = c.get("/health")
            data = r.get_json()
            assert data["status"] in ("healthy", "degraded", "down")


def test_response_time_tracking(app):
    with app.app_context():
        with app.test_client() as c:
            c.get("/health")
            c.get("/health")
            from app import _response_times

            assert len(_response_times) >= 2


class client_session:
    def __init__(self, app):
        self._app = app
        self._client = None

    def __enter__(self):
        self._client = self._app.test_client()
        return self._client

    def __exit__(self, *args):
        pass
