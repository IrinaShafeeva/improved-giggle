"""Living profile extraction and formatting."""

from __future__ import annotations

import json
from typing import Any

from bot.prompts.profile import build_profile_prompt
from bot.services.llm_client import llm_client

PROFILE_PERIOD = "profile"

PROFILE_FIELDS = (
    "roles",
    "active_projects",
    "priorities",
    "constraints",
    "recurring_tails",
    "support_style",
    "avoid",
)


def parse_profile(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"summary": raw}
    return data if isinstance(data, dict) else {}


def serialize_profile(profile: dict[str, Any]) -> str:
    return json.dumps(profile, ensure_ascii=False, indent=2)


def _as_clean_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items = []
    seen = set()
    for raw in value:
        item = str(raw).strip()
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            items.append(item)
    return items[:limit]


def normalize_profile(data: dict[str, Any]) -> dict[str, Any]:
    limits = {
        "roles": 6,
        "active_projects": 8,
        "priorities": 6,
        "constraints": 8,
        "recurring_tails": 6,
        "support_style": 6,
        "avoid": 6,
    }
    profile = {field: _as_clean_list(data.get(field), limit) for field, limit in limits.items()}
    profile["morning_hint"] = str(data.get("morning_hint", "")).strip()
    profile["summary"] = str(data.get("summary", "")).strip()
    confidence = data.get("confidence", 0.0)
    profile["confidence"] = confidence if isinstance(confidence, (int, float)) else 0.0
    return profile


async def extract_profile(text: str, existing_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    data = await llm_client.chat_json(
        system_prompt=build_profile_prompt(existing_profile),
        user_message=text,
        temperature=0.3,
        max_tokens=1400,
    )
    return normalize_profile(data)


def format_profile(profile: dict[str, Any]) -> str:
    if not profile:
        return "Профиль пока пустой."

    labels = {
        "roles": "Роли",
        "active_projects": "Активные линии",
        "priorities": "Что важно не потерять",
        "constraints": "Ограничения",
        "recurring_tails": "Повторяющиеся хвосты",
        "support_style": "Как помогать",
        "avoid": "Чего избегать",
    }
    parts: list[str] = []
    summary = str(profile.get("summary", "")).strip()
    if summary:
        parts.append(f"Коротко:\n{summary}")

    for field in PROFILE_FIELDS:
        items = profile.get(field) or []
        if items:
            body = "\n".join(f"• {item}" for item in items)
            parts.append(f"{labels[field]}:\n{body}")

    morning_hint = str(profile.get("morning_hint", "")).strip()
    if morning_hint:
        parts.append(f"Утренний фокус:\n{morning_hint}")

    return "\n\n".join(parts) if parts else "Профиль пока пустой."


def format_profile_context(profile: dict[str, Any]) -> str:
    if not profile:
        return ""
    lines = []
    summary = str(profile.get("summary", "")).strip()
    if summary:
        lines.append(f"Коротко: {summary}")
    for field in PROFILE_FIELDS:
        items = profile.get(field) or []
        if items:
            lines.append(f"{field}: {', '.join(items)}")
    hint = str(profile.get("morning_hint", "")).strip()
    if hint:
        lines.append(f"morning_hint: {hint}")
    return "\n".join(lines)


def build_morning_text(profile: dict[str, Any], open_todos: list[str]) -> str:
    if not profile:
        return (
            "☀️ Доброе утро!\n\n"
            "Сделаем «Мой день»? Отправь голосовое или текст — выгрузи всё, что в голове."
        )

    lines = ["☀️ Доброе утро."]
    roles = profile.get("roles") or []
    projects = profile.get("active_projects") or []
    constraints = profile.get("constraints") or []
    hint = str(profile.get("morning_hint", "")).strip()

    remembered = []
    if roles:
        remembered.append(", ".join(roles[:3]))
    if projects:
        remembered.append(", ".join(projects[:3]))
    if remembered:
        lines.append(f"\nЯ помню фон: {'; '.join(remembered)}.")
    if constraints:
        lines.append(f"Учитываю: {', '.join(constraints[:2])}.")
    if open_todos:
        tail_lines = "\n".join(f"• {item}" for item in open_todos[:3])
        lines.append(f"\nС прошлого раза осталось:\n{tail_lines}")
    if hint:
        lines.append(f"\n{hint}")
    lines.append("\nМожно выгрузить голову или сразу выбрать один посильный шаг.")
    return "\n".join(lines)
