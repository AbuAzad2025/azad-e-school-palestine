"""Blueprint API — لتطبيق الجوال مستقبلاً (نسخة 1: قراءة بيانات فقط).

الهدف: من M1، كل منطق الأعمال في app/services، وستُعرَّض
نقاط JSON هنا لاحقاً لتغذية تطبيق الجوال دون إعادة بناء.

Versioning:
- Current: v1 (stable)
- Prefix: /api/v1
- Deprecation: via Sunset header + warning in response
"""

from functools import wraps

from flask import Blueprint, jsonify

# API Version constants
API_VERSION: str = "v1"
API_VERSIONS: list[str] = ["v1"]
DEFAULT_VERSION: str = "v1"
DEPRECATED_VERSIONS: list[str] = []


def api_version_required(f):
    """Decorator to validate API version and add deprecation headers."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        version = kwargs.get("version", API_VERSION)
        if version in DEPRECATED_VERSIONS:
            from flask import current_app

            current_app.logger.warning("Deprecated API version used: %s", version)
        return f(*args, **kwargs)

    return wrapper


def create_api_blueprint(version: str = API_VERSION) -> Blueprint:
    """Create API blueprint with version prefix."""
    if version not in API_VERSIONS:
        raise ValueError(f"Unsupported API version: {version}")
    bp = Blueprint(f"api_{version}", __name__, url_prefix=f"/api/{version}")
    return bp


# Main v1 blueprint
bp = create_api_blueprint(API_VERSION)


@bp.get("/health")
@api_version_required
def api_health():
    response = jsonify(status="ok", api=API_VERSION, app="azad-e-school")
    # Add version headers
    response.headers["X-API-Version"] = API_VERSION
    response.headers["X-API-Versions"] = ",".join(API_VERSIONS)
    return response


@bp.get("/version")
def api_version():
    """Get current API version info."""
    return jsonify(
        current=API_VERSION,
        supported=API_VERSIONS,
        deprecated=DEPRECATED_VERSIONS,
        default=DEFAULT_VERSION,
    )


# Version negotiation helper
def negotiate_api_version(req) -> str:
    """
    Negotiate API version from:
    1. URL path (/api/v1/...)
    2. Accept header (application/vnd.azad.v1+json)
    3. Custom header (X-API-Version)
    4. Default to latest stable
    """
    # Check URL path version
    path_version = None
    if req.path.startswith("/api/"):
        parts = req.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "api" and parts[1] in API_VERSIONS:
            path_version = parts[1]

    # Check Accept header
    accept_version = None
    accept = req.headers.get("Accept", "")
    if "application/vnd.azad." in accept:
        try:
            accept_version = accept.split("application/vnd.azad.")[1].split("+")[0]
        except Exception:
            pass

    # Check custom header
    header_version = req.headers.get("X-API-Version")

    # Priority: URL path > Accept header > X-API-Version header > default
    version = path_version or accept_version or header_version or DEFAULT_VERSION

    if version not in API_VERSIONS:
        version = DEFAULT_VERSION

    return version
