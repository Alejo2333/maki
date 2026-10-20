"""The Plan: an in-memory virtual file tree. Preview renders it; generation writes it."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .errors import Issue
from .paths import join, normalize
from .templating import render


@dataclass
class Entry:
    path: str
    content: str
    origin: str
    executable: bool = False
    weak: bool = False  # placeholder (e.g. empty __init__.py) that anything may replace
    history: list[str] = field(default_factory=list)


@dataclass
class Conflict:
    path: str
    first: str
    second: str


@dataclass
class AppSpec:
    name: str
    root: str
    framework: str
    architecture: str
    kind: str  # "python" | "node"
    port: int
    options: dict[str, Any] = field(default_factory=dict)


class _Ext:
    def __init__(self, data: dict[str, list]):
        self._d = data

    def __getattr__(self, k: str) -> list:
        return self._d.get(k, [])


class Plan:
    def __init__(self) -> None:
        self.entries: dict[str, Entry] = {}
        self.dirs: dict[str, str] = {}
        self.conflicts: list[Conflict] = []
        self.issues: list[Issue] = []
        self.notes: list[str] = []
        self.ext: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        self.deps: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
        self.env: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
        self.apps: list[AppSpec] = []
        self.features: dict[str, dict] = {}
        self.base_ctx: dict[str, Any] = {}

    def put(self, path: str, content: str, origin: str, *, replace: bool = False,
            executable: bool = False, weak: bool = False) -> None:
        path = normalize(path)
        cur = self.entries.get(path)
        if cur is None:
            self.entries[path] = Entry(path, content, origin, executable, weak)
        elif weak:
            return
        elif cur.weak or replace or cur.origin == origin:
            cur.history.append(cur.origin)
            cur.content, cur.origin, cur.weak = content, origin, False
            cur.executable = executable or cur.executable
        elif cur.content != content:
            self.conflicts.append(Conflict(path, cur.origin, origin))

    def files(self) -> list[Entry]:
        return [self.entries[k] for k in sorted(self.entries)]

    def tree_text(self) -> str:
        paths = sorted([*self.entries, *(d + "/" for d in self.dirs)])
        lines: list[str] = []
        seen: set[str] = set()
        for p in paths:
            parts = p.rstrip("/").split("/")
            for i in range(1, len(parts)):
                d = "/".join(parts[:i])
                if d not in seen:
                    seen.add(d)
                    lines.append("  " * (i - 1) + parts[i - 1] + "/")
            if p.endswith("/"):
                d = "/".join(parts)
                if d not in seen:
                    seen.add(d)
                    lines.append("  " * (len(parts) - 1) + parts[-1] + "/")
            else:
                lines.append("  " * (len(parts) - 1) + parts[-1])
        return "\n".join(lines)

    def scoped(self, app: AppSpec | None, origin: str, cfg: dict | None = None) -> ScopedPlan:
        return ScopedPlan(self, app, origin, cfg or {})


class ScopedPlan:
    """What presets and features see: paths are relative to one app root."""

    def __init__(self, plan: Plan, app: AppSpec | None, origin: str, cfg: dict):
        self.plan, self.app, self.origin, self.cfg = plan, app, origin, cfg
        self.root = app.root if app else ""
        self.features = plan.features

    def context(self, **extra: Any) -> dict[str, Any]:
        ctx = dict(self.plan.base_ctx)
        m: dict[str, str] = {}
        if self.app and self.app.kind == "python":
            from .presets.python import mods

            m = mods(self.app)
        ctx.update(app=self.app, feature=self.cfg, features=self.features, m=m,
                   ext=_Ext(self.plan.ext[self.root]), **extra)
        return ctx

    def render(self, text: str, **extra: Any) -> str:
        return render(text, self.context(**extra), where=self.origin)

    def put(self, rel: str, content: str, *, templ: bool = True, replace: bool = False,
            executable: bool = False, weak: bool = False, **extra: Any) -> None:
        text = self.render(content, **extra) if templ and not weak else content
        self.plan.put(join(self.root, rel), text, self.origin, replace=replace,
                      executable=executable, weak=weak)

    def add_ext(self, point: str, value: Any) -> None:
        self.plan.ext[self.root][point].append(value)

    def dep(self, name: str, spec: str = "", dev: bool = False) -> None:
        from .versions import pin

        eco = self.app.kind if self.app else "python"
        self.plan.deps[(self.root, eco + ("-dev" if dev else ""))][name] = spec or pin(eco, name)

    def env(self, key: str, value: str, comment: str = "") -> None:
        self.plan.env[self.root][key] = (value, comment)

    def script(self, name: str, cmd: str) -> None:
        self.add_ext("scripts", (name, cmd))


def dumps_json(obj: Any) -> str:
    return json.dumps(obj, indent=2) + "\n"
