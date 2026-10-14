"""Secret-free diagnostics for provider and connection failures."""

from __future__ import annotations

_MIN_HTTP_STATUS = 100
_MAX_HTTP_STATUS = 599


def _safe_http_status(status: object) -> int | None:
    """Return a real HTTP status integer, else None.

    Booleans are int subclasses and must not be treated as codes. String
    statuses can carry secrets (``401?api_key=...``) and must never be
    interpolated.
    """
    if isinstance(status, bool) or not isinstance(status, int):
        return None
    if _MIN_HTTP_STATUS <= status <= _MAX_HTTP_STATUS:
        return status
    return None


def sanitize_provider_exception(exc: BaseException) -> str:
    """Describe a provider/connection failure without echoing exception text.

    Provider SDKs commonly embed request URLs that carry userinfo, query tokens,
    or path credentials. Logs, tool JSON, and durable trail metadata must never
    repeat that text. Preserve the exception type and a bounded integer HTTP
    status when present so operators still see a useful error category.
    """
    name = type(exc).__name__
    status = _safe_http_status(getattr(exc, "status_code", None))
    original = getattr(exc, "original_exception", None)
    if status is None and original is not None:
        status = _safe_http_status(getattr(original, "status_code", None))
    if status is not None:
        return f"{name} (HTTP {status})"
    return name
