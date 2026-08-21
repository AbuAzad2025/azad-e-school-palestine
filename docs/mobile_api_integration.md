# Mobile App Integration Guide — Azad E-School

## Base URL
All API requests should target:
```
https://azad.school/api/v1/
```

## Authentication
- Login via `POST /api/v1/auth/login` returns a session cookie.
- Include `X-CSRFToken` header for state-changing requests.
- Alternatively, use token-based auth when enabled (future release).

## CORS
API endpoints under `/api/v1/*` are CORS-enabled. Configure your mobile
HTTP client to:
- Send credentials
- Include `Content-Type`, `X-CSRFToken`, and `Authorization` headers

## Key Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/v1/health` | Service health |
| GET    | `/api/v1/health/deep` | Health incl. DB/Redis |
| POST   | `/api/v1/auth/login` | Login |
| POST   | `/api/v1/auth/logout` | Logout |
| GET    | `/api/v1/dashboard` | User dashboard |
| GET    | `/api/v1/classes` | My classes |
| GET    | `/api/v1/classes/<id>` | Class detail |
| GET    | `/api/v1/classes/<id>/lessons` | Lessons in class |
| GET    | `/api/v1/classes/<id>/quizzes` | Quizzes in class |
| POST   | `/api/v1/classes/<id>/join` | Join class |

## OpenAPI / Swagger
Interactive docs are available at:
```
https://azad.school/api/v1/docs/
```
Raw spec:
```
https://azad.school/api/v1/openapi.json
```

## Mobile-Specific Notes
- Respect rate limits (200 req/min per user).
- Cache static assets aggressively.
- Handle offline state using `/offline` page / service worker.
- Use `Accept-Language: ar` or `en` for localized responses.

## Error Format
```json
{
  "error": "friendly message",
  "code": "ERROR_CODE"
}
```

## SDK Generation
Generate a client SDK from OpenAPI spec:
```bash
# Example with openapi-generator
openapi-generator-cli generate -i https://azad.school/api/v1/openapi.json -g dart -o azad_mobile_sdk
```