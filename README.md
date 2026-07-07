# opentelemetry-instrumentation-sanic

Zero-code [OpenTelemetry](https://opentelemetry.io/) instrumentation for the
[Sanic](https://sanic.dev/) web framework (including ASGI deployments).

Every inbound HTTP request handled by Sanic is turned into a server span with
HTTP semantic-convention attributes, W3C context propagation, and correct
error status mapping — plus the standard HTTP server **metrics** — with **no
changes to your application code**.

## Metrics

Alongside spans, the instrumentation emits the standard HTTP server metrics:

| Metric                           | Instrument      | Unit        | Description                          |
| -------------------------------- | --------------- | ----------- | ------------------------------------ |
| `http.server.request.duration`   | histogram       | `s`         | Request latency.                     |
| `http.server.active_requests`    | up-down counter | `{request}` | In-flight requests.                  |
| `http.server.request.body.size`  | histogram       | `By`        | Request payload size (when present). |
| `http.server.response.body.size` | histogram       | `By`        | Response payload size.               |

Duration and body-size measurements carry `http.request.method`, `url.scheme`,
`http.route`, `network.protocol.version`, `http.response.status_code`, and
(for 5xx) `error.type`. The active-requests counter carries only the
low-cardinality `http.request.method` and `url.scheme`.

## Install

```bash
pip install opentelemetry-instrumentation-sanic
```

## Zero-code usage

```bash
opentelemetry-instrument \
    --traces_exporter console \
    --metrics_exporter console \
    python my_sanic_app.py
```

The `opentelemetry-instrument` launcher discovers this package through its
`opentelemetry_instrumentor` entry point and activates it before your app is
created.

## Programmatic usage

Call `instrument()` **before** constructing your `Sanic` app:

```python
from opentelemetry.instrumentation.sanic import SanicInstrumentor

SanicInstrumentor().instrument(excluded_urls="/health,/metrics")

from sanic import Sanic
app = Sanic("my-app")
```

See [`examples/manual_app.py`](examples/manual_app.py) for a runnable example.

## Configuration

`SanicInstrumentor().instrument()` accepts:

| Keyword           | Type                    | Description                                                    |
| ----------------- | ----------------------- | ------------------------------------------------------------- |
| `tracer_provider` | `TracerProvider`        | Provider to use; defaults to the global provider.             |
| `meter_provider`  | `MeterProvider`         | Provider to use; defaults to the global provider.             |
| `excluded_urls`   | `str` / iterable[`str`] | Regex patterns whose matching URLs are neither traced nor measured. |

## Development

```bash
pip install -e ".[test]"
pytest
```

## Design notes

The instrumentor patches `sanic.Sanic.__init__` in place so each app registers
request/response middleware as it is constructed. (Patching in place rather
than swapping in a subclass preserves the class identity that Sanic's `TouchUp`
metaclass keys on.) Middleware signatures are stable across Sanic releases, so
the integration stays decoupled from Sanic internals. Responsibilities are split across small modules: URL filtering
(`_url_filter`), attribute extraction (`_attributes`), the metric instruments
(`_metrics`), the request lifecycle that emits both signals (`_middleware`),
and activation (`__init__`).
