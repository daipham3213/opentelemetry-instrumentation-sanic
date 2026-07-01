"""Runtime access to the package version.

The version is derived from git tags at build time by ``hatch-vcs`` (see
``[tool.hatch.version]`` in ``pyproject.toml``). It is resolved here in three
steps so that ``__version__`` is always populated:

#. from the generated ``_version.py`` (present in built/installed trees);
#. from the installed distribution metadata (fallback);
#. a development placeholder when running from an unbuilt source checkout.
"""

from __future__ import annotations

try:  # Preferred: file written by hatch-vcs during the build.
    from ._version import __version__ as __version__
except ImportError:  # pragma: no cover - exercised only in unbuilt checkouts
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("opentelemetry-instrumentation-sanic")
    except PackageNotFoundError:
        __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
