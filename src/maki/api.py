"""Project Studio API with token-protected local and preview-only public modes."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .errors import MakiError, errors
from .migrations import migrate
from .service import catalog, plan_for
from .writer import write_plan


class PlanRequest(BaseModel):
    blueprint: dict[str, Any]


class GenerateRequest(PlanRequest):
    destination: str
    merge: bool = False
    overwrite: bool = False


def create_app(
    token: str | None,
    port: int = 8765,
    *,
    allow_generate: bool | None = None,
) -> FastAPI:
    app = FastAPI(title="Maki Studio", docs_url=None, redoc_url=None, openapi_url=None)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", "testserver"}
    if allow_generate is None:
        allow_generate = token is not None

    @app.middleware("http")
    async def guard(request: Request, call_next):
        from fastapi.responses import JSONResponse

        origin = request.headers.get("origin")
        host = request.headers.get("host", "").lower()
        if token is not None:
            if host not in allowed_hosts:
                return JSONResponse({"detail": "bad host"}, status_code=403)
            if origin and origin.split("://", 1)[-1].lower() not in allowed_hosts:
                return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
        elif origin:
            from urllib.parse import urlsplit

            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.netloc.lower() != host
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
        return await call_next(request)

    def auth(x_maki_token: str | None = Header(default=None)) -> None:
        if token is None:
            return
        if not x_maki_token or not secrets.compare_digest(x_maki_token, token):
            raise HTTPException(401, "missing or wrong X-Maki-Token")

    def run_plan(req: PlanRequest):
        try:
            return plan_for(req.blueprint)
        except MakiError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (Path(__file__).parent / "studio" / "index.html").read_text(encoding="utf-8")

    @app.get("/api/catalog", dependencies=[Depends(auth)])
    def get_catalog():
        return catalog()

    @app.post("/api/migrate", dependencies=[Depends(auth)])
    def do_migrate(req: PlanRequest):
        try:
            return migrate(req.blueprint)
        except MakiError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/plan", dependencies=[Depends(auth)])
    def plan(req: PlanRequest):
        _, p, issues = run_plan(req)
        return {"ok": not errors(issues), "issues": [i.to_dict() for i in issues], "notes": p.notes,
                "files": [{"path": e.path, "origin": e.origin, "content": e.content} for e in p.files()],
                "dirs": sorted(p.dirs)}

    if allow_generate:
        @app.post("/api/generate", dependencies=[Depends(auth)])
        def generate(req: GenerateRequest):
            _, p, issues = run_plan(req)
            if errors(issues):
                raise HTTPException(422, "; ".join(i.message for i in errors(issues)))
            try:
                r = write_plan(p, req.destination, merge=req.merge, overwrite=req.overwrite)
            except MakiError as exc:
                raise HTTPException(409, str(exc)) from exc
            return {"destination": str(r.destination), "created": r.created, "overwritten": r.overwritten}

    return app
