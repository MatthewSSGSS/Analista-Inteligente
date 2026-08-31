"""Autenticación de usuarios: pantalla de login con usuario y contraseña,
usando la misma base de datos compartida que ya tienes conectada (no una
cuenta ni servicio aparte).

Las contraseñas NUNCA se guardan en texto plano — se cifran con PBKDF2-SHA256
(estándar, sin dependencias externas) y una "sal" (salt) distinta por
usuario, para que ni siquiera alguien con acceso directo a la base de datos
pueda ver o deducir la contraseña real de nadie.

Si no hay base de datos configurada, el login queda desactivado por completo
(no tendría dónde guardar los usuarios de forma persistente) y la app sigue
funcionando exactamente igual que antes — mismo principio que el resto de
funciones conectadas a la base de datos.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re

import streamlit as st
from sqlalchemy import text

import core.db_engine as db_engine

TABLE_NAME = "app_users"
_ITERATIONS = 200_000


def is_available() -> bool:
    """El login solo tiene sentido si hay dónde guardar los usuarios de
    forma persistente (la misma base de datos compartida)."""
    return db_engine.is_configured()


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return salt.hex(), digest.hex()


def _verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    _, digest_hex = _hash_password(password, salt)
    return hmac.compare_digest(digest_hex, hash_hex)


def ensure_schema() -> None:
    engine = db_engine._get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                id BIGSERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))


def _normalize_username(username: str) -> str:
    return re.sub(r"\s+", "", str(username or "")).strip().lower()


def username_exists(username: str) -> bool:
    engine = db_engine._get_engine()
    ensure_schema()
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT 1 FROM {TABLE_NAME} WHERE username = :u"), {"u": _normalize_username(username)}).fetchone()
    return row is not None


def create_user(username: str, password: str, display_name: str = "") -> tuple[bool, str]:
    username = _normalize_username(username)
    if len(username) < 3:
        return False, "El usuario debe tener al menos 3 caracteres."
    if not re.match(r"^[a-z0-9._-]+$", username):
        return False, "El usuario solo puede tener letras, números, puntos, guiones y guiones bajos."
    if len(password) < 6:
        return False, "La contraseña debe tener al menos 6 caracteres."
    if username_exists(username):
        return False, "Ese usuario ya existe. Prueba con otro o inicia sesión."
    salt_hex, hash_hex = _hash_password(password)
    engine = db_engine._get_engine()
    ensure_schema()
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {TABLE_NAME} (username, display_name, salt, password_hash) VALUES (:u, :d, :s, :h)"),
            {"u": username, "d": display_name.strip() or username, "s": salt_hex, "h": hash_hex},
        )
    return True, "Cuenta creada correctamente."


def authenticate(username: str, password: str) -> tuple[bool, str]:
    username = _normalize_username(username)
    if not username or not password:
        return False, "Escribe usuario y contraseña."
    engine = db_engine._get_engine()
    ensure_schema()
    with engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT display_name, salt, password_hash FROM {TABLE_NAME} WHERE username = :u"),
            {"u": username},
        ).fetchone()
    if row is None:
        return False, "Usuario o contraseña incorrectos."
    display_name, salt_hex, hash_hex = row
    if not _verify_password(password, salt_hex, hash_hex):
        return False, "Usuario o contraseña incorrectos."
    st.session_state.auth_user = {"username": username, "display_name": display_name or username}
    st.session_state.authenticated = True
    return True, "ok"


def logout() -> None:
    st.session_state.authenticated = False
    st.session_state.auth_user = None
