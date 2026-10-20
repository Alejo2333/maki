"""Validation: blueprint-level (options, compatibility) and plan-level (paths, conflicts)."""

from __future__ import annotations

import re

from .errors import Issue, UnsafePathError
from .paths import normalize
from .plan import AppSpec, Plan
from .registry import FEATURES, PRESETS, load_all
from .schema import Blueprint

_SECRET = re.compile(r"""(?i)(secret|password|passwd|api[_-]?key|token)\w*\s*[:=]\s*["'][^"'\s]{8,}["']""")
_PLACEHOLDER = re.compile(r"(?i)change-?me|example|placeholder|your[_-]|<.*>|\$\{")


def effective_features(bp: Blueprint) -> dict[str, dict]:
    feats = dict(bp.features)
    if bp.deployment in ("container", "compose"):
        feats.setdefault("docker", {})
    if bp.deployment == "compose":
        feats.setdefault("compose", {})
    return feats


def derive_apps(bp: Blueprint) -> list[AppSpec]:
    load_all()
    apps: list[AppSpec] = []
    backend_root = {"single": "", "monorepo": "backend", "multi-service": "services"}[bp.layout]
    if bp.project_type in ("backend", "full-stack"):
        if bp.layout == "multi-service":
            names = bp.services or ["api"]
            roots = [(n, f"services/{n}") for n in names]
        else:
            roots = [("backend", backend_root if bp.project_type == "full-stack" else (backend_root if bp.layout == "single" else "apps/backend"))]
        for i, (name, root) in enumerate(roots):
            p = PRESETS.get(bp.stack.framework)
            apps.append(AppSpec(name, root, bp.stack.framework, bp.stack.architecture or bp.architecture,
                                p.language if p else "python", 8000 + i, bp.stack.options))
    fe = bp.frontend if bp.project_type == "full-stack" else (bp.stack if bp.project_type == "frontend" else None)
    if fe:
        p = PRESETS.get(fe.framework)
        root = "" if bp.project_type == "frontend" and bp.layout == "single" else (
            "apps/web" if bp.project_type == "frontend" else "frontend")
        arch = fe.architecture or (bp.architecture if bp.project_type == "frontend" else "layer")
        apps.append(AppSpec("frontend", root, fe.framework, arch, p.language if p else "node",
                            p.port if p else 5173, fe.options))
    return apps


def validate_blueprint(bp: Blueprint) -> list[Issue]:
    load_all()
    out: list[Issue] = []
    err = lambda code, msg: out.append(Issue("error", code, msg))  # noqa: E731

    def check_stack(stack, kind):
        p = PRESETS.get(stack.framework)
        if not p:
            err("unknown-framework", f"unknown framework {stack.framework!r}; available: {sorted(PRESETS)}")
        elif p.kind != kind:
            err("wrong-kind", f"{stack.framework} is a {p.kind} framework but a {kind} is required here")
        return p

    t = bp.project_type
    check_stack(bp.stack, "frontend" if t == "frontend" else "backend")
    if t == "full-stack":
        if not bp.frontend:
            err("missing-frontend", "full-stack projects need a `frontend` stack")
        else:
            check_stack(bp.frontend, "frontend")
        if bp.layout == "single":
            err("layout", "full-stack needs layout 'monorepo' or 'multi-service'")
    elif bp.frontend:
        err("unexpected-frontend", "`frontend` is only valid for full-stack projects")
    if bp.architecture == "microservices" and bp.layout != "multi-service":
        err("layout", "microservices architecture needs layout 'multi-service'")
    if bp.services and (bp.layout != "multi-service" or t == "frontend"):
        err("services", "`services` only applies to backend projects with layout 'multi-service'")
    for s in bp.services:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", s):
            err("service-name", f"invalid service name {s!r} (lowercase letters, digits, '-')")
    if len(set(bp.services)) != len(bp.services):
        err("service-name", "duplicate service names")
    if out:
        return out

    apps = derive_apps(bp)
    for a in apps:
        p = PRESETS[a.framework]
        if a.architecture not in p.architectures:
            err("architecture", f"{a.framework} does not support architecture {a.architecture!r}; "
                                f"supported: {list(p.architectures)}")
    feats = effective_features(bp)
    for fid, cfg in feats.items():
        f = FEATURES.get(fid)
        if not f:
            err("unknown-feature", f"unknown feature {fid!r}; available: {sorted(FEATURES)}")
            continue
        for r in f.requires:
            if r not in feats:
                err("requires", f"feature {fid!r} requires {r!r}")
        for c in f.conflicts_with:
            if c in feats:
                err("conflict", f"feature {fid!r} conflicts with {c!r}")
        if f.scope == "app" and not any(f.applies_to(a) for a in apps):
            err("incompatible", f"feature {fid!r} does not support the selected framework(s)")
        for k in cfg:
            if k not in f.inputs:
                err("config", f"feature {fid!r} has no setting {k!r}; settings: {sorted(f.inputs)}")
        for msg in f.check(feats):
            err("config", f"feature {fid!r}: {msg}")
    return out


def validate_plan(plan: Plan) -> list[Issue]:
    out = list(plan.issues)
    for c in plan.conflicts:
        out.append(Issue("error", "file-conflict",
                         f"{c.path} is provided by both {c.first} and {c.second}; remove one feature or override the file", c.path))
    lowered: dict[str, str] = {}
    paths = set(plan.entries) | set(plan.dirs)
    for p in sorted(paths):
        try:
            normalize(p)
        except UnsafePathError as exc:
            out.append(Issue("error", "unsafe-path", str(exc), p))
            continue
        if p.lower() in lowered and lowered[p.lower()] != p:
            out.append(Issue("error", "case-collision", f"{p} and {lowered[p.lower()]} differ only by case", p))
        lowered[p.lower()] = p
        parts = p.split("/")
        for i in range(1, len(parts)):
            if "/".join(parts[:i]) in plan.entries:
                out.append(Issue("error", "file-vs-folder", f"{'/'.join(parts[:i])} is a file but {p} needs it to be a folder", p))
    for p, e in plan.entries.items():
        name = p.rsplit("/", 1)[-1]
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            out.append(Issue("error", "env-file", f"{p}: real env files must not be generated; use .env.example", p))
        for m in _SECRET.finditer(e.content):
            if not _PLACEHOLDER.search(m.group(0)):
                out.append(Issue("warning", "possible-secret", f"{p} may contain a hardcoded secret", p))
                break
    return out
