"""Example: enabling Sanic tracing programmatically.

Run this file directly to see spans printed to the console::

    python examples/manual_app.py

Then, in another terminal::

    curl http://127.0.0.1:8000/hello/world

For fully **zero-code** usage you would instead skip the ``instrument()`` call
below and launch with::

    opentelemetry-instrument --traces_exporter console python examples/manual_app.py
"""

from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from opentelemetry import trace
from opentelemetry.instrumentation.sanic import SanicInstrumentor

# 1. Configure a tracer provider that prints spans to stdout.
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)

# 2. Instrument BEFORE the Sanic application is created. Skip the /health probe.
SanicInstrumentor().instrument(
    tracer_provider=provider,
    excluded_urls="/health",
)

# 3. Build the app exactly as you normally would — no tracing code required.
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
