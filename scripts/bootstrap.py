#!/usr/bin/env python3
"""DocMonitor bootstrap.

Однокомандный подъём стека на новой машине. Идемпотентный — повторный запуск
не перетирает то, что уже сконфигурировано пользователем.

Что делает:
  1. Проверяет docker / compose.
  2. Поднимает стек (docker compose up -d --build).
  3. Ждёт пока CDIO / mailpit / testsite ответят HTTP 200.
  4. Извлекает CDIO API key из datastore и дописывает в .env.
  5. Применяет рекомендуемые настройки CDIO (LLM model/multiplier/prompt,
     Notifications format=text + шаблон), не перетирая непустые значения.
  6. Если есть .env с AUTH_* и config/auth-sources.yaml — запускает auth_provision.
  7. Печатает чек-лист «что осталось задать руками».

Запуск:
  python scripts/bootstrap.py

Зависимости: stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
EMAIL_TEMPLATE = ROOT / "config" / "notification-email.j2"
AUTH_SOURCES_YAML = ROOT / "config" / "auth-sources.yaml"

# Рекомендуемые дефолты.
# Применяются, ТОЛЬКО если у пользователя соответствующее поле пустое — иначе сохраняем его выбор.
DEFAULTS = {
    "llm.enabled": True,
    "llm.override_diff_with_summary": True,
    "llm.model": "openai/deepseek-chat",
    "llm.api_base": "https://api.deepseek.com/v1",
    "llm.provider_kind": "openai_compatible",
    "llm.local_token_multiplier": 15,       # критично: deepseek без этого упирается в length
    "llm.max_summary_tokens": 3000,
    "llm.change_summary_default": (
        "Кратко по-русски: ЧТО и КАК изменилось в этом фрагменте документации. "
        "Только суть, без воды, без англоязычных заголовков."
    ),
    "notification_format": "text",
    "notification_title": "[DocMonitor] Изменилось: {{watch_title}}",
    "notification_urls": [
        "mailto://docmonitor@example.com?smtp=mailpit&port=1025&to=catch@example.com"
    ],
}


def step(msg: str) -> None:
    print(f"\n\033[1;36m▶ {msg}\033[0m", flush=True)


def ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"  \033[33m⚠\033[0m {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}", flush=True)
    sys.exit(1)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, **kw)


def run_capture(cmd: list[str]) -> str:
    p = run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        fail(f"{' '.join(cmd)} failed: {p.stderr.strip()}")
    return p.stdout


# --- 1. prereq ---------------------------------------------------------------
def check_prereqs() -> None:
    step("Проверяю docker / compose")
    if not shutil.which("docker"):
        fail("docker не найден в PATH. Установите Docker Desktop / Colima.")
    info = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if info.returncode != 0:
        fail("docker daemon не отвечает. Запустите Docker Desktop / Colima.")
    ok("docker готов")
    compose = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
    if compose.returncode != 0:
        fail("`docker compose` не доступен. Нужен Compose v2.")
    ok(f"compose: {compose.stdout.strip().splitlines()[0]}")


# --- 2. up -------------------------------------------------------------------
def compose_up() -> None:
    step("Поднимаю стек (docker compose up -d --build)")
    p = run(["docker", "compose", "up", "-d", "--build"])
    if p.returncode != 0:
        fail("docker compose up завершился с ошибкой")
    ok("compose up")


# --- 3. health-check ---------------------------------------------------------
def wait_http(url: str, name: str, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    ok(f"{name} → {url} (HTTP 200)")
                    return
        except Exception:
            pass
        time.sleep(2)
    fail(f"{name} ({url}) не ответил HTTP 200 за {timeout}с")


def health() -> None:
    step("Жду готовности сервисов")
    wait_http("http://localhost:5050/", "CDIO UI")
    wait_http("http://localhost:8025/", "mailpit UI")
    wait_http("http://localhost:8081/", "testsite")


# --- 4. CDIO API key ---------------------------------------------------------
def extract_api_key() -> str:
    p = run(
        ["docker", "compose", "exec", "-T", "changedetection", "python3", "-c",
         "import json; print(json.load(open('/datastore/changedetection.json'))"
         "['settings']['application']['api_access_token'])"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        fail(f"не удалось извлечь CDIO API key: {p.stderr.strip()}")
    key = p.stdout.strip().splitlines()[-1]
    if not re.fullmatch(r"[a-f0-9]{32}", key):
        fail(f"извлечённый CDIO API key не похож на ключ: {key!r}")
    return key


def upsert_env_var(name: str, value: str) -> bool:
    """Дописать/обновить KEY=VALUE в .env. Возвращает True, если значение изменилось."""
    if not ENV_PATH.exists():
        if ENV_EXAMPLE.exists():
            shutil.copyfile(ENV_EXAMPLE, ENV_PATH)
            ok(f".env создан из .env.example")
        else:
            ENV_PATH.touch()
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    pat = re.compile(rf"^\s*{re.escape(name)}\s*=")
    for i, ln in enumerate(lines):
        if pat.match(ln):
            existing = ln.split("=", 1)[1] if "=" in ln else ""
            if existing.strip() == value:
                return False
            lines[i] = f"{name}={value}"
            ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
    lines.append(f"{name}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def setup_api_key() -> str:
    step("CDIO API key → .env")
    key = extract_api_key()
    changed = upsert_env_var("CDIO_API_KEY", key)
    if changed:
        ok(f"CDIO_API_KEY записан в .env ({key[:6]}…)")
        # office-adapter перечитает env_file при recreate
        p = run(["docker", "compose", "up", "-d", "--force-recreate", "office-adapter"],
                capture_output=True, text=True)
        if p.returncode != 0:
            warn(f"office-adapter recreate: {p.stderr.strip()}")
        else:
            ok("office-adapter перезапущен с новым env")
    else:
        ok(f"CDIO_API_KEY уже актуален в .env ({key[:6]}…)")
    return key


# --- 5. apply CDIO defaults --------------------------------------------------
def deep_get(d: dict, path: str):
    cur = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def deep_set(d: dict, path: str, value) -> None:
    cur = d
    parts = path.split(".")
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def is_empty(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def apply_defaults() -> list[str]:
    step("Применяю рекомендуемые настройки CDIO (без перетирания непустых)")
    DATASTORE_PATH = "/datastore/changedetection.json"
    raw = run_capture(
        ["docker", "compose", "exec", "-T", "changedetection", "cat", DATASTORE_PATH]
    )
    d = json.loads(raw)
    app = d.setdefault("settings", {}).setdefault("application", {})
    app.setdefault("llm", {})

    body_default = EMAIL_TEMPLATE.read_text(encoding="utf-8") if EMAIL_TEMPLATE.exists() else ""
    changes: list[str] = []

    def apply(path: str, value, force: bool = False) -> None:
        # ключи llm.* живут под application.llm.*
        if path.startswith("llm."):
            full = path
        elif path == "llm":
            full = path
        else:
            full = path
        cur = deep_get(app, full)
        if force or is_empty(cur) or (isinstance(value, bool) and cur is not value):
            if cur == value:
                return
            deep_set(app, full, value)
            display = value if not isinstance(value, str) else (value[:60] + "…" if len(value) > 60 else value)
            changes.append(f"{full} = {display!r}")

    # notification_body — отдельно: из шаблона, если пусто
    if is_empty(app.get("notification_body")) and body_default:
        app["notification_body"] = body_default
        changes.append("notification_body = (из config/notification-email.j2)")

    for path, default in DEFAULTS.items():
        # local_token_multiplier и max_summary_tokens форсим — это известные «правильные»
        force = path in (
            "llm.local_token_multiplier",
            "llm.max_summary_tokens",
            "llm.enabled",
            "llm.override_diff_with_summary",
            "llm.provider_kind",
        )
        apply(path, default, force=force)

    if not changes:
        ok("Все рекомендуемые настройки уже применены — ничего не меняю")
        return []

    # Запишем обратно через python внутри контейнера
    payload = json.dumps(d, ensure_ascii=False)
    # передаём через stdin, чтобы не упереться в argv-лимит
    proc = subprocess.Popen(
        ["docker", "compose", "exec", "-T", "changedetection", "python3", "-c",
         "import sys, json; "
         f"json.dump(json.load(sys.stdin), open('{DATASTORE_PATH}','w'), indent=2, ensure_ascii=False)"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=ROOT,
    )
    _, err = proc.communicate(payload.encode("utf-8"), timeout=30)
    if proc.returncode != 0:
        fail(f"не удалось записать настройки в datastore: {err.decode(errors='replace')}")
    for c in changes:
        ok(c)
    # перезагрузить CDIO чтобы он подхватил настройки уведомлений/LLM
    run(["docker", "compose", "restart", "changedetection"], capture_output=True, text=True)
    wait_http("http://localhost:5050/", "CDIO UI после restart")
    return changes


# --- 6. auth provisioning ----------------------------------------------------
def auth_env_present() -> bool:
    if not ENV_PATH.exists():
        return False
    txt = ENV_PATH.read_text(encoding="utf-8")
    for ln in txt.splitlines():
        m = re.match(r"^\s*(AUTH_[A-Z0-9_]+_(USER|PASS))\s*=\s*(.+)$", ln)
        if m and m.group(3).strip():
            return True
    return False


def auth_provision() -> None:
    if not AUTH_SOURCES_YAML.exists():
        return
    step("auth-sources провижининг")
    if not auth_env_present():
        warn("в .env нет заполненных AUTH_*_USER/PASS — пропускаю (заполните и перезапустите bootstrap)")
        return
    p = run(["docker", "compose", "exec", "-T", "office-adapter",
             "python", "/src/docmonitor/auth_provision.py"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    for ln in (p.stdout + p.stderr).splitlines():
        ln = ln.strip()
        if ln:
            ok(ln)
    if p.returncode != 0:
        warn("auth_provision вернул ненулевой код — гляньте логи выше")


# --- 7. checklist ------------------------------------------------------------
def checklist() -> None:
    step("Что осталось задать руками")
    items: list[str] = []
    # LLM api key
    raw = run_capture(["docker", "compose", "exec", "-T", "changedetection",
                       "python3", "-c",
                       "import json; d=json.load(open('/datastore/changedetection.json'));"
                       "print(d['settings']['application']['llm'].get('api_key',''))"])
    llm_key = raw.strip().splitlines()[-1] if raw.strip() else ""
    if not llm_key:
        items.append("LLM API key — Settings → LLM в UI, либо обновите ключ напрямую "
                     "в datastore (раздел settings.application.llm.api_key)")
    # AUTH_* — если ничего не заполнено и в yaml есть sources
    if AUTH_SOURCES_YAML.exists() and not auth_env_present():
        items.append("AUTH_*_USER/PASS в .env для auth-источников (см. docs/auth-sources.md)")
    # SMTP реальный — необязательно, есть mailpit
    items.append("Email-канал на реальный SMTP — если нужно слать не в mailpit, "
                 "поменяйте Notification URL (см. docs/notifications-email.md)")
    # Watch'и
    items.append("Заведите watch'и: HTML/PDF через UI :5050; Office — в config/office-sources.yaml "
                 "+ файлы в office-src/")

    for i, it in enumerate(items, 1):
        print(f"  {i}. {it}")

    step("Готово")
    print("  CDIO UI:  http://localhost:5050")
    print("  Mailpit:  http://localhost:8025")
    print("  Testsite: http://localhost:8081")


# --- 8. open browser ---------------------------------------------------------
def open_browser() -> None:
    step("Открываю UI в браузере")
    for url in ("http://localhost:5050", "http://localhost:8025"):
        try:
            webbrowser.open_new_tab(url)
            ok(url)
        except Exception as e:
            warn(f"не удалось открыть {url}: {e}")


# --- main --------------------------------------------------------------------
def main() -> None:
    print("\033[1mDocMonitor bootstrap\033[0m")
    check_prereqs()
    compose_up()
    health()
    setup_api_key()
    apply_defaults()
    auth_provision()
    checklist()
    open_browser()


if __name__ == "__main__":
    main()
