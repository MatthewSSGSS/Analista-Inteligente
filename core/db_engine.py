"""Conexión opcional a una base de datos compartida (Postgres, p. ej.
Supabase) para el historial de "Análisis Seguimiento".

Por qué existe: con Streamlit, cada persona que abre la app tiene su propia
sesión aislada — si tú subes un Excel, tu compañero que abre el mismo link
NO lo ve, porque `st.session_state` no se comparte entre navegadores. Esta
pieza resuelve exactamente eso: el historial vive en una base de datos
central, así que todo el equipo ve siempre la misma información actualizada
con el mismo link, sin reenviar nada.

Es un complemento, no un reemplazo: si nadie configuró las credenciales en
`st.secrets`, el resto de la app sigue funcionando igual que antes (con el
flujo manual de exportar/subir el Excel consolidado).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from core.tracking_engine import CONSOLIDATED_COLUMNS

TABLE_NAME = "tracking_history"
_TO_DB = {"column": "column_name"}
_FROM_DB = {"column_name": "column"}


def is_configured() -> bool:
    """True si alguien ya puso la cadena de conexión en los Secrets."""
    try:
        return bool(st.secrets.get("DATABASE_URL"))
    except Exception:
        return False


def normalizar_url(url: str) -> str:
    """Deja la cadena de conexión como SQLAlchemy la espera.

    El esquema (lo que va antes de "://") es sensible a mayúsculas y tiene
    que ser exactamente `postgresql`. Al copiar la cadena desde el panel de
    Supabase es facilísimo traerse "PostgreSQL://…" —así, con mayúsculas, es
    como aparece rotulado el proveedor— y entonces SQLAlchemy busca un
    conector que se llame "PostgreSQL", no lo encuentra y el usuario ve
    "Can't load plugin: sqlalchemy.dialects:PostgreSQL", que no dice en
    ningún lado que lo único que sobra son tres mayúsculas.

    También se acepta `postgres://` (la forma antigua, la que todavía
    entregan Heroku y algunos tutoriales): SQLAlchemy la quitó en la
    versión 1.4 y falla igual.
    """
    url = (url or "").strip().strip('"').strip("'")
    if "://" not in url:
        return url
    esquema, resto = url.split("://", 1)
    esquema = esquema.lower()
    if esquema in {"postgres", "postgresql"}:
        esquema = "postgresql"
    return f"{esquema}://{resto}"


@st.cache_resource(show_spinner=False)
def _get_engine() -> Engine:
    url = normalizar_url(st.secrets["DATABASE_URL"])
    if not url:
        raise ValueError(
            "DATABASE_URL está vacío en los Secrets. Debe ser la cadena de conexión "
            "de la base, con esta forma: "
            "postgresql://usuario:contraseña@servidor:5432/nombre_de_la_base"
        )
    if not url.startswith("postgresql://"):
        esquema = url.split("://", 1)[0] if "://" in url else url[:20]
        raise ValueError(
            f"DATABASE_URL no parece una conexión de PostgreSQL: empieza por «{esquema}». "
            "Revisa el valor en los Secrets; tiene que empezar por «postgresql://» "
            "(por ejemplo: postgresql://usuario:contraseña@servidor:5432/postgres)."
        )
    return create_engine(url, pool_pre_ping=True, pool_recycle=300)


def ensure_schema() -> None:
    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                id BIGSERIAL PRIMARY KEY,
                person_key TEXT NOT NULL,
                person_id TEXT,
                person_name TEXT,
                supervisor TEXT,
                source_file TEXT,
                source_sheet TEXT,
                period TIMESTAMP,
                column_name TEXT NOT NULL,
                value TEXT,
                concept TEXT,
                upload_batch TEXT,
                match_confidence TEXT
            )
        """))


def load_from_db() -> pd.DataFrame:
    """Trae el historial completo y compartido. Si la tabla aún no existe o
    está vacía, devuelve un DataFrame vacío con las columnas correctas (no
    un error) para que el resto de la app lo trate como "sin datos todavía".
    """
    engine = _get_engine()
    ensure_schema()
    df = pd.read_sql(f"SELECT * FROM {TABLE_NAME}", engine)
    if df.empty:
        return pd.DataFrame(columns=CONSOLIDATED_COLUMNS)
    df = df.rename(columns=_FROM_DB)
    df["period"] = pd.to_datetime(df["period"], errors="coerce")
    for c in CONSOLIDATED_COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[CONSOLIDATED_COLUMNS]


def save_to_db(long_df: pd.DataFrame) -> None:
    """Guarda la versión combinada y ya deduplicada (viene de merge_long) como
    la nueva fuente de verdad compartida: se reemplaza todo el contenido de
    la tabla en una sola transacción, así nunca queda a medio actualizar.
    """
    engine = _get_engine()
    ensure_schema()
    out = long_df.rename(columns=_TO_DB).copy()
    out["period"] = pd.to_datetime(out["period"], errors="coerce")
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {TABLE_NAME}"))
        out.to_sql(TABLE_NAME, conn, if_exists="append", index=False)
