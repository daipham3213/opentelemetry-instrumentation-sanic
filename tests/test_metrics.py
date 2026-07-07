"""Unit tests for :class:`._metrics.MetricsRecorder`.

These drive the recorder against a real meter feeding an in-memory reader (the
``meter`` / ``metric_reader`` fixtures), so the emitted instruments can be
inspected without any HTTP machinery.
"""

from __future__ import annotations

from opentelemetry.semconv._incubating.metrics.http_metrics import (
    HTTP_SERVER_ACTIVE_REQUESTS,
    HTTP_SERVER_REQUEST_BODY_SIZE,
    HTTP_SERVER_RESPONSE_BODY_SIZE,
)
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_RESPONSE_STATUS_CODE,
)
from opentelemetry.semconv.metrics.http_metrics import (
    HTTP_SERVER_REQUEST_DURATION,
)

from opentelemetry.instrumentation.sanic._metrics import (
    MetricsRecorder,
    RequestMeasurement,
)


def test_start_increments_active_requests(
    meter, metric_reader, metrics_by_name, make_request
) -> None:
    MetricsRecorder(meter).start(make_request())

    active = metrics_by_name(metric_reader)[HTTP_SERVER_ACTIVE_REQUESTS]
    assert active.unit == "{request}"
    # Only the start was recorded, so the counter currently reads +1.
    assert any(point.value == 1 for point in active.data.data_points)


def test_full_cycle_records_duration_and_balances_active(
    meter,
    metric_reader,
    metrics_by_name,
    point_for_route,
    make_request,
    make_response,
) -> None:
    recorder = MetricsRecorder(meter)
    request = make_request()

    measurement = recorder.start(request)
    recorder.finish(request, make_response(status=200), measurement)

    metrics = metrics_by_name(metric_reader)

    duration = metrics[HTTP_SERVER_REQUEST_DURATION]
    assert duration.unit == "s"
    point = point_for_route(duration, "/hello/<name")
    assert point is not None
    assert point.count == 1
    assert point.attributes[HTTP_RESPONSE_STATUS_CODE] == 200
    assert ERROR_TYPE not in point.attributes

    active = metrics[HTTP_SERVER_ACTIVE_REQUESTS]
    assert all(point.value == 0 for point in active.data.data_points)


def test_finish_records_body_sizes(
    meter,
    metric_reader,
    metrics_by_name,
    point_for_route,
    make_request,
    make_response,
) -> None:
    recorder = MetricsRecorder(meter)
    request = make_request(headers={"content-length": "5"}, body=b"hello")

    measurement = recorder.start(request)
    recorder.finish(request, make_response(body=b"world!"), measurement)

    metrics = metrics_by_name(metric_reader)
    request_size = point_for_route(
        metrics[HTTP_SERVER_REQUEST_BODY_SIZE], "/hello/<name"
    )
    response_size = point_for_route(
        metrics[HTTP_SERVER_RESPONSE_BODY_SIZE], "/hello/<name"
    )
    assert request_size.sum == 5
    assert response_size.sum == len(b"world!")


def test_bodyless_exchange_records_no_body_size(
    meter, metric_reader, metrics_by_name, make_request, make_response
) -> None:
    recorder = MetricsRecorder(meter)
    request = make_request(headers={}, body=b"")

    measurement = recorder.start(request)
    recorder.finish(request, make_response(body=b""), measurement)

    metrics = metrics_by_name(metric_reader)
    assert HTTP_SERVER_REQUEST_BODY_SIZE not in metrics
    assert HTTP_SERVER_RESPONSE_BODY_SIZE not in metrics


def test_server_error_sets_error_type(
    meter,
    metric_reader,
    metrics_by_name,
    point_for_route,
    make_request,
    make_response,
) -> None:
    recorder = MetricsRecorder(meter)
    request = make_request()

    measurement = recorder.start(request)
    recorder.finish(request, make_response(status=500, body=b"x"), measurement)

    point = point_for_route(
        metrics_by_name(metric_reader)[HTTP_SERVER_REQUEST_DURATION],
        "/hello/<name",
    )
    assert point.attributes[HTTP_RESPONSE_STATUS_CODE] == 500
    assert point.attributes[ERROR_TYPE] == "500"


def test_finish_with_none_measurement_is_a_noop(
    meter, metric_reader, metrics_by_name, make_request, make_response
) -> None:
    MetricsRecorder(meter).finish(make_request(), make_response(), None)
    assert HTTP_SERVER_REQUEST_DURATION not in metrics_by_name(metric_reader)


def test_start_swallows_errors_and_returns_none(meter) -> None:
    class ExplodingRequest:
        @property
        def method(self):  # test double: attribute access explodes
            raise RuntimeError("boom")

    assert MetricsRecorder(meter).start(ExplodingRequest()) is None


def test_finish_balances_active_even_when_recording_fails(
    meter, metric_reader, metrics_by_name, make_request
) -> None:
    class ExplodingResponse:
        status = 200

        @property
        def body(self):  # test double: attribute access explodes
            raise RuntimeError("boom")

    recorder = MetricsRecorder(meter)
    request = make_request(body=b"")

    measurement = recorder.start(request)
    # Reading the response body raises, but the counter must still balance.
    recorder.finish(request, ExplodingResponse(), measurement)

    active = metrics_by_name(metric_reader)[HTTP_SERVER_ACTIVE_REQUESTS]
    assert all(point.value == 0 for point in active.data.data_points)


def test_request_measurement_is_slotted() -> None:
    measurement = RequestMeasurement(start_time=1.0, active_attributes={})
    assert not hasattr(measurement, "__dict__")  # dataclass(slots=True)
