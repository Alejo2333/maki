"""Blueprint schema migrations. Add one `v(n) -> v(n+1)` function per schema bump."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import BlueprintError

SCHEMA_VERSION = 1

# from_version -> function returning the next version's dict. Example for the future:
#   def _v1_to_v2(d): d["deployment"] = d.pop("deploy", "none"); return d
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a raw blueprint dict to the current schema version."""
    data = dict(data)
    version = data.get("schema_version", 1)
    if not isinstance(version, int) or version < 1:
        raise BlueprintError(f"invalid schema_version: {version!r}")
    if version > SCHEMA_VERSION:
        raise BlueprintError(
            f"blueprint uses schema v{version} but this Maki only understands up to v{SCHEMA_VERSION}; upgrade Maki"
        )
    while version < SCHEMA_VERSION:
        if version not in MIGRATIONS:
            raise BlueprintError(f"no migration from schema v{version}")
        data = MIGRATIONS[version](data)
        version += 1
        data["schema_version"] = version
    data["schema_version"] = version
    return data


def load_blueprint_data(source: str | Path) -> dict[str, Any]:
    try:
        raw = json.loads(Path(source).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BlueprintError(f"blueprint not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise BlueprintError(f"{source} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise BlueprintError("blueprint must be a JSON object")
    return migrate(raw)
