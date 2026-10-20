import ast
import json
import os

import pytest
from typer.testing import CliRunner

from maki.cli import app as cli
from maki.errors import UnsafePathError, WriteError, errors
from maki.migrations import migrate
from maki.paths import normalize
from maki.registry import FEATURES, PRESETS, load_all
from maki.service import plan_for
from maki.writer import write_plan

load_all()


def bp(**kw):
    d = {"project": {"name": "Demo App"}, "stack": {"framework": "fastapi"}}
    d.update(kw)
    return d


def plan(**kw):
    _, p, issues = plan_for(bp(**kw))
    return p, issues


@pytest.mark.parametrize("bad", ["/etc/passwd", "../x", "a/../../x", "C:/x", "a/CON", "a/b.", "", "~/x"])
def test_unsafe_paths_rejected(bad):
    with pytest.raises(UnsafePathError):
        normalize(bad)


def test_normalize_ok():
    assert normalize("a\\b//./c.py") == "a/b/c.py"


def test_migration_rejects_newer():
    with pytest.raises(Exception, match="upgrade Maki"):
        migrate({"schema_version": 99})


def test_migration_chain(monkeypatch):
    import maki.migrations as m

    monkeypatch.setattr(m, "SCHEMA_VERSION", 2)
    monkeypatch.setitem(m.MIGRATIONS, 1, lambda d: {**d, "migrated": True})
    out = m.migrate({"schema_version": 1})
    assert out["schema_version"] == 2 and out["migrated"]


def _all_valid(p):
    for e in p.files():
        if e.path.endswith(".py"):
            ast.parse(e.content, e.path)
        if e.path.endswith(".json"):
            json.loads(e.content)


PY_FEATS = [f.id for f in FEATURES.values() if f.id not in ("alembic", "compose")]


@pytest.mark.parametrize("fw,arch", [(f, a) for f in ("fastapi", "flask") for a in PRESETS[f].architectures])
def test_python_matrix(fw, arch):
    layout = {"layout": "multi-service", "services": ["api", "worker"]} if arch == "microservices" else {}
    feats = {"database": {"engine": "postgresql"}, "alembic": {}, "tests": {}, "lint": {}, "docker": {}, "docs": {}, "ci": {}}
    p, issues = plan(stack={"framework": fw}, architecture=arch, features=feats, deployment="compose", **layout)
    assert not errors(issues), issues
    _all_valid(p)


@pytest.mark.parametrize("arch", PRESETS["react-vite"].architectures)
def test_vite_matrix(arch):
    p, issues = plan(project_type="frontend", stack={"framework": "react-vite"}, architecture=arch,
                     features={"tests": {}, "lint": {}, "docker": {}, "ci": {}})
    assert not errors(issues), issues
    _all_valid(p)


def test_full_stack_layout_and_proxy():
    p, issues = plan(project_type="full-stack", layout="monorepo", frontend={"framework": "react-vite"},
                     features={"tests": {}}, deployment="compose")
    assert not errors(issues), issues
    paths = set(p.entries)
    assert {"backend/app/main.py", "frontend/src/App.tsx", "docker-compose.yml"} <= paths
    assert "localhost:8000" in p.entries["frontend/vite.config.ts"].content


def test_microservices_roots():
    p, issues = plan(architecture="microservices", layout="multi-service", services=["api", "worker"])
    assert not errors(issues)
    assert "services/api/app/main.py" in p.entries and "services/worker/app/main.py" in p.entries


@pytest.mark.parametrize("kw,code", [
    ({"stack": {"framework": "nope"}}, "unknown-framework"),
    ({"features": {"alembic": {}}}, "requires"),
    ({"features": {"database": {"engine": "oracle"}}}, "config"),
    ({"features": {"tests": {"x": 1}}}, "config"),
    ({"architecture": "microservices"}, "layout"),
    ({"project_type": "full-stack", "layout": "monorepo"}, "missing-frontend"),
    ({"stack": {"framework": "react-vite"}}, "wrong-kind"),
])
def test_validation_errors(kw, code):
    _, issues = plan(**kw)
    assert code in {i.code for i in errors(issues)}


