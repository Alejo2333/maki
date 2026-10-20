"""Tests, lint/format, docs."""

from __future__ import annotations

from ..plan import ScopedPlan, dumps_json
from ..registry import Feature, register_feature

CONFTEST = '''import os

{% if "database" in features %}
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
{% endif %}
'''

FASTAPI_TEST = '''from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}
'''

FLASK_TEST = '''from app import create_app


def test_health() -> None:
    response = create_app().test_client().get("/health")
    assert response.get_json() == {"status": "ok"}
'''

VITEST_CONFIG = '''import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom", setupFiles: ["./src/setupTests.ts"] },
});
'''

APP_TEST = '''import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import App from "./App";

test("renders the project name", () => {
  render(<App />);
  expect(screen.getByText("{{ project.name }}")).toBeInTheDocument();
});
'''


@register_feature
class Tests(Feature):
    id, label = "tests", "Unit tests"
    description = "pytest (Python) or Vitest + Testing Library (React)."
    frameworks = ("fastapi", "flask", "react-vite")

    def apply(self, sp: ScopedPlan) -> None:
        if sp.app.kind == "python":
            sp.put("tests/conftest.py", CONFTEST)
            sp.put("tests/test_health.py", FASTAPI_TEST if sp.app.framework == "fastapi" else FLASK_TEST, templ=False)
            sp.add_ext("pyproject", '[tool.pytest.ini_options]\npythonpath = ["."]\ntestpaths = ["tests"]\n')
            sp.dep("pytest", dev=True)
            sp.dep("httpx", dev=True)
        else:
            sp.put("vitest.config.ts", VITEST_CONFIG, templ=False)
            sp.put("src/setupTests.ts", 'import "@testing-library/jest-dom/vitest";\n', templ=False)
            sp.put("src/App.test.tsx", APP_TEST)
            for d in ("vitest", "jsdom", "@testing-library/react", "@testing-library/jest-dom"):
                sp.dep(d, dev=True)
            sp.script("test", "vitest run")


@register_feature
class Lint(Feature):
    id, label = "lint", "Linting and formatting"
    description = "ruff + mypy (Python) or Prettier (Node)."
    frameworks = ("fastapi", "flask", "react-vite")

    def apply(self, sp: ScopedPlan) -> None:
        if sp.app.kind == "python":
            sp.add_ext("pyproject", '[tool.ruff]\nline-length = 100\n\n[tool.ruff.lint]\nselect = ["E", "F", "I", "UP", "B"]\n\n[tool.mypy]\nignore_missing_imports = true\n')
            sp.dep("ruff", dev=True)
            sp.dep("mypy", dev=True)
        else:
            sp.put(".prettierrc.json", dumps_json({"printWidth": 100}), templ=False)
            sp.dep("prettier", dev=True)
            sp.script("format", "prettier --write src")
            sp.script("typecheck", "tsc --noEmit")


@register_feature
class Docs(Feature):
    id, label = "docs", "Documentation"
    description = "docs/architecture.md and docs/setup.md."
    scope = "project"

    def apply(self, sp: ScopedPlan) -> None:
        sp.put("docs/architecture.md", """# {{ project.name }} architecture

- Layout: `{{ blueprint.layout }}`; architecture: `{{ blueprint.architecture }}`; deployment: `{{ blueprint.deployment }}`
{% for a in apps %}
- `{{ a.root or "." }}`: {{ a.framework }} ({{ a.architecture }})
{% endfor %}
""")
        sp.put("docs/setup.md", """# Setup

{% for a in apps %}
## {{ a.name }} (`{{ a.root or "." }}`)
{% if a.kind == "python" %}
    cd {{ a.root or "." }}
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements{{ "-dev" if "tests" in features or "lint" in features else "" }}.txt
{% else %}
    cd {{ a.root or "." }}
    npm install
    npm run dev
{% endif %}

{% endfor %}
""")
