"""AZ-PH5: Lightweight Prometheus-compatible metrics exposition.

Collects request latency, HTTP status counters, DB transaction/error
counters and wallet volume counters in-process. Exposed via ``/metrics``
protected by admin/token auth. No raw PII is recorded.
"""

from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()

# Counters: name -> {labels_tuple: value}
_counters: dict[str, dict[tuple, int]] = defaultdict(lambda: defaultdict(int))
# Histograms: name -> list of observed values (bounded ring)
_histograms: dict[str, list[float]] = defaultdict(list)
_HIST_MAX = 10000


def inc_counter(name: str, labels: dict[str, str] | None = None, value: int = 1) -> None:
    key = tuple(sorted((labels or {}).items()))
    with _lock:
        _counters[name][key] += value


def observe_histogram(name: str, value: float, labels: dict[str, str] | None = None) -> None:
    with _lock:
        bucket = _histograms[name]
        bucket.append(float(value))
        if len(bucket) > _HIST_MAX:
            del bucket[: len(bucket) - _HIST_MAX]


def get_counter(name: str) -> dict[tuple, int]:
    with _lock:
        return dict(_counters.get(name, {}))


def get_histogram(name: str) -> list[float]:
    with _lock:
        return list(_histograms.get(name, []))


def render_prometheus() -> str:
    """Render all metrics in Prometheus text format."""
    lines: list[str] = []
    with _lock:
        for name, buckets in _counters.items():
            for labels, val in buckets.items():
                label_str = ",".join(f'{k}="{v}"' for k, v in labels)
                if label_str:
                    lines.append(f"{name}{{{label_str}}} {val}")
                else:
                    lines.append(f"{name} {val}")
        for name, vals in _histograms.items():
            if not vals:
                continue
            count = len(vals)
            total = sum(vals)
            lines.append(f"{name}_count {count}")
            lines.append(f"{name}_sum {total:.6f}")
            # simple quantiles
            s = sorted(vals)
            for q in (0.5, 0.95, 0.99):
                idx = min(len(s) - 1, int(len(s) * q))
                lines.append(f'{name}{{quantile="{q}"}} {s[idx]:.6f}')
    return "\n".join(lines) + "\n"


def record_request(method: str, path: str, status: int, duration_ms: float) -> None:
    inc_counter("http_requests_total", {"method": method, "status": str(status)})
    observe_histogram("http_request_duration_ms", duration_ms, {"method": method})


def record_db_tx(ok: bool) -> None:
    inc_counter("db_transactions_total", {"result": "ok" if ok else "error"})


def record_wallet_volume(currency: str, amount: float) -> None:
    inc_counter("wallet_volume_total", {"currency": currency})
    observe_histogram("wallet_volume_amount", amount, {"currency": currency})


def reset_metrics() -> None:
    with _lock:
        _counters.clear()
        _histograms.clear()