def test_overrides():
    p, issues = plan(overrides=[
        {"op": "add", "path": "app/extra.py", "mode": "custom", "content": "x = '{{ var.k }}'\n", "render": True},
        {"op": "add", "path": "docs/", "mode": "empty"},
        {"op": "move", "path": "app/api", "to": "app/http"},
        {"op": "remove", "path": "README.md"},
        {"op": "set_content", "path": "app/main.py", "mode": "custom", "content": "# mine\n"},
    ], variables={"k": "v"})
    assert not errors(issues), issues
    assert p.entries["app/extra.py"].content == "x = 'v'\n" and "docs" in p.dirs
    assert "app/http/routers/health.py" in p.entries and "README.md" not in p.entries
    assert p.entries["app/main.py"].origin == "user"
    assert any(i.code == "moved-owned-file" for i in issues)


def test_folder_overrides_move_contents_and_empty_folders():
    p, issues = plan(overrides=[
        {"op": "add", "path": "custom/empty/", "mode": "empty"},
        {"op": "add", "path": "custom/nested/file.txt", "mode": "empty"},
        {"op": "move", "path": "custom", "to": "renamed"},
    ])
    assert not errors(issues), issues
    assert "renamed/empty" in p.dirs
    assert "renamed/nested/file.txt" in p.entries
    assert not any(path == "custom" or path.startswith("custom/") for path in (*p.entries, *p.dirs))


def test_override_traversal_blocked():
    _, issues = plan(overrides=[{"op": "add", "path": "../evil.py", "mode": "empty"}])
    assert "unsafe-path" in {i.code for i in errors(issues)}


def test_env_file_blocked_and_undefined_var_errors():
    _, issues = plan(overrides=[{"op": "add", "path": ".env", "mode": "empty"}])
    assert "env-file" in {i.code for i in errors(issues)}
    _, issues = plan(overrides=[{"op": "add", "path": "a.txt", "content": "{{ nope }}", "render": True}])
    assert "build-failed" in {i.code for i in errors(issues)}


def test_file_conflict_reported():
    _, issues = plan(overrides=[{"op": "add", "path": "app/main.py/x.py", "mode": "empty"}])
    assert "file-vs-folder" in {i.code for i in errors(issues)}


def test_writer_refuses_nonempty_and_overwrite(tmp_path):
    p, _ = plan()
    dest = tmp_path / "out"
    write_plan(p, dest)
    assert (dest / "app/main.py").exists()
    with pytest.raises(WriteError, match="not empty"):
        write_plan(p, dest)
    with pytest.raises(WriteError, match="overwrite"):
        write_plan(p, dest, merge=True)
    (dest / "app/main.py").write_text("mine")
    write_plan(p, dest, merge=True, overwrite=True)
    assert (dest / "app/main.py").read_text() != "mine"


def test_merge_does_not_touch_other_files_and_dry_run(tmp_path):
    p, _ = plan()
    (tmp_path / "keep.txt").write_text("k")
    r = write_plan(p, tmp_path, dry_run=True) if False else write_plan(p, tmp_path, merge=True, dry_run=True)
    assert r.dry_run and not (tmp_path / "app").exists()
    write_plan(p, tmp_path, merge=True)
    assert (tmp_path / "keep.txt").read_text() == "k" and (tmp_path / "app/main.py").exists()


def test_merge_rollback_on_failure(tmp_path, monkeypatch):
    p, _ = plan()
    (tmp_path / "keep.txt").write_text("k")
    import maki.writer as w

    calls = {"n": 0}
    real = w.shutil.copy2

    def flaky(a, b, *x, **k):
        calls["n"] += 1
        if calls["n"] == 5:
            raise OSError("disk full")
        return real(a, b, *x, **k)

    monkeypatch.setattr(w.shutil, "copy2", flaky)
    with pytest.raises(WriteError):
        write_plan(p, tmp_path, merge=True)
    assert sorted(os.listdir(tmp_path)) == ["keep.txt"]


