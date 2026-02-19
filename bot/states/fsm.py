"""FSM states for all multi-step flows."""

from aiogram.fsm.state import State, StatesGroup


# ── Smart Onboarding ──────────────────────────────────────────────────────────

class OnboardingStates(StatesGroup):
    """Multi-step smart onboarding."""
    # Step 1: Spheres
    choosing_spheres = State()         # selecting preset spheres
    entering_custom_sphere = State()   # typing custom sphere name

    # Step 2: Sphere assessment (per sphere loop)
    rating_satisfaction = State()      # 1-10 satisfaction
    rating_importance = State()        # 1-10 importance
    entering_pain = State()            # free text: what hurts / what's wanted
    confirming_priorities = State()    # confirm bot-suggested priority spheres

    # Step 3: Monthly focus (per priority sphere loop) — один свободный вопрос
    entering_month_result = State()    # свободное описание цели (текст или голос)
    confirming_goal = State()          # LLM validates -> user confirms or reframes

    # Step 4: Decomposition
    reviewing_decomposition = State()  # LLM shows weeks + steps, user confirms

    # Step 5: Weekly focus
    choosing_weekly_focus = State()    # pick 1-2 results for this week

    # Step 6: Settings
    choosing_tone = State()
    choosing_morning_time = State()
    choosing_evening_time = State()


# ── Dump ──────────────────────────────────────────────────────────────────────

class DumpStates(StatesGroup):
    waiting_dump = State()


# ── Focus selection ───────────────────────────────────────────────────────────

class FocusStates(StatesGroup):
    choosing_option = State()
    confirming_energy = State()


# ── Checkin ───────────────────────────────────────────────────────────────────

class CheckinStates(StatesGroup):
    waiting_status = State()


# ── Evening ───────────────────────────────────────────────────────────────────

class EveningStates(StatesGroup):
    waiting_status = State()
    waiting_text = State()


# ── Go deeper ─────────────────────────────────────────────────────────────────

class DeeperStates(StatesGroup):
    in_session = State()


# ── Settings ──────────────────────────────────────────────────────────────────

class SettingsStates(StatesGroup):
    choosing_setting = State()
    editing_value = State()


# ── Focus editing ─────────────────────────────────────────────────────────────

class FocusEditStates(StatesGroup):
    choosing_sphere = State()
    choosing_period = State()   # month or week
    entering_text = State()
