# 4D AI Fluency Auditor

Інструмент Broscorp для персонального аудиту того, як співробітник працює зі штучним інтелектом,
за моделлю **4D**: Delegation · Description · Discernment · Diligence.
Оцінки 1–10, виявлені патерни, три поради з готовими шаблонами промптів і порівняння з минулим разом.

Критерії — з внутрішнього гайда Broscorp та Framework for AI Fluency v1.1 (Dakan & Feller).

## Два способи використання

### 1. Плагін для Claude Code — для співробітників (рекомендовано)

Аналізує вашу **локальну історію Claude Code**. Без API-ключів і без окремих програм.
Потрібен лише Python 3.9+.

```
/plugin marketplace add Broscorp-net/4D-method-claude-plugin
/plugin install broscorp-ai-fluency@broscorp-tools
```

Запуск: напишіть «оціни, як я працюю зі ШІ» або `/broscorp-ai-fluency:ai-fluency-audit`.

Докладно (приватність, роздача всій компанії, оновлення):
[plugins/broscorp-ai-fluency/README.md](plugins/broscorp-ai-fluency/README.md)

### 2. Streamlit-апка

Те саме, але з графічним інтерфейсом, а також підтримка експортів **ChatGPT, Claude (claude.ai) і Gemini**.
Потрібен Anthropic API-ключ.

```
pip install -r requirements.txt
streamlit run app.py
```

Автопошук історії Claude Code працює, лише коли апка запущена на вашому комп'ютері.

## Що в репозиторії

| Шлях | Призначення |
|---|---|
| `plugins/broscorp-ai-fluency/` | плагін Claude Code зі скілом `ai-fluency-audit` |
| `.claude-plugin/marketplace.json` | маркетплейс Broscorp для Claude Code |
| `app.py`, `core/` | Streamlit-апка та спільна логіка (парсери, маскування секретів, оцінювач) |
| `tools/sync_skill.py` | копіює спільні модулі з `core/` у скіл (скіл має бути самодостатнім) |
| `tests/` | автотести |

`core/` — єдине джерело правди. Копії в `plugins/.../scripts/core/` руками не редагувати:
після змін у `core/` запустіть `python tools/sync_skill.py` (тест падає, якщо вони розійшлися).

## Тести

```
python -m unittest discover -s tests -t .
```

## Приватність

Історія чатів може містити код і дані клієнтів. Інструмент читає лише тексти промптів і відповідей ШІ
(без вмісту файлів і виводу команд), автоматично маскує секрети й персональні дані та нічого
не публікує. Не аналізуйте історію з комерційною таємницею — це принцип Diligence.