def test_failed_new_write_leaves_nothing(tmp_path, monkeypatch):
    p, _ = plan()
    import maki.writer as w

    monkeypatch.setattr(w.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(WriteError):
        write_plan(p, tmp_path / "out")
    assert os.listdir(tmp_path) == []


def test_symlink_escape_blocked(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    try:
        (dest / "app").symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("creating symlinks requires the Windows symlink privilege")
        raise
    p, _ = plan()
    with pytest.raises(UnsafePathError):
        write_plan(p, dest, merge=True, overwrite=True)
    assert not list(outside.iterdir())


def test_plan_equals_output(tmp_path):
    p, _ = plan(features={"tests": {}, "lint": {}})
    write_plan(p, tmp_path / "o")
    on_disk = {str(f.relative_to(tmp_path / "o")).replace("\\", "/"): f.read_text()
               for f in (tmp_path / "o").rglob("*") if f.is_file()}
    assert on_disk == {e.path: e.content for e in p.files()}


def test_cli_roundtrip(tmp_path):
    r = CliRunner()
    out = r.invoke(cli, ["new", "Demo", "-f", "fastapi", "--feature", "tests", "--save", str(tmp_path / "b.json"), "-o", str(tmp_path / "p")])
    assert out.exit_code == 0, out.output
    assert r.invoke(cli, ["validate", str(tmp_path / "b.json")]).exit_code == 0
    again = r.invoke(cli, ["generate", str(tmp_path / "b.json"), "-o", str(tmp_path / "p")])
    assert again.exit_code == 1 and "not empty" in again.output


def test_api_security():
    from fastapi.testclient import TestClient

    from maki.api import create_app

    c = TestClient(create_app("tok"), base_url="http://testserver")
    assert c.get("/api/catalog").status_code == 401
    h = {"X-Maki-Token": "tok"}
    assert c.get("/api/catalog", headers=h).status_code == 200
    assert c.get("/api/catalog", headers={**h, "Origin": "http://evil.example"}).status_code == 403
    assert c.get("/api/catalog", headers={**h, "Host": "evil.example"}).status_code == 403
    r = c.post("/api/plan", headers=h, json={"blueprint": bp()})
    assert r.json()["ok"] and r.json()["files"]


def test_public_api_allows_preview_but_not_filesystem_generation():
    from fastapi.testclient import TestClient

    from maki.api import create_app

    c = TestClient(create_app(token=None, allow_generate=False), base_url="https://studio.example")
    assert c.get("/api/catalog").status_code == 200
    r = c.post("/api/plan", json={"blueprint": bp()})
    assert r.status_code == 200 and r.json()["files"]
    assert c.post(
        "/api/plan",
        headers={"Origin": "https://attacker.example"},
        json={"blueprint": bp()},
    ).status_code == 403
    assert c.post(
        "/api/plan",
        headers={"Origin": "https://studio.example/unexpected-path"},
        json={"blueprint": bp()},
    ).status_code == 403
    assert c.post(
        "/api/generate",
        json={"blueprint": bp(), "destination": "should-not-be-written"},
    ).status_code == 404


def test_api_generate(tmp_path):
    from fastapi.testclient import TestClient

    from maki.api import create_app

    c = TestClient(create_app("t"), base_url="http://testserver")
    r = c.post("/api/generate", headers={"X-Maki-Token": "t"}, json={"blueprint": bp(), "destination": str(tmp_path / "x")})
    assert r.status_code == 200 and (tmp_path / "x/app/main.py").exists()
    r = c.post("/api/generate", headers={"X-Maki-Token": "t"}, json={"blueprint": bp(), "destination": str(tmp_path / "x")})
    assert r.status_code == 409
