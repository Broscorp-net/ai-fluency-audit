"""
Каталог 24 поведінкових індикаторів 4D і підрахунок їхньої частоти за розміткою діалогів.

Оцінок тут немає. Оцінювач розмічає кожен діалог вибірки (які індикатори в ньому видно),
а цей модуль лише рахує: у скількох діалогах і проєктах індикатор зустрівся, скільки це
приблизно за весь період і чи змінилась частота порівняно з минулим аудитом понад випадкову
похибку вибірки. Число рахує код, а не модель.

Єдине місце, де перелічено індикатори. Тест звіряє каталог із rubric-4d.md і tips.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

DIMENSIONS = ("delegation", "description", "discernment", "diligence")
MIN_PP = 10  # зміна частки менше за 10 п.п. не називається помітною, хоч би що казала статистика
MIN_SAMPLE = 20  # на менших вибірках z-тест бреше (3 проти 0 із 5 виглядало б «значущим»): помітною зміну не називаємо
Z_NOTABLE = 2.0
RARE_SHARE = 0.05
FREQUENT_SHARE = 0.30


@dataclass(frozen=True)
class Indicator:
    code: str
    dimension: str
    name: str            # слова для людини; кодів у відгуку людина не знає
    note: str = ""       # "ситуативний" | "рідко видно" | "видно частково"
    flag: bool = False   # у рубриці є тривожний слід 🔴: розмічається окремо, як "Код!"

    @property
    def quiet(self) -> bool:
        """Відсутність такого індикатора не є прогалиною: поведінка ситуативна або йде поза чатом."""
        return self.note in ("ситуативний", "рідко видно")


CATALOG: tuple[Indicator, ...] = (
    Indicator("Del1", "delegation", "Формулює мету до запиту"),
    Indicator("Del2", "delegation", "Радиться щодо підходу до виконання"),
    Indicator("Del3", "delegation", "Розпізнає, що задача не для ШІ", "рідко видно", flag=True),
    Indicator("Del4", "delegation", "Зважає, що ШІ вміє добре, а де помиляється", "видно частково"),
    Indicator("Del5", "delegation", "Лишається залученим, а не просто приймає результат"),
    Indicator("Del6", "delegation", "Обирає інструмент і підхід під задачу", "видно частково"),
    Indicator("Del7", "delegation", "Перерозподіляє ролі по ходу роботи", "видно частково"),
    Indicator("Des1", "description", "Називає аудиторію результату", "ситуативний"),
    Indicator("Des2", "description", "Задає формат, структуру й умову готовності"),
    Indicator("Des3", "description", "Передає тон і стиль", "ситуативний"),
    Indicator("Des4", "description", "Розбиває складну задачу на кроки"),
    Indicator("Des5", "description", "Уточнює результат у наступних репліках"),
    Indicator("Des6", "description", "Дає приклади того, що вважає добрим"),
    Indicator("Des7", "description", "Каже, як ШІ має взаємодіяти"),
    Indicator("Des8", "description", "Ставить межі: що робити й чого не чіпати"),
    Indicator("Dis1", "discernment", "Перевіряє факти й твердження, які мають значення"),
    Indicator("Dis2", "discernment", "Помічає, коли міркування чи результат ШІ не тримається"),
    Indicator("Dis3", "discernment", "Розпізнає, що ШІ бракує контексту"),
    Indicator("Dis4", "discernment", "Оцінює, чи є прогрес у спільній роботі"),
    Indicator("Dis5", "discernment", "Помічає, що манера ШІ заважає роботі"),
    Indicator("Dil1", "diligence", "Зважає, якою інформацією ділиться з ШІ", flag=True),
    Indicator("Dil2", "diligence", "Чесно каже про роль ШІ там, де це важить", "рідко видно", flag=True),
    Indicator("Dil3", "diligence", "Відповідає за те, що віддає далі", "видно частково", flag=True),
    Indicator("Dil4", "diligence", "Зважає наслідки того, що випускає у світ", "видно частково", flag=True),
)
BY_CODE = {i.code: i for i in CATALOG}
_LOOKUP = {i.code.lower(): i.code for i in CATALOG}
ALL_CODES = ", ".join(i.code for i in CATALOG)

GROUPS = (
    ("delegation", "🎯", "Delegation — Делегування"),
    ("description", "✍️", "Description — Опис"),
    ("discernment", "🔍", "Discernment — Розсудливість"),
    ("diligence", "✅", "Diligence — Ретельність"),
)


# ── розмітка → лічильники ────────────────────────────────────────────────────

def _normalize(raw) -> str:
    text = str(raw).strip()
    flag = text.endswith("!")
    code = _LOOKUP.get(text.rstrip("!").strip().lower())
    if code is None:
        raise ValueError(f"невідомий індикатор {raw!r}; допустимі: {ALL_CODES}")
    if flag and not BY_CODE[code].flag:
        raise ValueError(f"{code}! не існує: для цього індикатора тривожного сліду в рубриці немає")
    return code + ("!" if flag else "")


def _ranges(numbers: list) -> str:
    out, start, prev = [], None, None
    for n in numbers + [None]:
        if start is None:
            start = prev = n
        elif n is not None and n == prev + 1:
            prev = n
        else:
            out.append(str(start) if start == prev else f"{start}–{prev}")
            start = prev = n
    return ", ".join(out)


def parse_labels(raw, sample_size: int) -> dict:
    """
    {"1": ["Del1", "Des2"], "2": [], ...} → {1: ["Del1", "Des2"], 2: []}.
    Розмітка мусить покривати КОЖЕН діалог вибірки (порожній список — діалог без індикаторів):
    так оцінювач проходить усі діалоги, а не складає враження про загальне.
    ValueError пояснює, що саме виправити.
    """
    if isinstance(raw, dict) and isinstance(raw.get("labels"), dict):
        raw = raw["labels"]
    if not isinstance(raw, dict):
        raise ValueError('очікується JSON-обʼєкт {"1": ["Del1", "Des2"], "2": [], ...}')
    out = {}
    for key, codes in raw.items():
        try:
            num = int(key)
        except (TypeError, ValueError):
            raise ValueError(f"ключ {key!r} має бути номером діалогу")
        if not 1 <= num <= sample_size:
            raise ValueError(f"діалогу №{num} у вибірці немає (у ній {sample_size})")
        if not isinstance(codes, list):
            raise ValueError(f"діалог {num}: очікується список кодів, отримано {codes!r}")
        seen = []
        for c in codes:
            code = _normalize(c)
            if code not in seen:
                seen.append(code)
        out[num] = seen
    missing = [i for i in range(1, sample_size + 1) if i not in out]
    if missing:
        raise ValueError(f"немає розмітки для діалогів: {_ranges(missing)} (для діалогу без індикаторів став [])")
    return out


def tally(labels: dict, meta: list, exchanges_total: int) -> dict:
    """Лічильники за розміткою. meta[i] — {"p": проєкт, ...} діалогу №i+1 вибірки."""
    stats = {c.code: {"dialogs": 0, "flags": 0, "projects": 0} for c in CATALOG}
    projects = {c.code: set() for c in CATALOG}
    for num, codes in labels.items():
        project = (meta[num - 1].get("p") if 0 <= num - 1 < len(meta) else "") or "?"
        for code in codes:
            base = code.rstrip("!")
            if code.endswith("!"):
                stats[base]["flags"] += 1
            else:
                stats[base]["dialogs"] += 1
                projects[base].add(project)
    for code, seen in projects.items():
        stats[code]["projects"] = len(seen)
    return {"sample_size": len(meta), "exchanges_total": exchanges_total, "indicators": stats}


def valid_tally(obj) -> bool:
    """Чи можна довіряти структурі (запис історії може бути чужим або пошкодженим)."""
    if not isinstance(obj, dict) or not isinstance(obj.get("indicators"), dict):
        return False
    ints = (obj.get("sample_size"), obj.get("exchanges_total"))
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in ints) or not obj["sample_size"]:
        return False
    for c in CATALOG:
        s = obj["indicators"].get(c.code)
        if not isinstance(s, dict) or any(
            isinstance(s.get(k), bool) or not isinstance(s.get(k), int) or s[k] < 0
            for k in ("dialogs", "flags", "projects")
        ):
            return False
    return True


# ── порівняння й орієнтири ───────────────────────────────────────────────────

def share(t: dict, code: str) -> float:
    return t["indicators"][code]["dialogs"] / t["sample_size"]


def estimate(t: dict, code: str) -> int:
    """Скільки разів за весь період: частка вибірки × усі діалоги періоду (точно, якщо вибірка = період)."""
    d, n, total = t["indicators"][code]["dialogs"], t["sample_size"], t["exchanges_total"]
    return d if total <= n else round(d * total / n)


def compare(cur: dict, prev: dict) -> dict:
    """
    Зміна частки кожного індикатора проти минулого аудиту.
    notable — перевищує випадкову похибку вибірки (двопропорційний z-тест), не менша за MIN_PP п.п.,
              і обидві вибірки мають щонайменше MIN_SAMPLE діалогів;
    noise   — частка змінилась, але в межах похибки; same — не змінилась.
    Порівнюються частки, а не сирі числа: вибірки двох аудитів можуть бути різного розміру.
    """
    out = {}
    n1, n2 = prev["sample_size"], cur["sample_size"]
    for c in CATALOG:
        was, now = prev["indicators"][c.code]["dialogs"], cur["indicators"][c.code]["dialogs"]
        p1, p2 = was / n1, now / n2
        pooled = (was + now) / (n1 + n2)
        se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
        pp = round((p2 - p1) * 100)
        z = (p2 - p1) / se if se else 0.0
        if min(n1, n2) >= MIN_SAMPLE and abs(z) >= Z_NOTABLE and abs(pp) >= MIN_PP:
            kind = "notable"
        elif pp == 0:
            kind = "same"
        else:
            kind = "noise"
        out[c.code] = {"was": was, "was_n": n1, "now": now, "now_n": n2, "pp": pp, "kind": kind}
    return out


def signals(t: dict) -> dict:
    """Орієнтири для відгуку: що частіше, що рідко, чого немає. Пороги — підказка, а не вердикт."""
    def label(c: Indicator, extra: str = "") -> str:
        note = f" ({c.note})" if c.note else ""
        return f"{c.code} — {c.name}{note}{extra}"

    out = {"never_shown": [], "rarely_shown": [], "frequently_shown": [], "red_flags": []}
    for c in CATALOG:
        s = t["indicators"][c.code]
        if s["flags"]:
            out["red_flags"].append(label(c, f": тривожних слідів {s['flags']}"))
        if c.quiet:
            continue
        sh = share(t, c.code)
        if s["dialogs"] == 0:
            out["never_shown"].append(label(c))
        elif sh <= RARE_SHARE:
            out["rarely_shown"].append(label(c, f": {s['dialogs']} з {t['sample_size']}"))
        elif sh >= FREQUENT_SHARE:
            out["frequently_shown"].append(label(c, f": {s['dialogs']} з {t['sample_size']}"))
    return out


def coverage(t: dict) -> dict:
    shown = [c for c in CATALOG if t["indicators"][c.code]["dialogs"] > 0]
    absent = [c for c in CATALOG if t["indicators"][c.code]["dialogs"] == 0]
    return {
        "shown": len(shown), "absent": len(absent), "absent_quiet": sum(c.quiet for c in absent),
        "flags": sum(t["indicators"][c.code]["flags"] for c in CATALOG),
    }


# ── markdown-таблиця для відгуку в чаті ──────────────────────────────────────

def _pct(d: int, n: int) -> int:
    return round(100 * d / n)


def _change_cell(ch: dict | None) -> str:
    if not ch:
        return "—"
    was = f"{ch['was']} з {ch['was_n']} ({_pct(ch['was'], ch['was_n'])}%)"
    if ch["kind"] == "same":
        return f"{was} · без змін"
    arrow = "▲" if ch["pp"] > 0 else "▼"
    verdict = "помітна зміна" if ch["kind"] == "notable" else "у межах похибки"
    return f"{was} · {arrow} {ch['pp']:+d} п.п. · {verdict}"


def render_markdown(t: dict, prev: dict | None = None) -> str:
    n, total = t["sample_size"], t["exchanges_total"]
    changes = compare(t, prev) if prev else {}
    cov = coverage(t)
    lines = [
        f"**У вибірці {n} діалогів із {total} за період.** Показано хоч в одному діалозі: **{cov['shown']} з {len(CATALOG)}** "
        f"індикаторів; жодного разу не помічено: {cov['absent']} (з них ситуативних чи рідко видних: {cov['absent_quiet']})."
        + (f" Тривожних слідів 🔴: **{cov['flags']}**." if cov["flags"] else ""),
        "",
    ]
    period_col = "За весь період" if total > n else "За період"
    for key, icon, title in GROUPS:
        lines += [f"### {icon} {title}", ""]
        head = f"| Поведінка | Діалогів | Частка | {period_col} | У проєктах | 🔴 |" + (" Було → зміна |" if prev else "")
        lines += [head, "|---|---|---|---|---|---|" + ("---|" if prev else "")]
        for c in (c for c in CATALOG if c.dimension == key):
            s = t["indicators"][c.code]
            name = f"{c.name} ({c.note})" if c.note else c.name
            est = f"≈ {estimate(t, c.code)}" if total > n else str(s["dialogs"])
            row = (f"| {name} | **{s['dialogs']}** з {n} | {_pct(s['dialogs'], n)}% | {est} | "
                   f"{s['projects'] if s['dialogs'] else '—'} | {s['flags'] or ''} |")
            if prev:
                row += f" {_change_cell(changes.get(c.code))} |"
            lines.append(row)
        lines.append("")
    lines += [
        "*Частка = діалоги з цією поведінкою / діалоги вибірки. «За весь період» — оцінка (частка × усі діалоги періоду), "
        "а не точний підрахунок, якщо вибірка менша за період. Зміну названо помітною, лише якщо вона перевищує випадкову "
        "похибку вибірки й становить щонайменше 10 п.п.; з 24 індикаторів один-два можуть змінитися й випадково.*",
    ]
    return "\n".join(lines)
