"""Anti-corruption layer over Sanic's request and response objects.

Sanic exposes a rich request/response API that shifts subtly between releases,
so the rest of this package never touches those objects directly. Every field
access is funnelled through the small, defensive readers defined here, which
return plain, typed Python values (or ``None`` when a field is absent or
empty).

Confining the ``Any`` typing and ``getattr`` calls to this one module keeps the
attribute- and telemetry-building code strongly typed and trivial to test, and
means Sanic version differences only ever need to be reconciled in one place.
No function here raises for a *missing* field; that resilience is the whole
point of the layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "header",
    "headers",
    "method",
    "path",
    "protocol_version",
    "query_string",
    "remote_address",
    "request_body_size",
    "response_body_size",
    "response_status",
    "route",
    "scheme",
    "server_address_and_port",
    "url",
    "user_agent",
]


def method(request: Any) -> str | None:
    """Return the HTTP request method (e.g. ``GET``), or ``None`` if absent."""
    return getattr(request, "method", None)


def scheme(request: Any) -> str | None:
    """Return the URL scheme (``http``/``https``), or ``None``."""
    return getattr(request, "scheme", None)


def path(request: Any) -> str | None:
    """Return the request path, or ``None``."""
    return getattr(request, "path", None)


def query_string(request: Any) -> str | None:
    """Return the raw query string, or ``None``."""
    return getattr(request, "query_string", None)


def url(request: Any) -> str | None:
    """Return the full request URL, or ``None``."""
    return getattr(request, "url", None)


def route(request: Any) -> str | None:
    """Return the matched, low-cardinality route template, or ``None``.

    Sanic exposes this as ``uri_template`` (e.g. ``/users/<id>``).
    """
    return getattr(request, "uri_template", None)


def remote_address(request: Any) -> str | None:
    """Return the client address, or ``None`` when unavailable or empty."""
    return getattr(request, "remote_addr", None) or None


def protocol_version(request: Any) -> str | None:
    """Return the negotiated HTTP protocol version as a string, or ``None``."""
    version = getattr(request, "version", None)
    return str(version) if version else None


def headers(request: Any) -> Mapping[str, str]:
    """Return the request headers mapping, or an empty mapping if absent.

    :param request: The Sanic request.
    :returns: The request's headers mapping, or an empty ``dict`` so callers
        (including context propagation) can treat the result uniformly.
    """
    return getattr(request, "headers", None) or {}


def header(request: Any, name: str) -> str | None:
    """Return a single request header by *name*, or ``None`` if absent.

    :param request: The Sanic request.
    :param name: The (case-insensitive) header name to read.
    :returns: The header value, or ``None`` when it is missing or empty.
    """
    value = headers(request).get(name)
    return value if value else None


def user_agent(request: Any) -> str | None:
    """Return the ``User-Agent`` header, or ``None``."""
    return header(request, "user-agent")


def server_address_and_port(request: Any) -> tuple[str | None, int | None]:
    """Split the request ``Host`` into ``(server.address, server.port)``.

    :param request: The Sanic request.
    :returns: An ``(address, port)`` tuple; either element may be ``None`` when
        the corresponding piece of information is unavailable or malformed.
    """
    host = getattr(request, "host", None)
    if not host:
        return None, None
    address, _, port = host.partition(":")
    port_number = int(port) if port.isdigit() else None
    return (address or None), port_number


def request_body_size(request: Any) -> int | None:
    """Best-effort size in bytes of the request payload body.

    Prefers the ``Content-Length`` header (cheap and correct for the common
    case), falling back to the length of any buffered body.

    :param request: The Sanic request.
    :returns: The body size in bytes, or ``None`` when unknown or zero — so
        that body-less requests are not recorded.
    """
    content_length = header(request, "content-length")
    if content_length is not None:
        try:
            return int(content_length) or None
        except ValueError:
            return None
    body = getattr(request, "body", None) or b""
    try:
        return len(body) or None
    except TypeError:  # pragma: no cover - non-sized body object
        return None


def response_body_size(response: Any) -> int | None:
    """Best-effort size in bytes of the response payload body.

    :param response: The Sanic response.
    :returns: The body size in bytes, or ``None`` when empty or unknown.
    """
    body = getattr(response, "body", None)
    if not body:
        return None
    try:
        return len(body)
    except TypeError:  # pragma: no cover - non-sized body object
        return None


def response_status(response: Any) -> int | None:
    """Return the numeric response status code, or ``None`` if not an integer.

    :param response: The Sanic response.
    :returns: The status code as an ``int``, or ``None`` when the response
        exposes no integer ``status``.
    """
    status = getattr(response, "status", None)
    return status if isinstance(status, int) else None
