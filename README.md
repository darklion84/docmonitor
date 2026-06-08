# DocMonitor

Отслеживание изменений документации на базе **changedetection.io (CDIO)**.
Источники (сайты, PDF, локальные/Markdown-файлы) проверяются по расписанию; при изменении
формируется дельта (**diff + AI-резюме**) и уходит на **email**. В перспективе — задача в JIRA.

Принцип: **конфигурируем CDIO, а не пишем код**. Кастомный код появляется только в поздних фазах
(Office-адаптер, JIRA-мост).

## Что сейчас работает
- **HTML / Markdown / plain-text** — нативно CDIO, в т.ч. локальные файлы через `file://`.
- **PDF** по URL (нативно) и **локальные PDF** через адаптер (`pdftotext`).
- **Word**: `.docx` (`python-docx`) и legacy `.doc` (`antiword`).
- **Источники за логином**: Keycloak/OAuth и обычные формы — через CDIO Browser Steps,
  секреты в `.env`, провижининг из YAML через `auth_provision.py`.
- **Детект изменений + текстовый diff + AI-резюме** (DeepSeek или Anthropic Claude).
- **Уведомление по email** на каждое изменение, формат `(changed)/(into)` с переносами.
- **Реактивный адаптер**: правка `.docx/.pdf` → `watched/<id>.txt` обновляется за ~1с.
- **Структура подпапок зеркалится**: `office-src/teams/x.docx` → `watched/teams/x.txt`.

---

## Предварительно
- Docker + Docker Compose v2 (Colima / Docker Desktop / нативный).
- Ключ LLM-провайдера (DeepSeek или Anthropic) — для AI-резюме.
- Доступ к **SMTP** для боевой почты — необязательно, для тестов в стеке есть **mailpit**.

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

## Дефолтные watch-и (демо)

`bootstrap.py` автоматически регистрирует три демо-источника:

| Источник | URL в CDIO | Файл на хосте |
|----------|-----------|---------------|
| Word-документ | `file:///datastore/watched/my-doc.txt` | `office-src/my-doc.docx` → конвертируется через office-adapter |
| Markdown | `file:///datastore/watched/sample.md` | `watched/sample.md` (создаётся при первом запуске) |
| Тестовый сайт | `http://testsite/` | `site/index.html` |

Все три получают тег `demo`. Проверить что детект и уведомления работают — end-to-end смок-тест:
```bash
PYTHONUTF8=1 python scripts/test_watches.py
```
Скрипт: проверяет наличие watch-ей, вносит изменения в каждый источник, принудительно запускает recheck и убеждается что в Mailpit пришли письма с корректным Subject, diff и AI-резюме.

> Для теста `my-doc.docx` нужен `python-docx` на хосте: `pip install python-docx`

Отключить тестовые сервисы (mailpit + testsite) после проверки:
```bash
docker compose stop mailpit testsite
```

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

## Проверка end-to-end
1. Завести любой watch (HTML через UI, или file://-watch из `watched/`, или Word/PDF через `office-src/`).
2. Изменить источник (или нажать **Recheck** в UI).
3. CDIO фиксирует diff; на email приходит письмо с **diff** и **AI-резюме**
   (для тестов смотрите письма в mailpit на `http://localhost:8025`).
4. Опционально: проверить подавление шума ignore-фильтрами на nav/footer/таймстемпы.

## Заметка о безопасности
`ALLOW_FILE_URI=true` включает доступ к `file://` (нужно для локальных файлов). Есть CVE-2024-51998
(path traversal). Меры: держать контейнер изолированным, заводить `file://`-watch только на файлы из
`./watched/`, своевременно обновлять образ CDIO.

`ALLOW_IANA_RESTRICTED_ADDRESSES=true` (включён для локальной разработки, чтобы CDIO мог ходить в
`http://testsite/` внутри compose-сети) ослабляет SSRF-защиту. **На проде уберите.**

## Дорожная карта

**Сделано:**
- **Фаза 1** — MVP: HTML / Markdown / локальные текстовые, AI-резюме, email-доставка.
- **Фаза 2** — PDF (URL и локальные через адаптер) + Office (`.doc`/`.docx`).
  Реактивный адаптер с PollingObserver, атомарная запись, зеркалирование подпапок.
  Подробно: [`docs/office-files.md`](docs/office-files.md).
- **Фаза 3** — источники за логином: CDIO Browser Steps + Playwright sidecar, секреты в `.env`,
  shared `auth_templates` в YAML, идемпотентный `auth_provision.py`. Проверено на Keycloak/OAuth.
  Подробно: [`docs/auth-sources.md`](docs/auth-sources.md).

**Дальше:**
- **Фаза 4** — JIRA-мост: `notification-jira.json.j2` (CDIO шлёт по `post://` webhook
  templated JSON) → `jira_bridge.py` принимает, создаёт задачу по шаблону,
  assignee из `config/assignee_map.yaml` по `watch_tag`. Идемпотентность по
  `watch_uuid+timestamp`, email-канал параллельно.
