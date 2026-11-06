"""Saves and loads analysis history from a local JSON file."""
import json
import uuid
from datetime import datetime
from pathlib import Path

HISTORY_FILE = Path(__file__).parent.parent / "history.json"


def save(result: dict, source: str, total_exchanges: int) -> dict:
    history = load_all()
    entry = {
        "id": str(uuid.uuid4())[:8],
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": source,
        "total_exchanges": total_exchanges,
        "scores": result.get("scores", {}),
        "summary": result.get("summary", ""),
        "dominant_mode": result.get("dominant_mode", ""),
        "patterns": result.get("patterns", []),
        "strengths": result.get("strengths", []),
        "gaps": result.get("gaps", []),
    }
    history.append(entry)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


def load_all() -> list:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def get_previous(current_id: str) -> dict | None:
    history = load_all()
    for i, entry in enumerate(history):
        if entry["id"] == current_id and i > 0:
            return history[i - 1]
    return None


def build_comparison(current: dict, previous: dict) -> list[dict]:
    """Returns list of {key, label, current, previous, delta, comment} for each D."""
    labels = {
        "delegation": ("🎯", "Delegation / Делегування"),
        "description": ("✍️", "Description / Опис"),
        "discernment": ("🔍", "Discernment / Розсудливість"),
        "diligence": ("✅", "Diligence / Ретельність"),
    }
    result = []
    for key, (icon, label) in labels.items():
        cur = current["scores"].get(key, 0)
        prev = previous["scores"].get(key, 0)
        delta = cur - prev
        if delta > 0:
            comment = f"Покращення на {delta} бал(и) — продовжуй у тому ж напрямку"
            trend = "up"
        elif delta < 0:
            comment = f"Зниження на {abs(delta)} бал(и) — зверни увагу"
            trend = "down"
        else:
            comment = "Без змін"
            trend = "same"
        result.append({
            "key": key, "icon": icon, "label": label,
            "current": cur, "previous": prev,
            "delta": delta, "comment": comment, "trend": trend,
        })
    return result
