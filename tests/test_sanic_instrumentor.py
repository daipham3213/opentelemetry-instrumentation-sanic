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
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.semconv._incubating.metrics.http_metrics import (
    HTTP_SERVER_ACTIVE_REQUESTS,
    HTTP_SERVER_REQUEST_BODY_SIZE,
    HTTP_SERVER_RESPONSE_BODY_SIZE,
)
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
from opentelemetry.semconv.metrics.http_metrics import (
    HTTP_SERVER_REQUEST_DURATION,
)
from opentelemetry.trace import SpanKind
from opentelemetry.trace.status import StatusCode

from opentelemetry.instrumentation.sanic import SanicInstrumentor
from opentelemetry.instrumentation.sanic._attributes import (
    active_request_attributes,
    collect_metric_attributes,
    collect_request_attributes,
    status_code_to_status,
)
from opentelemetry.instrumentation.sanic.exceptions import (
    RequestAttributeError,
)


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


@pytest.fixture()
def reader() -> InMemoryMetricReader:
    """Provide an in-memory metric reader wired to a fresh meter provider."""
    metric_reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[metric_reader])

    instrumentor = SanicInstrumentor()
    instrumentor.instrument(meter_provider=provider, excluded_urls="/health")
    try:
        yield metric_reader
    finally:
        instrumentor.uninstrument()


def _build_app(name: str):
    """Create a tiny instrumented Sanic app with a handful of routes."""
    from sanic import Sanic
    from sanic.response import json as json_response
    from sanic.response import text

    app = Sanic(name)

    @app.get("/hello/<name>")
    async def hello(request, name: str):
        return json_response({"hello": name})

    @app.post("/echo")
    async def echo(request):
        return text(request.body.decode() if request.body else "")

    @app.get("/boom")
    async def boom(request):
        return text("kaboom", status=500)

    @app.get("/health")
    async def health(request):
        return json_response({"status": "ok"})

    return app


def _metrics_by_name(reader: InMemoryMetricReader) -> dict:
    """Flatten the reader's collected metrics into a ``{name: metric}`` map."""
    collected = {}
    data = reader.get_metrics_data()
    if data is None:  # nothing was recorded at all
        return collected
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                collected[metric.name] = metric
    return collected


def _point_for_route(metric, route_prefix: str):
    """Return the first data point whose ``http.route`` starts with a prefix."""
    for point in metric.data.data_points:
        route = point.attributes.get(HTTP_ROUTE, "")
        if route.startswith(route_prefix):
            return point
    return None


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


class _StubRequest:
    """Minimal stand-in exposing the attributes the metric helpers read."""

    method = "POST"
    scheme = "https"
    version = "1.1"
    uri_template = "/items/<id>"


def test_active_request_attributes_are_the_low_cardinality_subset() -> None:
    assert active_request_attributes(_StubRequest()) == {
        HTTP_REQUEST_METHOD: "POST",
        URL_SCHEME: "https",
    }


def test_collect_metric_attributes_marks_server_errors() -> None:
    attrs = collect_metric_attributes(_StubRequest(), 503)
    assert attrs[HTTP_REQUEST_METHOD] == "POST"
    assert attrs[URL_SCHEME] == "https"
    assert attrs[HTTP_ROUTE] == "/items/<id>"
    assert attrs[NETWORK_PROTOCOL_VERSION] == "1.1"
    assert attrs[HTTP_RESPONSE_STATUS_CODE] == 503
    assert attrs[ERROR_TYPE] == "503"


def test_collect_metric_attributes_omits_error_type_for_success() -> None:
    attrs = collect_metric_attributes(_StubRequest(), 200)
    assert attrs[HTTP_RESPONSE_STATUS_CODE] == 200
    assert ERROR_TYPE not in attrs


# --------------------------------------------------------------------------- #
# Metrics                                                                      #
# --------------------------------------------------------------------------- #
async def test_request_records_duration_histogram(
    reader: InMemoryMetricReader,
) -> None:
    app = _build_app("duration-app")

    await app.asgi_client.get("/hello/world")

    metrics = _metrics_by_name(reader)
    duration = metrics[HTTP_SERVER_REQUEST_DURATION]
    assert duration.unit == "s"

    point = _point_for_route(duration, "/hello/<name")
    assert point is not None
    assert point.count == 1
    assert point.attributes[HTTP_REQUEST_METHOD] == "GET"
    assert point.attributes[HTTP_RESPONSE_STATUS_CODE] == 200
    assert point.attributes[URL_SCHEME] in ("http", "https")
    assert NETWORK_PROTOCOL_VERSION in point.attributes
    assert ERROR_TYPE not in point.attributes


async def test_active_requests_balances_to_zero(
    reader: InMemoryMetricReader,
) -> None:
    app = _build_app("active-app")

    await app.asgi_client.get("/hello/world")

    metrics = _metrics_by_name(reader)
    active = metrics[HTTP_SERVER_ACTIVE_REQUESTS]
    assert active.unit == "{request}"
    # Incremented on start and decremented on completion -> nets to zero.
    assert all(point.value == 0 for point in active.data.data_points)


async def test_server_error_sets_error_type(
    reader: InMemoryMetricReader,
) -> None:
    app = _build_app("error-app")

    _, response = await app.asgi_client.get("/boom")
    assert response.status_code == 500

    duration = _metrics_by_name(reader)[HTTP_SERVER_REQUEST_DURATION]
    point = _point_for_route(duration, "/boom")
    assert point is not None
    assert point.attributes[HTTP_RESPONSE_STATUS_CODE] == 500
    assert point.attributes[ERROR_TYPE] == "500"


async def test_body_size_histograms_recorded(
    reader: InMemoryMetricReader,
) -> None:
    app = _build_app("body-app")
    payload = "payload-body"

    await app.asgi_client.post("/echo", data=payload)

    metrics = _metrics_by_name(reader)

    request_size = metrics[HTTP_SERVER_REQUEST_BODY_SIZE]
    req_point = _point_for_route(request_size, "/echo")
    assert req_point is not None
    assert req_point.sum == len(payload)

    response_size = metrics[HTTP_SERVER_RESPONSE_BODY_SIZE]
    resp_point = _point_for_route(response_size, "/echo")
    assert resp_point is not None
    assert resp_point.sum == len(payload)


async def test_bodyless_request_records_no_request_body_size(
    reader: InMemoryMetricReader,
) -> None:
    app = _build_app("no-body-app")

    await app.asgi_client.get("/hello/world")

    metrics = _metrics_by_name(reader)
    # A bodyless GET must not emit a request-body-size measurement at all.
    assert HTTP_SERVER_REQUEST_BODY_SIZE not in metrics


async def test_excluded_url_records_no_metrics(
    reader: InMemoryMetricReader,
) -> None:
    app = _build_app("excluded-metrics-app")

    _, response = await app.asgi_client.get("/health")
    assert response.status_code == 200

    duration = _metrics_by_name(reader).get(HTTP_SERVER_REQUEST_DURATION)
    # No duration instrument data points for the excluded route.
    points = [] if duration is None else list(duration.data.data_points)
    assert all(
        not point.attributes.get(HTTP_ROUTE, "").startswith("/health")
        for point in points
    )
