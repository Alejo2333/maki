"""React + Vite (TypeScript) preset."""

from __future__ import annotations

from ..plan import ScopedPlan, dumps_json
from ..registry import Preset, register_preset

INDEX_HTML = '''<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{{ project.name }}</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
'''

VITE_CONFIG = '''import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
{% set backend = apps | selectattr("kind", "equalto", "python") | list %}

export default defineConfig({
  plugins: [react()],
{% if backend %}
  server: { proxy: { "/api": { target: "http://localhost:{{ backend[0].port }}", rewrite: (p) => p.replace(/^\\/api/, "") } } },
{% endif %}
});
'''

TSCONFIG = dumps_json({
    "compilerOptions": {
        "target": "ES2020", "lib": ["ES2020", "DOM", "DOM.Iterable"], "module": "ESNext",
        "moduleResolution": "bundler", "jsx": "react-jsx", "strict": True, "noEmit": True,
        "skipLibCheck": True, "isolatedModules": True, "types": ["vite/client"],
    },
    "include": ["src", "vite.config.ts", "vitest.config.ts"],
})

MAIN = '''import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
'''

APP = '''import { useEffect, useState } from "react";
{% if app.architecture in ("layer",) %}
import { fetchHealth } from "./services/api";
{% elif app.architecture == "feature" %}
import { fetchHealth } from "./features/health/api";
{% endif %}

export default function App() {
  const [status, setStatus] = useState("checking...");
  useEffect(() => {
{% if app.architecture in ("layer", "feature") %}
    fetchHealth().then(setStatus).catch(() => setStatus("backend unreachable"));
{% elif apps | length > 1 %}
    fetch("/api/health").then((r) => r.json()).then((d) => setStatus(d.status)).catch(() => setStatus("backend unreachable"));
{% else %}
    setStatus("ready");
{% endif %}
  }, []);

  return (
    <main>
      <h1>{{ project.name }}</h1>
      <p>Status: {status}</p>
    </main>
  );
}
'''

API = '''export async function fetchHealth(): Promise<string> {
{% if apps | length > 1 %}
  const res = await fetch("/api/health");
  const data = (await res.json()) as { status: string };
  return data.status;
{% else %}
  return "ready";
{% endif %}
}
'''


@register_preset
class ReactVite(Preset):
    id, label = "react-vite", "React + Vite (TypeScript)"
    kind, language, port = "frontend", "node", 5173
    architectures = ("minimal", "layer", "feature", "custom")

    def build(self, sp: ScopedPlan) -> None:
        app = sp.app
        assert app
        sp.put("index.html", INDEX_HTML)
        sp.put("vite.config.ts", VITE_CONFIG)
        sp.put("tsconfig.json", TSCONFIG, templ=False)
        sp.put("src/main.tsx", MAIN, templ=False)
        sp.put("src/App.tsx", APP)
        sp.put("src/index.css", "body {\n  font-family: system-ui, sans-serif;\n  margin: 2rem;\n}\n", templ=False)
        if app.architecture == "layer":
            sp.put("src/services/api.ts", API)
            for d in ("components", "hooks", "types"):
                sp.put(f"src/{d}/.gitkeep", "", templ=False)
        elif app.architecture == "feature":
            sp.put("src/features/health/api.ts", API)
        for name in ("react", "react-dom"):
            sp.dep(name)
        for name in ("vite", "@vitejs/plugin-react", "typescript", "@types/react", "@types/react-dom"):
            sp.dep(name, dev=True)
        sp.script("dev", "vite")
        sp.script("build", "tsc --noEmit && vite build")
        sp.script("preview", "vite preview")

    def finalize(self, sp: ScopedPlan) -> None:
        pkg = {
            "name": sp.plan.base_ctx["project"].slug if sp.root == "" else sp.app.name,
            "private": True, "version": "0.1.0", "type": "module",
            "scripts": dict(sp.plan.ext[sp.root]["scripts"]),
            "dependencies": dict(sorted(sp.plan.deps[(sp.root, "node")].items())),
            "devDependencies": dict(sorted(sp.plan.deps[(sp.root, "node-dev")].items())),
        }
        sp.put("package.json", dumps_json(pkg), templ=False)
