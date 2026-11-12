"""
Parsers for ChatGPT, Claude, and Gemini chat export formats.
Each parser returns a list of conversations: [{"user": str, "assistant": str}, ...]
"""
import json
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Exchange:
    user: str
    assistant: str
    # Нижче — лише для агентних джерел (Claude Code); для чат-експортів лишаються порожніми
    tools: list[str] = field(default_factory=list)  # інструменти, які викликав ШІ
    interrupted: bool = False  # користувач перервав/відхилив дію ШІ
    session: str = ""
    project: str = ""
    timestamp: str = ""


def parse_chatgpt(data: list) -> list[Exchange]:
    """Parse ChatGPT conversations.json export format."""
    exchanges = []
    conversations = data if isinstance(data, list) else [data]

    for conv in conversations:
        mapping = conv.get("mapping", {})
        if not mapping:
            continue

        current_node = conv.get("current_node")
        if not current_node:
            # fallback: find leaf node
            children_set = set()
            for node in mapping.values():
                for c in node.get("children", []):
                    children_set.add(c)
            leaves = [nid for nid in mapping if nid not in children_set]
            current_node = leaves[-1] if leaves else None

        if not current_node:
            continue

        thread = []
        node_id = current_node
        while node_id:
            node = mapping.get(node_id)
            if not node:
                break
            msg = node.get("message")
            if msg:
                role = msg.get("author", {}).get("role", "")
                if role in ("user", "assistant"):
                    content = msg.get("content", {})
                    parts = content.get("parts", [])
                    text = " ".join(str(p) for p in parts if isinstance(p, str)).strip()
                    if text:
                        thread.insert(0, {"role": role, "content": text})
            node_id = node.get("parent")

        exchanges.extend(_thread_to_exchanges(thread))

    return exchanges


def parse_claude(data: list | dict) -> list[Exchange]:
    """Parse Claude.ai export format."""
    exchanges = []
    conversations = data if isinstance(data, list) else [data]

    for conv in conversations:
        messages = conv.get("chat_messages") or conv.get("messages") or []
        thread = []
        for msg in messages:
            role = msg.get("sender") or msg.get("role") or ""
            if role == "human":
                role = "user"
            if role not in ("user", "assistant"):
                continue
            content = msg.get("text") or msg.get("content") or ""
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            if isinstance(content, str) and content.strip():
                thread.append({"role": role, "content": content.strip()})

        exchanges.extend(_thread_to_exchanges(thread))

    return exchanges


def parse_gemini(data: dict | list) -> list[Exchange]:
    """Parse Google Gemini / Bard export format."""
    exchanges = []

    # Google Takeout wraps everything in a top-level dict
    if isinstance(data, dict):
        conversations = (
            data.get("conversations")
            or data.get("messages")
            or data.get("chats")
            or []
        )
        if not conversations and "requestContent" in data:
            conversations = [data]
    else:
        conversations = data

    for conv in conversations:
        # Gemini Takeout format: requestContent / responseContent
        if "requestContent" in conv or "responseContent" in conv:
            user_parts = conv.get("requestContent", [])
            ai_parts = conv.get("responseContent", [])
            user_text = _extract_gemini_text(user_parts)
            ai_text = _extract_gemini_text(ai_parts)
            if user_text and ai_text:
                exchanges.append(Exchange(user=user_text, assistant=ai_text))
            continue

        # Generic messages array
        thread = []
        for msg in conv.get("messages", []):
            role = msg.get("role") or msg.get("author") or ""
            if role in ("user", "human"):
                role = "user"
            elif role in ("model", "assistant", "gemini"):
                role = "assistant"
            else:
                continue
            content = msg.get("content") or msg.get("text") or ""
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            if content.strip():
                thread.append({"role": role, "content": content.strip()})
        exchanges.extend(_thread_to_exchanges(thread))

    return exchanges


def parse_generic(data: list | dict) -> list[Exchange]:
    """Fallback parser for generic [{role, content}] arrays."""
    exchanges = []
    messages = data if isinstance(data, list) else data.get("messages", [])
    thread = []
    for msg in messages:
        role = msg.get("role") or msg.get("sender") or ""
        if role in ("human", "Human"):
            role = "user"
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content") or msg.get("text") or ""
        if isinstance(content, str) and content.strip():
            thread.append({"role": role, "content": content.strip()})
    exchanges.extend(_thread_to_exchanges(thread))
    return exchanges


