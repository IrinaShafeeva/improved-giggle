"""Inline and reply keyboard builders."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)


# ── Main menu (ReplyKeyboard, persistent) ──────────────────────────────────────

def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧠 Dump"), KeyboardButton(text="🎯 Фокус дня")],
            [KeyboardButton(text="📅 Фокус недели"), KeyboardButton(text="🗓 Фокус месяца")],
            [KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
    )


# ── Onboarding: spheres ───────────────────────────────────────────────────────

SPHERES = [
    "💼 Работа/Карьера",
    "💪 Здоровье",
    "❤️ Отношения",
    "📚 Обучение",
    "💰 Финансы",
    "🎨 Творчество",
    "🏠 Быт/Дом",
    "🧘 Духовность",
]


def spheres_kb(selected: set[str] | None = None) -> InlineKeyboardMarkup:
    selected = selected or set()
    buttons = []
    for s in SPHERES:
        check = "✅ " if s in selected else ""
        buttons.append([InlineKeyboardButton(
            text=f"{check}{s}",
            callback_data=f"sphere:{s}",
        )])
    buttons.append([InlineKeyboardButton(text="Готово ➡️", callback_data="spheres_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ── Onboarding: tone ──────────────────────────────────────────────────────────

def tone_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="😐 Нейтральный", callback_data="tone:neutral"),
            InlineKeyboardButton(text="🤗 Мягкий", callback_data="tone:soft"),
            InlineKeyboardButton(text="💪 Строгий", callback_data="tone:strict"),
        ],
    ])


# ── Onboarding: time picker ───────────────────────────────────────────────────

def time_picker_kb(prefix: str) -> InlineKeyboardMarkup:
    """Simple time picker with common times."""
    times = ["07:00", "08:00", "09:00", "10:00", "11:00", "12:00"]
    if prefix == "evening":
        times = ["18:00", "19:00", "20:00", "21:00", "22:00", "23:00"]

    rows = []
    row = []
    for t in times:
        row.append(InlineKeyboardButton(text=t, callback_data=f"{prefix}_time:{t}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Morning ping ──────────────────────────────────────────────────────────────

def morning_ping_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да, поехали 🧠", callback_data="dump_yes"),
            InlineKeyboardButton(text="Позже ⏰", callback_data="dump_later"),
        ],
    ])


# ── Focus options A/B ─────────────────────────────────────────────────────────

def focus_options_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🅰️ Вариант A", callback_data="focus:A"),
            InlineKeyboardButton(text="🅱️ Вариант B", callback_data="focus:B"),
        ],
    ])


# ── Energy confirm ────────────────────────────────────────────────────────────

def energy_kb(suggested: int) -> InlineKeyboardMarkup:
    buttons = []
    for i in range(1, 6):
        mark = " ✓" if i == suggested else ""
        buttons.append(InlineKeyboardButton(
            text=f"{i}{mark}", callback_data=f"energy:{i}"
        ))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


# ── Checkin statuses ──────────────────────────────────────────────────────────

def checkin_kb(session_id: int, kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Сделано", callback_data=f"checkin:{session_id}:{kind}:done"),
            InlineKeyboardButton(text="🟡 В процессе", callback_data=f"checkin:{session_id}:{kind}:progress"),
        ],
        [
            InlineKeyboardButton(text="⏳ Перенёс", callback_data=f"checkin:{session_id}:{kind}:moved"),
            InlineKeyboardButton(text="🆘 Нужна помощь", callback_data=f"checkin:{session_id}:{kind}:help"),
        ],
    ])


# ── Evening report statuses ───────────────────────────────────────────────────

def evening_status_kb(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Сделано", callback_data=f"evening:{session_id}:done"),
            InlineKeyboardButton(text="🟡 Частично", callback_data=f"evening:{session_id}:partial"),
            InlineKeyboardButton(text="❌ Не получилось", callback_data=f"evening:{session_id}:fail"),
        ],
    ])


# ── Go deeper ─────────────────────────────────────────────────────────────────

def go_deeper_kb(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Копнуть глубже", callback_data=f"deeper:{session_id}")],
    ])


# ── Settings ──────────────────────────────────────────────────────────────────

def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Фокус недели", callback_data="set:weekly_focus")],
        [InlineKeyboardButton(text="🗓 Фокус месяца", callback_data="set:monthly_focus")],
        [InlineKeyboardButton(text="🎭 Тон бота", callback_data="set:tone")],
        [InlineKeyboardButton(text="🌅 Утренний пинг", callback_data="set:morning_time")],
        [InlineKeyboardButton(text="🌙 Вечерний отчёт", callback_data="set:evening_time")],
    ])
