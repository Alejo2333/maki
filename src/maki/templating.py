"""Sandboxed Jinja2 rendering with strict undefined variables."""

from __future__ import annotations

import re
from typing import Any

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from .errors import TemplateRenderError


def _words(value: str) -> list[str]:
    return [w for w in re.split(r"[^A-Za-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)) if w]


def snake(value: str) -> str:
    return "_".join(w.lower() for w in _words(value))


def kebab(value: str) -> str:
    return "-".join(w.lower() for w in _words(value))


def pascal(value: str) -> str:
    return "".join(w.capitalize() for w in _words(value))


_env = SandboxedEnvironment(
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)
_env.filters.update(snake=snake, kebab=kebab, pascal=pascal)


def render(text: str, context: dict[str, Any], *, where: str = "<template>") -> str:
    """Render `text`. A missing variable is an error, never a silent blank."""
    try:
        return _env.from_string(text).render(**context)
    except TemplateError as exc:
        raise TemplateRenderError(f"{where}: {exc}") from exc
