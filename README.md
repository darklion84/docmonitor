# DocMonitor

Отслеживание изменений документации на базе **changedetection.io (CDIO)**.
Источники (сайты, PDF, локальные/Markdown-файлы) проверяются по расписанию; при изменении
формируется дельта (**diff + AI-резюме**) и уходит на **email**. В перспективе — задача в JIRA.

Принцип: **конфигурируем CDIO, а не пишем код**. Кастомный код появляется только в поздних фазах
(Office-адаптер, JIRA-мост).

## MVP: что работает на этом этапе
- HTML-страницы и локальные/Markdown-файлы.
- Детект изменений, текстовый **diff**, **AI-резюме** через Anthropic Claude.
- Уведомление **на каждое изменение** по email.

---

## Предварительно
- Docker + Docker Compose.
- Ключ **Anthropic** (`ANTHROPIC_API_KEY`) — для AI-резюме.
- Доступ к **SMTP** (хост, логин/пароль, отправитель/получатель) — для email.

## Быстрый старт
```bash
git clone <repo-url> docmonitor && cd docmonitor
python3 scripts/bootstrap.py
# UI:  http://localhost:5050
```
`bootstrap.py` поднимет стек, дотащит CDIO API key в `.env`, применит рекомендуемые
настройки CDIO (LLM model/multiplier, Notifications format/template), при наличии
`AUTH_*` в `.env` — провижионирует auth-источники, и напечатает чек-лист.
Идемпотентен: непустые значения не перетирает. Подробно — [`docs/deploy.md`](docs/deploy.md).

## Настройка (один раз, через UI)

### 1. Email-уведомления (глобально)
`Settings → Notifications`:
- **Notification URL** — Apprise-строка SMTP, например:
  ```
  mailtos://USER:PASS@smtp.example.com?to=team@example.com&from=docmonitor@example.com
  ```
- **Notification format = `Text`** (глобально). `text/plain` Gmail рендерит с переносами стабильно;
  `?format=` к URL не дописывать. (При `HTML` Apprise оборачивает тело в `<pre>` + впрыскивает `<br>` —
  Gmail теряет переносы; проверено через mailpit.)
- **Notification Title**: `[DocMonitor] Изменилось: {{watch_url}}`
- **Notification Body**: вставьте `config/notification-email.j2` — `{{raw_diff}}` даёт читабельный diff
  формата `(changed) … / (into) …` с переносами.
- **ВАЖНО — diff и Telegram несовместимы в одном уведомлении**: `{{raw_diff}}` чист только когда email —
  ЕДИНСТВЕННЫЙ канал. Если в том же списке есть Telegram, его разметка diff (`<s>/<b>`) протекает в письмо
  (баг общего diff-объекта в CDIO) — либо теги, либо пустой diff. Нужен Telegram параллельно → свой
  webhook-рендер (фаза JIRA).
- Нюанс: для `.md` текст извлекается одной строкой (длинные `(changed)/(into)`); для реальных HTML-страниц
  diff многострочный и читабельный.
- Тестировать без спама в Gmail: поднят **mailpit** (`http://localhost:8025`), SMTP `mailpit:1025`;
  временно укажите канал `mailto://x@example.com?smtp=mailpit&port=1025&to=catch@example.com`.

### 2. AI-резюме (глобально)
`Settings → LLM`:
- Провайдер **Anthropic**, ключ `ANTHROPIC_API_KEY`, модель Claude.
- Включить мастер-переключатель LLM и **AI change summary**.
- Промпт под документацию, например:
  > Кратко опиши на русском, ЧТО и КАК изменилось в этом фрагменте документации. Только суть, без воды.
- AI-резюме доступно в шаблоне токеном **`{{llm_summary}}`** (подтверждено). `{{raw_diff}}` — буквальный diff.

### 3. Источники
**HTML** — `Add` (вставить URL) либо `Import` (список URL построчно или `.xlsx`). Для каждого:
- **Tag** (напр. `payments`, `auth-api`) — пригодится для маршрутизации assignee в JIRA-фазе.
- **Recheck time / Schedule** — интервал или по часам работы/таймзоне.
- **Фильтры от шума**: `Visual Selector` или CSS/XPath, плюс *Ignore text* для nav/footer/таймстемпов.

**Локальные/Markdown** — положить файл в `./watched/`, затем `Add` с URL:
```
file:///datastore/watched/имя_файла.md
```
(каталог `./watched` смонтирован в контейнер как `/datastore/watched`).

**PDF по URL** — обычный `Add` на URL `.pdf`. CDIO извлекает текст нативно (`pdftohtml`).
Удобно ignore-фильтром убрать строки `Document checksum` / `Original file size` от шума.

**Word (.doc/.docx) и локальные PDF** — через `office-adapter`. Подробно: [`docs/office-files.md`](docs/office-files.md).
Кратко: положите файл в `office-src/`, добавьте 3 строки в `config/office-sources.yaml` — `watched/<id>.txt`
появится автоматически, дальше заводите обычный `file://`-watch в CDIO.

**Источники за логином** (Keycloak/OAuth, обычные формы) — через `config/auth-sources.yaml` +
provisioning-скрипт. Секреты в `.env`. Подробно: [`docs/auth-sources.md`](docs/auth-sources.md).

**Email-уведомления** (свой ящик-бот, разные получатели, нюансы Gmail, транзакционные провайдеры) —
[`docs/notifications-email.md`](docs/notifications-email.md).

**Развёртывание на другой машине** — [`docs/deploy.md`](docs/deploy.md).

---

## Проверка MVP (end-to-end)
1. Завести один HTML-watch и один `file://`-watch на тест-файл из `./watched/`.
2. Изменить файл (или дождаться изменения страницы) → в watch нажать **Recheck**.
3. В CDIO появляется непустой diff; на email приходит письмо с **diff** и **AI-резюме**.
4. Проверить подавление шума: правка footer/nav не должна триггерить уведомление.

## Заметка о безопасности
`ALLOW_FILE_URI=true` включает доступ к `file://` (нужно для локальных файлов). Есть CVE-2024-51998
(path traversal). Меры: держать контейнер изолированным, заводить `file://`-watch только на файлы из
`./watched/`, своевременно обновлять образ CDIO.

## Дальше по дорожной карте
- **Фаза 2**: PDF (нативно) + `src/docmonitor/office_adapter.py` (docx/xlsx → `watched/*.txt`).
- **Фаза 3**: источники за авторизацией — `Browser Steps` (логин), секреты через env.
- **Фаза 4**: `src/docmonitor/jira_bridge.py` — CDIO шлёт templated JSON по webhook → создание задачи
  в JIRA по шаблону + assignee из `config/assignee_map.yaml`.
