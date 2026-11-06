"""
Маскування секретів і очевидних персональних даних ПЕРЕД відправкою тексту
в Anthropic API (принцип Diligence).

Це страховка, а не гарантія: регулярні вирази не знайдуть усього, тому
користувач усе одно сам обирає, які проєкти/файли аналізувати.
Маркер [REDACTED:тип] лишається в тексті — оцінювач бачить, що секрет
був, але не бачить самого значення.
"""
import re

# (тип, шаблон, які групи лишити як префікс)
_RULES: list[tuple[str, re.Pattern, tuple[int, ...]]] = [
    ("private-key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), ()),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), ()),
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), ()),
    ("github-token", re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})"), ()),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), ()),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), ()),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), ()),
    ("jwt", re.compile(
        r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), ()),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/\-]{20,}=*"), ()),
    ("db-credentials", re.compile(
        r"(?i)\b((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqps?)://)[^\s:@/]+:[^\s@/]+@"),
        (1,)),
    ("secret-value", re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd)(\s*[:=]\s*[\"']?)([^\s\"'`,;]{6,})"),
        (1, 2)),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), ()),
]


def redact(text: str) -> tuple[str, int]:
    """Повертає (замаскований_текст, кількість_замін)."""
    total = 0
    for kind, rx, keep in _RULES:
        def _sub(m: re.Match, kind=kind, keep=keep) -> str:
            nonlocal total
            total += 1
            return "".join(m.group(i) for i in keep) + f"[REDACTED:{kind}]"
        text = rx.sub(_sub, text)
    return text, total
