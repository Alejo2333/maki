"""Shared exception and issue types."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


class MakiError(Exception):
    """Base class for all expected Maki failures."""


class BlueprintError(MakiError):
    """The blueprint could not be loaded or migrated."""


class UnsafePathError(MakiError):
    """A path would escape the destination or is otherwise invalid."""


class TemplateRenderError(MakiError):
    """A template failed to render (usually an undefined variable)."""


class WriteError(MakiError):
    """Generation failed or was refused. Nothing is left half-written."""


@dataclass(frozen=True)
class Issue:
    """A validation finding. Errors block generation; warnings do not."""

    level: Literal["error", "warning"]
    code: str
    message: str
    path: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]
