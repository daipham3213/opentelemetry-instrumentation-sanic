"""Unit tests for :class:`._span.SpanRecorder`.

These drive the recorder against a real tracer feeding an in-memory exporter
(the ``tracer`` / ``span_exporter`` fixtures) so the produced span can be
inspected without any HTTP machinery.
"""

from __future__ import annotations

import pytest
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_REQUEST_METHOD,
    HTTP_RESPONSE_STATUS_CODE,
)
from opentelemetry.trace import SpanKind
from opentelemetry.trace.status import StatusCode

from opentelemetry.instrumentation.sanic._span import SpanRecorder
from opentelemetry.instrumentation.sanic.exceptions import (
    RequestAttributeError,
)


def test_start_then_finish_exports_one_server_span(
    span_exporter, tracer, make_request, make_response
) -> None:
    recorder = SpanRecorder(tracer)

    active = recorder.start(make_request())
    assert active.span.is_recording()
    # Nothing is exported until the span ends.
    assert span_exporter.get_finished_spans() == ()

    recorder.finish(active, make_response(status=200))

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.kind is SpanKind.SERVER
    assert span.name.startswith("GET /hello/<name")
    assert span.attributes[HTTP_REQUEST_METHOD] == "GET"
    assert span.attributes[HTTP_RESPONSE_STATUS_CODE] == 200
    assert span.status.status_code is StatusCode.UNSET


def test_finish_marks_server_error(
    span_exporter, tracer, make_request, make_response
) -> None:
    recorder = SpanRecorder(tracer)

    active = recorder.start(make_request())
    recorder.finish(active, make_response(status=500))

    span = span_exporter.get_finished_spans()[0]
    assert span.attributes[HTTP_RESPONSE_STATUS_CODE] == 500
    assert span.status.status_code is StatusCode.ERROR


def test_finish_with_none_is_a_noop(
    span_exporter, tracer, make_response
) -> None:
    SpanRecorder(tracer).finish(None, make_response())
    assert span_exporter.get_finished_spans() == ()


def test_start_rejects_non_request(tracer) -> None:
    with pytest.raises(RequestAttributeError):
        SpanRecorder(tracer).start(object())
