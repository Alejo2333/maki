# Maki

 Presets are starting points, never restrictions.

The blueprint is data, generation is a pure pipeline:

```
Blueprint (JSON) -> Resolve -> Plan (virtual tree) -> Validate -> Write
```

Preview shows the Plan and generation writes the same Plan, so they cannot disagree.
The CLI and the browser Studio are thin clients over `maki.service`. Studio downloads
the validated project as a ZIP in the browser; it does not write generated files to
the Studio server's filesystem.

## Install and use

```bash
pip install -e ".[dev]"
maki presets                                   # frameworks, architectures, features
maki new Shop -f fastapi --feature database:engine=postgresql --feature alembic \
     --feature tests --feature lint --deployment compose -o ./shop --save shop.json
maki new Shop -f fastapi --frontend react-vite --feature tests -o ./shop-fs   # full-stack
maki init                                      # guided wizard (custom files, per-file content)
maki plan shop.json | maki validate shop.json
maki generate shop.json -o ./out [--merge [--overwrite]] [--dry-run] [--set key=value]
maki studio                                    # browser UI on 127.0.0.1 with a one-time token
```

## Deploy the Studio to Vercel

The repository includes a Vercel FastAPI entrypoint at `index.py`. Import this
repository into Vercel and deploy from the repository root; Vercel installs the
runtime dependencies from `pyproject.toml`. The deployed Studio allows public
catalog, migration, and preview requests, but disables `/api/generate`: projects
are downloaded as ZIPs in the browser, so the deployment never writes them to
the server filesystem. Use Vercel Deployment Protection if the Studio should
only be accessible to a private team.

## What is supported

| Area | Included |
|---|---|
| Frameworks | FastAPI, Flask, React + Vite (TypeScript) |
| Architectures | minimal, layer, feature, modular-monolith, microservices, custom (React: minimal/layer/feature/custom) |
| Layout / deployment | single, monorepo, multi-service; none, container, compose (separate settings) |
| Features | database (SQLite/Postgres/MySQL), alembic, tests, lint, docker, compose, ci (GitHub Actions), docs |
| Customization | add / remove / move files and folders, per-file content (preset, empty, starter, custom, optionally Jinja-rendered), template variables |
| Safety | traversal, symlink, Windows-reserved and case-collision checks; conflict detection with origin; no `.env` output; atomic new-project writes; rollback on merge; no overwrite without `--overwrite` |

Not built yet: Django and Next.js presets, auth/RBAC/scheduler features, template packs, a React-based Studio
(the shipped Studio is a no-build single HTML file), and plugin examples (the `maki.plugins` entry-point hook exists).

## Extending

A preset subclasses `Preset` (`build`, `finalize`); a feature subclasses `Feature` (`requires`, `frameworks`,
`inputs`, `apply`). Register with `@register_preset` / `@register_feature`, or ship them in a package that exposes the
`maki.plugins` entry point. Features contribute to extension points (`sp.add_ext("routers", ...)`, `settings`,
`imports`, `startup`) and the preset writes the entrypoint last, so features never patch each other's files.
Dependency pins live in `src/maki/versions.py`.

## Tests

```bash
pytest              # 49 fast tests: path safety, matrix over every preset x architecture, writer, CLI, API
pytest -m smoke     # generates real projects, installs them, runs their own ruff + pytest
```

Blueprint schema changes: bump `SCHEMA_VERSION` and add a `v(n) -> v(n+1)` function in `migrations.py`.
