# opentelemetry-instrumentation-sanic

Zero-code [OpenTelemetry](https://opentelemetry.io/) instrumentation for the
[Sanic](https://sanic.dev/) web framework (including ASGI deployments).

Every inbound HTTP request handled by Sanic is turned into a server span with
HTTP semantic-convention attributes, W3C context propagation, and correct
error status mapping — with **no changes to your application code**.

## Install

```bash
pip install opentelemetry-instrumentation-sanic
```

## Zero-code usage

```bash
opentelemetry-instrument --traces_exporter console python my_sanic_app.py
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

| Keyword           | Type                    | Description                                        |
| ----------------- | ----------------------- | -------------------------------------------------- |
| `tracer_provider` | `TracerProvider`        | Provider to use; defaults to the global provider.  |
| `excluded_urls`   | `str` / iterable[`str`] | Regex patterns whose matching URLs are not traced. |

## Development

```bash
pip install -e ".[test]"
pytest
```

## Design notes

The instrumentor swaps `sanic.Sanic` for a subclass that registers
request/response middleware on construction. Middleware signatures are stable
across Sanic releases, so the integration stays decoupled from Sanic
internals. Responsibilities are split across small modules: URL filtering
(`_url_filter`), attribute extraction (`_attributes`), span lifecycle
(`_middleware`), and activation (`__init__`).
