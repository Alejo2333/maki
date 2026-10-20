"""Docker, Compose, CI."""

from __future__ import annotations

from ..plan import ScopedPlan
from ..registry import Feature, register_feature

PY_DOCKER = '''FROM python:3.12-slim
WORKDIR /app
RUN useradd --create-home appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt{{ " gunicorn==23.0.0" if app.framework == "flask" else "" }}
COPY . .
USER appuser
EXPOSE {{ app.port }}
{% if app.framework == "fastapi" %}
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "{{ app.port }}"]
{% else %}
CMD ["gunicorn", "-b", "0.0.0.0:{{ app.port }}", "wsgi:app"]
{% endif %}
'''

NODE_DOCKER = '''FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
'''

IGNORE = ".git\n.env\n.venv\nnode_modules\n__pycache__\n*.db\n"

COMPOSE = '''services:
{% for a in apps %}
  {{ a.name }}:
    build: ./{{ a.root or "." }}
    ports:
      - "{{ a.port }}:{{ 80 if a.kind == "node" else a.port }}"
{% if a.kind == "python" %}
    env_file:
      - path: ./{{ a.root + "/" if a.root else "" }}.env
        required: false
{% if db %}
    environment:
      DATABASE_URL: {{ db_url }}
    depends_on:
      - db
{% endif %}
{% endif %}
{% endfor %}
{% if db %}
  db:
    image: {{ "postgres:16" if db == "postgresql" else "mysql:8" }}
    environment:
{% if db == "postgresql" %}
      POSTGRES_USER: app
      POSTGRES_PASSWORD: ${DB_PASSWORD:?set DB_PASSWORD in .env}
      POSTGRES_DB: app
{% else %}
      MYSQL_USER: app
      MYSQL_PASSWORD: ${DB_PASSWORD:?set DB_PASSWORD in .env}
      MYSQL_DATABASE: app
      MYSQL_RANDOM_ROOT_PASSWORD: "1"
{% endif %}
{% endif %}
'''


@register_feature
class Docker(Feature):
    id, label = "docker", "Docker"
    description = "Dockerfile and .dockerignore per app (never copies .env)."
    frameworks = ("fastapi", "flask", "react-vite")

    def apply(self, sp: ScopedPlan) -> None:
        sp.put("Dockerfile", PY_DOCKER if sp.app.kind == "python" else NODE_DOCKER)
        sp.put(".dockerignore", IGNORE, templ=False)


@register_feature
class Compose(Feature):
    id, label = "compose", "Docker Compose"
    description = "docker-compose.yml wiring every app (and the database, if any)."
    requires = ("docker",)
    scope = "project"

    def apply(self, sp: ScopedPlan) -> None:
        db = sp.features.get("database", {}).get("engine", "sqlite")
        db = "" if db == "sqlite" else db
        scheme = "postgresql+psycopg" if db == "postgresql" else "mysql+pymysql"
        url = f"{scheme}://app:${{DB_PASSWORD}}@db/app" if db else ""
        sp.put("docker-compose.yml", COMPOSE, db=db, db_url=url)
        if db:
            sp.env("DB_PASSWORD", "change-me", "Used by docker-compose for the database")


CI = '''name: CI
on: [push, pull_request]
jobs:
{% for a in apps %}
  {{ a.name }}:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: {{ a.root or "." }}
    steps:
      - uses: actions/checkout@v4
{% if a.kind == "python" %}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements{{ "-dev" if "tests" in features or "lint" in features else "" }}.txt
{% if "lint" in features %}
      - run: ruff check .
{% endif %}
{% if "tests" in features %}
      - run: pytest
{% endif %}
{% else %}
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: npm install
{% if "tests" in features %}
      - run: npm test
{% endif %}
      - run: npm run build
{% endif %}
{% endfor %}
'''


@register_feature
class CI_(Feature):
    id, label = "ci", "GitHub Actions CI"
    description = "One CI job per app: install, lint, test, build."
    scope = "project"

    def apply(self, sp: ScopedPlan) -> None:
        sp.put(".github/workflows/ci.yml", CI)
