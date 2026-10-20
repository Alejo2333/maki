"""Preset and feature registries. Third parties add entries via the `maki.plugins` entry point."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
from typing import Any, ClassVar

from .plan import AppSpec, ScopedPlan


@dataclass
class Input:
    type: str = "string"  # string | choice | bool
    default: Any = None
    choices: tuple = ()
    description: str = ""


class Preset:
    id: ClassVar[str]
    label: ClassVar[str]
    kind: ClassVar[str]  # backend | frontend
    language: ClassVar[str]  # python | node
    architectures: ClassVar[tuple[str, ...]]
    port: ClassVar[int] = 8000

    def build(self, sp: ScopedPlan) -> None: ...
    def finalize(self, sp: ScopedPlan) -> None: ...


class Feature:
    id: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str] = ""
    requires: ClassVar[tuple[str, ...]] = ()
    conflicts_with: ClassVar[tuple[str, ...]] = ()
    frameworks: ClassVar[tuple[str, ...] | None] = None  # None = every framework
    scope: ClassVar[str] = "app"  # app | project
    inputs: ClassVar[dict[str, Input]] = {}

    def applies_to(self, app: AppSpec) -> bool:
        return self.frameworks is None or app.framework in self.frameworks

    def check(self, features: dict[str, dict]) -> list[str]:
        return []

    def apply(self, sp: ScopedPlan) -> None: ...
    def finalize(self, sp: ScopedPlan) -> None: ...


PRESETS: dict[str, Preset] = {}
FEATURES: dict[str, Feature] = {}


def register_preset(cls: type[Preset]) -> type[Preset]:
    PRESETS[cls.id] = cls()
    return cls


def register_feature(cls: type[Feature]) -> type[Feature]:
    FEATURES[cls.id] = cls()
    return cls


def load_all() -> None:
    from . import features, presets  # noqa: F401  (import side effects register built-ins)

    for ep in metadata.entry_points(group="maki.plugins"):
        ep.load()
