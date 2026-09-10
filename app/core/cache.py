"""تخزين مؤقت بسيط (TTL) — Redis إن توفر، وإلا ذاكرة العملية.

P2-PERF-01: يُستخدم لإزالة استعلامات العدادات المتكررة (مثل عدادات شريط
الإدارة) عن كل طلب، بصلاحية قصيرة (60 ثانية) أو إبطال فوري بالحدث.

التصميم:
    - Redis اختياري: إن فشل الاتصال نرجع للذاكرة تلقائياً (graceful).
    - get/set/delete موحّدة لكل الواجهات.
    - آمن للاختبارات: ``cache.clear()`` يمسح كل شيء.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_TTL = 60
_MEM: dict[str, tuple[float, str]] = {}  # key -> (expires_at, payload_json)

_redis = None
_redis_checked = False


def _get_redis():
    """Redis client واحدة (اتصال خامل) أو None."""
    global _redis, _redis_checked
    if _redis_checked:
        return _redis
    _redis_checked = True
    try:
        import os

        url = os.getenv("RATELIMIT_STORAGE_URL", "memory://")
        if not url.startswith("redis"):
            return None
        import redis

        _redis = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        _redis.ping()
        logger.info("cache_backend", backend="redis")
    except Exception:  # noqa: BLE001 — أي فشل → ذاكرة
        _redis = None
        logger.info("cache_backend", backend="memory")
    return _redis


def reset_cache_backend() -> None:
    """إعادة فحص الـ backend (للاختبارات)."""
    global _redis, _redis_checked
    _redis = None
    _redis_checked = False


def get(key: str) -> Any | None:
    """قراءة قيمة من الكاش أو None."""
    r = _get_redis()
    if r is not None:
        try:
            raw = r.get(f"azad:cache:{key}")
            return json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001
            pass
    entry = _MEM.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if expires_at < time.monotonic():
        _MEM.pop(key, None)
        return None
    return json.loads(payload)


def set(key: str, value: Any, ttl: int = _DEFAULT_TTL) -> None:
    """كتابة قيمة بصلاحية زمنية بالثواني."""
    payload = json.dumps(value, default=str)
    r = _get_redis()
    if r is not None:
        try:
            r.setex(f"azad:cache:{key}", ttl, payload)
            return
        except Exception:  # noqa: BLE001
            pass
    _MEM[key] = (time.monotonic() + ttl, payload)


def delete(key: str) -> None:
    """إبطال مفتاح فوراً (event-based invalidation)."""
    r = _get_redis()
    if r is not None:
        try:
            r.delete(f"azad:cache:{key}")
        except Exception:  # noqa: BLE001
            pass
    _MEM.pop(key, None)


def clear() -> None:
    """مسح الكاش بالكامل (اختبارات/صيانة)."""
    global _redis, _redis_checked
    _MEM.clear()
    r = _get_redis()
    if r is not None:
        try:
            for k in r.scan_iter("azad:cache:*"):
                r.delete(k)
        except Exception:  # noqa: BLE001
            pass
