"""Assemble OpenTelemetry *metric* attributes from a Sanic request.

The HTTP metric conventions are deliberately stricter about cardinality than
the span conventions, so metric attributes are built here rather than reusing
the span attributes wholesale:

* :func:`active_request_attributes` — the low-cardinality subset (method and
  scheme only) shared by the increment and decrement of the active-requests
  counter, so that counter always balances back to zero;
* :func:`collect_metric_attributes` — the fuller set used for the duration and
  body-size histograms, adding route, protocol version, response status, and
  ``error.type`` for server errors.

Every function is pure and reads the request only through :mod:`._request`.
"""

from __future__ import annotations

from typing import Any

from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_REQUEST_METHOD,
    HTTP_RESPONSE_STATUS_CODE,
    HTTP_ROUTE,
)
from opentelemetry.semconv.attributes.network_attributes import (
    NETWORK_PROTOCOL_VERSION,
)
from opentelemetry.semconv.attributes.url_attributes import URL_SCHEME
from opentelemetry.trace.status import StatusCode

from . import _request
from ._span_attributes import status_code_to_status

__all__ = [
    "active_request_attributes",
    "collect_metric_attributes",
]


def active_request_attributes(request: Any) -> dict[str, Any]:
    """Low-cardinality attributes for the active-requests up-down counter.

    ``http.server.active_requests`` is incremented on request *start* and
    decremented on request *end*, so its attributes must be knowable at start
    time and identical across the pair — otherwise the counter never returns to
    zero. Per the HTTP metric conventions that means the request method and URL
    scheme only.

    :param request: A Sanic ``Request`` instance.
    :returns: A mapping of stable semantic-convention keys to values.
    """
    candidates = (
        (HTTP_REQUEST_METHOD, _request.method(request)),
        (URL_SCHEME, _request.scheme(request)),
    )
    return {key: val for key, val in candidates if val not in (None, "")}


def collect_metric_attributes(
    request: Any, status_code: int | None
) -> dict[str, Any]:
    """Attributes for the request-duration and body-size histograms.

    Extends :func:`active_request_attributes` with the response-dependent
    dimensions: the matched route, negotiated protocol version, response status
    code, and — for server errors — ``error.type`` (mirroring the span-status
    mapping in :func:`._span_attributes.status_code_to_status`).

    :param request: A Sanic ``Request`` instance.
    :param status_code: The numeric response status, or ``None`` if unknown.
    :returns: A mapping of stable semantic-convention keys to values.
    """
    attributes = active_request_attributes(request)

    route = _request.route(request)
    if route:
        attributes[HTTP_ROUTE] = route

    version = _request.protocol_version(request)
    if version:
        attributes[NETWORK_PROTOCOL_VERSION] = version

    if isinstance(status_code, int):
        attributes[HTTP_RESPONSE_STATUS_CODE] = status_code
        if status_code_to_status(status_code) is StatusCode.ERROR:
            attributes[ERROR_TYPE] = str(status_code)

    return attributes
