"""Database and migrations."""

from __future__ import annotations

from ..plan import ScopedPlan
from ..presets.python import loc, py_put
from ..registry import Feature, Input, register_feature

DATABASE = '''from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from {{ m.config }} import settings

_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
'''

URLS = {
    "sqlite": "sqlite:///./app.db",
    "postgresql": "postgresql+psycopg://app:change-me@localhost:5432/app",
    "mysql": "mysql+pymysql://app:change-me@localhost:3306/app",
}


@register_feature
class Database(Feature):
    id, label = "database", "Database (SQLAlchemy)"
    description = "SQLAlchemy engine, session and declarative Base."
    frameworks = ("fastapi", "flask")
    inputs = {"engine": Input("choice", "sqlite", ("sqlite", "postgresql", "mysql"), "Database engine")}

    def check(self, features):
        eng = features.get("database", {}).get("engine", "sqlite")
        return [] if eng in self.inputs["engine"].choices else [f"engine must be one of {self.inputs['engine'].choices}"]

    def apply(self, sp: ScopedPlan) -> None:
        engine = sp.cfg.get("engine", "sqlite")
        py_put(sp, loc(sp.app, "core", "database"), DATABASE)
        sp.put("app/db_models.py", '"""Import every model module here so metadata is complete."""\n', templ=False)
        sp.add_ext("settings", 'database_url: str = "sqlite:///./app.db"' if engine == "sqlite" else "database_url: str")
        sp.env("DATABASE_URL", URLS[engine], "Replace the placeholder credentials before real use")
        sp.dep("sqlalchemy")
        if engine == "postgresql":
            sp.dep("psycopg[binary]")
        elif engine == "mysql":
            sp.dep("pymysql")
        if "alembic" not in sp.features:  # no migrations: create tables on startup
            sp.add_ext("imports", f"from {sp.render('{{ m.database }}')} import Base, engine")
            sp.add_ext("imports", "import app.db_models  # noqa: F401")
            sp.add_ext("startup", "Base.metadata.create_all(bind=engine)")


ENV_PY = '''from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.db_models  # noqa: F401
from {{ m.config }} import settings
from {{ m.database }} import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''

MAKO = '''"""${message}"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''


@register_feature
class Alembic(Feature):
    id, label = "alembic", "Alembic migrations"
    description = "Alembic wired to the SQLAlchemy Base."
    requires = ("database",)
    frameworks = ("fastapi", "flask")

    def apply(self, sp: ScopedPlan) -> None:
        sp.put("alembic.ini", "[alembic]\nscript_location = migrations\n", templ=False)
        sp.put("migrations/env.py", ENV_PY)
        sp.put("migrations/script.py.mako", MAKO, templ=False)
        sp.put("migrations/versions/.gitkeep", "", templ=False)
        sp.dep("alembic")
