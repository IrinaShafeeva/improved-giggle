"""FSM states for all multi-step flows."""

from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    """Onboarding after /start."""
    choosing_spheres = State()
    entering_weekly_focus = State()
    entering_monthly_focus = State()
    choosing_tone = State()
    choosing_morning_time = State()
    choosing_evening_time = State()


class DumpStates(StatesGroup):
    """Mind dump flow."""
    waiting_dump = State()  # waiting for voice or text


class FocusStates(StatesGroup):
    """After LLM analysis — choosing focus option."""
    choosing_option = State()
    confirming_energy = State()


class CheckinStates(StatesGroup):
    """Mini-checkin response."""
    waiting_status = State()


class EveningStates(StatesGroup):
    """Evening report."""
    waiting_status = State()
    waiting_text = State()


class DeeperStates(StatesGroup):
    """Go deeper coaching session."""
    in_session = State()


class SettingsStates(StatesGroup):
    """User settings editing."""
    choosing_setting = State()
    editing_value = State()
