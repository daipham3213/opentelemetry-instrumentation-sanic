"""Assemble OpenTelemetry *span* data from a Sanic request.

Every function here is pure and free of tracing side effects, reading the
request only through :mod:`._request`. That keeps the span-attribute logic
trivial to unit-test in isolation from the span lifecycle owned by
:mod:`._span`.

Attribute keys come from the **stable** semantic-convention modules
(:mod:`opentelemetry.semconv.attributes`), which replaced the deprecated
``opentelemetry.semconv.trace.SpanAttributes`` class in semantic-conventions
1.25.0.
"""

from __future__ import annotations

from typing import Any

from opentelemetry.semconv.attributes.client_attributes import CLIENT_ADDRESS
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_REQUEST_METHOD,
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

from . import _request
from .exceptions import RequestAttributeError

__all__ = [
    "SERVER_SPAN_KIND",
    "collect_request_attributes",
    "span_name_for",
    "status_code_to_status",
]

#: Sanic handles inbound HTTP requests, so its root span is always a server
#: span.
SERVER_SPAN_KIND: SpanKind = SpanKind.SERVER


def span_name_for(request: Any) -> str:
    """Build a low-cardinality span name of the form ``{method} {route}``.

    Follows the HTTP semantic-convention span-name recipe, preferring the
    matched route template (e.g. ``GET /users/<id>``) so span names stay
    bounded, then falling back to the request path, and finally to the bare
    HTTP method when no target information is available.

    :param request: A Sanic ``Request`` instance.
    :returns: A human-readable, low-cardinality span name.
    :raises RequestAttributeError: If *request* exposes no ``method``.
    """
    verb = _request.method(request)
    if verb is None:
        raise RequestAttributeError(
            "Object is not a Sanic request (missing 'method')."
        )
    target = _request.route(request) or _request.path(request)
    return f"{verb} {target}" if target else str(verb)


def collect_request_attributes(request: Any) -> dict[str, Any]:
    """Derive HTTP semantic-convention span attributes from a request.

    Only attributes that are actually present are emitted; individual missing
    fields never raise, keeping tracing resilient to Sanic version differences.

    :param request: A Sanic ``Request`` instance.
    :returns: A mapping of stable semantic-convention keys to values, suitable
        for ``span.set_attributes``.
    :raises RequestAttributeError: If *request* is not a Sanic request at all
        (no ``method``).
    """
    verb = _request.method(request)
    if verb is None:
        raise RequestAttributeError(
            "Object is not a Sanic request (missing 'method')."
        )

    address, port = _request.server_address_and_port(request)
    candidates: dict[str, Any] = {
        HTTP_REQUEST_METHOD: verb,
        URL_SCHEME: _request.scheme(request),
        URL_PATH: _request.path(request),
        URL_QUERY: _request.query_string(request),
        URL_FULL: _request.url(request),
        HTTP_ROUTE: _request.route(request),
        SERVER_ADDRESS: address,
        SERVER_PORT: port,
        CLIENT_ADDRESS: _request.remote_address(request),
        USER_AGENT_ORIGINAL: _request.user_agent(request),
    }
    return {
        key: val for key, val in candidates.items() if val not in (None, "")
    }


def status_code_to_status(status_code: int) -> StatusCode:
    """Map an HTTP status code to an OpenTelemetry span status.

    Follows the specification for *server* spans: only 5xx (and malformed
    codes) are reported as errors; everything else is left ``UNSET``.

    :param status_code: The numeric HTTP response status code.
    :returns: The corresponding
        :class:`~opentelemetry.trace.status.StatusCode`.
    """
    if status_code < 100 or status_code >= 500:
        return StatusCode.ERROR
    return StatusCode.UNSET
