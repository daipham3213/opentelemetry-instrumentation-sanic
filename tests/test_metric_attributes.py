"""Unit tests for
:mod:`opentelemetry.instrumentation.sanic._metric_attributes`.
"""

from __future__ import annotations

from types import SimpleNamespace

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

from opentelemetry.instrumentation.sanic._metric_attributes import (
    active_request_attributes,
    collect_metric_attributes,
)


def _stub_request() -> SimpleNamespace:
    return SimpleNamespace(
        method="POST",
        scheme="https",
        version="1.1",
        uri_template="/items/<id>",
    )


# --------------------------------------------------------------------------- #
# active_request_attributes                                                    #
# --------------------------------------------------------------------------- #
def test_active_request_attributes_are_the_low_cardinality_subset() -> None:
    assert active_request_attributes(_stub_request()) == {
        HTTP_REQUEST_METHOD: "POST",
        URL_SCHEME: "https",
    }


def test_active_request_attributes_drop_missing_fields() -> None:
    assert active_request_attributes(object()) == {}


# --------------------------------------------------------------------------- #
# collect_metric_attributes                                                    #
# --------------------------------------------------------------------------- #
def test_collect_metric_attributes_marks_server_errors() -> None:
    attrs = collect_metric_attributes(_stub_request(), 503)
    assert attrs[HTTP_REQUEST_METHOD] == "POST"
    assert attrs[URL_SCHEME] == "https"
    assert attrs[HTTP_ROUTE] == "/items/<id>"
    assert attrs[NETWORK_PROTOCOL_VERSION] == "1.1"
    assert attrs[HTTP_RESPONSE_STATUS_CODE] == 503
    assert attrs[ERROR_TYPE] == "503"


def test_collect_metric_attributes_omits_error_type_for_success() -> None:
    attrs = collect_metric_attributes(_stub_request(), 200)
    assert attrs[HTTP_RESPONSE_STATUS_CODE] == 200
    assert ERROR_TYPE not in attrs


def test_collect_metric_attributes_omits_status_when_unknown() -> None:
    attrs = collect_metric_attributes(_stub_request(), None)
    assert HTTP_RESPONSE_STATUS_CODE not in attrs
    assert ERROR_TYPE not in attrs
    # The response-independent dimensions are still present.
    assert attrs[HTTP_ROUTE] == "/items/<id>"
