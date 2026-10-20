"""Path safety. Every path in a Plan goes through `normalize` before it is stored."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .errors import UnsafePathError

_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def normalize(path: str) -> str:
    """Return a clean relative POSIX path or raise UnsafePathError.

    Rejects absolute paths, drive letters, `..`, control characters, Windows-reserved
    names and trailing dots/spaces so a blueprint generated on one OS is safe on all.
    """
    if not isinstance(path, str) or not path.strip():
        raise UnsafePathError("path is empty")
    raw = path.replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw) or raw.startswith("~"):
        raise UnsafePathError(f"absolute paths are not allowed: {path!r}")
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise UnsafePathError(f"'..' is not allowed: {path!r}")
        if _BAD_CHARS.search(part):
            raise UnsafePathError(f"invalid character in {part!r}")
        if part != part.strip() or part.endswith("."):
            raise UnsafePathError(f"name may not start/end with space or end with '.': {part!r}")
        if part.split(".")[0].lower() in _RESERVED:
            raise UnsafePathError(f"reserved name on Windows: {part!r}")
        if len(part) > 255:
            raise UnsafePathError(f"name too long: {part[:20]!r}...")
        parts.append(part)
    if not parts:
        raise UnsafePathError(f"path resolves to nothing: {path!r}")
    return "/".join(parts)


def join(root: str, rel: str) -> str:
    return normalize(f"{root}/{rel}" if root else rel)


def resolve_inside(dest: Path, rel: str) -> Path:
    """Resolve `rel` under `dest`, following symlinks, and verify it stays inside."""
    base = Path(os.path.realpath(dest))
    target = Path(os.path.realpath(base / normalize(rel)))
    if target != base and base not in target.parents:
        raise UnsafePathError(f"{rel!r} resolves outside the destination (symlink escape?)")
    return target
