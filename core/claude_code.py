"""
Читач історії Claude Code.

Claude Code пише кожну сесію в окремий файл
    <config>/projects/<закодований-шлях-проєкту>/<session-id>.jsonl
де <config> це:
    Windows : %USERPROFILE%\\.claude
    macOS   : ~/.claude
    Linux   : ~/.claude (або ~/.config/claude у новіших версіях)
    будь-де : $CLAUDE_CONFIG_DIR, якщо змінну задано
Кожен рядок файлу — окремий JSON-запис (user / assistant / службові).

З усього цього нам потрібні лише справжні промпти людини та відповіді ШІ.
Результати інструментів (вміст файлів, виводи команд) ми НЕ читаємо у вибірку —
це і шум, і ризик витоку; зберігаємо лише назви викликаних інструментів.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from core.parsers import Exchange

SOURCE_NAME = "Claude Code"


# ── Пошук файлів ─────────────────────────────────────────────────────────────

def projects_dirs(extra: str | os.PathLike | None = None) -> list[Path]:
    """Усі існуючі папки `projects`, де може лежати історія."""
    candidates: list[Path] = []
    if extra:
        p = Path(extra).expanduser()
        candidates += [p, p / "projects"]  # можна вказати і .claude, і projects
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        candidates.append(Path(env).expanduser() / "projects")
    home = Path.home()
    candidates.append(home / ".claude" / "projects")
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    candidates.append(xdg / "claude" / "projects")

    found: list[Path] = []
    seen: set[Path] = set()
    for c in candidates:
        try:
            if c.is_dir():
                key = c.resolve()
                if key not in seen:
                    seen.add(key)
                    found.append(c)
        except OSError:
            continue
    return found


@dataclass
class SessionInfo:
    path: Path
    project: str
    title: str
    modified: datetime  # UTC, aware
    size: int


def discover_sessions(extra: str | os.PathLike | None = None) -> list[SessionInfo]:
    """Список сесій (новіші першими). Читає лише початок/кінець файлів — швидко."""
    sessions: list[SessionInfo] = []
    for root in projects_dirs(extra):
        try:
            project_dirs = [d for d in root.iterdir() if d.is_dir()]
        except OSError:
            continue
        for pdir in project_dirs:
            for f in pdir.glob("*.jsonl"):  # лише верхній рівень: без субагентів
                try:
                    st = f.stat()
                except OSError:
                    continue
                if st.st_size < 200:
                    continue
                cwd, title = _peek(f)
                sessions.append(SessionInfo(
                    path=f,
                    project=project_label(cwd, pdir.name),
                    title=title or f.stem[:8],
                    modified=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
                    size=st.st_size,
                ))
    sessions.sort(key=lambda s: s.modified, reverse=True)
    return sessions


def project_label(cwd: str, fallback: str) -> str:
    """Людська назва проєкту з робочої папки (worktree зливаємо з основним проєктом)."""
    parts = [p for p in re.split(r"[\\/]+", cwd) if p]
    for i in range(len(parts) - 2):  # .../<проєкт>/.claude/worktrees/<назва>
        if parts[i + 1] == ".claude" and parts[i + 2] == "worktrees":
            return parts[i]
    return parts[-1] if parts else fallback


def _peek(path: Path) -> tuple[str, str]:
    """cwd (з початку файлу) і назва сесії (з кінця), не читаючи весь файл."""
    chunk = 128 * 1024
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            head = f.read(chunk)
            tail = b""
            if size > len(head):
                f.seek(max(len(head), size - chunk))
                tail = f.read()
    except OSError:
        return "", ""

    cwd = ""
    for raw in head.splitlines():
        d = _loads(raw)
        if d and d.get("cwd"):
            cwd = d["cwd"]
            break

    title = ""
    for raw in reversed((tail or head).splitlines()):
        d = _loads(raw)
        if d and d.get("type") in ("custom-title", "ai-title"):
            title = d.get("customTitle") or d.get("aiTitle") or ""
            if title:
                break
    return cwd, title


# ── Розбір записів ───────────────────────────────────────────────────────────

# Службові вставки, які Claude Code додає у «user»-повідомлення
_INJECTED = re.compile(
    r"<(system-reminder|local-command-caveat|local-command-stdout|local-command-stderr|"
    r"command-name|command-message|command-args|ide_opened_file|ide_selection|"
    r"task-notification|side-sessions-event|ci-monitor-event|user-prompt-submit-hook)\b[^>]*>"
    r".*?</\1>",
    re.S,
)
_NOISE_PREFIXES = (
    "Caveat:",
    "This session is being continued from a previous conversation",
)
# Ознаки того, що користувач відхилив дію ШІ (сигнал Discernment)
_REJECT_MARKERS = ("want to proceed", "was rejected")


def _loads(raw: bytes | str) -> dict | None:
    try:
        d = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return d if isinstance(d, dict) else None


def _flat(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def _human_text(content) -> tuple[str, bool]:
    """(текст_промпту_людини, чи_відхилено_дію_ШІ). Порожній текст = не промпт."""
    rejected = False
    parts: list[str] = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            kind = b.get("type")
            if kind == "text":
                parts.append(b.get("text") or "")
            elif kind == "image":
                parts.append("[зображення]")
            elif kind == "tool_result" and b.get("is_error"):
                if any(m in _flat(b.get("content")).lower() for m in _REJECT_MARKERS):
                    rejected = True
    text = _INJECTED.sub("", "\n".join(parts)).strip()
    if text.startswith(_NOISE_PREFIXES):
        text = ""
    return text, rejected


def _parse_ts(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_records(records: Iterable[dict], project: str = "", session: str = "") -> list[Exchange]:
    """Перетворює записи однієї сесії на пари «промпт людини → дії/відповідь ШІ»."""
    exchanges: list[Exchange] = []
    current: Exchange | None = None
    seen: set[str] = set()

    for d in records:
        kind = d.get("type")
        if kind not in ("user", "assistant") or d.get("isSidechain"):
            continue
        uid = d.get("uuid")
        if uid:
            if uid in seen:
                continue
            seen.add(uid)

        message = d.get("message") or {}
        content = message.get("content")

        if kind == "user":
            if d.get("isMeta"):
                continue
            text, rejected = _human_text(content)
            if rejected and current:
                current.interrupted = True
            if not text:
                continue  # tool_result або службовий запис
            if text.startswith("[Request interrupted"):
                if current:
                    current.interrupted = True
                continue
            current = Exchange(
                user=text, assistant="", session=session, project=project,
                timestamp=d.get("timestamp", ""),
            )
            exchanges.append(current)
            continue

        # assistant
        if current is None or message.get("model") == "<synthetic>":
            continue
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for b in content or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and (b.get("text") or "").strip():
                current.assistant = (current.assistant + "\n" + b["text"]).strip()
            elif b.get("type") == "tool_use" and b.get("name"):
                current.tools.append(b["name"])
            # thinking-блоки свідомо ігноруємо

    return exchanges


def read_jsonl(path: str | os.PathLike) -> Iterator[dict]:
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            d = _loads(line)
            if d is not None:
                yield d


def load_sessions(paths: Iterable[str | os.PathLike], since: datetime | None = None) -> list[Exchange]:
    """Читає вибрані сесії (бажано в хронологічному порядку) в один список обмінів."""
    result: list[Exchange] = []
    for n, path in enumerate(paths, 1):
        records = list(read_jsonl(path))
        cwd = next((r["cwd"] for r in records if r.get("cwd")), "")
        project = project_label(cwd, Path(path).parent.name)
        result.extend(_since(parse_records(records, project=project, session=f"S{n}"), since))
    return result


def parse_uploads(blobs: Iterable[bytes], since: datetime | None = None) -> list[Exchange]:
    """Те саме, але з завантажених вручну .jsonl файлів (коли застосунок не на вашому ПК)."""
    result: list[Exchange] = []
    for n, blob in enumerate(blobs, 1):
        records = [d for d in (_loads(line) for line in blob.decode("utf-8", "replace").splitlines()) if d]
        cwd = next((r["cwd"] for r in records if r.get("cwd")), "")
        result.extend(_since(parse_records(records, project=project_label(cwd, ""), session=f"S{n}"), since))
    return result


def looks_like_claude_code(records: list[dict]) -> bool:
    return any(r.get("sessionId") and r.get("type") in ("user", "assistant") for r in records[:50])


def _since(exchanges: list[Exchange], since: datetime | None) -> list[Exchange]:
    if since is None:
        return exchanges
    out = []
    for e in exchanges:
        ts = _parse_ts(e.timestamp)
        if ts is None or ts >= since:
            out.append(e)
    return out
