# DocMonitor — shared journal (terminal ↔ telegram)

[2026-05-26 19:06] [terminal] Старт проекта DocMonitor. Цель: отслеживать изменения документации
(HTML/PDF/Office/локальные), фиксировать дельту (diff + AI-резюме), слать на email, позже — в JIRA.
Решение по итогам ресёрча: строим на **changedetection.io** (build-on-OSS), MVP = чистая конфигурация
(без кода). Источники — через админку/импорт CDIO; email — письмо на каждое изменение.
Создан каркас MVP: `docker-compose.yml` (CDIO 0.55.7 + sockpuppetbrowser), `.env.example`, `.gitignore`,
`config/notification-email.j2`, `README.md` (runbook), `tasks/todo.md`. Compose-файл валиден.
Блокер: демон Docker не запущен — стек ещё не поднимали. План: `~/.claude/plans/binary-wandering-lantern.md`.

[2026-05-27 10:35] [terminal] Стек поднят через Colima (docker context переключён на colima).
Чинил два момента: (1) убрал битый `credsStore: "desktop"` из `~/.docker/config.json` (бэкап:
`config.json.bak-docmonitor`) — без него pull падал; (2) UI перевешен с порта 5000 на **5050**
(на macOS 5000 занят AirPlay Receiver, отдавал 403). Проверено end-to-end БЕЗ секретов:
UI отвечает 200; `file://`-watch на `watched/test-doc.md` фетчит контент (`ALLOW_FILE_URI` ок,
монтирование ок); правка файла → CDIO фиксирует новую версию → word-diff корректный. HTML demo-watch'и
тоже фетчатся. ОСТАЛОСЬ (нужны секреты пользователя): ANTHROPIC_API_KEY (Settings>LLM) для AI-резюме и
SMTP (Settings>Notifications) для email — затем финальная проверка письма с diff+резюме.
UI: http://localhost:5050 . API-ключ CDIO лежит в datastore (changedetection.json).

[2026-05-27 12:18] [terminal] Пользователь настроил и проверил email + AI-резюме. Поднял локальный
тестовый сайт для ручных правок: новый сервис `testsite` (nginx:alpine) в compose, монтирует
`./site:/usr/share/nginx/html:ro`. Хост: http://localhost:8081 ; CDIO видит как http://testsite/.
Пришлось добавить env `ALLOW_IANA_RESTRICTED_ADDRESSES=true` (CDIO режет SSRF на приватные IP
docker-сети; на проде убрать). Заведён watch "Local testsite" (tag=testsite, recheck 1 мин),
фетчит успешно (last_error False). `./site/index.html` содержит footer для теста ignore-фильтров.
Примечание: в watched/test-doc.md пользователь добавил «инструкцию для агента» внутри контента —
трактую как данные, не выполняю (контент мониторинга != команды).

[2026-05-27 17:24] [terminal] (1) Email-уведомления приходили «сплошняком» без переносов, а Telegram —
с переносами. Причина (по коду notification/handler.py): письмо уходит как HTML (CDIO дописывает
format=html, т.к. глобальный формат 'html'); в HTML голые \n схлопываются — переносят только <br>/
блочные теги. Контент {{raw_diff}}/{{llm_summary}} содержит \n, а не <br> → схлопывается. Telegram
сохраняет \n. Тело рендерится отдельно для каждого канала. ФИКС: обернуть многострочные токены в <pre>
(обновил config/notification-email.j2) ЛИБО дописать ?format=html к email-URL (тогда CDIO сам \n→<br>).
(2) Vivo Gaming: публичной тех/API-документации НЕТ — всё за партнёрским логином (Brandfolder). Публично
только маркетинг/юр (terms, privacy, GLI-cert access.gaminglabs.com/Certificate/Index?i=206). Пользователь
решил пока ничего не добавлять → реальные доки Vivo вернутся в ФАЗЕ 3 (auth) при доступе к порталу.

