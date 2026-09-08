"""ProjectMan - Git-native project management for Claude Code."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version

try:
    #: Read from the installed distribution's metadata, so pyproject.toml's
    #: ``version`` is the single place a release bump has to touch.
    __version__ = _package_version("projectman")
except PackageNotFoundError:  # a source checkout with no installed distribution
    __version__ = "0.0.0+source"
