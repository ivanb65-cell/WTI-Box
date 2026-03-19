from __future__ import annotations

import json
import os
import time
from typing import Dict, Any

STATE_FILE = os.getenv("STATE_FILE", "state.json")


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {"subscriptions": {}, "sent": {}}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {"subscriptions": {}, "sent": {}}
    data.setdefault("subscriptions", {})
    data.setdefault("sent", {})
    return data


def save_state(state: Dict[str, Any]) -> None:
    directory = os.path.dirname(STATE_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def get_chat_config(state: Dict[str, Any], chat_id: int) -> Dict[str, Any]:
    sub = state["subscriptions"].get(str(chat_id), {})
    sub.setdefault("enabled", False)
    sub.setdefault("threshold", int(os.getenv("ALERT_THRESHOLD", "7")))
    return sub


def set_chat_config(state: Dict[str, Any], chat_id: int, cfg: Dict[str, Any]) -> None:
    state["subscriptions"][str(chat_id)] = cfg


def was_recently_sent(state: Dict[str, Any], chat_id: int, headline_id: str, dedupe_window_minutes: int) -> bool:
    now = int(time.time())
    chat_key = str(chat_id)
    sent_map = state["sent"].setdefault(chat_key, {})
    ts = sent_map.get(headline_id)
    if not ts:
        return False
    return now - int(ts) < dedupe_window_minutes * 60


def mark_sent(state: Dict[str, Any], chat_id: int, headline_id: str) -> None:
    chat_key = str(chat_id)
    sent_map = state["sent"].setdefault(chat_key, {})
    sent_map[headline_id] = int(time.time())


def cleanup_old_sent(state: Dict[str, Any], dedupe_window_minutes: int) -> None:
    cutoff = int(time.time()) - dedupe_window_minutes * 60 * 3
    for chat_id, sent_map in state.get("sent", {}).items():
        old = [k for k, ts in sent_map.items() if int(ts) < cutoff]
        for key in old:
            sent_map.pop(key, None)