def auto_detect_and_parse(raw: bytes) -> tuple[list[Exchange], str]:
    """Detect export source and parse. Returns (exchanges, source_name)."""
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        data = json.loads(text)
    except Exception:
        # Не цілий JSON — можливо JSONL (історія Claude Code: один запис на рядок)
        from core import claude_code  # імпорт тут, щоб уникнути циклу

        records = [d for d in (claude_code._loads(l) for l in text.splitlines()) if d]
        if records and claude_code.looks_like_claude_code(records):
            return claude_code.parse_records(records, session="S1"), claude_code.SOURCE_NAME
        raise ValueError("Файл не є валідним JSON. Спробуйте інший формат.")

    # ChatGPT: list with mapping key
    if isinstance(data, list) and data and "mapping" in data[0]:
        return parse_chatgpt(data), "ChatGPT"

    # Claude: list with chat_messages key
    if isinstance(data, list) and data and (
        "chat_messages" in data[0] or "sender" in str(data[0])[:200]
    ):
        return parse_claude(data), "Claude"

    # Claude single conversation
    if isinstance(data, dict) and ("chat_messages" in data or "uuid" in data):
        return parse_claude([data] if isinstance(data, dict) else data), "Claude"

    # Gemini Takeout
    if isinstance(data, dict) and (
        "conversations" in data or "requestContent" in data
    ):
        return parse_gemini(data), "Gemini"

    # Generic fallback
    return parse_generic(data), "Generic"


def _thread_to_exchanges(thread: list[dict]) -> list[Exchange]:
    """Convert a flat thread of messages into paired user/assistant exchanges."""
    exchanges = []
    i = 0
    while i < len(thread):
        if thread[i]["role"] == "user":
            user_text = thread[i]["content"]
            assistant_text = ""
            if i + 1 < len(thread) and thread[i + 1]["role"] == "assistant":
                assistant_text = thread[i + 1]["content"]
                i += 2
            else:
                i += 1
            exchanges.append(Exchange(user=user_text, assistant=assistant_text))
        else:
            i += 1
    return exchanges


def _extract_gemini_text(parts: list) -> str:
    texts = []
    for part in parts:
        if isinstance(part, str):
            texts.append(part)
        elif isinstance(part, dict):
            texts.append(part.get("text", ""))
    return " ".join(t for t in texts if t).strip()


def sample_exchanges(exchanges: list[Exchange], max_exchanges: int = 40) -> list[Exchange]:
    """Return a representative sample — prefer recent, keep diversity."""
    if len(exchanges) <= max_exchanges:
        return exchanges
    step = len(exchanges) / max_exchanges
    return [exchanges[int(i * step)] for i in range(max_exchanges)]


def format_for_analysis(exchanges: list[Exchange], with_project: bool = False) -> str:
    """Format exchanges as readable text for the evaluator.

    with_project=True додає назву проєкту в заголовок діалогу, щоб оцінювач міг назвати
    діалог зрозуміло для людини.
    """
    lines = []
    for i, ex in enumerate(exchanges, 1):
        # Мітка сесії показує оцінювачу структуру ітерацій
        header = f"--- Діалог {i}" + (f" · сесія {ex.session}" if ex.session else "")
        if with_project and ex.project:
            header += f" · проєкт {ex.project}"
        header += " ---"
        lines.append(header)
        lines.append(f"[КОРИСТУВАЧ]: {ex.user[:600]}")
        if ex.tools:
            counts = Counter(ex.tools)
            lines.append("[ДІЇ ШІ]: " + ", ".join(
                f"{name}×{n}" if n > 1 else name for name, n in counts.items()
            ))
        if ex.assistant:
            lines.append(f"[ШІ]: {ex.assistant[:400]}")
        if ex.interrupted:
            lines.append("[ПЕРЕРВАНО КОРИСТУВАЧЕМ]")
        lines.append("")
    return "\n".join(lines)
