"""Unit tests for :mod:`opentelemetry.instrumentation.sanic._request`.

The anti-corruption readers are pure and defensive, so they are exercised here
with minimal :class:`types.SimpleNamespace` stubs and a bare ``object()`` for
the "field absent" case.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opentelemetry.instrumentation.sanic import _request


# --------------------------------------------------------------------------- #
# Simple pass-through readers                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "func_name, attr, value",
    [
        ("method", "method", "POST"),
        ("scheme", "scheme", "https"),
        ("path", "path", "/x"),
        ("query_string", "query_string", "a=1"),
        ("url", "url", "http://host/x"),
        ("route", "uri_template", "/x/<id>"),
    ],
)
def test_simple_reader_returns_value(func_name, attr, value) -> None:
    request = SimpleNamespace(**{attr: value})
    assert getattr(_request, func_name)(request) == value


@pytest.mark.parametrize(
    "func_name",
    [
        "method",
        "scheme",
        "path",
        "query_string",
        "url",
        "route",
        "remote_address",
        "protocol_version",
        "user_agent",
        "response_status",
    ],
)
def test_reader_returns_none_when_field_absent(func_name) -> None:
    assert getattr(_request, func_name)(object()) is None


# --------------------------------------------------------------------------- #
# Readers with normalisation logic                                            #
# --------------------------------------------------------------------------- #
def test_remote_address_maps_empty_to_none() -> None:
    assert _request.remote_address(SimpleNamespace(remote_addr="")) is None
    assert (
        _request.remote_address(SimpleNamespace(remote_addr="1.2.3.4"))
        == "1.2.3.4"
    )


@pytest.mark.parametrize(
    "version, expected",
    [("1.1", "1.1"), (1.1, "1.1"), (2, "2"), (0, None), (None, None)],
)
def test_protocol_version_coerces_to_string(version, expected) -> None:
    assert (
        _request.protocol_version(SimpleNamespace(version=version)) == expected
    )


def test_headers_returns_mapping_or_empty() -> None:
    mapping = {"user-agent": "UA"}
    assert _request.headers(SimpleNamespace(headers=mapping)) is mapping
    assert _request.headers(object()) == {}


def test_header_reads_single_value() -> None:
    request = SimpleNamespace(headers={"content-length": "12", "empty": ""})
    assert _request.header(request, "content-length") == "12"
    assert _request.header(request, "missing") is None
    assert _request.header(request, "empty") is None  # empty -> None


def test_user_agent_reads_user_agent_header() -> None:
    request = SimpleNamespace(headers={"user-agent": "curl/8"})
    assert _request.user_agent(request) == "curl/8"


@pytest.mark.parametrize(
    "host, expected",
    [
        ("host:8000", ("host", 8000)),
        ("host", ("host", None)),
        ("host:notaport", ("host", None)),
        ("", (None, None)),
    ],
)
def test_server_address_and_port(host, expected) -> None:
    request = SimpleNamespace(host=host)
    assert _request.server_address_and_port(request) == expected


def test_server_address_and_port_without_host() -> None:
    assert _request.server_address_and_port(object()) == (None, None)


# --------------------------------------------------------------------------- #
# Body sizes                                                                   #
# --------------------------------------------------------------------------- #
def test_request_body_size_prefers_content_length() -> None:
    request = SimpleNamespace(
        headers={"content-length": "42"}, body=b"ignored"
    )
    assert _request.request_body_size(request) == 42


@pytest.mark.parametrize("content_length", ["0", "not-a-number"])
def test_request_body_size_rejects_zero_or_invalid_content_length(
    content_length,
) -> None:
    request = SimpleNamespace(
        headers={"content-length": content_length}, body=b""
    )
    assert _request.request_body_size(request) is None


def test_request_body_size_falls_back_to_body_length() -> None:
    request = SimpleNamespace(headers={}, body=b"abc")
    assert _request.request_body_size(request) == 3


def test_request_body_size_none_for_empty_body() -> None:
    request = SimpleNamespace(headers={}, body=b"")
    assert _request.request_body_size(request) is None


def test_response_body_size() -> None:
    assert _request.response_body_size(SimpleNamespace(body=b"abcd")) == 4
    assert _request.response_body_size(SimpleNamespace(body=b"")) is None
    assert _request.response_body_size(object()) is None


def test_response_status_only_returns_ints() -> None:
    assert _request.response_status(SimpleNamespace(status=204)) == 204
    assert _request.response_status(SimpleNamespace(status="204")) is None
    assert _request.response_status(object()) is None
