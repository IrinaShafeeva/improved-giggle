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


# ── Spheres ────────────────────────────────────────────────────────────────────

PRESET_SPHERES = [
    "💼 Работа/Карьера",
    "💪 Здоровье",
    "❤️ Отношения",
    "👨‍👩‍👧 Семья",
    "📚 Обучение",
    "💰 Финансы",
    "🎨 Творчество",
    "🏠 Быт/Дом",
    "🧘 Духовность",
    "🎉 Отдых/Хобби",
]


def spheres_kb(selected: set[str] | None = None) -> InlineKeyboardMarkup:
    selected = selected or set()
    buttons = []
    # Preset spheres (use index as callback_data to stay within 64 bytes)
    for i, s in enumerate(PRESET_SPHERES):
        check = "✅ " if s in selected else ""
        buttons.append([InlineKeyboardButton(
            text=f"{check}{s}",
            callback_data=f"sphere:{i}",
        )])
    # Custom spheres added by user (not in presets)
    custom = sorted(s for s in selected if s not in PRESET_SPHERES)
    for j, s in enumerate(custom):
        buttons.append([InlineKeyboardButton(
            text=f"✅ {s}",
            callback_data=f"sphere:c{j}",
        )])
    buttons.append([InlineKeyboardButton(text="➕ Своя сфера", callback_data="sphere_custom")])
    buttons.append([InlineKeyboardButton(text="Готово ➡️", callback_data="spheres_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ── Rating scale 1-10 ─────────────────────────────────────────────────────────

def rating_scale_kb(prefix: str) -> InlineKeyboardMarkup:
    """Rating scale 1-10 in two rows."""
    row1 = [InlineKeyboardButton(text=str(i), callback_data=f"{prefix}:{i}") for i in range(1, 6)]
    row2 = [InlineKeyboardButton(text=str(i), callback_data=f"{prefix}:{i}") for i in range(6, 11)]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


# ── Priority spheres confirmation ──────────────────────────────────────────────

def priority_confirm_kb(priorities: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    for i, p in enumerate(priorities):
        buttons.append([InlineKeyboardButton(text=f"✅ {p}", callback_data=f"pri:{i}")])
    buttons.append([InlineKeyboardButton(text="Подтверждаю ➡️", callback_data="priorities_confirmed")])
    buttons.append([InlineKeyboardButton(text="Выбрать другие", callback_data="priorities_reselect")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ── Goal confirmation (after LLM validation) ──────────────────────────────────

def goal_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принимаю", callback_data="goal_accept"),
            InlineKeyboardButton(text="✏️ Переформулировать", callback_data="goal_reframe"),
        ],
        [InlineKeyboardButton(text="📝 Написать заново", callback_data="goal_rewrite")],
    ])


# ── Decomposition review ──────────────────────────────────────────────────────

def decomposition_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ок, поехали", callback_data="decomp_accept"),
            InlineKeyboardButton(text="🔄 Перегенерировать", callback_data="decomp_regen"),
        ],
    ])


# ── Weekly focus selection ─────────────────────────────────────────────────────

def weekly_focus_kb(options: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """options: list of (focus_id, text)"""
    buttons = []
    for fid, text in options:
        short = text[:50] + "..." if len(text) > 50 else text
        buttons.append([InlineKeyboardButton(text=f"🎯 {short}", callback_data=f"weekly:{fid}")])
    buttons.append([InlineKeyboardButton(text="Готово ➡️", callback_data="weekly_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ── Tone ──────────────────────────────────────────────────────────────────────

def tone_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="😐 Нейтральный", callback_data="tone:neutral"),
            InlineKeyboardButton(text="🤗 Мягкий", callback_data="tone:soft"),
            InlineKeyboardButton(text="💪 Строгий", callback_data="tone:strict"),
        ],
    ])


# ── Time picker ───────────────────────────────────────────────────────────────

def time_picker_kb(prefix: str) -> InlineKeyboardMarkup:
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
        buttons.append(InlineKeyboardButton(text=f"{i}{mark}", callback_data=f"energy:{i}"))
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


# ── Evening report ────────────────────────────────────────────────────────────

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
        [InlineKeyboardButton(text="🌍 Сферы и фокусы", callback_data="set:spheres")],
        [InlineKeyboardButton(text="📅 Фокус недели", callback_data="set:weekly_focus")],
        [InlineKeyboardButton(text="🗓 Фокус месяца", callback_data="set:monthly_focus")],
        [InlineKeyboardButton(text="🎭 Тон бота", callback_data="set:tone")],
        [InlineKeyboardButton(text="🌅 Утренний пинг", callback_data="set:morning_time")],
        [InlineKeyboardButton(text="🌙 Вечерний отчёт", callback_data="set:evening_time")],
    ])


# ── Sphere list for focus editing ─────────────────────────────────────────────

def sphere_list_kb(spheres: list[tuple[int, str]], prefix: str = "edit_sphere") -> InlineKeyboardMarkup:
    buttons = []
    for sid, name in spheres:
        buttons.append([InlineKeyboardButton(text=name, callback_data=f"{prefix}:{sid}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ── Todo checklist ─────────────────────────────────────────────────────────────

def todo_input_kb() -> InlineKeyboardMarkup:
    """Shown when asking user to add daily todos."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить ➡️", callback_data="todo_skip")],
    ])


def todo_list_kb(todos: list) -> InlineKeyboardMarkup:
    """Inline keyboard for a list of pending TodoItems."""
    buttons = []
    for todo in todos:
        label = todo.text[:28] + "…" if len(todo.text) > 28 else todo.text
        buttons.append([
            InlineKeyboardButton(text=f"✅ {label}", callback_data=f"todo:done:{todo.id}"),
            InlineKeyboardButton(text="➡️ Завтра", callback_data=f"todo:carry:{todo.id}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ── Focus view with edit button ────────────────────────────────────────────────

def focus_view_kb(period: str) -> InlineKeyboardMarkup:
    """period: 'week' or 'month'"""
    key = "weekly_focus" if period == "week" else "monthly_focus"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить", callback_data=f"set:{key}")],
    ])
