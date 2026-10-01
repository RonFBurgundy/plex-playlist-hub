#!/usr/bin/env python3
"""Legacy entry point provided for backward compatibility."""

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from plex_playlist_sync.cli import main

if __name__ == "__main__":
    sys.exit(main())
