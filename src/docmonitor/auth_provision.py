#!/usr/bin/env python3
"""Provisioning auth-источников в CDIO.

Читает config/auth-sources.yaml, подставляет ${ENV_VAR} из окружения (env_file: .env
в compose уже залит в контейнер), POSTит или PUTит watch'и в CDIO REST API.

Состояние «id → uuid» хранится в state/auth_provision_map.json, чтобы повторные прогоны
обновляли существующие watch'и, а не создавали дубликаты.

Запуск:
  docker compose exec -T office-adapter python /src/docmonitor/auth_provision.py
"""
import json
import os
import string
import sys
import urllib.error
import urllib.request

import yaml

CONFIG = os.environ.get("AUTH_CONFIG", "/config/auth-sources.yaml")
STATE_DIR = os.environ.get("STATE_DIR", "/state")
STATE_FILE = os.path.join(STATE_DIR, "auth_provision_map.json")
CDIO_BASE = os.environ.get("CDIO_BASE", "http://changedetection:5000")
API_KEY = os.environ.get("CDIO_API_KEY", "")


def _sub(value):
    """Рекурсивная подстановка ${VAR} из os.environ внутри строк/списков/словарей."""
    if isinstance(value, str):
        return string.Template(value).safe_substitute(os.environ)
    if isinstance(value, list):
        return [_sub(v) for v in value]
    if isinstance(value, dict):
        return {k: _sub(v) for k, v in value.items()}
    return value


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE) as f:
        return json.load(f)


def _save_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _req(method: str, path: str, payload: dict | None = None) -> tuple[int, dict | str]:
    url = f"{CDIO_BASE}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body) if body else {}
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def _normalize_steps(steps: list) -> list:
    """CDIO API ждёт в каждом шаге одновременно selector и optional_value
    (даже когда операции не нужно одно из них) — дозаполняем пустыми."""
    return [
        {
            "operation": st.get("operation", ""),
            "selector": st.get("selector", "") or "",
            "optional_value": st.get("optional_value", "") or "",
        }
        for st in steps or []
    ]


def _build_payload(s: dict) -> dict:
    """Из записи sources.yaml собрать watch-payload для CDIO API."""
    s = _sub(s)
    payload = {
        "url": s["url"],
        "title": s.get("title") or s["id"],
        "tag": s.get("tag", ""),
        "fetch_backend": "html_webdriver",   # Playwright sidecar — ровно где работают Browser Steps
        "browser_steps": _normalize_steps(s.get("browser_steps", [])),
    }
    if "time_between_check" in s:
        payload["time_between_check"] = s["time_between_check"]
    return payload


def provision_one(s: dict, state: dict) -> None:
    sid = s["id"]
    payload = _build_payload(s)
    uuid = state.get(sid)
    if uuid:
        status, body = _req("PUT", f"/api/v1/watch/{uuid}", payload)
        if status == 200:
            print(f"[auth] {sid}: updated (uuid={uuid})", flush=True)
        else:
            print(f"[auth] {sid}: PUT failed {status}: {body!r}", file=sys.stderr, flush=True)
            return
    else:
        status, body = _req("POST", "/api/v1/watch", payload)
        if status in (200, 201) and isinstance(body, dict) and body.get("uuid"):
            uuid = body["uuid"]
            state[sid] = uuid
            print(f"[auth] {sid}: created (uuid={uuid})", flush=True)
        else:
            print(f"[auth] {sid}: POST failed {status}: {body!r}", file=sys.stderr, flush=True)


def _resolve_template(s: dict, templates: dict) -> dict:
    """Если у source есть 'auth: <name>' и нет собственных browser_steps —
    подтягиваем browser_steps из шаблона. Если есть свои — оставляем как есть."""
    auth_name = s.get("auth")
    if not auth_name:
        return s
    tpl = templates.get(auth_name)
    if not tpl:
        raise ValueError(f"auth template '{auth_name}' не найден (source id={s.get('id')!r})")
    if "browser_steps" in s:
        return s
    merged = dict(s)
    merged["browser_steps"] = tpl.get("browser_steps", [])
    return merged


def main() -> None:
    if not API_KEY:
        sys.exit("CDIO_API_KEY не задан (положите в .env)")
    if not os.path.exists(CONFIG):
        sys.exit(f"конфиг {CONFIG} не найден")
    with open(CONFIG) as f:
        cfg = yaml.safe_load(f) or {}
    templates = cfg.get("auth_templates", {}) or {}
    state = _load_state()
    for s in cfg.get("sources", []) or []:
        if not s.get("id"):
            print(f"[auth] пропуск некорректной записи: {s!r}", file=sys.stderr)
            continue
        s = _resolve_template(s, templates)
        provision_one(s, state)
    _save_state(state)
    print(f"[auth] state -> {STATE_FILE}", flush=True)


if __name__ == "__main__":
    main()
