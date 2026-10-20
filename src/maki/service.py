"""Thin facade used by both the CLI and the API so they can never diverge."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .errors import BlueprintError, Issue
from .migrations import migrate
from .plan import Plan
from .registry import FEATURES, PRESETS, load_all
from .resolve import build_plan
from .schema import Blueprint


def parse_blueprint(data: dict[str, Any]) -> Blueprint:
    try:
        return Blueprint.model_validate(migrate(data))
    except ValidationError as exc:
        msgs = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise BlueprintError(f"invalid blueprint: {msgs}") from exc


def plan_for(data: dict[str, Any]) -> tuple[Blueprint, Plan, list[Issue]]:
    bp = parse_blueprint(data)
    plan, issues = build_plan(bp)
    return bp, plan, issues


def catalog() -> dict[str, Any]:
    load_all()
    return {
        "presets": [{"id": p.id, "label": p.label, "kind": p.kind, "architectures": list(p.architectures)}
                    for p in PRESETS.values()],
        "features": [{"id": f.id, "label": f.label, "description": f.description, "requires": list(f.requires),
                      "frameworks": list(f.frameworks) if f.frameworks else None,
                      "inputs": {k: {"type": v.type, "default": v.default, "choices": list(v.choices)}
                                 for k, v in f.inputs.items()}} for f in FEATURES.values()],
        "schema": Blueprint.model_json_schema(),
    }
