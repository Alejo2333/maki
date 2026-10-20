"""All pinned dependency versions live here: updating a preset's stack is a one-line change."""

PYTHON = {
    "fastapi": "0.115.6", "uvicorn[standard]": "0.34.0", "pydantic-settings": "2.7.0",
    "flask": "3.1.0", "gunicorn": "23.0.0", "sqlalchemy": "2.0.36", "alembic": "1.14.0",
    "psycopg[binary]": "3.2.3", "pymysql": "1.1.1", "pytest": "8.3.4", "httpx": "0.28.1",
    "ruff": "0.8.4", "mypy": "1.14.0",
}
NODE = {
    "react": "^18.3.1", "react-dom": "^18.3.1", "vite": "^6.0.5", "@vitejs/plugin-react": "^4.3.4",
    "typescript": "^5.7.2", "@types/react": "^18.3.18", "@types/react-dom": "^18.3.5",
    "vitest": "^2.1.8", "jsdom": "^25.0.1", "@testing-library/react": "^16.1.0",
    "@testing-library/jest-dom": "^6.6.3", "prettier": "^3.4.2",
}


def pin(eco: str, name: str) -> str:
    if eco.startswith("python"):
        return f"=={PYTHON[name]}"
    return NODE[name]
