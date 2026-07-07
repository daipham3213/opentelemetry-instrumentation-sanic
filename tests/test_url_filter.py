"""Unit tests for :mod:`opentelemetry.instrumentation.sanic._url_filter`."""

from __future__ import annotations

import pytest

from opentelemetry.instrumentation.sanic._url_filter import ExcludeUrlFilter
from opentelemetry.instrumentation.sanic.exceptions import (
    SanicConfigurationError,
)


def test_none_excludes_nothing() -> None:
    assert ExcludeUrlFilter(None).is_excluded("/anything") is False


def test_empty_string_excludes_nothing() -> None:
    assert ExcludeUrlFilter("").is_excluded("/health") is False


def test_string_patterns_are_split_on_commas() -> None:
    url_filter = ExcludeUrlFilter("/health,/metrics")
    assert url_filter.is_excluded("http://host/health") is True
    assert url_filter.is_excluded("http://host/metrics/live") is True
    assert url_filter.is_excluded("http://host/api/users") is False


def test_iterable_patterns() -> None:
    url_filter = ExcludeUrlFilter(["/health", "/ping"])
    assert url_filter.is_excluded("/ping") is True
    assert url_filter.is_excluded("/other") is False


def test_blank_and_whitespace_fragments_are_ignored() -> None:
    url_filter = ExcludeUrlFilter(" /health , , ")
    assert url_filter.is_excluded("/health") is True


def test_invalid_regex_raises_configuration_error() -> None:
    # An unbalanced group is invalid regex — a *configuration* error, distinct
    # from a runtime request-attribute error.
    with pytest.raises(SanicConfigurationError):
        ExcludeUrlFilter("(unclosed")
