"""Pytest configuration and global fixtures for TrackSeerr test suite."""

import os

# Default to legacy UI for backwards compatibility with existing frontend tests.
# New React SPA tests explicitly unset or set TRACKSEERR_LEGACY_UI to '0'.
os.environ["TRACKSEERR_LEGACY_UI"] = "1"