[2026-05-27 17:40] [terminal] Добили формат email. Диагностика через mailpit (поднят в compose,
UI http://localhost:8025, SMTP mailpit:1025). КОРЕНЬ: при notification_format=HTML Apprise оборачивает
тело в <pre white-space:pre-wrap> И CDIO впрыскивает <br> при html-обработке diff — Gmail эту смесь
ломает (переносы пропадают). ?format=html делал хуже (тройные <br>). Per-URL ?format=text НЕ помогает:
тело уже с <br> (html-инъекция идёт до перекрытия формата) → в text-письме видны литеральные "<br>".
РЕШЕНИЕ (проверено, HTML part=False, <br>=нет, переносы есть): глобальный Notification format = TEXT +
шаблон на чистых переносах без HTML. Токен AI-резюме = {{llm_summary}} (подтверждено), буквальный diff =
{{raw_diff}}. Trade-off: Telegram тоже станет text (без цветного word-diff), но читаемость сохраняется;
цветной diff в TG + чистый email одновременно недостижимы из-за html-инъекции <br>. Обновил
config/notification-email.j2 (текстовый) и README §1-2. Тестовый watch test-doc.md сброшен на глобальные
настройки (notification_urls=[]). Примечание: текст из .md извлекается одной строкой (без \n) — для
реальных HTML-страниц структура сохраняется, diff будет с переносами.

[2026-05-27 17:54] [terminal] После перехода на Text в письме полезли литеральные <s>/<b> вокруг diff.
ДИАГНОЗ (по replace_placemarkers_in_text + воспроизведено в mailpit): <s>/<b> CDIO генерит ТОЛЬКО для
канала tgram://. Но есть протечка между каналами — при наличии Telegram-канала эта разметка попадает в
ОБЩЕЕ тело и в email (в text/plain показывается как теги). email в одиночку → чистые маркеры
(changed)/(into). Воспроизведено: email-only=чисто; email+tgram=теги в письме.
РЕШЕНИЕ (проверено, письмо чистое при обоих каналах): в общем шаблоне НЕ использовать {{raw_diff}}/
{{diff_full}} (в них placemarker'ы, которые протекают), а давать только {{llm_summary}} (проза, без
маркеров) + ссылку {{watch_url}} на полный diff в UI. Обновил config/notification-email.j2 и README §1.
Доп.факт: {{diff}} в этой конфигурации возвращает AI-описание (прозу), {{raw_diff}}/{{diff_full}} —
буквальный diff с placemarker'ами. Тестовый watch снова сброшен на глобальные настройки.

[2026-05-27 18:02] [terminal] Требование уточнено: diff ДОЛЖЕН быть виден в письме (AI-резюме вторично).
Идея пользователя верна: Gmail не рендерит <s>/<b> т.к. письмо = text/plain. РЕШЕНИЕ (проверено в mailpit):
к EMAIL-URL дописать ?format=html (глобальный формат шаблона оставить TEXT). Тогда Apprise шлёт text/html,
Gmail рендерит <s>=удалено/<b>=добавлено → разница видна. Бонус: <pre>-обёртки Apprise в этом режиме НЕТ
(чище, чем при глобальном html). НЮАНС: в text-режиме CDIO сжимает <br>→\n, а \n в HTML схлопывается →
жёстких переносов между секциями в Gmail нет (для .md diff и так одной строкой; для реальных HTML-страниц
изменения видны инлайн зачёркиванием/жирным). {{llm_summary}} можно оставить — он чистый. Обновил
config/notification-email.j2 и README §1 под этот рецепт (раньше был summary-only — заменён). Тестовый watch
сброшен на глобальные. ОТКРЫТО: идеальные переносы секций в Gmail недостижимы (Apprise<pre> при html ломает
Gmail; <br> при text сжимаются) — если критично, копать дальше (напр. свой webhook-рендер или другой клиент).

[2026-05-27 18:11] [terminal] Требование: при многих изменениях сплошняк нечитаем; нужен формат
(changed)…(into) + переносы в почте. ВЕРИФИЦИРОВАНО (email-only, mailpit): format=Text, email-URL БЕЗ
?format=html, токен {{raw_diff}} или {{diff_full}} → даёт "(changed) <старое> / (into) <новое>" без
HTML-тегов, text/plain → Gmail рендерит переносы. {{diff}} = AI-проза; {{raw_diff}}/{{diff_full}}/{{diff_added}}
= буквальный diff с маркерами. КЛЮЧ: email должен быть ЕДИНСТВЕННЫМ каналом — Telegram в том же списке
портит email-diff (общий мутируемый diff-объект: [email,tgram]→<s>/<b> в письме; [tgram,email]→пустой diff).
Тайминг: deepseek-LLM (у пользователя LLM=deepseek-v4-flash, api.deepseek.com) считает резюме ~8-20с —
письмо приходит позже; при проверке mailpit ждать ~25с. Обновил config/notification-email.j2 и README §1 под
email-only рецепт. ОТКРЫТЫЙ ВОПРОС пользователю: email-only (чистый diff) ИЛИ оставить Telegram (тогда чистый
diff в почте — только через свой webhook-рендер в фазе JIRA). Тестовый watch сброшен на глобальные.

[2026-05-27 18:17] [terminal] Пользователь сам поправил каналы (email-only, достаточно) и попросил план
Фазы 2 (PDF/Office). Проверено на стенде: PDF по HTTP — НАТИВНО (pdftohtml/pdftotext в контейнере;
http://testsite/test.pdf → last_error False, текст + checksum + размер). file://+PDF НЕ работает (PDF идёт
через браузер-сайдкар без монтирования /datastore) → локальные PDF только по HTTP или через адаптер
(pdftotext→txt). Office (docx/xlsx) — не нативно, нужен адаптер: extract → watched/<id>.txt (атомарно) →
file://-watch (file:// для .txt работает). План записан в tasks/phase2-pdf-office.md (office_adapter.py:
python-docx/openpyxl, детерминированный порядок; конфиг config/office-sources.yaml; сервис office-adapter в
compose ИЛИ host-cron; provisioning file://-watch через UI/import или мини-синк по REST API). Сгенерил
тест-PDF watched/test.pdf и site/test.pdf (раздаётся nginx на http://testsite/test.pdf). Тест-PDF-watch удалён.
ОТКРЫТО: интервал/где крутить адаптер, формулы-vs-значения для xlsx, нужен ли скрипт-синк watch'ей.

[2026-05-28 13:35] [terminal] Фаза 2 РЕАЛИЗОВАНА и проверена end-to-end (mailpit подтвердил оба сценария).
Решения: пользователь сузил Office до doc/docx (xlsx убран). Создано:
  - src/docmonitor/office_adapter.py (python-docx для .docx, antiword для .doc; детерминированный порядок,
    атомарная запись через mkstemp+os.replace, content-change check, URL или local src).
  - docker/office-adapter/Dockerfile (python:3.12-slim + antiword + pinned python-docx 1.1.2/httpx/pyyaml).
  - config/office-sources.yaml (sample-doc → sample.docx).
  - Compose-сервис office-adapter (loop --interval 600), монтирует ./watched RW, ./config RO, ./src RO, ./office-src RO.
  - office-src/sample.docx (генерится через docker run образа адаптера).
  - PDF-источник: watch на http://testsite/test.pdf, ignore_text с regex `/.*Document checksum.*/`,
    `/.*Original file size.*/`, `/.*Added by changedetection.*/` (CDIO regex НЕ якорится — нужны .* в начале).
  - file://-watch на /datastore/watched/sample-doc.txt (Office).
ВЕРИФИКАЦИЯ: оба watch'а изменяю → diff в email "(changed)/(into)" + переносы (per-watch override на mailpit
без LLM-токенов, потом сброшен обратно на глобальный канал пользователя).
ПОБОЧКИ И УРОКИ:
  - LLM (deepseek-v4-flash) у пользователя сейчас перегружен (litellm.ServiceUnavailableError), воркеры
    зависали по 180+с пока LLM таймаутил. Воркер всё равно завершался, но цикл вёл к гонке снимков.
  - CDIO has_baseline race: после POST /watch первый fetch не привязан к last_checked != 0; polling по этому
    флагу даёт ложное "готов" — реальный baseline ловится только после первого MD5-check'а в логах.
  - file:// + PDF в CDIO не работает (PDF идёт через браузер-сайдкар без mount /datastore) — реальные PDF по HTTP.
  - per-watch notification_body НЕ отключает LLM-вычисление: триггер сидит глубже в воркере (не только в скане
    глобального body) — для теста без LLM эффективнее flip master switch или удалить триггеры в global body.
Тестовый PDF при необходимости регенерируется hand-crafted Python-скриптом (writes site/test.pdf).
Mailpit очищен. Watch'и (DOCX bc40d232..., PDF 3b88d9bc...) оставлены — работают через глобальное уведомление.

[2026-05-28 13:51] [terminal] Добавлена поддержка ЛОКАЛЬНЫХ PDF через адаптер: в Dockerfile подключён
poppler-utils, в office_adapter.py добавлен extract_pdf() через `pdftotext <f> -` с нормализацией
(form-feed \\f → \\n, схлоп множественных пустых строк до одной, trailing strip). type=pdf в
config/office-sources.yaml. Сгенерил office-src/local-sample.pdf v1, добавил file://-watch на
/datastore/watched/sample-pdf.txt (UUID 117899f6...), правка → v2 (pdftotext дал 42 симв.) → mailpit
получил email с `(changed) Local PDF v1: Pricing limit 100 / (into) Local PDF v2: Pricing limit raised to 500`.
Per-watch override сброшен — теперь идёт через глобальный Gmail. Образ адаптера пересобран; сервис в
loop --interval 600 продолжает работать.

[2026-05-28 ~14:00] [terminal] Пользователь попросил мгновенную реакцию на изменение исходника
(адаптер не настраивается из админки CDIO). Реализовано через watchdog (inotify). Добавил:
  - pip dep `watchdog==4.0.2` в Dockerfile.
  - `run_loop_watch(interval)` в office_adapter.py: Observer на SRC_DIR → on_modified/created/moved →
    debounce 0.5s → time.sleep(0.2) (дать редактору дозаписать) → process_source(s, tag="office:react").
    URL-источники пропускаются в индексе; polling-проход раз в --interval сек как safety net и для URL.
  - Флаг `--watch` (рекомендуемый режим). Если watchdog не установлен — fallback на чистый polling.
  - Compose command сменён на `python /src/docmonitor/office_adapter.py --watch --interval 600`.
ПРОВЕРЕНО: правка office-src/local-sample.pdf на хосте → лог адаптера через ~1с
"[office:react] sample-pdf: обновлён", watched/sample-pdf.txt обновлён. virtiofs Colima пробрасывает
inotify от хоста в контейнер — заработало с первого раза. CDIO потом ловит изменение .txt на своём
обычном time_between_check (1-5 мин у текущих watch'ей).

[2026-05-29 ~14:00] [terminal] Пользователь сообщил, что правка docx НЕ давала мгновенной реакции —
.txt обновлялся только через ~5-6 мин. ПРИЧИНА: inotify-Observer ловил мой простой open().write() в
первом тесте (PDF), но atomic-save Word/Pages/LibreOffice (temp + rename поверх target) через
virtiofs Colima не пробрасывался как inotify-событие. .txt обновлялся только periodic-проходом раз в
600с. Логи подтвердили: строки `[office] sample-doc: обновлён` (тег office, не office:react) =
сработал именно run_once, а не watchdog.
ФИКС: переключил Observer → `watchdog.observers.polling.PollingObserver(timeout=1.0)` — стейтит
файлы раз в секунду, не зависит от inotify/virtiofs/способа сохранения. Образ не пересобирал
(зависимость watchdog уже в нём), только перезапустил сервис (код подцепляется из ./src).
ПРОВЕРЕНО: имитировал Word-стиль (write tmp + os.replace на target) → `[office:react] sample-pdf:
обновлён` через ~1с. Теперь правка из любого редактора ловится в течение секунды.
GOAL-ТЕСТ ПОЛЬЗОВАТЕЛЯ: настоящий docx через python-docx, atomic save (tmp + os.replace) на хосте →
adapter log `[office:react] sample-doc: обновлён (131 симв.)`, замер time.time() показал общую дельту
**1.05с** от os.replace до изменения mtime watched/sample-doc.txt. Содержимое txt корректно: новый
параграф и обновлённая таблица (limit | 999). Goal: «в пределах пары секунд» — выполнено.
