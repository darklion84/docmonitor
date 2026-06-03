# Развёртывание на другой машине

Шпаргалка по подъёму всего стека DocMonitor с нуля. Watch'и переносить не будем —
заведём свежие.

## TL;DR — короткий путь (рекомендуется)

```bash
git clone <repo-url> docmonitor
cd docmonitor
python3 scripts/bootstrap.py        # поднимет стек, дотащит CDIO key в .env,
                                    # применит рекомендуемые настройки CDIO,
                                    # запустит auth_provision (если в .env есть AUTH_*)
                                    # и напечатает чек-лист «что осталось задать руками».
```

Скрипт идемпотентный — можно перезапускать сколько угодно, **не перетирает** уже
сконфигурированные значения. После того как добавите LLM-ключ или AUTH_* в `.env`,
просто запустите `bootstrap.py` ещё раз — он добьёт недостающее.

Дальше в этом файле — расшифровка по шагам (что именно делает bootstrap и что
сделать вручную, если хочется без скрипта).

## 1. Что нужно на новой машине

- **Docker** + **Docker Compose v2** (Colima, Docker Desktop, нативный docker на Linux — любой)
- **git**

Порты, которые проброс наружу:
- `5050` — UI changedetection.io
- `8025` — UI mailpit (локальный тестовый SMTP)
- `8081` — testsite (локальный nginx для тестов HTML/PDF)

На macOS порт `5000` занят AirPlay Receiver, поэтому UI вынесен на `5050`.
Если другие порты конфликтуют — поменяйте левую часть `host:container` в `docker-compose.yml`.

## 2. Клон и стартовая настройка

```bash
git clone <ваш-remote> docmonitor
cd docmonitor
cp .env.example .env
docker compose up -d
```

Проверка:

```bash
docker compose ps                                              # 5 контейнеров Up
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5050/   # 200
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8025/   # 200 mailpit
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8081/   # 200 testsite
```

## 3. Получить `CDIO_API_KEY`

Ключ генерится самим CDIO при первом старте.

1. Открыть `http://localhost:5050` → **Settings → API**.
2. Скопировать `x-api-key`.
3. Положить в `.env`:
   ```bash
   CDIO_API_KEY=<скопированный-ключ>
   ```
4. Перечитать env у office-adapter:
   ```bash
   docker compose up -d --force-recreate office-adapter
   ```

## 4. Заполнить остальные секреты в `.env`

Шаблон — `.env.example`. Заполнить под себя:

```bash
# AI-резюме (LLM-провайдер)
ANTHROPIC_API_KEY=                # если решите перейти на Claude
                                  # (дефолт — DeepSeek, ключ вставляется в UI)

# Источники за логином — конвенция AUTH_<UPPER_ID>_USER / AUTH_<UPPER_ID>_PASS
# (для каждой записи в config/auth-sources.yaml)
AUTH_AMUSNET_USER=
AUTH_AMUSNET_PASS=
```

`.env` в git **не попадает** (см. `.gitignore`).

## 5. Настройки в UI (один раз)

### Settings → LLM

- **Provider**: OpenAI-compatible
- **Model**: `openai/deepseek-chat` (быстрая, дешёвая, без reasoning — оптимально для резюме)
  - либо `anthropic/claude-haiku-4-5` если хотите Claude (тогда ключ в `ANTHROPIC_API_KEY`)
- **API base**: `https://api.deepseek.com/v1` (для DeepSeek) или пусто для Claude
- **API key**: ваш ключ провайдера
- **Local token multiplier**: **15** (важно! при дефолте 5 в коротких diff'ах ответ обрезается на `finish_reason=length`)
- **Max summary tokens**: `3000` (хватает)
- **Включить мастер-переключатель LLM** + **AI change summary**
- **Промпт** (на русском, под документацию):
  ```
  Кратко по-русски: ЧТО и КАК изменилось в этом фрагменте документации.
  Только суть, без воды, без англоязычных заголовков.
  ```

### Settings → Notifications

- **Format**: **`Text`** (не HTML — иначе Gmail ломает переносы)
- **Notification URL**: ваш SMTP-канал Apprise; примеры — в [`notifications-email.md`](notifications-email.md).
  Для теста — на локальный mailpit:
  ```
  mailto://x@example.com?smtp=mailpit&port=1025&to=catch@example.com
  ```
- **Title**: `[DocMonitor] Изменилось: {{watch_title}}`
- **Body**: вставить содержимое [`config/notification-email.j2`](../config/notification-email.j2)

## 6. Заведение watch'ей

Watch'и переносим не через export — настраиваем заново. Три категории.

### HTML / PDF по URL — через UI CDIO
**Add** → вставить URL → задать **tag** и **time_between_check**.
Для PDF дополнительно — *Ignore text* фильтры на строки `Document checksum`,
`Original file size`, `Added by changedetection` (CDIO добавляет служебные строки в diff).

### Word (.doc/.docx) и локальные PDF — через office-adapter
1. Положить файлы в `office-src/` (можно в подпапки — структура зеркалится в `watched/`).
2. Добавить записи в [`config/office-sources.yaml`](../config/office-sources.yaml):
   ```yaml
   sources:
     - id: pricing-policy
       type: docx          # docx | doc | pdf
       src: pricing.docx
   ```
3. Адаптер реактивный (PollingObserver 1с) — сразу создаст `watched/<id>.txt`.
   Лог: `docker compose logs --tail 10 office-adapter`.
4. В UI CDIO **Add** → `file:///datastore/watched/<id>.txt` → тег, расписание.

Подробно: [`office-files.md`](office-files.md).

### Источники за логином — через provisioner
1. Креды в `.env`: `AUTH_<UPPER_ID>_USER` / `AUTH_<UPPER_ID>_PASS`.
2. Записи в [`config/auth-sources.yaml`](../config/auth-sources.yaml) — используйте
   `auth_templates` чтобы не дублировать browser_steps между страницами одного логина.
3. Прогнать provisioner:
   ```bash
   docker compose exec -T office-adapter python /src/docmonitor/auth_provision.py
   ```
   Идемпотентный: повторный прогон обновит существующие watch'и, не создаст дубликаты
   (маппинг id→uuid лежит в `state/auth_provision_map.json`, gitignored).

Подробно: [`auth-sources.md`](auth-sources.md).

## 7. Проверочный пинг

После настройки одного watch'а:

1. Изменить контент источника (для testsite — поправить `site/index.html` любым редактором).
2. В UI нажать **Recheck** или дождаться `time_between_check`.
3. Письмо приходит на ваш `to=` (или в mailpit на `:8025`).

## Когда что-то идёт не так

- **5 контейнеров стартанули, но CDIO не отвечает 200** → `docker compose logs changedetection` —
  обычно либо порт занят, либо bind на `./watched`/`./config` упёрся в права.
- **Watch шлёт пустой `{{llm_summary}}`** → откройте `docker compose logs changedetection | grep llm.client` —
  если видите `finish_reason='length' text_len=0`, поднимите Local token multiplier до 15 (см. шаг 5).
- **PDF/Office не обновляются** → `docker compose logs office-adapter` — должны видеть строки `[office:react]`.
  Если только `[office]` без `:react` — проверьте, что путь в `src:` совпадает с реальным файлом и нет опечатки в подпапке.
- **Auth-watch уходит в `last_error: BrowserType.connect_over_cdp Timeout`** при массовом recheck —
  это burst sockpuppetbrowser'а. Перезапустите `docker compose restart browser-sockpuppet-chrome` и
  проверяйте по одному, либо снизьте `MAX_CONCURRENT_CHROME_PROCESSES` (env у browser-сайдкара) до 4.
