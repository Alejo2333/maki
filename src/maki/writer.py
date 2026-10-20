"""Safe materialization of a Plan: no silent overwrites, no escapes, no partial output."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .errors import WriteError, errors
from .paths import resolve_inside
from .plan import Plan
from .validate import validate_plan


@dataclass
class WriteReport:
    destination: Path
    created: list[str] = field(default_factory=list)
    overwritten: list[str] = field(default_factory=list)
    dry_run: bool = False


def write_plan(plan: Plan, dest: str | Path, *, merge: bool = False, overwrite: bool = False,
               dry_run: bool = False) -> WriteReport:
    dest = Path(dest).expanduser().absolute()
    bad = errors(validate_plan(plan))
    if bad:
        raise WriteError("plan is invalid:\n" + "\n".join(f"  - {i.message}" for i in bad))
    if dest.exists() and not dest.is_dir():
        raise WriteError(f"{dest} exists and is not a directory")
    non_empty = dest.is_dir() and any(dest.iterdir())
    if non_empty and not merge:
        raise WriteError(f"{dest} is not empty; pass merge=True (--merge) to add files to it")

    targets = {e.path: resolve_inside(dest, e.path) if dest.exists() else dest / e.path for e in plan.files()}
    clashes = [p for p, t in targets.items() if t.exists()]
    if clashes and not overwrite:
        raise WriteError("refusing to overwrite existing files (use overwrite=True / --overwrite):\n"
                         + "\n".join(f"  - {p}" for p in clashes[:20]))
    report = WriteReport(dest, created=[p for p in targets if p not in clashes], overwritten=clashes, dry_run=dry_run)
    if dry_run:
        return report

    dest.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".maki-stage-", dir=dest.parent))
    try:
        for e in plan.files():
            f = stage / e.path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(e.content, encoding="utf-8", newline="\n")
            if e.executable:
                f.chmod(0o755)
        for d in plan.dirs:
            (stage / d).mkdir(parents=True, exist_ok=True)
        if not dest.exists() or not non_empty:
            if dest.exists():
                dest.rmdir()
            os.replace(stage, dest)
        else:
            _merge(stage, dest, plan)
    except BaseException as exc:
        raise WriteError(f"generation failed, nothing was left behind: {exc}") from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return report


def _merge(stage: Path, dest: Path, plan: Plan) -> None:
    """Copy staged files into an existing dir; roll back on any failure."""
    backup = Path(tempfile.mkdtemp(prefix=".maki-backup-", dir=dest.parent))
    created: list[Path] = []
    made_dirs: list[Path] = []
    replaced: list[tuple[Path, Path]] = []
    try:
        for e in plan.files():
            target = resolve_inside(dest, e.path)
            for parent in reversed(target.relative_to(dest).parents):
                d = dest / parent
                if not d.exists():
                    d.mkdir()
                    made_dirs.append(d)
            if target.exists():
                b = backup / e.path
                b.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, b)
                replaced.append((target, b))
            else:
                created.append(target)
            tmp = target.with_name(target.name + ".maki-tmp")
            shutil.copy2(stage / e.path, tmp)
            os.replace(tmp, target)
        for d in plan.dirs:
            (dest / d).mkdir(parents=True, exist_ok=True)
    except BaseException:
        for t in created:
            t.unlink(missing_ok=True)
        for t, b in replaced:
            shutil.copy2(b, t)
        for d in reversed(made_dirs):
            try:
                d.rmdir()
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)
