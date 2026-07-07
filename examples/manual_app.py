"""Example: enabling Sanic tracing and metrics programmatically.

Run this file directly to see spans (and, every few seconds, metrics) printed
to the console::

    python examples/manual_app.py

Then, in another terminal::

    curl http://127.0.0.1:8000/hello/world

For fully **zero-code** usage you would instead skip the ``instrument()`` call
below and launch with::

    opentelemetry-instrument \
        --traces_exporter console \
        --metrics_exporter console \
        python examples/manual_app.py
"""

from __future__ import annotations

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from opentelemetry import metrics, trace
from opentelemetry.instrumentation.sanic import SanicInstrumentor

# 1. Configure a tracer provider that prints spans to stdout.
tracer_provider = TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(tracer_provider)

# 2. Configure a meter provider that periodically prints metrics to stdout.
meter_provider = MeterProvider(
    metric_readers=[PeriodicExportingMetricReader(ConsoleMetricExporter())]
)
metrics.set_meter_provider(meter_provider)

# 3. Instrument BEFORE the Sanic application is created. Skip the /health probe.
SanicInstrumentor().instrument(
    tracer_provider=tracer_provider,
    meter_provider=meter_provider,
    excluded_urls="/health",
)

# 4. Build the app exactly as you normally would — no telemetry code required.
from sanic import Sanic  # noqa: E402 - imported after instrument() on purpose
from sanic.response import json as json_response  # noqa: E402

app = Sanic("otel-example")


@app.get("/hello/<name>")
async def hello(request, name: str):
    return json_response({"message": f"Hello, {name}!"})


@app.get("/health")
async def health(request):
    return json_response({"status": "ok"})  # not traced (excluded)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, single_process=True)
