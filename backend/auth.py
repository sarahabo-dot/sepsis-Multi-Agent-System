"""
auth.py — minimal real authentication for the Sepsis Bundle system.

Design choices, deliberately conservative for a small-team clinical tool:
- Passwords are hashed with PBKDF2-HMAC-SHA256 (stdlib only — no extra
  dependency to install on Render). Never stored or logged in plaintext.
- Users and sessions are simple JSON files, consistent with how the rest of
  this codebase stores state (pending_guideline_reviews.json, etc.). This is
  fine for a small clinical team; swap for a real database before any
  larger-scale or multi-institution deployment.
- Sessions are opaque random tokens with a server-side expiry — not JWTs.
  Simpler to reason about and to revoke (logout just deletes the row).
- There is no "forgot password" flow. A colleague with an existing account
  creates new accounts (see create_user) — there is no open self-signup
  except the one-time bootstrap when zero users exist yet.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

USERS_PATH = Path(os.environ.get("SEPSIS_USERS_PATH", Path(__file__).parent / "users.json"))
SESSIONS_PATH = Path(os.environ.get("SEPSIS_SESSIONS_PATH", Path(__file__).parent / "sessions.json"))
SESSION_TTL_HOURS = 12
PBKDF2_ITERATIONS = 260_000


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text() or "{}")


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return hmac.compare_digest(candidate.hex(), digest_hex)


def any_users_exist() -> bool:
    return len(_load_json(USERS_PATH)) > 0


def create_user(username: str, password: str, role: str = "physician", created_by: Optional[str] = None) -> None:
    username = username.strip()
    if not username or not password:
        raise ValueError("username_and_password_required")
    if len(password) < 8:
        raise ValueError("password_too_short_min_8_chars")
    users = _load_json(USERS_PATH)
    if username in users:
        raise ValueError("username_taken")
    users[username] = {
        "password_hash": hash_password(password),
        "role": role,
        "created_at": datetime.utcnow().isoformat(),
        "created_by": created_by,
    }
    _save_json(USERS_PATH, users)


def authenticate(username: str, password: str) -> Optional[dict]:
    users = _load_json(USERS_PATH)
    user = users.get(username)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return {"username": username, "role": user.get("role", "physician")}


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    sessions = _load_json(SESSIONS_PATH)
    sessions[token] = {
        "username": username,
        "expires_at": (datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS)).isoformat(),
    }
    _save_json(SESSIONS_PATH, sessions)
    return token


def get_user_from_token(token: str) -> Optional[dict]:
    sessions = _load_json(SESSIONS_PATH)
    session = sessions.get(token)
    if not session:
        return None
    if datetime.fromisoformat(session["expires_at"]) < datetime.utcnow():
        sessions.pop(token, None)
        _save_json(SESSIONS_PATH, sessions)
        return None
    users = _load_json(USERS_PATH)
    user = users.get(session["username"])
    if not user:
        return None
    return {"username": session["username"], "role": user.get("role", "physician")}


def revoke_session(token: str) -> None:
    sessions = _load_json(SESSIONS_PATH)
    sessions.pop(token, None)
    _save_json(SESSIONS_PATH, sessions)

