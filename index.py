"""Vercel entrypoint for the public, browser-download Studio deployment."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from maki.api import create_app

app = create_app(token=None, allow_generate=False)
