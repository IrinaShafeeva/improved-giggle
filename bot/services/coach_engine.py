"""CoachEngine – LLM-based mind dump analysis and coaching."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from bot.services.llm_client import llm_client
from bot.prompts.analyze_dump import build_analyze_prompt
from bot.prompts.go_deeper import build_deeper_prompt

logger = logging.getLogger(__name__)


@dataclass
class FocusOption:
    label: str  # "A" or "B"
    focus_text: str
    step_text: str  # 30-45 min step
    plan_b_text: str  # 10 min plan B


@dataclass
class DumpAnalysis:
    emotion_mirror: str = ""  # A
    need_meaning: str = ""  # B
    structure: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)  # C
    blind_spots: list[str] = field(default_factory=list)
    main_tension: str = ""
    day_risk: str = ""
    context_links: str = ""
    sharp_question: str = ""
    day_summary: str = ""
    focus_mapping: str = ""  # D
    option_a: Optional[FocusOption] = None  # E+F
    option_b: Optional[FocusOption] = None  # E+F
    suggested_energy: int = 3  # G
    go_deeper_triggered: bool = False  # H
    raw: dict[str, Any] = field(default_factory=dict)


class CoachEngine:
    """Stateless coaching engine that delegates to LLM."""

    async def analyze_mind_dump(
        self,
        text: str,
        weekly_focus: str,
        monthly_focus: str,
        tone: str,
        spheres: str = "",
        weekly_context: str = "",
        monthly_context: str = "",
        profile_context: str = "",
    ) -> DumpAnalysis:
        system_prompt = build_analyze_prompt(
            tone=tone,
            weekly_focus=weekly_focus,
            monthly_focus=monthly_focus,
            spheres=spheres,
            weekly_context=weekly_context,
            monthly_context=monthly_context,
            profile_context=profile_context,
        )

        data = await llm_client.chat_json(
            system_prompt=system_prompt,
            user_message=text,
            temperature=0.7,
            max_tokens=2000,
        )

        if "error" in data:
            logger.error("LLM analysis failed: %s", data)
            return DumpAnalysis(
                emotion_mirror="Не удалось проанализировать. Попробуй ещё раз.",
                raw=data,
            )

        return self._parse_analysis(data)

    async def go_deeper(
        self,
        dump_text: str,
        emotion_mirror: str,
        tone: str,
    ) -> str:
        system_prompt = build_deeper_prompt(tone=tone)
        user_msg = (
            f"Мой mind dump:\n{dump_text}\n\n"
            f"Зеркало эмоций:\n{emotion_mirror}"
        )
        return await llm_client.chat(
            system_prompt=system_prompt,
            user_message=user_msg,
            temperature=0.7,
            max_tokens=1200,
        )

    @staticmethod
    def _parse_analysis(data: dict[str, Any]) -> DumpAnalysis:
        def _as_list(value: Any) -> list[str]:
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
            if isinstance(value, str):
                return [t.strip("- •") for t in value.split("\n") if t.strip()]
            return []

        tasks_raw = data.get("tasks", [])
        tasks_raw = _as_list(tasks_raw)

        opt_a_raw = data.get("option_a", {})
        opt_b_raw = data.get("option_b", {})

        option_a = FocusOption(
            label="A",
            focus_text=opt_a_raw.get("focus", ""),
            step_text=opt_a_raw.get("step", ""),
            plan_b_text=opt_a_raw.get("plan_b", ""),
        ) if opt_a_raw else None

        option_b = FocusOption(
            label="B",
            focus_text=opt_b_raw.get("focus", ""),
            step_text=opt_b_raw.get("step", ""),
            plan_b_text=opt_b_raw.get("plan_b", ""),
        ) if opt_b_raw else None

        energy = data.get("suggested_energy", 3)
        if not isinstance(energy, int) or energy < 1 or energy > 5:
            energy = 3

        return DumpAnalysis(
            emotion_mirror=data.get("emotion_mirror", ""),
            need_meaning=data.get("need_meaning", ""),
            structure=_as_list(data.get("structure", []))[:4],
            tasks=tasks_raw[:6],
            blind_spots=_as_list(data.get("blind_spots", []))[:2],
            main_tension=data.get("main_tension", ""),
            day_risk=data.get("day_risk", ""),
            context_links=data.get("context_links", ""),
            sharp_question=data.get("sharp_question", ""),
            day_summary=data.get("day_summary", ""),
            focus_mapping=data.get("focus_mapping", ""),
            option_a=option_a,
            option_b=option_b,
            suggested_energy=energy,
            go_deeper_triggered=bool(data.get("go_deeper_triggered", False)),
            raw=data,
        )


# Singleton
coach = CoachEngine()
