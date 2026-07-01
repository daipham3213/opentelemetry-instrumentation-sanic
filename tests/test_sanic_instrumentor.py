"""Skeletal test suite for the Sanic OpenTelemetry instrumentation.

Covers:

* the happy path — a normal request produces one well-formed server span;
* an edge case — an excluded URL produces no span at all;
* a unit-level edge case for the pure attribute/status helpers.

The tests use Sanic's built-in ``asgi_client`` (via ``app.test_client``) so no
real network sockets are involved, and an in-memory span exporter so no
collector is required.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_REQUEST_METHOD,
    HTTP_RESPONSE_STATUS_CODE,
    HTTP_ROUTE,
)
from opentelemetry.trace import SpanKind
from opentelemetry.trace.status import StatusCode

from opentelemetry.instrumentation.sanic import SanicInstrumentor
from opentelemetry.instrumentation.sanic._attributes import (
    collect_request_attributes,
    status_code_to_status,
)
from opentelemetry.instrumentation.sanic.exceptions import RequestAttributeError


@pytest.fixture()
def exporter() -> InMemorySpanExporter:
    """Provide an isolated in-memory exporter wired to a fresh provider."""
    memory_exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory_exporter))

    instrumentor = SanicInstrumentor()
    instrumentor.instrument(tracer_provider=provider, excluded_urls="/health")
    try:
        yield memory_exporter
    finally:
        instrumentor.uninstrument()
        memory_exporter.clear()


def _build_app(name: str):
    """Create a tiny instrumented Sanic app with two routes."""
    from sanic import Sanic
    from sanic.response import json as json_response

    app = Sanic(name)

    @app.get("/hello/<name>")
    async def hello(request, name: str):
        return json_response({"hello": name})

    @app.get("/health")
    async def health(request):
        return json_response({"status": "ok"})

    return app


# --------------------------------------------------------------------------- #
# Happy path                                                                   #
# --------------------------------------------------------------------------- #
async def test_traced_request_produces_server_span(
    exporter: InMemorySpanExporter,
) -> None:
    app = _build_app("happy-app")

    _, response = await app.asgi_client.get("/hello/world")

    assert response.status_code == 200
    spans = exporter.get_finished_spans()
    assert len(spans) == 1

    span = spans[0]
    assert span.kind is SpanKind.SERVER
    assert span.attributes[HTTP_REQUEST_METHOD] == "GET"
    assert span.attributes[HTTP_RESPONSE_STATUS_CODE] == 200
    # Route template is low-cardinality; exact param syntax varies by Sanic
    # version (e.g. "/hello/<name>" vs "/hello/<name:str>").
    assert span.attributes[HTTP_ROUTE].startswith("/hello/<name")
    assert span.name.startswith("GET /hello/<name")
    assert span.status.status_code is StatusCode.UNSET


# --------------------------------------------------------------------------- #
# Edge case: excluded URLs are not traced                                      #
# --------------------------------------------------------------------------- #
async def test_excluded_url_produces_no_span(
    exporter: InMemorySpanExporter,
) -> None:
    app = _build_app("excluded-app")

    _, response = await app.asgi_client.get("/health")

    assert response.status_code == 200
    assert exporter.get_finished_spans() == ()


# --------------------------------------------------------------------------- #
# Unit-level edge cases for the pure helpers                                   #
# --------------------------------------------------------------------------- #
def test_status_code_to_status_mapping() -> None:
    assert status_code_to_status(200) is StatusCode.UNSET
    assert (
        status_code_to_status(404) is StatusCode.UNSET
    )  # client error, not span error
    assert status_code_to_status(500) is StatusCode.ERROR
    assert status_code_to_status(0) is StatusCode.ERROR  # malformed


def test_collect_request_attributes_rejects_non_request() -> None:
    with pytest.raises(RequestAttributeError):
        collect_request_attributes(object())
