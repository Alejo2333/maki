"""Slow: generate real projects, install them, run their own lint and tests. Run with: pytest -m smoke"""

import subprocess
import sys
import venv

import pytest

from maki.service import plan_for
from maki.writer import write_plan

CASES = {
    "fastapi-sqlite": {"stack": {"framework": "fastapi"}, "features": {"database": {}, "alembic": {}, "tests": {}, "lint": {}}},
    "fastapi-feature": {"stack": {"framework": "fastapi"}, "architecture": "feature", "features": {"database": {}, "tests": {}, "lint": {}}},
    "flask-minimal": {"stack": {"framework": "flask"}, "architecture": "minimal", "features": {"database": {}, "tests": {}, "lint": {}}},
}


@pytest.mark.smoke
@pytest.mark.parametrize("name", CASES)
def test_generated_project_passes_its_own_checks(name, tmp_path):
    _, plan, issues = plan_for({"project": {"name": "Smoke"}, **CASES[name]})
    write_plan(plan, tmp_path / "p")
    venv.create(tmp_path / "v", with_pip=True)
    py = str(tmp_path / "v/bin/python")
    run = lambda *a: subprocess.run([py, "-m", *a], cwd=tmp_path / "p", capture_output=True, text=True)  # noqa: E731
    r = run("pip", "install", "-q", "-r", "requirements-dev.txt")
    assert r.returncode == 0, r.stderr
    for cmd in (("ruff", "check", "."), ("pytest", "-q")):
        r = run(*cmd)
        assert r.returncode == 0, r.stdout + r.stderr
