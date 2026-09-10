"""Secret-free diagnostics for provider and connection failures."""

from __future__ import annotations


def sanitize_provider_exception(exc: BaseException) -> str:
    """Describe a provider/connection failure without echoing exception text.

    Provider SDKs commonly embed request URLs that carry userinfo, query tokens,
    or path credentials. Logs, tool JSON, and durable trail metadata must never
    repeat that text. Preserve the exception type and HTTP status when present
    so operators still see a useful error category.
    """
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    original = getattr(exc, "original_exception", None)
    if status is None and original is not None:
        status = getattr(original, "status_code", None)
    if status is not None:
        return f"{name} (HTTP {status})"
    return name
