"""OpenAPI/Swagger configuration (flasgger)."""

from flasgger import Swagger

SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec_v1",
            "route": "/api/v1/apispec.json",
            "rule_filter": lambda rule: rule.rule.startswith("/api/v1/"),
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/api/v1/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api/v1/docs/",
    "title": "Azad E-School API",
    "version": "1.0.0",
    "description": """
# Azad E-School API v1

منصة مدرسة أزاد الإلكترونية — API للعمليات الأساسية

## Authentication
جميع النقاط المحمية تتطلب JWT token في header:
```
Authorization: Bearer <token>
```

## Rate Limiting
- General: 100 requests/minute
- Auth endpoints: 5 requests/minute

## Versioning
- Current: v1 (stable)
- Header: `X-API-Version: v1`
- Accept: `application/vnd.azad.v1+json`

## Error Responses
```json
{
  "error": "error_code",
  "message": "Human readable message",
  "details": {}
}
```
    """,
    "contact": {"name": "Azad E-School Team", "email": "api@azad-school.ps"},
    "license": {
        "name": "Proprietary",
    },
}

SWAGGER_TEMPLATE: dict = {
    "swagger": "2.0",
    "info": {
        "title": "Azad E-School API",
        "description": "API للعمليات الأساسية في منصة أزاد",
        "version": "1.0.0",
        "contact": {"name": "Azad E-School Team", "email": "api@azad-school.ps"},
    },
    "host": None,
    "basePath": "/api/v1",
    "schemes": ["https", "http"],
    "securityDefinitions": {
        "Bearer": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": (
                'JWT Authorization header using the Bearer scheme. Example: "Authorization: Bearer {token}"'
            ),
        }
    },
    "security": [{"Bearer": []}],
    "tags": [
        {"name": "Health", "description": "فحص صحة الخدمة"},
        {"name": "Auth", "description": "المصادقة والتسجيل"},
        {"name": "Schools", "description": "إدارة المدارس"},
        {"name": "Classes", "description": "إدارة الصفوف"},
        {"name": "Students", "description": "إدارة الطلاب"},
        {"name": "Teachers", "description": "إدارة المعلمين"},
        {"name": "Billing", "description": "الاشتراكات والفوترة"},
        {"name": "Content", "description": "المحتوى التعليمي"},
        {"name": "Tutoring", "description": "الدروس الخصوصية"},
        {"name": "Assessment", "description": "التقييم والاختبارات"},
        {"name": "Grades", "description": "الدرجات والتقارير"},
    ],
    "definitions": {
        "Error": {
            "type": "object",
            "properties": {
                "error": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                        "code": {"type": "string"},
                    },
                },
            },
        },
        "ApiResponse": {
            "type": "object",
            "properties": {
                "data": {"type": "object"},
                "meta": {
                    "type": "object",
                    "properties": {
                        "version": {"type": "string"},
                        "request_id": {"type": "string"},
                    },
                },
            },
        },
        "HealthResponse": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["ok", "degraded", "down"]},
                "api": {"type": "string"},
                "app": {"type": "string"},
            },
        },
        "VersionInfo": {
            "type": "object",
            "properties": {
                "current": {"type": "string"},
                "supported": {"type": "array", "items": {"type": "string"}},
                "deprecated": {"type": "array", "items": {"type": "string"}},
                "default": {"type": "string"},
            },
        },
        "User": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "email": {"type": "string", "format": "email"},
                "name_ar": {"type": "string"},
                "role": {"type": "string", "enum": ["super_admin", "school_admin", "teacher", "student", "parent"]},
            },
        },
        "Lesson": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "class_id": {"type": "integer"},
                "sort_order": {"type": "integer", "nullable": True},
                "is_offline_available": {"type": "boolean"},
                "created_at": {"type": "string", "format": "date-time", "nullable": True},
            },
        },
        "TutoringSession": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "student_id": {"type": "integer"},
                "tutor_id": {"type": "integer"},
                "subject": {"type": "string"},
                "status": {"type": "string"},
                "price": {"type": "number", "nullable": True},
                "currency": {"type": "string", "nullable": True},
                "scheduled_at": {"type": "string", "format": "date-time", "nullable": True},
                "duration_min": {"type": "integer", "nullable": True},
            },
        },
        "PaginatedMeta": {
            "type": "object",
            "properties": {
                "page": {"type": "integer"},
                "per_page": {"type": "integer"},
                "total": {"type": "integer"},
                "pages": {"type": "integer"},
            },
        },
    },
}


def init_swagger(app):
    """تهيئة Swagger/OpenAPI للتطبيق."""
    if not app.config.get("SWAGGER_ENABLED", True):
        return None

    # تعيين host ديناميكياً
    template = SWAGGER_TEMPLATE.copy()
    template["host"] = app.config.get("SWAGGER_HOST", None)

    swagger = Swagger(app, config=SWAGGER_CONFIG, template=template)

    # إضافة endpoint لملف OpenAPI الخام
    @app.get("/api/v1/openapi.json")
    def openapi_json():
        from flask import current_app, jsonify

        return jsonify(current_app.config.get("SWAGGER_SPEC", {}))

    return swagger
