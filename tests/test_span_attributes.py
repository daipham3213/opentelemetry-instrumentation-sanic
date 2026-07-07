"""Unit tests for
:mod:`opentelemetry.instrumentation.sanic._span_attributes`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from opentelemetry.semconv.attributes.client_attributes import CLIENT_ADDRESS
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_REQUEST_METHOD,
    HTTP_ROUTE,
)
from opentelemetry.semconv.attributes.server_attributes import (
    SERVER_ADDRESS,
    SERVER_PORT,
)
from opentelemetry.semconv.attributes.url_attributes import (
    URL_QUERY,
    URL_SCHEME,
)
from opentelemetry.semconv.attributes.user_agent_attributes import (
    USER_AGENT_ORIGINAL,
)
from opentelemetry.trace.status import StatusCode

from opentelemetry.instrumentation.sanic._span_attributes import (
    collect_request_attributes,
    span_name_for,
    status_code_to_status,
)
from opentelemetry.instrumentation.sanic.exceptions import (
    RequestAttributeError,
)


# --------------------------------------------------------------------------- #
# span_name_for                                                                #
# --------------------------------------------------------------------------- #
def test_span_name_prefers_route_template() -> None:
    request = SimpleNamespace(
        method="GET", uri_template="/users/<id>", path="/users/5"
    )
    assert span_name_for(request) == "GET /users/<id>"


def test_span_name_falls_back_to_path() -> None:
    request = SimpleNamespace(method="GET", path="/users/5")
    assert span_name_for(request) == "GET /users/5"


def test_span_name_falls_back_to_method_only() -> None:
    assert span_name_for(SimpleNamespace(method="GET")) == "GET"


def test_span_name_requires_method() -> None:
    with pytest.raises(RequestAttributeError):
        span_name_for(object())


# --------------------------------------------------------------------------- #
# collect_request_attributes                                                   #
# --------------------------------------------------------------------------- #
def test_collect_request_attributes_happy_path() -> None:
    request = SimpleNamespace(
        method="POST",
        scheme="https",
        path="/x",
        query_string="a=1",
        url="https://host/x",
        uri_template="/x",
        host="host:443",
        remote_addr="1.2.3.4",
        headers={"user-agent": "UA"},
    )
    attrs = collect_request_attributes(request)
    assert attrs[HTTP_REQUEST_METHOD] == "POST"
    assert attrs[URL_SCHEME] == "https"
    assert attrs[HTTP_ROUTE] == "/x"
    assert attrs[SERVER_ADDRESS] == "host"
    assert attrs[SERVER_PORT] == 443
    assert attrs[CLIENT_ADDRESS] == "1.2.3.4"
    assert attrs[USER_AGENT_ORIGINAL] == "UA"
    assert attrs[URL_QUERY] == "a=1"


def test_collect_request_attributes_drops_empty_values() -> None:
    request = SimpleNamespace(method="GET", scheme="http", query_string="")
    attrs = collect_request_attributes(request)
    assert URL_SCHEME in attrs
    assert URL_QUERY not in attrs  # empty string is dropped


def test_collect_request_attributes_rejects_non_request() -> None:
    with pytest.raises(RequestAttributeError):
        collect_request_attributes(object())


# --------------------------------------------------------------------------- #
# status_code_to_status                                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "status_code, expected",
    [
        (200, StatusCode.UNSET),
        (201, StatusCode.UNSET),
        (302, StatusCode.UNSET),
        (404, StatusCode.UNSET),  # client error is not a server span error
        (499, StatusCode.UNSET),
        (500, StatusCode.ERROR),
        (503, StatusCode.ERROR),
        (99, StatusCode.ERROR),  # malformed (< 100)
        (0, StatusCode.ERROR),
    ],
)
def test_status_code_to_status(status_code, expected) -> None:
    assert status_code_to_status(status_code) is expected
