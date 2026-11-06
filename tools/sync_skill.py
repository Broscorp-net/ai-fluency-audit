#!/usr/bin/env python3
"""
Скіл має бути самодостатнім (його встановлюють окремо від решти репозиторію),
тому спільні модулі з core/ копіюються всередину скіла.

    python tools/sync_skill.py          # скопіювати
    python tools/sync_skill.py --check  # лише перевірити; код виходу 1, якщо розбіжність

Єдине джерело правди — core/. Копії в скілі руками не редагувати.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "core"
DST = ROOT / "plugins" / "broscorp-ai-fluency" / "skills" / "ai-fluency-audit" / "scripts" / "core"
FILES = ("__init__.py", "parsers.py", "claude_code.py", "redact.py")


def out_of_sync() -> list[str]:
    return [
        f for f in FILES
        if not (DST / f).exists() or (DST / f).read_bytes() != (SRC / f).read_bytes()
    ]


def main() -> int:
    try:  # консоль Windows за замовчуванням не UTF-8
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    stale = out_of_sync()
    if "--check" in sys.argv:
        for f in stale:
            print(f"Розбіжність: {f}")
        return 1 if stale else 0
    DST.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        shutil.copyfile(SRC / f, DST / f)
    print(f"Скопійовано {len(FILES)} файлів → {DST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
