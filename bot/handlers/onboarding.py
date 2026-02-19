"""Smart onboarding: spheres -> assessment -> monthly focus -> decomposition -> weekly -> settings."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from aiogram import Bot, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User, Sphere, Focus, StepBank
from bot.keyboards.inline import (
    spheres_kb,
    rating_scale_kb,
    priority_confirm_kb,
    goal_confirm_kb,
    decomposition_kb,
    weekly_focus_kb,
    tone_kb,
    time_picker_kb,
    main_menu_kb,
    voice_confirm_kb,
)
from bot.services.llm_client import llm_client
from bot.services.transcriber import transcriber
from bot.prompts.validate_goal import build_validate_goal_prompt, build_validate_goal_user_message
from bot.prompts.decompose import build_decompose_prompt, build_decompose_user_message
from bot.states.fsm import OnboardingStates
from bot.utils.analytics import log_event

logger = logging.getLogger(__name__)
router = Router()

# Menu button texts that must NOT be treated as onboarding input
_MENU_TEXTS = frozenset({
    "🧠 Dump", "🎯 Фокус дня", "📅 Фокус недели", "🗓 Фокус месяца", "⚙️ Настройки"
})


async def _transcribe_voice(message: Message, bot: Bot) -> str | None:
    """Скачать и транскрибировать голосовое. Возвращает None при ошибке."""
    file = await bot.get_file(message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await bot.download_file(file.file_path, tmp_path)
    try:
        text = await transcriber.transcribe(tmp_path)
        return text.strip() or None
    except Exception as e:
        logger.error("Transcription failed in onboarding: %s", e)
        return None
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: SPHERES SELECTION
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(OnboardingStates.choosing_spheres, F.data.startswith("sphere:"))
async def on_sphere_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    from bot.keyboards.inline import PRESET_SPHERES

    raw = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected: set = set(data.get("selected_spheres", []))

    # Resolve index to sphere name
    if raw.startswith("c"):
        # Custom sphere — find by index among custom items
        custom = sorted(s for s in selected if s not in PRESET_SPHERES)
        idx = int(raw[1:])
        sphere = custom[idx] if idx < len(custom) else None
    else:
        idx = int(raw)
        sphere = PRESET_SPHERES[idx] if idx < len(PRESET_SPHERES) else None

    if sphere is None:
        await callback.answer()
        return

    if sphere in selected:
        selected.discard(sphere)
    else:
        selected.add(sphere)

    await state.update_data(selected_spheres=list(selected))
    await callback.message.edit_reply_markup(reply_markup=spheres_kb(selected))
    await callback.answer()


@router.callback_query(OnboardingStates.choosing_spheres, F.data == "sphere_custom")
async def on_sphere_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "✏️ Напечатай название своей сферы на клавиатуре:\n\n"
        "(например: Путешествия, Спорт, Бизнес)"
    )
    await state.set_state(OnboardingStates.entering_custom_sphere)
    await callback.answer()


@router.message(OnboardingStates.entering_custom_sphere, F.text)
async def on_custom_sphere_text(message: Message, state: FSMContext) -> None:
    if message.text.strip() in _MENU_TEXTS:
        await message.answer("✏️ Напечатай название своей сферы:")
        return
    custom = message.text.strip()[:50]
    data = await state.get_data()
    selected: set = set(data.get("selected_spheres", []))
    selected.add(f"✨ {custom}")
    await state.update_data(selected_spheres=list(selected))

    await message.answer(
        f"Добавлена: ✨ {custom}\n\nВыбери ещё сферы или нажми «Готово»:",
        reply_markup=spheres_kb(selected),
    )
    await state.set_state(OnboardingStates.choosing_spheres)


@router.callback_query(OnboardingStates.choosing_spheres, F.data == "spheres_done")
async def on_spheres_done(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    data = await state.get_data()
    selected = list(data.get("selected_spheres", []))

    if len(selected) < 3:
        await callback.answer("Выбери минимум 3 сферы", show_alert=True)
        return

    # Save spheres to DB
    for name in selected:
        existing = await db.execute(
            select(Sphere).where(Sphere.user_id == user_db.id, Sphere.name == name)
        )
        if not existing.scalar_one_or_none():
            db.add(Sphere(
                user_id=user_db.id,
                name=name,
                is_custom=name.startswith("✨"),
            ))
    await db.commit()

    # Start assessment loop
    await state.update_data(
        sphere_list=selected,
        current_sphere_idx=0,
    )
    await _ask_satisfaction(callback.message, state, selected[0])
    await callback.answer()


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: SPHERE ASSESSMENT (loop per sphere)
# ═══════════════════════════════════════════════════════════════════════════════

async def _ask_satisfaction(message, state: FSMContext, sphere_name: str) -> None:
    await message.edit_text(
        f"📊 *{sphere_name}*\n\n"
        "Насколько ты удовлетворён(а) этой сферой сейчас?",
        parse_mode="Markdown",
        reply_markup=rating_scale_kb("satisfaction"),
    )
    await state.set_state(OnboardingStates.rating_satisfaction)


@router.callback_query(OnboardingStates.rating_satisfaction, F.data.startswith("satisfaction:"))
async def on_satisfaction(callback: CallbackQuery, state: FSMContext) -> None:
    score = int(callback.data.split(":")[1])
    data = await state.get_data()
    idx = data["current_sphere_idx"]
    sphere_name = data["sphere_list"][idx]

    assessments = data.get("assessments", {})
    assessments.setdefault(sphere_name, {})["satisfaction"] = score
    await state.update_data(assessments=assessments)

    await callback.message.edit_text(
        f"📊 *{sphere_name}*\n"
        f"Удовлетворённость: {score}/10\n\n"
        "Насколько важны изменения в этой сфере?",
        parse_mode="Markdown",
        reply_markup=rating_scale_kb("importance"),
    )
    await state.set_state(OnboardingStates.rating_importance)
    await callback.answer()


@router.callback_query(OnboardingStates.rating_importance, F.data.startswith("importance:"))
async def on_importance(callback: CallbackQuery, state: FSMContext) -> None:
    score = int(callback.data.split(":")[1])
    data = await state.get_data()
    idx = data["current_sphere_idx"]
    sphere_name = data["sphere_list"][idx]

    assessments = data.get("assessments", {})
    assessments[sphere_name]["importance"] = score
    await state.update_data(assessments=assessments)

    sat = assessments[sphere_name]["satisfaction"]
    await callback.message.edit_text(
        f"📊 *{sphere_name}*\n"
        f"Удовлетворённость: {sat}/10 | Важность изменений: {score}/10\n\n"
        "Напиши одну фразу: что сейчас болит или чего хочется в этой сфере?",
        parse_mode="Markdown",
    )
    await state.set_state(OnboardingStates.entering_pain)
    await callback.answer()


async def _handle_pain(
    message: Message, state: FSMContext, db: AsyncSession, user_db: User, pain: str
) -> None:
    data = await state.get_data()
    idx = data["current_sphere_idx"]
    sphere_name = data["sphere_list"][idx]

    assessments = data.get("assessments", {})
    assessments[sphere_name]["pain"] = pain
    await state.update_data(assessments=assessments)

    # Save to DB
    result = await db.execute(
        select(Sphere).where(Sphere.user_id == user_db.id, Sphere.name == sphere_name)
    )
    sphere_obj = result.scalar_one_or_none()
    if sphere_obj:
        sphere_obj.satisfaction = assessments[sphere_name]["satisfaction"]
        sphere_obj.importance = assessments[sphere_name]["importance"]
        sphere_obj.pain_text = pain
        await db.commit()

    # Move to next sphere or finish assessment
    sphere_list = data["sphere_list"]
    next_idx = idx + 1

    if next_idx < len(sphere_list):
        await state.update_data(current_sphere_idx=next_idx)
        await message.answer(f"✅ {sphere_name} — записано!\n\nДальше:")
        await message.answer(
            f"📊 *{sphere_list[next_idx]}*\n\n"
            "Насколько ты удовлетворён(а) этой сферой сейчас?",
            parse_mode="Markdown",
            reply_markup=rating_scale_kb("satisfaction"),
        )
        await state.set_state(OnboardingStates.rating_satisfaction)
    else:
        await _show_priorities(message, state, assessments)


@router.message(OnboardingStates.entering_pain, F.text)
async def on_pain_text(
    message: Message, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    if message.text.strip() in _MENU_TEXTS:
        await message.answer("Ты в процессе настройки. Напиши одну фразу: что сейчас болит или чего хочется в этой сфере?")
        return
    await _handle_pain(message, state, db, user_db, message.text.strip())


@router.message(OnboardingStates.entering_pain, F.voice)
async def on_pain_voice(
    message: Message, bot: Bot, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    text = await _transcribe_voice(message, bot)
    if not text:
        await message.answer("Не удалось распознать голосовое. Напиши текстом.")
        return
    await state.update_data(voice_pending_pain=text)
    await message.answer(
        f"🎙 _{text}_\n\nВсё верно?",
        parse_mode="Markdown",
        reply_markup=voice_confirm_kb("pain"),
    )


@router.callback_query(OnboardingStates.entering_pain, F.data == "vc_ok:pain")
async def confirm_voice_pain(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    data = await state.get_data()
    text = data.get("voice_pending_pain", "")
    if not text:
        await callback.answer("Текст не найден", show_alert=True)
        return
    await callback.answer()
    await callback.message.delete()
    await _handle_pain(callback.message, state, db, user_db, text)


@router.callback_query(OnboardingStates.entering_pain, F.data == "vc_edit:pain")
async def edit_voice_pain(callback: CallbackQuery) -> None:
    await callback.message.edit_text("✏️ Напиши, что сейчас болит или чего хочется:")
    await callback.answer()


async def _show_priorities(message: Message, state: FSMContext, assessments: dict) -> None:
    # Priority score = importance * (11 - satisfaction) — higher = more priority
    scored = []
    for name, data in assessments.items():
        imp = data.get("importance", 5)
        sat = data.get("satisfaction", 5)
        priority_score = imp * (11 - sat)
        scored.append((name, priority_score, imp, sat))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:3]

    priorities_text = "\n".join(
        f"  {i+1}. {name} (удовл. {sat}/10, важность {imp}/10)"
        for i, (name, _, imp, sat) in enumerate(top)
    )

    priority_names = [name for name, _, _, _ in top]
    await state.update_data(priority_spheres=priority_names)

    await message.answer(
        "🎯 *Карта реальности готова!*\n\n"
        f"Приоритетные сферы на месяц:\n{priorities_text}\n\n"
        "Подтверждаешь или хочешь выбрать другие?",
        parse_mode="Markdown",
        reply_markup=priority_confirm_kb(priority_names),
    )
    await state.set_state(OnboardingStates.confirming_priorities)


@router.callback_query(OnboardingStates.confirming_priorities, F.data == "priorities_confirmed")
async def on_priorities_confirmed(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    data = await state.get_data()
    priority_names = data["priority_spheres"]

    # Mark priorities in DB
    for name in priority_names:
        result = await db.execute(
            select(Sphere).where(Sphere.user_id == user_db.id, Sphere.name == name)
        )
        sphere_obj = result.scalar_one_or_none()
        if sphere_obj:
            sphere_obj.is_priority = True
    await db.commit()

    # Start monthly focus loop for first priority
    await state.update_data(
        current_priority_idx=0,
        monthly_focuses={},
    )
    sphere_name = priority_names[0]
    await callback.message.edit_text(
        f"🗓 *Месячный фокус: {sphere_name}*\n\n"
        "Расскажи про цель на этот месяц — чего хочешь достичь и зачем?\n\n"
        "Пиши свободно, голосом или текстом. Одного-двух предложений хватит.",
        parse_mode="Markdown",
    )
    await state.set_state(OnboardingStates.entering_month_result)
    await callback.answer()


@router.callback_query(OnboardingStates.confirming_priorities, F.data == "priorities_reselect")
async def on_priorities_reselect(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = set(data.get("selected_spheres", []))
    await callback.message.edit_text(
        "Выбери сферы заново:",
        reply_markup=spheres_kb(selected),
    )
    await state.set_state(OnboardingStates.choosing_spheres)
    await callback.answer()


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: MONTHLY FOCUS (loop per priority sphere) — один свободный вопрос
# ═══════════════════════════════════════════════════════════════════════════════

async def _handle_month_goal(message: Message, state: FSMContext, raw_text: str) -> None:
    """Общая логика обработки свободного описания цели (текст или голос)."""
    data = await state.get_data()
    idx = data["current_priority_idx"]
    sphere_name = data["priority_spheres"][idx]
    mf = data.get("monthly_focuses", {})
    mf.setdefault(sphere_name, {})["raw_text"] = raw_text
    await state.update_data(monthly_focuses=mf)

    await message.answer("🤔 Оцениваю формулировку цели...")

    sys_prompt = build_validate_goal_prompt(data.get("tone", "neutral"))
    user_msg = build_validate_goal_user_message(sphere=sphere_name, goal_text=raw_text)

    try:
        llm_result = await llm_client.chat_json(
            system_prompt=sys_prompt,
            user_message=user_msg,
        )
    except Exception as e:
        logger.error("Goal validation LLM failed: %s", e)
        llm_result = {}

    score = llm_result.get("score", "ok")
    result_text = llm_result.get("result", raw_text[:150])
    analysis = llm_result.get("analysis", "")
    reframe = llm_result.get("reframe", "")

    mf[sphere_name]["result"] = result_text
    mf[sphere_name]["llm_score"] = score
    mf[sphere_name]["llm_reframe"] = reframe
    await state.update_data(monthly_focuses=mf)

    score_emoji = {"ok": "✅", "vague": "🌫", "imposed": "🚩", "too_big": "📏"}.get(score, "❓")
    score_label = {
        "ok": "Отличная цель!",
        "vague": "Расплывчато — давай конкретнее",
        "imposed": "Похоже на навязанную цель",
        "too_big": "Слишком много за 30 дней",
    }.get(score, "")

    display = (
        f"🗓 *{sphere_name}*\n\n"
        f"Цель: _{result_text}_\n\n"
        f"{score_emoji} *{score_label}*"
    )
    if analysis:
        display += f"\n{analysis}"
    if reframe and score != "ok":
        display += f"\n\n💡 *Предлагаю:*\n_{reframe}_"

    await message.answer(display, parse_mode="Markdown", reply_markup=goal_confirm_kb())
    await state.set_state(OnboardingStates.confirming_goal)


@router.message(OnboardingStates.entering_month_result, F.text)
async def on_month_goal_text(message: Message, state: FSMContext) -> None:
    if message.text.strip() in _MENU_TEXTS:
        await message.answer("Ты в процессе настройки. Расскажи про цель на месяц — чего хочешь достичь и зачем?")
        return
    await _handle_month_goal(message, state, message.text.strip())


@router.message(OnboardingStates.entering_month_result, F.voice)
async def on_month_goal_voice(message: Message, bot: Bot, state: FSMContext) -> None:
    text = await _transcribe_voice(message, bot)
    if not text:
        await message.answer("Не удалось распознать голосовое. Напиши текстом.")
        return
    await state.update_data(voice_pending_month_goal=text)
    await message.answer(
        f"🎙 _{text}_\n\nВсё верно?",
        parse_mode="Markdown",
        reply_markup=voice_confirm_kb("month_goal"),
    )


@router.callback_query(OnboardingStates.entering_month_result, F.data == "vc_ok:month_goal")
async def confirm_voice_month_goal(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    text = data.get("voice_pending_month_goal", "")
    if not text:
        await callback.answer("Текст не найден", show_alert=True)
        return
    await callback.answer()  # must answer before LLM call in _handle_month_goal
    await callback.message.delete()
    await _handle_month_goal(callback.message, state, text)


@router.callback_query(OnboardingStates.entering_month_result, F.data == "vc_edit:month_goal")
async def edit_voice_month_goal(callback: CallbackQuery) -> None:
    await callback.message.edit_text("✏️ Напиши исправленный вариант:")
    await callback.answer()


@router.callback_query(OnboardingStates.confirming_goal, F.data == "goal_accept")
async def on_goal_accept(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    data = await state.get_data()
    idx = data["current_priority_idx"]
    priorities = data["priority_spheres"]
    sphere_name = priorities[idx]
    mf = data["monthly_focuses"][sphere_name]

    # Acknowledge callback immediately — LLM decomp takes 10-20s
    await callback.answer()

    # Save focus to DB
    result = await db.execute(
        select(Sphere).where(Sphere.user_id == user_db.id, Sphere.name == sphere_name)
    )
    sphere_obj = result.scalar_one_or_none()

    focus = Focus(
        user_id=user_db.id,
        sphere_id=sphere_obj.id if sphere_obj else None,
        period="month",
        text=mf["result"],
        meaning=mf.get("raw_text"),
        llm_score=mf.get("llm_score"),
        llm_reframe=mf.get("llm_reframe"),
        is_active=True,
    )
    db.add(focus)
    await db.commit()
    await db.refresh(focus)

    # Decompose this focus
    await callback.message.edit_text("📋 Декомпозирую на недели и шаги...")

    try:
        decomp_result = await llm_client.chat_json(
            system_prompt=build_decompose_prompt(user_db.tone),
            user_message=build_decompose_user_message(
                sphere=sphere_name,
                focus_text=mf["result"],
                raw_description=mf.get("raw_text", ""),
            ),
        )
    except Exception as e:
        logger.error("Decomposition LLM failed: %s", e)
        decomp_result = {"weeks": [], "first_3_steps": []}

    # Save steps to StepBank
    weeks = decomp_result.get("weeks", [])
    for week_data in weeks:
        wn = week_data.get("week", 1)
        for i, step_data in enumerate(week_data.get("steps", [])):
            step = StepBank(
                focus_id=focus.id,
                week_number=wn,
                step_text=step_data.get("step", ""),
                plan_b_text=step_data.get("plan_b", ""),
                order=i,
            )
            db.add(step)
    await db.commit()

    # Format decomposition for display
    decomp_text = f"📋 *Декомпозиция: {sphere_name}*\n\n"
    for week_data in weeks:
        wn = week_data.get("week", "?")
        wr = week_data.get("result", "")
        decomp_text += f"*Неделя {wn}:* {wr}\n"
        for step_data in week_data.get("steps", [])[:3]:
            step = step_data.get("step", "")
            plan_b = step_data.get("plan_b", "")
            decomp_text += f"  • {step}\n"
            if plan_b:
                decomp_text += f"    _Plan B (10 мин):_ {plan_b}\n"
        decomp_text += "\n"

    first_steps = decomp_result.get("first_3_steps", [])
    if first_steps:
        decomp_text += "🔥 *Первые 3 шага на эту неделю:*\n"
        for i, s in enumerate(first_steps, 1):
            decomp_text += f"  {i}. {s}\n"

    await state.update_data(current_focus_id=focus.id)

    await callback.message.edit_text(
        decomp_text,
        parse_mode="Markdown",
        reply_markup=decomposition_kb(),
    )
    await state.set_state(OnboardingStates.reviewing_decomposition)


@router.callback_query(OnboardingStates.confirming_goal, F.data == "goal_reframe")
async def on_goal_reframe(
    callback: CallbackQuery, state: FSMContext,
) -> None:
    data = await state.get_data()
    idx = data["current_priority_idx"]
    sphere_name = data["priority_spheres"][idx]
    mf = data["monthly_focuses"][sphere_name]
    reframe = mf.get("llm_reframe", "")

    if reframe:
        # Update result to the reframe so "Принять" will accept it
        mf["result"] = reframe
        mf["llm_score"] = "ok"
        await state.update_data(monthly_focuses=data["monthly_focuses"])
        await callback.message.edit_text(
            f"💡 *Переформулировка для {sphere_name}:*\n\n"
            f"_{reframe}_\n\n"
            "Подходит? Или хочешь написать по-другому?",
            parse_mode="Markdown",
            reply_markup=goal_confirm_kb(),
        )
    else:
        await callback.message.edit_text(
            "Нет готовой переформулировки. Попробуй написать заново:",
            reply_markup=goal_confirm_kb(),
        )
    await callback.answer()


@router.message(OnboardingStates.confirming_goal, F.text)
async def on_goal_manual_edit(message: Message, state: FSMContext) -> None:
    """User typed their own wording while in the confirmation stage."""
    if message.text.strip() in _MENU_TEXTS:
        await message.answer(
            "Ты в процессе настройки цели. Нажми «✅ Принимаю», «📝 Написать заново» "
            "или напечатай свою формулировку."
        )
        return
    # Run validation on the manually typed text
    await _handle_month_goal(message, state, message.text.strip())


@router.callback_query(OnboardingStates.confirming_goal, F.data == "goal_rewrite")
async def on_goal_rewrite(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    idx = data["current_priority_idx"]
    sphere_name = data["priority_spheres"][idx]

    await callback.message.edit_text(
        f"🗓 *{sphere_name}*\n\n"
        "Расскажи заново — чего хочешь достичь и зачем?\n"
        "Голосом или текстом, свободно.",
        parse_mode="Markdown",
    )
    await state.set_state(OnboardingStates.entering_month_result)
    await callback.answer()


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4: DECOMPOSITION REVIEW
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(OnboardingStates.reviewing_decomposition, F.data == "decomp_accept")
async def on_decomp_accept(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    data = await state.get_data()
    idx = data["current_priority_idx"]
    priorities = data["priority_spheres"]

    # Move to next priority sphere or proceed to weekly focus
    next_idx = idx + 1
    if next_idx < len(priorities):
        await state.update_data(current_priority_idx=next_idx)
        sphere_name = priorities[next_idx]
        await callback.message.edit_text(
            f"🗓 *Месячный фокус: {sphere_name}*\n\n"
            "Расскажи про цель на этот месяц — чего хочешь достичь и зачем?\n\n"
            "Пиши свободно, голосом или текстом.",
            parse_mode="Markdown",
        )
        await state.set_state(OnboardingStates.entering_month_result)
    else:
        # All priorities done — choose weekly focus
        await _ask_weekly_focus(callback.message, state, db, user_db)

    await callback.answer()


@router.callback_query(OnboardingStates.reviewing_decomposition, F.data == "decomp_regen")
async def on_decomp_regen(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    # Re-run decomposition (re-trigger goal_accept logic)
    await on_goal_accept(callback, state, db, user_db)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5: WEEKLY FOCUS
# ═══════════════════════════════════════════════════════════════════════════════

async def _ask_weekly_focus(
    message, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    result = await db.execute(
        select(Focus).where(
            Focus.user_id == user_db.id,
            Focus.period == "month",
            Focus.is_active.is_(True),
        )
    )
    monthly_focuses = result.scalars().all()

    options = [(f.id, f.text) for f in monthly_focuses]
    await state.update_data(selected_weekly_ids=[])

    await message.edit_text(
        "📅 *Фокус недели*\n\n"
        "Выбери 1-2 цели из месячных фокусов — "
        "это будет твой фокус на эту неделю.\n"
        "(нажми на нужные, потом «Готово»)",
        parse_mode="Markdown",
        reply_markup=weekly_focus_kb(options),
    )
    await state.set_state(OnboardingStates.choosing_weekly_focus)


@router.callback_query(OnboardingStates.choosing_weekly_focus, F.data.startswith("weekly:"))
async def on_weekly_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    fid = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected_ids: list = data.get("selected_weekly_ids", [])

    if fid in selected_ids:
        selected_ids.remove(fid)
    else:
        if len(selected_ids) >= 2:
            await callback.answer("Максимум 2 фокуса на неделю", show_alert=True)
            return
        selected_ids.append(fid)

    await state.update_data(selected_weekly_ids=selected_ids)
    await callback.answer(f"Выбрано: {len(selected_ids)}")


@router.callback_query(OnboardingStates.choosing_weekly_focus, F.data == "weekly_done")
async def on_weekly_done(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    data = await state.get_data()
    selected_ids = data.get("selected_weekly_ids", [])

    if not selected_ids:
        await callback.answer("Выбери хотя бы 1 фокус", show_alert=True)
        return

    # Create weekly focuses from monthly ones
    for fid in selected_ids:
        result = await db.execute(select(Focus).where(Focus.id == fid))
        monthly = result.scalar_one_or_none()
        if monthly:
            weekly = Focus(
                user_id=user_db.id,
                sphere_id=monthly.sphere_id,
                period="week",
                text=monthly.text,
                meaning=monthly.meaning,
                is_active=True,
                week_number=1,
            )
            db.add(weekly)
    await db.commit()

    # Move to settings
    await callback.message.edit_text(
        "Отлично! Фокусы на неделю установлены.\n\n"
        "Последний шаг — настроим тон и расписание.\n\n"
        "Выбери тон, в котором я буду общаться:",
        reply_markup=tone_kb(),
    )
    await state.set_state(OnboardingStates.choosing_tone)
    await callback.answer()


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 6: SETTINGS (tone + times)
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(OnboardingStates.choosing_tone, F.data.startswith("tone:"))
async def on_tone_chosen(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    tone = callback.data.split(":", 1)[1]
    user_db.tone = tone
    await db.commit()

    await callback.message.edit_text(
        "🌅 В какое время утром присылать пинг для mind dump?",
        reply_markup=time_picker_kb("morning"),
    )
    await state.set_state(OnboardingStates.choosing_morning_time)
    await callback.answer()


@router.callback_query(
    OnboardingStates.choosing_morning_time, F.data.startswith("morning_time:")
)
async def on_morning_time(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    time_str = callback.data.split(":", 1)[1]
    user_db.morning_ping_time = time_str
    await db.commit()

    await callback.message.edit_text(
        "🌙 В какое время вечером напомнить о закрытии дня?",
        reply_markup=time_picker_kb("evening"),
    )
    await state.set_state(OnboardingStates.choosing_evening_time)
    await callback.answer()


@router.callback_query(
    OnboardingStates.choosing_evening_time, F.data.startswith("evening_time:")
)
async def on_evening_time(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    time_str = callback.data.split(":", 1)[1]
    user_db.evening_report_time = time_str
    user_db.onboarding_complete = True
    await db.commit()

    await log_event(db, "onboarding_complete", user_id=user_db.id)

    # Summary
    priorities = (await state.get_data()).get("priority_spheres", [])
    pri_text = "\n".join(f"  • {p}" for p in priorities)

    await callback.message.edit_text(
        "✅ *Настройка завершена!*\n\n"
        f"*Приоритетные сферы:*\n{pri_text}\n\n"
        f"Утренний пинг: {user_db.morning_ping_time}\n"
        f"Вечерний отчёт: {user_db.evening_report_time}\n"
        f"Тон: {user_db.tone}\n\n"
        "Ты можешь сделать mind dump прямо сейчас — "
        "отправь голосовое или текст. Поехали! 🚀",
        parse_mode="Markdown",
    )
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await state.clear()
    await callback.answer()
