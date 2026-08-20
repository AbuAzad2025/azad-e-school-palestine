"""اختبارات Structured Logging + Correlation IDs"""

from app.core.logging import (
    clear_correlation_id,
    get_correlation_id,
    get_logger,
    set_correlation_id,
)


def test_request_id_in_response_header(client, app):
    """X-Request-ID يظهر في رؤوس الاستجابة"""
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) == 16


def test_request_id_preserved_from_client(client, app):
    """X-Request-ID المُرسل من العميل يُحتفظ به"""
    custom_id = "my-custom-request-id"
    response = client.get("/auth/login", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_id


def test_correlation_id_context_var():
    """ContextVar لـ correlation ID يعمل بشكل صحيح"""
    clear_correlation_id()
    cid = get_correlation_id()
    assert len(cid) == 16

    custom = "test-abc-123"
    set_correlation_id(custom)
    assert get_correlation_id() == custom

    clear_correlation_id()
    assert get_correlation_id() != custom


def test_structlog_json_output_contains_correlation_id(app):
    """الإخراج بصيغة JSON يحتوي على correlation_id"""
    import structlog
    from app.core.logging import _add_correlation_id, configure_structlog

    captured_events: list[dict] = []

    def capture_processor(logger, method_name, event_dict):
        captured_events.append(dict(event_dict))
        return event_dict

    app.config["LOG_JSON"] = True
    configure_structlog(app)

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_correlation_id,
            capture_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    set_correlation_id("test-corr-123")
    log = get_logger("test_json")
    log.info("test_event", key="value")

    assert len(captured_events) == 1
    assert captured_events[0]["correlation_id"] == "test-corr-123"
    assert captured_events[0]["event"] == "test_event"

    app.config["LOG_JSON"] = False
    configure_structlog(app)


def test_service_bind_includes_context(app):
    """logger.bind() يضيف السياق المطلوب في السجلات"""
    import structlog
    from app.core.logging import configure_structlog

    captured_events: list[dict] = []

    def capture_processor(logger, method_name, event_dict):
        captured_events.append(dict(event_dict))
        return event_dict

    app.config["LOG_JSON"] = True
    configure_structlog(app)

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            capture_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    log = get_logger("test_bind").bind(service="payments", user_id=42)
    log.info("payment_created", amount=100)

    assert len(captured_events) == 1
    assert captured_events[0]["service"] == "payments"
    assert captured_events[0]["user_id"] == 42
    assert captured_events[0]["event"] == "payment_created"

    app.config["LOG_JSON"] = False
    configure_structlog(app)
