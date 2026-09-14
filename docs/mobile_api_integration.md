# دليل تكامل واجهة الجوال — Mobile API Integration Guide

منصة مدرسة أزاد الإلكترونية — v2.0

هذا الدليل موجّه لمطوّري تطبيق الجوال (Android/iOS/Flutter) للتكامل مع واجهات REST الخاصة بالمنصة.

## 1. الأساسيات

- **Base URL:** `https://<domain>/api/v1/`
- **الصيغة:** JSON في الطلب والاستجابة (يُقبل أيضاً `application/x-www-form-urlencoded` على `/auth/token`).
- **OpenAPI / Swagger:** المواصفات الحيّة متاحة على:
  - `/api/v1/openapi.json` — مواصفة OpenAPI كاملة.
  - `/api/v1/docs/` — واجهة Swagger UI التفاعلية.
  - `/api/v1/apispec.json` — مواصفة Flasgger المجمّعة.

## 2. المصادقة — Session أو Bearer Token

الواجهات تقبل أسلوبين متكافئين:

### أ) Bearer Token (للتطبيق)
```http
POST /api/v1/auth/token
Content-Type: application/json

{"email": "user@example.com", "password": "secret"}
```
الاستجابة:
```json
{
  "data": {"token": "<JWT-like PAT>", "token_type": "Bearer", "expires_in": 2592000},
  "meta": {"version": "v1", "request_id": "..."}
}
```
ثم أرسل التوكن مع كل طلب:
```http
Authorization: Bearer <token>
```
التوكن موقّع بـ itsdangerous (نفس SECRET_KEY) وصلاحيته 30 يوماً.

### ب) Session Cookie (للمتصفح)
تسجيل الدخول عبر `/auth/login` يعيد كوكي الجلسة؛ نفس الواجهات تعمل مباشرة.

> **CSRF:** طلبات المتصفح (Session) ترسل رمز الحماية في ترويسة `X-CSRFToken`.
> طلبات Bearer لا تحتاج CSRF — الترويسة مسموحة ضمن `CORS_ALLOW_HEADERS` لكنها غير مطلوبة للتوكنات.

## 3. CORS

المنصة تسمح لعملاء الجوال بالوصول المباشر عبر `flask-cors`:
- `origins`: حسب إعداد `CORS_ORIGINS` (فارغ = نفس الأصل).
- `supports_credentials`: `true` للجلسات.
- `allow_headers`: `Content-Type`, `X-CSRFToken`, `Authorization`.

## 4. الواجهات المتاحة

| Endpoint | الطريقة | الوصف | الصلاحيات |
|---|---|---|---|
| `/api/v1/auth/token` | POST | إصدار Bearer token | عام |
| `/api/v1/me` | GET | بيانات المستخدم الحالي | مُصادق |
| `/api/v1/schools` | GET | قائمة المدارس | مُصادق |
| `/api/v1/lessons` | GET | قائمة الدروس المتاحة | مُصادق |
| `/api/v1/lessons/<id>` | GET | درس محدد | عضو الصف / إدارة المدرسة |
| `/api/v1/classes` | GET | قائمة الصفوف | مُصادق |
| `/api/v1/users` | GET | قائمة المستخدمين | مشرفون فقط |
| `/api/v1/search?q=` | GET | بحث عالمي (≥ حرفين) | مُصادق |
| `/api/health` | GET | فحص صحة مُبسّط | عام |

الترقيم: `?page=1&per_page=20` — الاستجابة تبدو `{"data": [...], "meta": {"page": 1, "per_page": 20, "pages": N, "total": M}}`.

## 5. شكل الاستجابة الموحّد

نجاح:
```json
{"data": {...}, "meta": {"version": "v1", "request_id": "corr-id"}}
```
خطأ:
```json
{"error": {"code": "FORBIDDEN", "message": "غير مصرح بالوصول", "details": {}}, "meta": {"version": "v1", "request_id": "corr-id"}}
```

| HTTP | code | السبب |
|---|---|---|
| 400 | `VALIDATION_ERROR` / `QUERY_TOO_SHORT` | مدخلات ناقصة |
| 401 | `UNAUTHORIZED` | لا توكن / توكن منتهٍ |
| 403 | `FORBIDDEN` | صلاحيات غير كافية أو خارج نطاق المدرسة |
| 404 | `NOT_FOUND` | المورد غير موجود |
| 429 | `RATE_LIMITED` | تجاوز حد الطلبات |
| 500 | `INTERNAL_ERROR` | خطأ داخلي |

## 6. عيّنات

```bash
# إصدار توكن
curl -X POST https://school.example/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"email":"s@x.test","password":"pw"}'

# قائمة الدروس
curl https://school.example/api/v1/lessons?page=1 \
  -H "Authorization: Bearer $TOKEN"
```
