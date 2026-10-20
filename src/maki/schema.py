"""Versioned blueprint schema (the single source of truth for a project config)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .migrations import SCHEMA_VERSION
from .templating import kebab, snake

Architecture = Literal["minimal", "layer", "feature", "modular-monolith", "microservices", "custom"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectMeta(_M):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9 _.-]{0,63}$")
    description: str = ""
    author: str = ""
    version: str = "0.1.0"

    @property
    def slug(self) -> str:
        return kebab(self.name)

    @property
    def package(self) -> str:
        s = snake(self.name)
        return s if s and not s[0].isdigit() else f"app_{s}"


class Stack(_M):
    framework: str
    architecture: Architecture | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class Override(_M):
    """A user edit applied last. ops: add | remove | move | set_content."""

    op: Literal["add", "remove", "move", "set_content"]
    path: str
    to: str | None = None
    mode: Literal["preset", "empty", "starter", "custom"] = "custom"
    content: str | None = None
    render: bool = False  # render custom content as a Jinja template


class Blueprint(_M):
    schema_version: int = SCHEMA_VERSION
    project: ProjectMeta
    project_type: Literal["frontend", "backend", "full-stack"] = "backend"
    layout: Literal["single", "monorepo", "multi-service"] = "single"
    architecture: Architecture = "layer"
    deployment: Literal["none", "container", "compose"] = "none"
    stack: Stack
    frontend: Stack | None = None
    services: list[str] = Field(default_factory=list)
    features: dict[str, dict[str, Any]] = Field(default_factory=dict)
    overrides: list[Override] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)
