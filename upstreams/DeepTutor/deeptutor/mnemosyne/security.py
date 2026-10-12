"""Single-owner device pairing for Mnemosyne's private learning surface.

Pairing codes and bearer tokens are stored only as SHA-256 fingerprints. The
state file lives in DeepTutor's runtime data directory and is atomically
replaced with owner-only permissions; it is never part of the source tree.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

PAIRING_COOKIE = "mnemosyne_session"
PAIRING_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(days=90)
_LOCK = threading.RLock()


def _state_path() -> Path:
    from deeptutor.runtime.home import get_runtime_data_root

    return get_runtime_data_root() / "system" / "mnemosyne-pairing.json"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "pairing": None, "devices": {}}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Mnemosyne pairing state could not be read") from exc
    if (
        not isinstance(value, dict)
        or value.get("version") != 1
        or not isinstance(value.get("devices"), dict)
        or (value.get("pairing") is not None and not isinstance(value.get("pairing"), dict))
    ):
        raise RuntimeError("Mnemosyne pairing state has an unsupported format")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    from deeptutor.services.file_io import atomic_write_json

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    atomic_write_json(path, value)
    os.chmod(path, 0o600)


@contextmanager
def _state_lock(path: Path):
    """Serialize read/modify/write across threads and worker processes."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.chmod(lock_path, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


class MnemosyneSessionStore:
    """Durable one-time pairing and revocable bearer sessions."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _state_path()

    def issue_pairing_code(self) -> tuple[str, datetime]:
        code = "mnp_" + secrets.token_urlsafe(32)
        expires = _now() + PAIRING_TTL
        with _LOCK, _state_lock(self.path):
            state = _read(self.path)
            state["pairing"] = {"sha256": _digest(code), "expires_at": _iso(expires)}
            _write(self.path, state)
        return code, expires

    def pair(self, code: str, device_name: str) -> dict[str, str] | None:
        normalized = str(device_name or "").strip()
        if not normalized or len(normalized) > 120 or not isinstance(code, str):
            return None
        now = _now()
        with _LOCK, _state_lock(self.path):
            state = _read(self.path)
            pairing = state.get("pairing")
            expires = _parse_time(pairing.get("expires_at")) if pairing else None
            expected = str(pairing.get("sha256") or "") if pairing else ""
            if (
                not expected
                or expires is None
                or expires <= now
                or not hmac.compare_digest(expected, _digest(code))
            ):
                return None
            token = "mnemo_" + secrets.token_urlsafe(48)
            device_id = str(uuid4())
            session_expiry = now + SESSION_TTL
            state["pairing"] = None
            state["devices"][device_id] = {
                "token_sha256": _digest(token),
                "device_name": normalized,
                "created_at": _iso(now),
                "expires_at": _iso(session_expiry),
                "revoked_at": None,
            }
            _write(self.path, state)
        return {"device_id": device_id, "access_token": token, "expires_at": _iso(session_expiry)}

    def authenticate(self, token: str) -> str | None:
        if not isinstance(token, str) or len(token) < 32 or len(token) > 256:
            return None
        fingerprint = _digest(token)
        now = _now()
        with _LOCK, _state_lock(self.path):
            state = _read(self.path)
            for device_id, record in state["devices"].items():
                if not isinstance(record, dict):
                    continue
                expiry = _parse_time(record.get("expires_at"))
                if (
                    record.get("revoked_at") is None
                    and expiry is not None
                    and expiry > now
                    and hmac.compare_digest(str(record.get("token_sha256") or ""), fingerprint)
                ):
                    return device_id
        return None

    def revoke(self, token: str) -> bool:
        if not isinstance(token, str) or len(token) < 32:
            return False
        fingerprint = _digest(token)
        now = _iso(_now())
        with _LOCK, _state_lock(self.path):
            state = _read(self.path)
            for record in state["devices"].values():
                if (
                    isinstance(record, dict)
                    and record.get("revoked_at") is None
                    and hmac.compare_digest(str(record.get("token_sha256") or ""), fingerprint)
                ):
                    record["revoked_at"] = now
                    _write(self.path, state)
                    return True
        return False


def _normalize_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return None
        host = parsed.hostname.lower().rstrip(".")
        port = parsed.port
        default_port = (parsed.scheme == "https" and port in {None, 443}) or (
            parsed.scheme == "http" and port in {None, 80}
        )
        authority = host if default_port else f"{host}:{port}"
        return f"{parsed.scheme}://{authority}"
    except ValueError:
        return None


def allowed_origin(request: Any, origin: str | None) -> bool:
    if origin is None:
        return False
    normalized = _normalize_origin(origin)
    if normalized is None:
        return False
    configured = {
        candidate
        for raw in os.environ.get("MNEMOSYNE_ALLOWED_ORIGINS", "").split(",")
        if (candidate := _normalize_origin(raw.strip())) is not None
    }
    request_base = urlsplit(str(request.base_url))
    request_scheme = {"ws": "http", "wss": "https"}.get(request_base.scheme, request_base.scheme)
    request_origin = _normalize_origin(
        f"{request_scheme}://{request_base.netloc}/" if request_base.netloc else ""
    )
    if request_origin:
        configured.add(request_origin)
    return normalized in configured


def request_token(request: Any) -> tuple[str | None, bool]:
    authorization = request.headers.get("authorization", "")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        return (
            (token.strip(), False)
            if scheme.lower() == "bearer" and token.strip()
            else (None, False)
        )
    cookie = request.cookies.get(PAIRING_COOKIE)
    return (cookie, True) if cookie else (None, False)
