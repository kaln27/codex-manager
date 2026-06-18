#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import shutil
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from codex_session_manager import (
    DEFAULT_CODEX_DIR,
    Session,
    delete_selected_sessions,
    format_timestamp,
    load_conversation_lines,
    load_sessions,
    update_selected_sessions,
)


APP_DIR = Path(__file__).resolve().parent
PROFILES_DIR = APP_DIR / "provider_profiles"
SQLITE_NAME = "state_5.sqlite"


DIST_DIR = APP_DIR / "dist"
PASSWORD_FILE = APP_DIR / ".manager_password"
SECRET_FILE = APP_DIR / ".manager_secret"
SESSION_COOKIE = "codex_manager_session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def read_password() -> str:
    password = os.environ.get("CODEX_MANAGER_PASSWORD", "").strip()
    if password:
        return password
    if PASSWORD_FILE.exists():
        return PASSWORD_FILE.read_text(encoding="utf-8").strip()
    return ""


def get_auth_secret() -> str:
    if SECRET_FILE.exists():
        secret = SECRET_FILE.read_text(encoding="utf-8").strip()
        if secret:
            return secret
    secret = secrets.token_urlsafe(48)
    SECRET_FILE.write_text(secret, encoding="utf-8")
    return secret


def sign_token(token: str) -> str:
    return hmac.new(get_auth_secret().encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def make_session_cookie() -> str:
    issued_at = str(int(time.time()))
    signature = sign_token(issued_at)
    return f"{issued_at}.{signature}"


def is_valid_session_cookie(value: str) -> bool:
    issued_at, sep, signature = value.partition(".")
    if not sep or not issued_at.isdigit():
        return False
    if int(time.time()) - int(issued_at) > SESSION_MAX_AGE:
        return False
    return hmac.compare_digest(signature, sign_token(issued_at))


def sanitize_profile_name(name: str) -> str:
    cleaned = "".join(ch for ch in name.strip() if ch.isalnum() or ch in "-_ .")
    cleaned = cleaned.strip(" .")
    if not cleaned:
        raise ValueError("Profile name cannot be empty.")
    if cleaned in {".", ".."}:
        raise ValueError("Invalid profile name.")
    return cleaned


def profile_dir(name: str) -> Path:
    safe_name = sanitize_profile_name(name)
    return PROFILES_DIR / safe_name


def codex_file(name: str) -> Path:
    return DEFAULT_CODEX_DIR / name


def backup_codex_files(files: list[Path], label: str) -> Path:
    backup_dir = DEFAULT_CODEX_DIR / "web_manager_backups" / f"{label}-{stamp()}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for path in files:
        if path.exists():
            shutil.copy2(path, backup_dir / path.name)
    return backup_dir


def list_profiles() -> list[dict[str, object]]:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profiles = []
    for path in sorted(PROFILES_DIR.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir():
            continue
        profiles.append(
            {
                "name": path.name,
                "has_config": (path / "config.toml").exists(),
                "has_auth": (path / "auth.json").exists(),
            }
        )
    return profiles


def add_profile(name: str, config_toml: str, auth_json: str) -> dict[str, object]:
    if not config_toml.strip():
        raise ValueError("config.toml content is required.")
    if not auth_json.strip():
        raise ValueError("auth.json content is required.")
    try:
        json.loads(auth_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"auth.json is not valid JSON: {exc}") from exc

    target = profile_dir(name)
    target.mkdir(parents=True, exist_ok=True)
    (target / "config.toml").write_text(config_toml, encoding="utf-8")
    (target / "auth.json").write_text(auth_json, encoding="utf-8")
    return {"name": target.name}


def read_profile(name: str) -> dict[str, str]:
    target = profile_dir(name)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError("Profile not found.")
    return {
        "name": target.name,
        "config_toml": (target / "config.toml").read_text(encoding="utf-8")
        if (target / "config.toml").exists()
        else "",
        "auth_json": (target / "auth.json").read_text(encoding="utf-8")
        if (target / "auth.json").exists()
        else "",
    }


def update_profile(name: str, config_toml: str, auth_json: str) -> dict[str, object]:
    if not config_toml.strip():
        raise ValueError("config.toml content is required.")
    if not auth_json.strip():
        raise ValueError("auth.json content is required.")
    try:
        json.loads(auth_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"auth.json is not valid JSON: {exc}") from exc

    target = profile_dir(name)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError("Profile not found.")
    (target / "config.toml").write_text(config_toml, encoding="utf-8")
    (target / "auth.json").write_text(auth_json, encoding="utf-8")
    return {"name": target.name}


def switch_profile(name: str) -> dict[str, object]:
    source = profile_dir(name)
    config_source = source / "config.toml"
    auth_source = source / "auth.json"
    if not config_source.exists() or not auth_source.exists():
        raise FileNotFoundError("Profile must contain config.toml and auth.json.")

    DEFAULT_CODEX_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_source, codex_file("config.toml"))
    shutil.copy2(auth_source, codex_file("auth.json"))
    return {"name": source.name}


def delete_profile(name: str) -> None:
    target = profile_dir(name)
    if not target.exists():
        raise FileNotFoundError("Profile not found.")
    shutil.rmtree(target)


def read_current_provider_files() -> dict[str, str]:
    return {
        "config_toml": codex_file("config.toml").read_text(encoding="utf-8")
        if codex_file("config.toml").exists()
        else "",
        "auth_json": codex_file("auth.json").read_text(encoding="utf-8")
        if codex_file("auth.json").exists()
        else "",
    }


def parse_env_text(text: str) -> list[dict[str, str]]:
    entries = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        entries.append({"key": key.strip(), "value": value if sep else ""})
    return entries


def read_env() -> dict[str, object]:
    env_path = DEFAULT_CODEX_DIR / ".env"
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    return {"exists": env_path.exists(), "text": text, "entries": parse_env_text(text)}


def save_env(entries: list[dict[str, str]]) -> None:
    DEFAULT_CODEX_DIR.mkdir(parents=True, exist_ok=True)
    env_path = DEFAULT_CODEX_DIR / ".env"
    if env_path.exists():
        backup_codex_files([env_path], "env")
    lines = []
    for entry in entries:
        key = str(entry.get("key", "")).strip()
        value = str(entry.get("value", ""))
        if not key:
            continue
        if "=" in key or "\n" in key:
            raise ValueError(f"Invalid env key: {key}")
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def session_to_dict(session: Session) -> dict[str, object]:
    return {
        "id": session.id,
        "short_id": session.short_id,
        "rollout_path": str(session.rollout_path),
        "created_at": session.created_at,
        "created_label": session.created_label,
        "updated_at": session.updated_at,
        "updated_label": format_timestamp(session.updated_at),
        "model_provider": session.model_provider,
        "title": session.title,
        "cwd": session.cwd,
        "project": session.workdir_label,
        "archived": session.archived,
        "model": session.model,
        "preview": session.preview,
    }


def sort_sessions(sessions: list[Session], sort_key: str, desc: bool) -> list[Session]:
    if sort_key == "provider":
        return sorted(
            sessions,
            key=lambda session: (
                session.model_provider.lower(),
                session.workdir_label.lower(),
                -session.created_at,
                session.title.lower(),
            ),
        )
    if sort_key == "projects":
        return sorted(
            sessions,
            key=lambda session: (
                session.workdir_label.lower(),
                session.model_provider.lower(),
                -session.created_at,
                session.title.lower(),
            ),
        )
    return sorted(sessions, key=lambda session: session.created_at, reverse=desc)


def session_matches(session: Session, query: str) -> bool:
    terms = [term.lower() for term in query.split() if term.strip()]
    return all(term in session.searchable_text for term in terms)


def load_filtered_sessions(query: str, include_archived: bool, sort_key: str, desc: bool) -> list[Session]:
    sessions = load_sessions(DEFAULT_CODEX_DIR, include_archived=include_archived)
    if query.strip():
        sessions = [session for session in sessions if session_matches(session, query)]
    return sort_sessions(sessions, sort_key, desc)


def sessions_by_id(ids: list[str]) -> list[Session]:
    wanted = set(ids)
    sessions = [session for session in load_sessions(DEFAULT_CODEX_DIR, include_archived=True) if session.id in wanted]
    missing = wanted.difference(session.id for session in sessions)
    if missing:
        raise ValueError(f"Session not found: {', '.join(sorted(missing))}")
    return sessions


class CodexManagerHandler(BaseHTTPRequestHandler):
    server_version = "CodexManager/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if not self.ensure_authenticated(parsed.path):
                return
            if parsed.path == "/":
                self.send_static("index.html")
            elif parsed.path in {"/index.html", "/login.html", "/styles.css", "/app.js"}:
                self.send_static(parsed.path.lstrip("/"))
            elif parsed.path == "/api/provider-profiles":
                self.send_json({"profiles": list_profiles(), "codex_dir": str(DEFAULT_CODEX_DIR)})
            elif parsed.path == "/api/provider-profiles/detail":
                query = parse_qs(parsed.query)
                self.send_json(read_profile(query.get("name", [""])[0]))
            elif parsed.path == "/api/provider-current":
                self.send_json(read_current_provider_files())
            elif parsed.path == "/api/env":
                self.send_json(read_env())
            elif parsed.path == "/api/sessions":
                query = parse_qs(parsed.query)
                sessions = load_filtered_sessions(
                    query.get("q", [""])[0],
                    query.get("include_archived", ["1"])[0] == "1",
                    query.get("sort", ["created"])[0],
                    query.get("desc", ["1"])[0] == "1",
                )
                self.send_json({"sessions": [session_to_dict(session) for session in sessions]})
            elif parsed.path == "/api/sessions/detail":
                query = parse_qs(parsed.query)
                session_id = query.get("id", [""])[0]
                session = sessions_by_id([session_id])[0]
                data = session_to_dict(session)
                data["conversation"] = load_conversation_lines(session, 120)
                self.send_json(data)
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            data = self.read_json()
            if parsed.path == "/api/login":
                self.login(data)
            elif parsed.path == "/api/logout":
                self.logout()
            elif not self.ensure_authenticated(parsed.path):
                return
            elif parsed.path == "/api/provider-profiles":
                result = add_profile(
                    str(data.get("name", "")),
                    str(data.get("config_toml", "")),
                    str(data.get("auth_json", "")),
                )
                self.send_json({"ok": True, **result})
            elif parsed.path == "/api/provider-profiles/switch":
                self.send_json({"ok": True, **switch_profile(str(data.get("name", "")))})
            elif parsed.path == "/api/provider-profiles/update":
                result = update_profile(
                    str(data.get("name", "")),
                    str(data.get("config_toml", "")),
                    str(data.get("auth_json", "")),
                )
                self.send_json({"ok": True, **result})
            elif parsed.path == "/api/provider-profiles/delete":
                delete_profile(str(data.get("name", "")))
                self.send_json({"ok": True})
            elif parsed.path == "/api/env":
                entries = data.get("entries", [])
                if not isinstance(entries, list):
                    raise ValueError("entries must be a list.")
                save_env(entries)
                self.send_json({"ok": True})
            elif parsed.path == "/api/sessions/provider":
                ids = data.get("ids", [])
                provider = str(data.get("provider", "")).strip()
                if not isinstance(ids, list):
                    raise ValueError("ids must be a list.")
                result = update_selected_sessions(DEFAULT_CODEX_DIR, sessions_by_id(ids), provider)
                self.send_json(
                    {
                        "ok": True,
                        "sqlite_rows": result.sqlite_rows,
                        "jsonl_files": result.jsonl_files,
                        "jsonl_lines": result.jsonl_lines,
                        "backup_dir": str(result.backup_dir) if result.backup_dir else "",
                        "missing_jsonl": [str(path) for path in (result.missing_jsonl or [])],
                    }
                )
            elif parsed.path == "/api/sessions/delete":
                ids = data.get("ids", [])
                if not isinstance(ids, list):
                    raise ValueError("ids must be a list.")
                result = delete_selected_sessions(DEFAULT_CODEX_DIR, sessions_by_id(ids))
                self.send_json(
                    {
                        "ok": True,
                        "sqlite_rows": result.sqlite_rows,
                        "jsonl_files": result.jsonl_files,
                        "backup_dir": str(result.backup_dir) if result.backup_dir else "",
                        "missing_jsonl": [str(path) for path in (result.missing_jsonl or [])],
                    }
                )
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def ensure_authenticated(self, path: str) -> bool:
        if not read_password():
            return True
        if path in {"/login.html", "/styles.css"}:
            return True
        if self.is_authenticated():
            return True
        if path.startswith("/api/"):
            self.send_json({"ok": False, "error": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
        else:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/login.html")
            self.end_headers()
        return False

    def is_authenticated(self) -> bool:
        cookies = self.headers.get("Cookie", "")
        for item in cookies.split(";"):
            name, sep, value = item.strip().partition("=")
            if sep and name == SESSION_COOKIE and is_valid_session_cookie(value):
                return True
        return False

    def login(self, data: dict[str, object]) -> None:
        configured_password = read_password()
        if not configured_password:
            self.send_json({"ok": True, "disabled": True})
            return
        password = str(data.get("password", ""))
        if not hmac.compare_digest(password, configured_password):
            self.send_json({"ok": False, "error": "Invalid password."}, HTTPStatus.UNAUTHORIZED)
            return
        cookie = make_session_cookie()
        self.send_json(
            {"ok": True},
            headers=[
                (
                    "Set-Cookie",
                    f"{SESSION_COOKIE}={cookie}; Max-Age={SESSION_MAX_AGE}; Path=/; HttpOnly; SameSite=Lax",
                )
            ],
        )

    def logout(self) -> None:
        self.send_json(
            {"ok": True},
            headers=[("Set-Cookie", f"{SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax")],
        )

    def read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object.")
        return data

    def send_static(self, relative_path: str) -> None:
        path = (DIST_DIR / relative_path).resolve()
        dist_root = DIST_DIR.resolve()
        if path != dist_root and dist_root not in path.parents:
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        payload = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix in {".html", ".css", ".js"}:
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(
        self,
        data: dict[str, object],
        status: HTTPStatus = HTTPStatus.OK,
        headers: list[tuple[str, str]] | None = None,
    ) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for name, value in headers or []:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex Manager Web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), CodexManagerHandler)
    print(f"Codex Manager running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Codex Manager.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
