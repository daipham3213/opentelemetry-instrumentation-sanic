"""Standard-library URL exclusion matching.

Rather than pulling in an extra dependency for the common "don't trace my
health-check endpoint" use case, this module implements a tiny, well-tested
matcher on top of :mod:`re` from the standard library.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TypeAlias

from .exceptions import SanicConfigurationError

#: Accepted input forms for building an :class:`ExcludeUrlFilter`.
ExcludeUrlsInput: TypeAlias = str | Iterable[str] | None

__all__ = ["ExcludeUrlFilter", "ExcludeUrlsInput"]


class ExcludeUrlFilter:
    """Decides whether a URL should be excluded from instrumentation.

    Patterns are treated as regular expressions and combined into a single
    alternation, so a match anywhere in the URL excludes it. An empty filter
    never excludes anything.

    :param patterns: A comma-separated string (e.g. ``"/health,/metrics"``) or
        an iterable of regular-expression fragments. ``None`` yields a filter
        that excludes nothing.
    :raises SanicConfigurationError: If a pattern is not valid
        regular-expression syntax.
    """

    __slots__ = ("_regex",)

    def __init__(self, patterns: ExcludeUrlsInput = None) -> None:
        fragments = self._normalise(patterns)
        if not fragments:
            self._regex: re.Pattern[str] | None = None
            return
        try:
            self._regex = re.compile("|".join(f"(?:{p})" for p in fragments))
        except re.error as exc:  # narrow: only invalid regex syntax
            raise SanicConfigurationError(
                f"Invalid excluded-URL pattern(s): {patterns!r}"
            ) from exc

    @staticmethod
    def _normalise(patterns: ExcludeUrlsInput) -> list[str]:
        """Coerce the accepted input forms into a list of pattern fragments."""
        if patterns is None:
            return []
        if isinstance(patterns, str):
            return [
                chunk.strip() for chunk in patterns.split(",") if chunk.strip()
            ]
        return [str(chunk).strip() for chunk in patterns if str(chunk).strip()]

    def is_excluded(self, url: str) -> bool:
        """Return ``True`` if *url* matches any configured exclusion pattern.

        :param url: The absolute or relative URL to test.
        :returns: Whether the URL should be skipped for instrumentation.
        """
        if self._regex is None:
            return False
        return self._regex.search(url) is not None
