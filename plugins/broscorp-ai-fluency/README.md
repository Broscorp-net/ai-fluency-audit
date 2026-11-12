# broscorp-ai-fluency

Плагін для Claude Code з одним скілом — **`ai-fluency-audit`**. Він читає *вашу локальну* історію
Claude Code і видає персональний відгук за моделлю 4D (Delegation · Description · Discernment ·
Diligence): оцінки 1–10, патерни з прикладами, три поради з готовими шаблонами промптів і
порівняння з минулим разом. Критерії — з внутрішнього гайда Broscorp та Framework for AI Fluency v1.1.

## Для співробітника

Встановлення (один раз):

```
/plugin marketplace add Broscorp-net/4D-method-claude-plugin
/plugin install broscorp-ai-fluency@broscorp-tools
```

Запуск — або словами («оціни, як я працюю зі ШІ»), або командою:

```
/broscorp-ai-fluency:ai-fluency-audit
/broscorp-ai-fluency:ai-fluency-audit 60      ← за 60 днів
```

Скіл спершу покаже список ваших проєктів і **спитає, що виключити** (наприклад, клієнтські).
Без вашої відповіді нічого не читається.

Потрібен **Python 3.9+** (python.org); пакетів встановлювати не треба.

## Приватність — що відбувається з даними

| Питання | Відповідь |
|---|---|
| Що читається | `~/.claude/projects/*/*.jsonl`: лише тексти ваших промптів, текст відповідей ШІ та **назви** викликаних інструментів |
| Що НЕ читається | Вміст файлів, виводи команд, «думки» моделі, субагенти |
| Секрети | Ключі, токени, паролі, email автоматично маскуються (`[REDACTED:…]`) до того, як текст потрапить у вибірку |
| Куди йдуть дані | Нікуди окрім поточної сесії Claude Code, яка й формує відгук. Скрипт не має мережевого коду (це перевіряє тест) |
| Що зберігається | Локально `~/.claude/ai-fluency/history.json`: оцінки, короткі висновки й числа збору (кількість сесій, проєктів і діалогів, медіанна довжина промпту, частка коротких промптів, перервані дії, замасковані фрагменти). **Без текстів промптів і назв проєктів** |
| HTML-звіт | Локальний файл у `~/.claude/ai-fluency/reports/`: оцінки, патерни, поради з шаблонами промптів, прогрес, історія всіх аудитів із графіком і згорнутий блок зі статистикою збору. Відкривається у браузері напряму, без вебсервера |
| Хто бачить результат | Лише ви. Компанія результатів не отримує |

## Для адміністратора

### Автоматична роздача всім співробітникам

У керованих налаштуваннях Claude Code (managed settings):

```json
{
  "extraKnownMarketplaces": {
    "broscorp-tools": {
      "source": { "source": "github", "repo": "Broscorp-net/4D-method-claude-plugin" },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "broscorp-ai-fluency@broscorp-tools": true
  }
}
```

Розташування файлу `managed-settings.json`:

| ОС | Шлях |
|---|---|
| Windows | `C:\Program Files\ClaudeCode\managed-settings.json` |
| macOS | `/Library/Application Support/ClaudeCode/managed-settings.json` |
| Linux / WSL | `/etc/claude-code/managed-settings.json` |

Нюанси з документації Claude Code:
- За замовчуванням на машині діє лише **одне** джерело керованих налаштувань
  (server-managed → MDM → файл). Якщо вже використовуєте одне з них, додавайте ключі саме туди
  або виставте `managedSourcesBehavior: "merge"`.
- Альтернатива без прав адміністратора ОС: ті самі два ключі в `.claude/settings.json` репозиторію
  компанії (діє після того, як співробітник довірить папку).
- **Приватний репозиторій:** Claude Code не має власного git-токена, використовує звичайні
  git-облікові дані співробітника (SSH або `gh auth login` + `gh auth setup-git`).
  Для автооновлення у фоні `GITHUB_TOKEN` сам по собі не діє — лише через credential helper.
- Плагіни **недоступні в хмарних і WSL-сесіях**. Робота в Claude Desktop (вкладка Code) за документацією
  має підхоплювати керовані плагіни так само, але прямо це не підтверджено — перевірте на тестовій машині.

### Перед роздачею

1. `claude plugin validate ./plugins/broscorp-ai-fluency --strict` і `claude plugin validate .` (маркетплейс).
2. Локальна перевірка: `/plugin marketplace add ./шлях/до/репозиторію`, `/plugin install broscorp-ai-fluency@broscorp-tools`,
   потім запустити скіл на своїй історії.
3. Прочитати розділ про безпеку плагінів у документації Claude Code: плагін запускає скрипт на машинах співробітників.
   Скрипт ([`fluency.py`](skills/ai-fluency-audit/scripts/fluency.py)) невеликий і читається за 10 хвилин:
   лише стандартна бібліотека, без мережі, пише тільки у `~/.claude/ai-fluency/`.

### Оновлення

Змінили код чи рубрику → підніміть `version` у `plugin.json` **і** в `.claude-plugin/marketplace.json`
(у корені репозиторію) — без цього співробітники не отримають оновлення.

## Для розробника

Спільні модулі живуть у `core/` (їх використовує й Streamlit-апка). У скіл їх копіює
`python tools/sync_skill.py` — скіл має бути самодостатнім. Копії в `skills/.../scripts/core/`
руками не редагувати; тест `tests/test_skill.py` падає, якщо вони розійшлися з `core/`.
Тести: `python -m unittest discover -s tests -t .`

Рубрика оцінювання — `skills/ai-fluency-audit/references/rubric-4d.md`. Її критерії відповідають
системному промпту в `core/evaluator.py` (апка); змінюючи одне, перевіряйте друге.
