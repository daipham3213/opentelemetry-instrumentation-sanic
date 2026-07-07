"""Own the HTTP-server-metrics half of the request lifecycle.

:class:`MetricsRecorder` mirrors :class:`._span.SpanRecorder`: it turns a
request/response pair into OpenTelemetry *metric* measurements and knows
nothing about how it is wired onto an app. It emits the standard HTTP server
instruments:

* ``http.server.request.duration`` — request latency histogram (seconds);
* ``http.server.active_requests`` — in-flight request up-down counter;
* ``http.server.request.body.size`` / ``http.server.response.body.size`` —
  payload-size histograms (bytes).

Only ``http.server.request.duration`` has been promoted to the **stable** metric
semantic conventions; the remaining names still live under
:mod:`opentelemetry.semconv._incubating.metrics.http_metrics`, so they are
imported from there until they stabilise.

Recording never raises: like the span recorder, a failure here is logged and
swallowed so instrumentation can never break the request pipeline. In
particular the active-requests decrement is issued from a ``finally`` block so
the counter always balances back to zero.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from opentelemetry.metrics import Meter
from opentelemetry.semconv._incubating.metrics.http_metrics import (
    HTTP_SERVER_ACTIVE_REQUESTS,
    HTTP_SERVER_REQUEST_BODY_SIZE,
    HTTP_SERVER_RESPONSE_BODY_SIZE,
)
from opentelemetry.semconv.metrics.http_metrics import (
    HTTP_SERVER_REQUEST_DURATION,
)

from . import _request
from ._metric_attributes import (
    active_request_attributes,
    collect_metric_attributes,
)

__all__ = ["MetricsRecorder", "RequestMeasurement"]

_logger = logging.getLogger(__name__)

# Advisory histogram buckets (seconds) for request duration, taken verbatim
# from the HTTP metrics semantic conventions. Backends may ignore the advisory,
# but honouring it keeps latency histograms comparable across instrumentations.
_DURATION_BUCKETS_S: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    7.5,
    10.0,
)


@dataclass(slots=True)
class RequestMeasurement:
    """Per-request metric state carried from request start to response.

    Held opaquely by the middleware on ``request.ctx`` and handed back to
    :meth:`MetricsRecorder.finish`.

    :ivar start_time: A :func:`time.perf_counter` reading taken at request
        start.
    :ivar active_attributes: The exact attribute set used to increment the
        active-requests counter, reused to decrement it so the counter
        balances.
    """

    start_time: float
    active_attributes: dict[str, Any]


class MetricsRecorder:
    """Owns the HTTP server instruments and records per-request measurements.

    A single instance is stateless with respect to individual requests — all
    per-request state lives in the :class:`RequestMeasurement` it returns — so
    one recorder can safely serve many concurrent requests and applications.

    :param meter: The :class:`~opentelemetry.metrics.Meter` used to create the
        instruments.
    """

    def __init__(self, meter: Meter) -> None:
        self._duration = meter.create_histogram(
            name=HTTP_SERVER_REQUEST_DURATION,
            description="Duration of HTTP server requests.",
            unit="s",
            explicit_bucket_boundaries_advisory=list(_DURATION_BUCKETS_S),
        )
        self._active_requests = meter.create_up_down_counter(
            name=HTTP_SERVER_ACTIVE_REQUESTS,
            description="Number of active HTTP server requests.",
            unit="{request}",
        )
        self._request_body_size = meter.create_histogram(
            name=HTTP_SERVER_REQUEST_BODY_SIZE,
            description="Size of HTTP server request bodies.",
            unit="By",
        )
        self._response_body_size = meter.create_histogram(
            name=HTTP_SERVER_RESPONSE_BODY_SIZE,
            description="Size of HTTP server response bodies.",
            unit="By",
        )

    def start(self, request: Any) -> RequestMeasurement | None:
        """Mark a request in-flight and start its latency clock.

        :param request: The incoming Sanic request.
        :returns: A :class:`RequestMeasurement` to hand back to :meth:`finish`,
            or ``None`` if the start could not be recorded (in which case there
            is nothing for :meth:`finish` to finalise).
        """
        try:
            active_attributes = active_request_attributes(request)
            self._active_requests.add(1, active_attributes)
            return RequestMeasurement(perf_counter(), active_attributes)
        except Exception:  # boundary guard: telemetry must not break requests
            _logger.exception("Failed to record Sanic request-start metrics.")
            return None

    def finish(
        self,
        request: Any,
        response: Any,
        measurement: RequestMeasurement | None,
    ) -> None:
        """Record the latency/size histograms and clear the in-flight count.

        :param request: The Sanic request the response belongs to.
        :param response: The outgoing Sanic response.
        :param measurement: The value returned by the paired :meth:`start`, or
            ``None`` to skip.
        """
        if measurement is None:
            return
        try:
            elapsed = perf_counter() - measurement.start_time
            status_code = _request.response_status(response)
            attributes = collect_metric_attributes(request, status_code)

            self._duration.record(elapsed, attributes)

            req_size = _request.request_body_size(request)
            if req_size is not None:
                self._request_body_size.record(req_size, attributes)

            resp_size = _request.response_body_size(response)
            if resp_size is not None:
                self._response_body_size.record(resp_size, attributes)
        except Exception:  # boundary guard: telemetry must not break requests
            _logger.exception("Failed to record Sanic request metrics.")
        finally:
            # Always balance the increment from start(), even on error.
            try:
                self._active_requests.add(-1, measurement.active_attributes)
            except Exception:  # boundary guard: must not break requests
                _logger.exception(
                    "Failed to decrement Sanic active-requests counter."
                )
