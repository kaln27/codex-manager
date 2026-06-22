#!/usr/bin/env python3

from __future__ import annotations

import curses
import json
import shutil
import sqlite3
import sys
import textwrap
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEFAULT_CODEX_DIR = Path("~/.codex").expanduser()
SQLITE_NAME = "state_5.sqlite"


@dataclass(frozen=True)
class Session:
    id: str
    rollout_path: Path
    created_at: int
    updated_at: int
    model_provider: str
    title: str
    cwd: str
    archived: bool
    model: str
    preview: str

    @property
    def short_id(self) -> str:
        return self.id[:8]

    @property
    def created_label(self) -> str:
        return format_timestamp(self.created_at)

    @property
    def workdir_label(self) -> str:
        return Path(self.cwd).name or self.cwd or "-"

    @property
    def searchable_text(self) -> str:
        return " ".join(
            [
                self.id,
                self.title,
                self.preview,
                self.cwd,
                self.model_provider,
                self.model,
                str(self.rollout_path),
            ]
        ).lower()


@dataclass
class UpdateResult:
    sqlite_rows: int = 0
    jsonl_files: int = 0
    jsonl_lines: int = 0
    backup_dir: Path | None = None
    missing_jsonl: list[Path] | None = None


@dataclass
class DeleteResult:
    sqlite_rows: int = 0
    jsonl_files: int = 0
    backup_dir: Path | None = None
    missing_jsonl: list[Path] | None = None


def format_timestamp(value: int | None) -> str:
    if not value:
        return "-"
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")


def ellipsize(text: str, width: int) -> str:
    text = " ".join((text or "").split())
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 1:
        return "…"
    return text[: width - 1] + "…"


def cell_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        if unicodedata.category(char)[0] == "C":
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def clip_cells(text: str, max_width: int) -> str:
    if max_width <= 0:
        return ""
    result: list[str] = []
    used = 0
    for char in text:
        char_width = cell_width(char)
        if used + char_width > max_width:
            break
        result.append(char)
        used += char_width
    return "".join(result)


def ellipsize_cells(text: str, max_width: int) -> str:
    text = " ".join((text or "").split())
    if cell_width(text) <= max_width:
        return text
    if max_width <= 1:
        return "…" if max_width == 1 else ""
    return clip_cells(text, max_width - 1) + "…"


def wrap_cells(text: str, width: int, indent: str = "") -> list[str]:
    if width <= 0:
        return [""]
    lines: list[str] = []
    indent_width = cell_width(indent)
    content_width = max(1, width - indent_width)
    for raw_line in (text.splitlines() or [""]):
        remaining = raw_line
        if not remaining:
            lines.append(indent.rstrip())
            continue
        while remaining:
            chunk = clip_cells(remaining, content_width)
            if not chunk:
                chunk = remaining[0]
            lines.append(indent + chunk)
            remaining = remaining[len(chunk) :]
    return lines


def safe_addnstr(
    window: curses.window,
    y: int,
    x: int,
    text: str,
    width: int,
    attr: int = curses.A_NORMAL,
) -> None:
    if width <= 0 or y < 0 or x < 0:
        return
    with suppress(curses.error):
        max_y, max_x = window.getmaxyx()
        if y >= max_y or x >= max_x:
            return
        available = max(0, min(width, max_x - x - 1))
        if available <= 0:
            return
        window.addstr(y, x, clip_cells(text, available), attr)


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def sqlite_path(codex_dir: Path) -> Path:
    return codex_dir / SQLITE_NAME


def require_codex_dir(codex_dir: Path) -> None:
    if not codex_dir.exists():
        raise FileNotFoundError(f"Codex directory not found: {codex_dir}")
    if not sqlite_path(codex_dir).exists():
        raise FileNotFoundError(f"SQLite file not found: {sqlite_path(codex_dir)}")


def load_session_index_titles(codex_dir: Path) -> dict[str, str]:
    index_path = codex_dir / "session_index.jsonl"
    titles: dict[str, str] = {}
    if not index_path.exists():
        return titles
    try:
        with index_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                session_id = str(record.get("id") or "").strip()
                title = str(record.get("thread_name") or "").strip()
                if session_id and title:
                    titles[session_id] = title
    except OSError:
        return titles
    return titles


