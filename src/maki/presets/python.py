"""FastAPI and Flask presets, sharing one architecture-aware layout."""

from __future__ import annotations

from ..plan import AppSpec, ScopedPlan, dumps_json  # noqa: F401
from ..registry import Preset, register_preset

Loc = tuple[str, str]  # (file path, dotted module)


def _style(arch: str) -> str:
    return {"microservices": "layer", "custom": "minimal"}.get(arch, arch)


def loc(app: AppSpec, kind: str, name: str) -> Loc:
    s = _style(app.architecture)
    if s == "minimal":
        stem = name if kind == "core" else f"{name}_{'routes' if kind == 'router' else 'models'}"
        parts = ["app", stem]
    elif s == "layer":
        parts = ["app", {"core": "core", "router": "api/routers", "model": "models"}[kind], name]
    else:  # feature / modular-monolith
        group = "modules" if s == "modular-monolith" else "features"
        parts = ["app", "core", name] if kind == "core" else ["app", group, name, "router" if kind == "router" else "models"]
    path = "/".join(parts)
    return path + ".py", path.replace("/", ".")


def mods(app: AppSpec) -> dict[str, str]:
    return {
        "config": loc(app, "core", "config")[1],
        "database": loc(app, "core", "database")[1],
        "db_models": "app.db_models",
        "main": "app.main" if app.framework == "fastapi" else "app",
    }


def py_put(sp: ScopedPlan, where: Loc, content: str, **kw) -> None:
    sp.put(where[0], content, **kw)
    parts = where[0].split("/")[:-1]
    for i in range(1, len(parts) + 1):
        sp.put("/".join(parts[:i]) + "/__init__.py", "", weak=True)


CONFIG = '''from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "{{ project.name }}"
    environment: str = "development"
{% for line in ext.settings %}
    {{ line }}
{% endfor %}


settings = Settings()
'''

FASTAPI_ROUTER = '''from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
'''

FLASK_ROUTER = '''from flask import Blueprint

bp = Blueprint("health", __name__)


@bp.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
'''

FASTAPI_MAIN = '''from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

{% for line in imports %}
{{ line }}
{% endfor %}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
{% for line in ext.startup %}
    {{ line }}
{% endfor %}
    yield
{% for line in ext.shutdown %}
    {{ line }}
{% endfor %}


app = FastAPI(title=settings.app_name, lifespan=lifespan)
{% for r in ext.routers %}
app.include_router({{ r.alias }})
{% endfor %}
'''

FLASK_INIT = '''from flask import Flask

{% for line in imports %}
{{ line }}
{% endfor %}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["APP_NAME"] = settings.app_name
{% for line in ext.startup %}
    {{ line }}
{% endfor %}
{% for r in ext.routers %}
    app.register_blueprint({{ r.alias }})
{% endfor %}
    return app
'''


def sorted_imports(sp: ScopedPlan) -> list[str]:
    """First-party imports in ruff/isort order: plain `import` first, then `from`, by module."""
    lines = [f"from {sp.render('{{ m.config }}')} import settings", *sp.plan.ext[sp.root]["imports"],
             *(f"from {r['module']} import {r['attr']} as {r['alias']}" for r in sp.plan.ext[sp.root]["routers"])]
    return sorted(set(lines), key=lambda ln: (not ln.startswith("import "), ln.split()[1]))


class _PyPreset(Preset):
    kind, language = "backend", "python"
    architectures = ("minimal", "layer", "feature", "modular-monolith", "microservices", "custom")
    router_src: str
    router_attr: str

    def build(self, sp: ScopedPlan) -> None:
        app = sp.app
        assert app
        file, module = loc(app, "router", "health")
        py_put(sp, (file, module), self.router_src)
        sp.add_ext("routers", {"module": module, "attr": self.router_attr, "alias": "health_router"})
        if _style(app.architecture) == "modular-monolith":
            sp.put("app/modules/README.md",
                   "# Modules\n\nEach module owns its router, models and logic. "
                   "Import other modules only through their router/public surface.\n", templ=False)
        for dep in self.deps:
            sp.dep(dep)
        sp.dep("pydantic-settings")

    def finalize(self, sp: ScopedPlan) -> None:
        app = sp.app
        assert app
        py_put(sp, loc(app, "core", "config"), CONFIG)
        self.write_entry(sp)
        runtime = sp.plan.deps[(sp.root, "python")]
        sp.put("requirements.txt", "".join(f"{n}{s}\n" for n, s in sorted(runtime.items())), templ=False)
        dev = sp.plan.deps[(sp.root, "python-dev")]
        if dev:
            sp.put("requirements-dev.txt", "-r requirements.txt\n" + "".join(f"{n}{s}\n" for n, s in sorted(dev.items())), templ=False)
        if sp.plan.ext[sp.root]["pyproject"]:
            sp.put("pyproject.toml", "\n".join(sp.plan.ext[sp.root]["pyproject"]), templ=False)


@register_preset
class FastAPI(_PyPreset):
    id, label = "fastapi", "FastAPI"
    router_src, router_attr = FASTAPI_ROUTER, "router"
    deps = ("fastapi", "uvicorn[standard]")

    def write_entry(self, sp: ScopedPlan) -> None:
        py_put(sp, ("app/main.py", "app.main"), FASTAPI_MAIN, imports=sorted_imports(sp))


@register_preset
class Flask(_PyPreset):
    id, label = "flask", "Flask"
    router_src, router_attr = FLASK_ROUTER, "bp"
    deps = ("flask",)

    def write_entry(self, sp: ScopedPlan) -> None:
        sp.put("app/__init__.py", FLASK_INIT, imports=sorted_imports(sp))
        sp.put("wsgi.py", "from app import create_app\n\napp = create_app()\n", templ=False)
