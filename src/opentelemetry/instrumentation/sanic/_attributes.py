"""Translate a Sanic request/response into OpenTelemetry span data.

Kept deliberately free of any tracing side effects: every function here is
pure, which makes the attribute logic trivial to unit-test in isolation from
the span lifecycle.

Attribute keys come from the **stable** OpenTelemetry semantic-convention
modules (:mod:`opentelemetry.semconv.attributes`), which replaced the
deprecated ``opentelemetry.semconv.trace.SpanAttributes`` class in
semantic-conventions 1.25.0.
"""

from __future__ import annotations

from typing import Any

from opentelemetry.semconv.attributes.client_attributes import CLIENT_ADDRESS
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_REQUEST_METHOD,
    HTTP_RESPONSE_STATUS_CODE,
    HTTP_ROUTE,
)
from opentelemetry.semconv.attributes.server_attributes import (
    SERVER_ADDRESS,
    SERVER_PORT,
)
from opentelemetry.semconv.attributes.url_attributes import (
    URL_FULL,
    URL_PATH,
    URL_QUERY,
    URL_SCHEME,
)
from opentelemetry.semconv.attributes.user_agent_attributes import (
    USER_AGENT_ORIGINAL,
)
from opentelemetry.trace import SpanKind
from opentelemetry.trace.status import StatusCode

from .exceptions import RequestAttributeError

__all__ = [
    "HTTP_RESPONSE_STATUS_CODE",
    "SERVER_SPAN_KIND",
    "collect_request_attributes",
    "span_name_for",
    "status_code_to_status",
]

#: Sanic handles inbound HTTP requests, so its root span is always a server span.
SERVER_SPAN_KIND: SpanKind = SpanKind.SERVER


def span_name_for(request: Any) -> str:
    """Build a low-cardinality span name from a request.

    Follows the HTTP semantic-convention span-name recipe ``{method} {route}``,
    preferring the matched route template (e.g. ``GET /users/<id>``) so that
    span names stay bounded, and falling back to the bare HTTP method when no
    route information is available.

    :param request: A Sanic ``Request`` instance.
    :returns: A human-readable, low-cardinality span name.
    :raises RequestAttributeError: If *request* exposes no ``method`` attribute.
    """
    method = getattr(request, "method", None)
    if method is None:
        raise RequestAttributeError(
            "Object passed to span_name_for is not a Sanic request (missing 'method')."
        )
    route = getattr(request, "uri_template", None) or getattr(request, "path", None)
    return f"{method} {route}" if route else str(method)


def collect_request_attributes(request: Any) -> dict[str, Any]:
    """Derive HTTP semantic-convention span attributes from a request.

    Only attributes that are actually present on the request are emitted; the
    function never raises on a *missing* individual field, keeping tracing
    resilient to Sanic version differences.

    :param request: A Sanic ``Request`` instance.
    :returns: A mapping of stable semantic-convention attribute keys to values,
        suitable for ``span.set_attributes``.
    :raises RequestAttributeError: If *request* does not look like a Sanic
        request at all (no ``method``).
    """
    if getattr(request, "method", None) is None:
        raise RequestAttributeError(
            "Object passed to collect_request_attributes is not a Sanic request "
            "(missing 'method')."
        )

    server_address, server_port = _server_address_and_port(request)

    # (attribute key, source value) pairs; empty values are dropped below.
    candidates: dict[str, Any] = {
        HTTP_REQUEST_METHOD: getattr(request, "method", None),
        URL_SCHEME: getattr(request, "scheme", None),
        URL_PATH: getattr(request, "path", None),
        URL_QUERY: getattr(request, "query_string", None),
        URL_FULL: getattr(request, "url", None),
        HTTP_ROUTE: getattr(request, "uri_template", None),
        SERVER_ADDRESS: server_address,
        SERVER_PORT: server_port,
        CLIENT_ADDRESS: getattr(request, "remote_addr", None) or None,
    }

    user_agent = _header(request, "user-agent")
    if user_agent is not None:
        candidates[USER_AGENT_ORIGINAL] = user_agent

    return {key: value for key, value in candidates.items() if value not in (None, "")}


def status_code_to_status(status_code: int) -> StatusCode:
    """Map an HTTP status code to an OpenTelemetry span status.

    Follows the specification for *server* spans: only 5xx (and malformed
    codes) are reported as errors; everything else is left ``UNSET``.

    :param status_code: The numeric HTTP response status code.
    :returns: The corresponding :class:`~opentelemetry.trace.status.StatusCode`.
    """
    if status_code < 100 or status_code >= 500:
        return StatusCode.ERROR
    return StatusCode.UNSET


def _server_address_and_port(request: Any) -> tuple[str | None, int | None]:
    """Split a request's ``Host`` into ``server.address`` and ``server.port``.

    :param request: A Sanic ``Request`` instance.
    :returns: A ``(address, port)`` tuple; either element may be ``None`` when
        the corresponding piece of information is unavailable.
    """
    host = getattr(request, "host", None)
    if not host:
        return None, None
    address, _, port = host.partition(":")
    port_number = int(port) if port.isdigit() else None
    return (address or None), port_number


def _header(request: Any, name: str) -> str | None:
    """Safely read a single request header, returning ``None`` if absent."""
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    return value if value else None