def load_sessions(codex_dir: Path, include_archived: bool = True) -> list[Session]:
    require_codex_dir(codex_dir)
    indexed_titles = load_session_index_titles(codex_dir)
    conn = sqlite3.connect(sqlite_path(codex_dir))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'threads'
            """
        )
        if cursor.fetchone() is None:
            raise RuntimeError("Table 'threads' not found in Codex sqlite database.")

        filters = [
            "COALESCE(thread_source, '') != 'subagent'",
            "COALESCE(model, '') != 'codex-auto-review'",
            "COALESCE(source, '') NOT LIKE '%\"subagent\"%'",
        ]
        if not include_archived:
            filters.append("archived = 0")
        where = "WHERE " + " AND ".join(filters)
        cursor.execute(
            f"""
            SELECT
                id,
                rollout_path,
                created_at,
                updated_at,
                model_provider,
                title,
                cwd,
                archived,
                COALESCE(model, '') AS model,
                COALESCE(preview, first_user_message, '') AS preview
            FROM threads
            {where}
            ORDER BY created_at DESC, id DESC
            """
        )
        return [
            Session(
                id=row["id"],
                rollout_path=Path(row["rollout_path"]).expanduser(),
                created_at=int(row["created_at"] or 0),
                updated_at=int(row["updated_at"] or 0),
                model_provider=row["model_provider"] or "",
                title=indexed_titles.get(row["id"]) or row["title"] or "(untitled)",
                cwd=row["cwd"] or "",
                archived=bool(row["archived"]),
                model=row["model"] or "",
                preview=row["preview"] or "",
            )
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def known_providers(sessions: Iterable[Session]) -> list[str]:
    providers = {session.model_provider for session in sessions if session.model_provider}
    providers.add("openai")
    return sorted(providers)


def make_backup_dir(codex_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = codex_dir / "provider_gui_backups" / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    prune_backup_dirs(codex_dir)
    return backup_dir


def prune_backup_dirs(codex_dir: Path, keep: int = 3) -> None:
    backup_root = codex_dir / "provider_gui_backups"
    if keep < 1 or not backup_root.exists():
        return
    backups = [path for path in backup_root.iterdir() if path.is_dir()]
    backups.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    for path in backups[keep:]:
        shutil.rmtree(path, ignore_errors=True)


def backup_file(file_path: Path, codex_dir: Path, backup_dir: Path) -> None:
    try:
        relative = file_path.relative_to(codex_dir)
    except ValueError:
        relative = Path(file_path.name)
    target = backup_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file_path, target)


def update_jsonl_provider(path: Path, provider: str) -> int:
    changed_lines = 0
    output_lines: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if not line:
                output_lines.append(raw_line)
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                output_lines.append(raw_line)
                continue
            if update_json_record_provider(record, provider):
                changed_lines += 1
                output_lines.append(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
            else:
                output_lines.append(raw_line)

    if changed_lines:
        with path.open("w", encoding="utf-8") as handle:
            handle.writelines(output_lines)
    return changed_lines


def update_json_record_provider(record: object, provider: str) -> bool:
    if not isinstance(record, dict):
        return False

    changed = False
    if record.get("model_provider") != provider and "model_provider" in record:
        record["model_provider"] = provider
        changed = True

    payload = record.get("payload")
    if isinstance(payload, dict):
        if payload.get("model_provider") != provider and "model_provider" in payload:
            payload["model_provider"] = provider
            changed = True

        session_config = payload.get("session_config")
        if isinstance(session_config, dict):
            if (
                session_config.get("model_provider") != provider
                and "model_provider" in session_config
            ):
                session_config["model_provider"] = provider
                changed = True

    return changed


def extract_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(
                    extract_text(
                        item.get("text")
                        or item.get("input_text")
                        or item.get("output_text")
                        or item.get("content")
                    )
                )
            else:
                parts.append(extract_text(item))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        return extract_text(
            value.get("text")
            or value.get("input_text")
            or value.get("output_text")
            or value.get("content")
            or value.get("message")
        )
    return str(value)


def load_conversation_lines(session: Session, width: int) -> list[str]:
    if not session.rollout_path.exists():
        return [f"jsonl 文件不存在: {session.rollout_path}"]

    wrap_width = max(20, width)
    lines: list[str] = []
    try:
        with session.rollout_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue

                payload_type = payload.get("type")
                if record.get("type") != "event_msg":
                    continue
                if payload_type == "user_message":
                    role = "User"
                    message = extract_text(payload.get("message"))
                elif payload_type == "agent_message":
                    role = "Assistant"
                    message = extract_text(payload.get("message"))
                else:
                    continue

                message = message.strip()
                if not message:
                    continue
                if lines:
                    lines.append("")
                lines.append(f"{role}:")
                for paragraph in message.splitlines() or [message]:
                    lines.extend(wrap_cells(paragraph, wrap_width, indent="  "))
    except OSError as exc:
        return [f"读取 jsonl 失败: {exc}"]

    return lines or ["这个 session 里没有找到用户/助手对话。"]


def update_selected_sessions(
    codex_dir: Path,
    sessions: Iterable[Session],
    provider: str,
    *,
    backup: bool = True,
    dry_run: bool = False,
) -> UpdateResult:
    selected = list(sessions)
    if not selected:
        raise ValueError("No sessions selected.")
    if not provider.strip():
        raise ValueError("Target model provider cannot be empty.")

    result = UpdateResult(missing_jsonl=[])
    backup_dir: Path | None = None
    existing_jsonl = sorted({s.rollout_path for s in selected if s.rollout_path.exists()})

    if backup and not dry_run:
        backup_dir = make_backup_dir(codex_dir)
        backup_file(sqlite_path(codex_dir), codex_dir, backup_dir)
        for path in existing_jsonl:
            backup_file(path, codex_dir, backup_dir)
        result.backup_dir = backup_dir

    for session in selected:
        if not session.rollout_path.exists():
            result.missing_jsonl.append(session.rollout_path)
            continue
        if not dry_run:
            changed = update_jsonl_provider(session.rollout_path, provider)
        else:
            changed = 1
        if changed:
            result.jsonl_files += 1
            result.jsonl_lines += changed

    if not dry_run:
        conn = sqlite3.connect(sqlite_path(codex_dir))
        try:
            cursor = conn.cursor()
            cursor.executemany(
                "UPDATE threads SET model_provider = ? WHERE id = ?",
                [(provider, session.id) for session in selected],
            )
            result.sqlite_rows = cursor.rowcount
            conn.commit()
        finally:
            conn.close()
    else:
        result.sqlite_rows = len(selected)

    return result


def delete_selected_sessions(
    codex_dir: Path,
    sessions: Iterable[Session],
    *,
    backup: bool = True,
    dry_run: bool = False,
) -> DeleteResult:
    selected = list(sessions)
    if not selected:
        raise ValueError("No sessions selected.")

    result = DeleteResult(missing_jsonl=[])
    existing_jsonl = sorted({s.rollout_path for s in selected if s.rollout_path.exists()})

    if backup and not dry_run:
        backup_dir = make_backup_dir(codex_dir)
        backup_file(sqlite_path(codex_dir), codex_dir, backup_dir)
        for path in existing_jsonl:
            backup_file(path, codex_dir, backup_dir)
        result.backup_dir = backup_dir

    if not dry_run:
        conn = sqlite3.connect(sqlite_path(codex_dir))
        try:
            cursor = conn.cursor()
            cursor.executemany(
                "DELETE FROM threads WHERE id = ?",
                [(session.id,) for session in selected],
            )
            result.sqlite_rows = cursor.rowcount
            conn.commit()
        finally:
            conn.close()
    else:
        result.sqlite_rows = len(selected)

    for session in selected:
        if not session.rollout_path.exists():
            result.missing_jsonl.append(session.rollout_path)
            continue
        if not dry_run:
            session.rollout_path.unlink()
        result.jsonl_files += 1

    return result


class SessionPicker:
    def __init__(self, codex_dir: Path, include_archived: bool = True) -> None:
        self.codex_dir = codex_dir
        self.include_archived = include_archived
        self.sessions = load_sessions(codex_dir, include_archived=include_archived)
        self.selected: set[str] = set()
        self.cursor = 0
        self.scroll = 0
        self.query = ""
        self.sort_key = "created"
        self.sort_desc = True
        self.header_buttons: dict[str, tuple[int, int, int]] = {}
        self.confirm_button: tuple[int, int, int] | None = None
        self.quit_button: tuple[int, int, int] | None = None
        self.help_text = "Created/Provider/Projects 排序 | Space 选择 | Enter/确认 修改 | x 删除 | i 详情 | / 搜索 | a 全选 | c 清空 | t 归档 | q 退出"
        self.status = self.help_text

    @property
    def filtered(self) -> list[Session]:
        if not self.query.strip():
            sessions = list(self.sessions)
        else:
            terms = [term.lower() for term in self.query.split() if term.strip()]
            sessions = [
                session
                for session in self.sessions
                if all(term in session.searchable_text for term in terms)
            ]
        return self.sorted_sessions(sessions)

    def sorted_sessions(self, sessions: list[Session]) -> list[Session]:
        if self.sort_key == "provider":
            return sorted(
                sessions,
                key=lambda session: (
                    session.model_provider.lower(),
                    session.workdir_label.lower(),
                    -session.created_at,
                    session.title.lower(),
                ),
            )
        if self.sort_key == "projects":
            return sorted(
                sessions,
                key=lambda session: (
                    session.workdir_label.lower(),
                    session.model_provider.lower(),
                    -session.created_at,
                    session.title.lower(),
                ),
            )
        return sorted(
            sessions,
            key=lambda session: session.created_at,
            reverse=self.sort_desc,
        )

    def run(self, stdscr: curses.window) -> int:
        with suppress(curses.error):
            curses.curs_set(0)
        stdscr.keypad(True)
        with suppress(curses.error):
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        while True:
            self.draw(stdscr)
            key = stdscr.getch()
            filtered = self.filtered
            if key in (ord("q"), 27):
                return 1
            if key in (curses.KEY_UP, ord("k")):
                self.move_cursor(-1)
            elif key in (curses.KEY_DOWN, ord("j")):
                self.move_cursor(1)
            elif key == curses.KEY_PPAGE:
                self.move_cursor(-10)
            elif key == curses.KEY_NPAGE:
                self.move_cursor(10)
            elif key == ord(" "):
                if filtered:
                    session = filtered[self.cursor]
                    if session.id in self.selected:
                        self.selected.remove(session.id)
                    else:
                        self.selected.add(session.id)
            elif key == ord("a"):
                visible_ids = {session.id for session in filtered}
                if visible_ids and visible_ids.issubset(self.selected):
                    self.selected.difference_update(visible_ids)
                else:
                    self.selected.update(visible_ids)
            elif key == ord("c"):
                self.selected.clear()
            elif key == ord("x"):
                self.delete_selected(stdscr)
            elif key == ord("t"):
                self.include_archived = not self.include_archived
                self.reload_sessions()
                self.cursor = 0
                self.scroll = 0
            elif key == ord("i"):
                session = self.detail_target(filtered)
                if session:
                    self.show_session_detail(stdscr, session)
            elif key == ord("/"):
                self.query = self.prompt(stdscr, "Search")
                self.cursor = 0
                self.scroll = 0
            elif key == curses.KEY_MOUSE:
                if self.handle_mouse(stdscr):
                    return 0
            elif key in (curses.KEY_ENTER, 10, 13):
                if self.apply_selected(stdscr):
                    return 0
            self.keep_cursor_visible(stdscr)

    def handle_mouse(self, stdscr: curses.window) -> bool:
        try:
            _, x, y, _, button_state = curses.getmouse()
        except curses.error:
            return False

        if button_state & getattr(curses, "BUTTON4_PRESSED", 0):
            self.scroll_list(stdscr, -3)
            return False
        if button_state & getattr(curses, "BUTTON5_PRESSED", 0):
            self.scroll_list(stdscr, 3)
            return False

        # Some terminals report wheel motion as button clicks 4/5.
        if button_state & (1 << 20):
            self.scroll_list(stdscr, -3)
            return False
        if button_state & (1 << 21):
            self.scroll_list(stdscr, 3)
            return False

        if not (button_state & curses.BUTTON1_CLICKED):
            return False

        if y == 2:
            for key, (row, start, end) in self.header_buttons.items():
                if y == row and start <= x < end:
                    self.set_sort(key)
                    return False

        if self.confirm_button:
            row, start, end = self.confirm_button
            if y == row and start <= x < end:
                return self.apply_selected(stdscr)

        if self.quit_button:
            row, start, end = self.quit_button
            if y == row and start <= x < end:
                return True

        list_row = y - 3
        filtered = self.filtered
        index = self.scroll + list_row
        if 0 <= list_row and index < len(filtered):
            self.cursor = index
            session = filtered[index]
            if session.id in self.selected:
                self.selected.remove(session.id)
            else:
                self.selected.add(session.id)
        return False

    def set_sort(self, key: str) -> None:
        if key == "created":
            if self.sort_key == "created":
                self.sort_desc = not self.sort_desc
            else:
                self.sort_key = "created"
                self.sort_desc = True
        elif key in {"provider", "projects"}:
            self.sort_key = key
            self.sort_desc = False
        self.status = self.help_text
        self.cursor = 0
        self.scroll = 0

    def scroll_list(self, stdscr: curses.window, delta: int) -> None:
        filtered = self.filtered
        if not filtered:
            return
        height, _ = stdscr.getmaxyx()
        list_height = max(1, height - 6)
        max_scroll = max(0, len(filtered) - list_height)
        self.scroll = clamp(self.scroll + delta, 0, max_scroll)
        self.cursor = clamp(self.cursor + delta, 0, len(filtered) - 1)

    def detail_target(self, filtered: list[Session]) -> Session | None:
        if filtered and filtered[self.cursor].id in self.selected:
            return filtered[self.cursor]
        if len(self.selected) == 1:
            selected_id = next(iter(self.selected))
            for session in self.sessions:
                if session.id == selected_id:
                    return session
        if filtered:
            return filtered[self.cursor]
        return None

    def apply_selected(self, stdscr: curses.window) -> bool:
        if not self.selected:
            self.status = "请先选择至少一个 session。"
            return False
        provider = self.choose_provider(stdscr)
        if provider is None:
            return False
        selected_sessions = [s for s in self.sessions if s.id in self.selected]
        try:
            result = update_selected_sessions(
                self.codex_dir,
                selected_sessions,
                provider,
                backup=True,
                dry_run=False,
            )
            self.show_result(stdscr, result, provider)
            return True
        except Exception as exc:  # pragma: no cover - displayed by curses
            self.message(stdscr, f"更新失败: {exc}")
            self.sessions = load_sessions(
                self.codex_dir, include_archived=self.include_archived
            )
            return False

    def delete_selected(self, stdscr: curses.window) -> None:
        if not self.selected:
            self.status = "请先选择至少一个 session。"
            return
        selected_sessions = [s for s in self.sessions if s.id in self.selected]
        answer = self.confirm_popup(
            stdscr,
            "删除 Sessions",
            f"确认删除 {len(selected_sessions)} 个 session? 输入 yes",
        )
        if answer.lower() != "yes":
            self.status = "已取消删除。"
            return
        try:
            result = delete_selected_sessions(
                self.codex_dir,
                selected_sessions,
                backup=True,
                dry_run=False,
            )
            self.selected.clear()
            self.cursor = 0
            self.scroll = 0
            self.show_delete_result(stdscr, result)
            self.status = self.help_text
            self.reload_sessions()
            self.draw(stdscr)
        except Exception as exc:  # pragma: no cover - displayed by curses
            self.message(stdscr, f"删除失败: {exc}")

    def reload_sessions(self) -> None:
        self.sessions = load_sessions(
            self.codex_dir, include_archived=self.include_archived
        )
        filtered_len = len(self.filtered)
        if filtered_len == 0:
            self.cursor = 0
            self.scroll = 0
        else:
            self.cursor = clamp(self.cursor, 0, filtered_len - 1)
            self.scroll = clamp(self.scroll, 0, filtered_len - 1)

    def move_cursor(self, delta: int) -> None:
        filtered = self.filtered
        if not filtered:
            self.cursor = 0
            self.scroll = 0
            return
        self.cursor = max(0, min(len(filtered) - 1, self.cursor + delta))

    def keep_cursor_visible(self, stdscr: curses.window) -> None:
        height, _ = stdscr.getmaxyx()
        list_height = max(1, height - 6)
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        elif self.cursor >= self.scroll + list_height:
            self.scroll = self.cursor - list_height + 1

    def draw(self, stdscr: curses.window) -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        filtered = self.filtered
        header = (
            f"Codex Model Provider GUI | {self.codex_dir} | "
            f"selected {len(self.selected)} / visible {len(filtered)} / all {len(self.sessions)}"
        )
        safe_addnstr(stdscr, 0, 0, header, width - 1, curses.A_BOLD)
        filter_text = self.query or "(none)"
        archive_text = "include archived" if self.include_archived else "active only"
        safe_addnstr(stdscr, 1, 0, f"filter: {filter_text} | {archive_text}", width - 1)
        created_label = "Created ↓" if self.sort_key == "created" and self.sort_desc else "Created ↑" if self.sort_key == "created" else "Created"
        provider_label = "Provider *" if self.sort_key == "provider" else "Provider"
        projects_label = "Projects *" if self.sort_key == "projects" else "Projects"
        header_line = (
            f"Sel  {created_label:<16} "
            f"{provider_label:<10} "
            f"{projects_label:<15} "
            "Title"
        )
        safe_addnstr(stdscr, 2, 0, header_line, width - 1, curses.A_UNDERLINE)
        self.header_buttons = {
            "created": (2, 5, 5 + 16),
            "provider": (2, 22, 22 + 10),
            "projects": (2, 33, 33 + 15),
        }

        list_height = max(1, height - 6)
        self.keep_cursor_visible(stdscr)
        workdir_width = 15
        title_width = max(10, width - 50)
        for row, session in enumerate(
            filtered[self.scroll : self.scroll + list_height], start=3
        ):
            index = self.scroll + row - 3
            marker = "[x]" if session.id in self.selected else "[ ]"
            archived = "A" if session.archived else " "
            line = (
                f"{marker}{archived} {session.created_label:<16} "
                f"{ellipsize_cells(session.model_provider, 10):<10} "
                f"{ellipsize_cells(session.workdir_label, workdir_width):<{workdir_width}} "
                f"{ellipsize_cells(session.title, title_width)}"
            )
            attr = curses.A_REVERSE if index == self.cursor else curses.A_NORMAL
            safe_addnstr(stdscr, row, 0, line, width - 1, attr)

        if filtered:
            current = filtered[self.cursor]
            detail = f"{current.short_id} | {current.cwd} | {current.rollout_path}"
        else:
            detail = "没有匹配的 session。"
        safe_addnstr(stdscr, height - 2, 0, ellipsize(detail, width - 1), width - 1)
        confirm = "[确认]"
        quit_text = "[退出]"
        confirm_width = cell_width(confirm)
        quit_width = cell_width(quit_text)
        button_gap = 3
        button_area = confirm_width + quit_width + button_gap + 1
        safe_addnstr(
            stdscr,
            height - 1,
            0,
            ellipsize_cells(self.status, max(0, width - button_area)),
            max(0, width - button_area),
        )
        confirm_start = max(0, width - confirm_width - quit_width - button_gap - 1)
        quit_start = max(0, width - quit_width - 1)
        safe_addnstr(stdscr, height - 1, confirm_start, confirm, confirm_width, curses.A_BOLD)
        safe_addnstr(stdscr, height - 1, quit_start, quit_text, quit_width, curses.A_BOLD)
        self.confirm_button = (height - 1, confirm_start, confirm_start + confirm_width)
        self.quit_button = (height - 1, quit_start, quit_start + quit_width)
        with suppress(curses.error):
            stdscr.refresh()

    def prompt(self, stdscr: curses.window, label: str, default: str = "") -> str:
        with suppress(curses.error):
            curses.curs_set(1)
        height, width = stdscr.getmaxyx()
        value = default
        while True:
            with suppress(curses.error):
                stdscr.move(height - 1, 0)
                stdscr.clrtoeol()
            prompt = f"{label}: {value}"
            safe_addnstr(stdscr, height - 1, 0, prompt, width - 1, curses.A_BOLD)
            with suppress(curses.error):
                stdscr.refresh()
            key = stdscr.getch()
            if key in (10, 13, curses.KEY_ENTER):
                with suppress(curses.error):
                    curses.curs_set(0)
                return value.strip()
            if key in (27,):
                with suppress(curses.error):
                    curses.curs_set(0)
                return default
            if key in (curses.KEY_BACKSPACE, 127, 8):
                value = value[:-1]
            elif 32 <= key <= 126:
                value += chr(key)

    def choose_provider(self, stdscr: curses.window) -> str | None:
        providers = known_providers(self.sessions)
        provider = self.provider_popup(stdscr, providers, default="openai")
        if not provider:
            self.status = "已取消 provider 输入。"
            return None
        return provider

    def provider_popup(
        self, stdscr: curses.window, providers: list[str], default: str = "openai"
    ) -> str | None:
        height, width = stdscr.getmaxyx()
        box_height = 9
        box_width = min(max(58, width // 2), max(20, width - 4))
        top = max(0, (height - box_height) // 2)
        left = max(0, (width - box_width) // 2)
        win = curses.newwin(box_height, box_width, top, left)
        win.keypad(True)
        with suppress(curses.error):
            curses.curs_set(1)
        value = default
        title = "目标 model_provider"
        hint = "OpenAI 官方 provider: openai"
        known = "已知: " + ", ".join(providers)

        while True:
            win.erase()
            with suppress(curses.error):
                win.box()
            safe_addnstr(win, 1, 2, title, box_width - 4, curses.A_BOLD)
            safe_addnstr(win, 2, 2, hint, box_width - 4)
            safe_addnstr(win, 3, 2, ellipsize(known, box_width - 4), box_width - 4)
            safe_addnstr(win, 5, 2, "> " + value, box_width - 4, curses.A_REVERSE)
            safe_addnstr(win, 7, 2, "Enter 应用修改 | Esc 取消", box_width - 4)
            with suppress(curses.error):
                win.move(5, min(box_width - 3, 4 + len(value)))
            with suppress(curses.error):
                win.refresh()
            key = win.getch()
            if key in (10, 13, curses.KEY_ENTER):
                with suppress(curses.error):
                    curses.curs_set(0)
                return value.strip() or None
            if key == 27:
                with suppress(curses.error):
                    curses.curs_set(0)
                return None
            if key in (curses.KEY_BACKSPACE, 127, 8):
                value = value[:-1]
            elif 32 <= key <= 126:
                value += chr(key)

    def confirm_popup(self, stdscr: curses.window, title: str, prompt: str) -> str:
        height, width = stdscr.getmaxyx()
        box_height = 7
        box_width = min(max(56, cell_width(prompt) + 6), max(20, width - 4))
        top = max(0, (height - box_height) // 2)
        left = max(0, (width - box_width) // 2)
        win = curses.newwin(box_height, box_width, top, left)
        win.keypad(True)
        with suppress(curses.error):
            curses.curs_set(1)
        value = ""
        content_width = max(10, box_width - 4)

        while True:
            win.erase()
            with suppress(curses.error):
                win.box()
            safe_addnstr(win, 1, 2, title, content_width, curses.A_BOLD)
            safe_addnstr(win, 2, 2, prompt, content_width)
            safe_addnstr(win, 4, 2, "> " + value, content_width, curses.A_REVERSE)
            safe_addnstr(win, 5, 2, "Enter 确认 | Esc 取消", content_width)
            with suppress(curses.error):
                win.move(4, min(box_width - 3, 4 + cell_width(value)))
            with suppress(curses.error):
                win.refresh()
            key = win.getch()
            if key in (10, 13, curses.KEY_ENTER):
                with suppress(curses.error):
                    curses.curs_set(0)
                return value.strip()
            if key == 27:
                with suppress(curses.error):
                    curses.curs_set(0)
                return ""
            if key in (curses.KEY_BACKSPACE, 127, 8):
                value = value[:-1]
            elif 32 <= key <= 126:
                value += chr(key)

    def show_session_detail(self, stdscr: curses.window, session: Session) -> None:
        height, width = stdscr.getmaxyx()
        box_height = min(max(12, height - 4), height)
        box_width = min(max(60, width - 8), width)
        top = max(0, (height - box_height) // 2)
        left = max(0, (width - box_width) // 2)
        content_width = max(20, box_width - 4)
        body_height = max(1, box_height - 5)
        lines = self.session_detail_lines(session, content_width)
        scroll = 0

        win = curses.newwin(box_height, box_width, top, left)
        win.keypad(True)
        with suppress(curses.error):
            curses.curs_set(0)

        while True:
            max_scroll = max(0, len(lines) - body_height)
            scroll = clamp(scroll, 0, max_scroll)
            win.erase()
            with suppress(curses.error):
                win.box()
            safe_addnstr(win, 1, 2, "Session 详情", content_width, curses.A_BOLD)
            safe_addnstr(
                win,
                2,
                2,
                f"Lines {scroll + 1}-{min(len(lines), scroll + body_height)}/{len(lines)}",
                content_width,
                curses.A_UNDERLINE,
            )
            for row, line in enumerate(lines[scroll : scroll + body_height], start=3):
                safe_addnstr(win, row, 2, line, content_width)
            safe_addnstr(
                win,
                box_height - 2,
                2,
                "↑/↓/PgUp/PgDn/鼠标滚轮 滚动 | q/Esc/i 关闭",
                content_width,
                curses.A_BOLD,
            )
            with suppress(curses.error):
                win.refresh()

            key = win.getch()
            if key in (ord("q"), ord("i"), 27, 10, 13, curses.KEY_ENTER):
                return
            if key in (curses.KEY_UP, ord("k")):
                scroll -= 1
            elif key in (curses.KEY_DOWN, ord("j")):
                scroll += 1
            elif key == curses.KEY_PPAGE:
                scroll -= body_height
            elif key == curses.KEY_NPAGE:
                scroll += body_height
            elif key == curses.KEY_HOME:
                scroll = 0
            elif key == curses.KEY_END:
                scroll = max_scroll
            elif key == curses.KEY_MOUSE:
                try:
                    _, _, _, _, button_state = curses.getmouse()
                except curses.error:
                    continue
                if button_state & getattr(curses, "BUTTON4_PRESSED", 0):
                    scroll -= 3
                elif button_state & getattr(curses, "BUTTON5_PRESSED", 0):
                    scroll += 3
                elif button_state & (1 << 20):
                    scroll -= 3
                elif button_state & (1 << 21):
                    scroll += 3

    def session_detail_lines(self, session: Session, width: int) -> list[str]:
        lines: list[str] = []
        meta = [
            ("Title", session.title),
            ("ID", session.id),
            ("CWD", session.cwd),
            (
                "Created",
                f"{session.created_label} | Provider: {session.model_provider}",
            ),
            ("JSONL", str(session.rollout_path)),
        ]
        for label, value in meta:
            prefix = f"{label}: "
            wrapped = wrap_cells(str(value), width, indent=" " * len(prefix))
            if wrapped:
                lines.append(prefix + wrapped[0].lstrip())
                lines.extend(wrapped[1:])
            else:
                lines.append(prefix)
        lines.append("")
        lines.append("Conversation:")
        if session.preview:
            lines.append("Preview:")
            lines.extend(wrap_cells(session.preview, max(20, width - 2), indent="  "))
            lines.append("")
        lines.extend(load_conversation_lines(session, max(20, width - 2)))
        return lines

    def message(self, stdscr: curses.window, text: str, wait: bool = True) -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        lines = textwrap.wrap(text, max(20, width - 2)) or [""]
        start = max(0, height // 2 - len(lines) // 2)
        for offset, line in enumerate(lines):
            safe_addnstr(stdscr, start + offset, 1, line, width - 2)
        if wait:
            safe_addnstr(stdscr, height - 1, 0, "按任意键继续", width - 1, curses.A_BOLD)
            with suppress(curses.error):
                stdscr.refresh()
            stdscr.getch()
        else:
            with suppress(curses.error):
                stdscr.refresh()

    def show_result(
        self, stdscr: curses.window, result: UpdateResult, provider: str
    ) -> None:
        parts = [
            f"完成: 已把 {result.sqlite_rows} 条 sqlite 记录改为 '{provider}'。",
            f"jsonl 文件: {result.jsonl_files}, 修改行: {result.jsonl_lines}。",
        ]
        if result.backup_dir:
            parts.append(f"备份目录: {result.backup_dir}")
        if result.missing_jsonl:
            parts.append(f"缺失 jsonl: {len(result.missing_jsonl)} 个。")
        self.message(stdscr, " ".join(parts), wait=True)

    def show_delete_result(self, stdscr: curses.window, result: DeleteResult) -> None:
        parts = [
            f"完成: 已删除 {result.sqlite_rows} 条 sqlite 记录。",
            f"jsonl 文件: {result.jsonl_files}。",
        ]
        if result.backup_dir:
            parts.append(f"备份目录: {result.backup_dir}")
        if result.missing_jsonl:
            parts.append(f"缺失 jsonl: {len(result.missing_jsonl)} 个。")
        self.message(stdscr, " ".join(parts), wait=True)


def run_curses(app: SessionPicker) -> int:
    stdscr = curses.initscr()
    try:
        with suppress(curses.error):
            curses.noecho()
        with suppress(curses.error):
            curses.cbreak()
        stdscr.keypad(True)
        return app.run(stdscr)
    finally:
        with suppress(curses.error):
            stdscr.keypad(False)
        with suppress(curses.error):
            curses.nocbreak()
        with suppress(curses.error):
            curses.echo()
        with suppress(curses.error):
            curses.endwin()


def main() -> int:
    try:
        picker = SessionPicker(DEFAULT_CODEX_DIR.resolve(), include_archived=True)
        return run_curses(picker)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
