"""Shared pytest fixtures for the Sanic instrumentation test suite.

The fixtures fall into three groups:

* **SDK plumbing** — in-memory span exporters and metric readers wired to
  fresh, isolated providers, plus the ``tracer``/``meter`` built from them, so
  recorder tests never need a collector or network sockets.
* **Test doubles** — ``make_request`` / ``make_response`` factories that build
  duck-typed stand-ins exposing exactly the fields the code reads.
* **Assertion helpers** — ``metrics_by_name`` / ``point_for_route`` for
  navigating the metric data model.

The factories and helpers are exposed as fixtures returning callables so tests
stay independent (each ``make_request()`` call yields a fresh object with its
own ``ctx``) without importing across test modules.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.semconv.attributes.http_attributes import HTTP_ROUTE


# --------------------------------------------------------------------------- #
# SDK plumbing                                                                 #
# --------------------------------------------------------------------------- #
@pytest.fixture
def span_exporter() -> InMemorySpanExporter:
    """An isolated in-memory span exporter."""
    return InMemorySpanExporter()


@pytest.fixture
def tracer_provider(span_exporter: InMemorySpanExporter) -> TracerProvider:
    """A tracer provider that exports synchronously to ``span_exporter``."""
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    return provider


@pytest.fixture
def tracer(tracer_provider: TracerProvider):
    """A tracer drawn from ``tracer_provider``."""
    return tracer_provider.get_tracer("test")


@pytest.fixture
def metric_reader() -> InMemoryMetricReader:
    """An isolated in-memory metric reader."""
    return InMemoryMetricReader()


@pytest.fixture
def meter_provider(metric_reader: InMemoryMetricReader) -> MeterProvider:
    """A meter provider wired to ``metric_reader``."""
    return MeterProvider(metric_readers=[metric_reader])


@pytest.fixture
def meter(meter_provider: MeterProvider):
    """A meter drawn from ``meter_provider``."""
    return meter_provider.get_meter("test")


# --------------------------------------------------------------------------- #
# Test doubles                                                                 #
# --------------------------------------------------------------------------- #
@pytest.fixture
def make_request() -> Callable[..., SimpleNamespace]:
    """Return a factory building duck-typed Sanic-request stand-ins.

    Every call produces a fresh object (with its own ``ctx``); keyword
    arguments override the sensible defaults for a ``GET /hello/world``.
    """

    def _make(**overrides: Any) -> SimpleNamespace:
        data: dict[str, Any] = {
            "method": "GET",
            "scheme": "http",
            "path": "/hello/world",
            "query_string": "",
            "url": "http://testserver/hello/world",
            "uri_template": "/hello/<name>",
            "host": "testserver:8000",
            "remote_addr": "127.0.0.1",
            "version": "1.1",
            "headers": {"user-agent": "pytest-agent"},
            "body": b"",
        }
        data.update(overrides)
        request = SimpleNamespace(**data)
        request.ctx = SimpleNamespace()
        return request

    return _make


@pytest.fixture
def make_response() -> Callable[..., SimpleNamespace]:
    """Return a factory building duck-typed Sanic-response stand-ins."""

    def _make(**overrides: Any) -> SimpleNamespace:
        data: dict[str, Any] = {"status": 200, "body": b""}
        data.update(overrides)
        return SimpleNamespace(**data)

    return _make


# --------------------------------------------------------------------------- #
# Assertion helpers                                                            #
# --------------------------------------------------------------------------- #
@pytest.fixture
def metrics_by_name() -> Callable[[InMemoryMetricReader], dict[str, Any]]:
    """Return a helper flattening a reader's metrics into ``{name: metric}``."""

    def _collect(reader: InMemoryMetricReader) -> dict[str, Any]:
        collected: dict[str, Any] = {}
        data = reader.get_metrics_data()
        if data is None:  # nothing was recorded at all
            return collected
        for resource_metrics in data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    collected[metric.name] = metric
        return collected

    return _collect


@pytest.fixture
def point_for_route() -> Callable[[Any, str], Any]:
    """Return a helper finding the first data point for an ``http.route``."""

    def _find(metric: Any, route_prefix: str) -> Any:
        for point in metric.data.data_points:
            route = point.attributes.get(HTTP_ROUTE, "")
            if route.startswith(route_prefix):
                return point
        return None

    return _find
