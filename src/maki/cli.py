"""Maki CLI. It only builds a Blueprint and calls the shared pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .errors import MakiError, errors
from .migrations import load_blueprint_data
from .service import catalog, plan_for
from .writer import write_plan

app = typer.Typer(help="Maki: your project, your structure, your way.", no_args_is_help=True)


def _show_issues(issues) -> None:
    for i in issues:
        typer.secho(f"  {i.level}: {i.message}", fg="red" if i.level == "error" else "yellow", err=True)


def _load(path: Path, sets: list[str] | None = None):
    data = load_blueprint_data(path)
    for s in sets or []:
        k, _, v = s.partition("=")
        data.setdefault("variables", {})[k] = v
    return plan_for(data)


def _fail(exc: Exception):
    typer.secho(f"error: {exc}", fg="red", err=True)
    raise typer.Exit(1)


@app.command()
def version() -> None:
    typer.echo(__version__)


@app.command()
def presets() -> None:
    """List frameworks, architectures and features."""
    c = catalog()
    for p in c["presets"]:
        typer.echo(f"{p['id']:12} {p['kind']:9} architectures: {', '.join(p['architectures'])}")
    typer.echo("")
    for f in c["features"]:
        typer.echo(f"{f['id']:10} {f['description']}  inputs={list(f['inputs']) or '-'}")


@app.command()
def schema() -> None:
    """Print the blueprint JSON schema."""
    typer.echo(json.dumps(catalog()["schema"], indent=2))


@app.command()
def plan(blueprint: Path, as_json: bool = typer.Option(False, "--json")) -> None:
    """Preview the file tree without writing anything."""
    try:
        _, p, issues = _load(blueprint)
    except MakiError as exc:
        _fail(exc)
    if as_json:
        typer.echo(json.dumps({"files": [{"path": e.path, "origin": e.origin} for e in p.files()],
                               "issues": [i.to_dict() for i in issues]}, indent=2))
    else:
        typer.echo(p.tree_text())
        _show_issues(issues)
    raise typer.Exit(1 if errors(issues) else 0)


@app.command()
def validate(blueprint: Path) -> None:
    """Validate a blueprint."""
    try:
        _, _, issues = _load(blueprint)
    except MakiError as exc:
        _fail(exc)
    _show_issues(issues)
    typer.echo("invalid" if errors(issues) else "ok")
    raise typer.Exit(1 if errors(issues) else 0)


@app.command()
def generate(
    blueprint: Path,
    dest: Path = typer.Option(..., "--dest", "-o", help="Destination directory"),
    merge: bool = typer.Option(False, help="Allow writing into a non-empty directory"),
    overwrite: bool = typer.Option(False, help="With --merge, replace files that already exist"),
    dry_run: bool = typer.Option(False, help="Show what would happen, write nothing"),
    set_: Optional[list[str]] = typer.Option(None, "--set", help="Template variable key=value"),
) -> None:
    """Generate a project from a blueprint."""
    try:
        _, p, issues = _load(blueprint, set_)
        _show_issues(issues)
        if errors(issues):
            raise typer.Exit(1)
        report = write_plan(p, dest, merge=merge, overwrite=overwrite, dry_run=dry_run)
    except MakiError as exc:
        _fail(exc)
    verb = "Would create" if dry_run else "Created"
    typer.echo(f"{verb} {len(report.created)} files, overwrote {len(report.overwritten)} in {report.destination}")


@app.command()
def new(
    name: str,
    framework: str = typer.Option("fastapi", "--framework", "-f"),
    frontend: Optional[str] = typer.Option(None, help="Frontend framework (makes it full-stack)"),
    architecture: str = typer.Option("layer", "--arch", "-a"),
    layout: str = typer.Option("single"),
    deployment: str = typer.Option("none"),
    feature: Optional[list[str]] = typer.Option(None, "--feature", help="id or id:key=value (repeatable)"),
    dest: Optional[Path] = typer.Option(None, "--dest", "-o"),
    save: Optional[Path] = typer.Option(None, "--save", help="Save the blueprint JSON here"),
) -> None:
    """Non-interactive: build a blueprint from flags, then preview or generate."""
    feats: dict[str, dict] = {}
    for f in feature or []:
        fid, _, rest = f.partition(":")
        feats[fid] = dict(kv.split("=", 1) for kv in rest.split(",") if kv)
    from .registry import load_all, PRESETS

    load_all()
    kind = PRESETS[framework].kind if framework in PRESETS else "backend"
    data = {"project": {"name": name}, "project_type": "frontend" if kind == "frontend" else "backend",
            "layout": layout, "architecture": architecture, "deployment": deployment,
            "stack": {"framework": framework}, "features": feats}
    if frontend:
        data.update(project_type="full-stack", layout="monorepo" if layout == "single" else layout,
                    frontend={"framework": frontend})
    _finish(data, dest, save)


def _finish(data: dict, dest: Optional[Path], save: Optional[Path]) -> None:
    try:
        _, p, issues = plan_for(data)
    except MakiError as exc:
        _fail(exc)
    if save:
        save.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        typer.echo(f"Saved blueprint to {save}")
    typer.echo(p.tree_text())
    _show_issues(issues)
    if errors(issues):
        raise typer.Exit(1)
    if dest:
        try:
            r = write_plan(p, dest)
        except MakiError as exc:
            _fail(exc)
        typer.echo(f"Created {len(r.created)} files in {r.destination}")


@app.command()
def init() -> None:
    """Guided setup: stack, architecture, features, custom files, preview, generate."""
    from .registry import FEATURES, PRESETS, load_all

    load_all()
    name = typer.prompt("Project name")
    fw = typer.prompt("Framework", type=typer.Choice(sorted(PRESETS)))
    kind = PRESETS[fw].kind
    arch = typer.prompt("Architecture", type=typer.Choice(list(PRESETS[fw].architectures)), default="layer"
                        if "layer" in PRESETS[fw].architectures else "minimal")
    data: dict = {"project": {"name": name}, "project_type": kind, "architecture": arch, "stack": {"framework": fw},
                  "deployment": typer.prompt("Deployment", type=typer.Choice(["none", "container", "compose"]), default="none"),
                  "features": {}, "overrides": []}
    if kind == "backend" and typer.confirm("Add a frontend (full-stack)?", default=False):
        data.update(project_type="full-stack", layout="monorepo",
                    frontend={"framework": typer.prompt("Frontend", type=typer.Choice(
                        [p for p, v in PRESETS.items() if v.kind == "frontend"]))})
    for f in FEATURES.values():
        if f.frameworks and fw not in f.frameworks and data.get("frontend", {}).get("framework") not in f.frameworks:
            continue
        if typer.confirm(f"Feature: {f.label}?", default=False):
            cfg = {k: typer.prompt(f"  {k}", type=typer.Choice(list(i.choices)) if i.choices else str, default=i.default)
                   for k, i in f.inputs.items()}
            data["features"][f.id] = cfg
    while typer.confirm("Add a custom file or folder?", default=False):
        path = typer.prompt("  Path (end with / for a folder)")
        if path.endswith("/"):
            data["overrides"].append({"op": "add", "path": path})
            continue
        mode = typer.prompt("  Content", type=typer.Choice(["empty", "starter", "custom"]), default="starter")
        content = typer.edit("") if mode == "custom" else None
        data["overrides"].append({"op": "add", "path": path, "mode": mode, "content": content})
    save = typer.prompt("Save blueprint to", default="maki.json")
    _finish(data, None, Path(save))
    if typer.confirm("Generate now?", default=True):
        _, p, issues = plan_for(data)
        if not errors(issues):
            r = write_plan(p, typer.prompt("Destination", default=f"./{p.base_ctx['project'].slug}"))
            typer.echo(f"Created {len(r.created)} files in {r.destination}")


@app.command()
def studio(port: int = 8765, open_browser: bool = typer.Option(True, "--open/--no-open")) -> None:
    """Start the browser Project Studio (localhost only, token-protected)."""
    import secrets
    import webbrowser

    import uvicorn

    from .api import create_app

    token = secrets.token_urlsafe(24)
    url = f"http://127.0.0.1:{port}/#token={token}"
    typer.echo(f"Maki Studio: {url}")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(token, port), host="127.0.0.1", port=port, log_level="warning")
