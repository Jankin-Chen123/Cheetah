"""Public voice catalogue and explicit per-session duration policy."""

import time

from app.modules.outreach.interview import termination_reason

VOICES = [
    {"id": "longyan_v3.1", "label": "龙颜 · 自然亲切女声"},
    {"id": "longanwen_v3.1", "label": "龙安温 · 知性女声"},
    {"id": "longanlang_v3.1", "label": "龙安朗 · 清爽男声"},
    {"id": "longtian_v3.1", "label": "龙天 · 磁性男声"},
    {"id": "longanhuan_v3.1", "label": "龙安欢 · 原音色"},
]
DEFAULT_VOICE = "longyan_v3.1"
VOLC_VOICES = [
    {"id": "zh_female_vv_uranus_bigtts", "label": "Vivi 2.0 · 女声"},
    {"id": "zh_female_xiaohe_uranus_bigtts", "label": "小何 2.0 · 女声"},
    {"id": "zh_female_tuanzi_uranus_bigtts", "label": "团子 2.0 · 女声"},
    {"id": "zh_male_m191_uranus_bigtts", "label": "云舟 2.0 · 男声"},
    {"id": "zh_male_taocheng_uranus_bigtts", "label": "小天 2.0 · 男声"},
    {"id": "zh_male_liufei_uranus_bigtts", "label": "刘飞 2.0 · 男声"},
]
PRACTICE_LIMITS = {"max_seconds": 3600, "max_rounds": 30, "max_turn_seconds": 600}


def voice_id(case):
    catalog = voice_catalog()
    selected = case.session_data.get("voice_id")
    return selected if selected in {item["id"] for item in catalog} else catalog[0]["id"]


def limits(case):
    return case.session_data.get(
        "interview_limits", {"max_seconds": 3600, "max_rounds": 30, "max_turn_seconds": 600}
    )


def case_termination(case, answer, round_count, elapsed_seconds):
    policy = limits(case)
    return termination_reason(
        answer,
        round_count,
        elapsed_seconds,
        max_rounds=policy["max_rounds"],
        max_seconds=policy["max_seconds"],
    )


def enforce_duration(case):
    started = case.session_data.get("started_at")
    if (
        started
        and time.time() - started >= limits(case)["max_seconds"]
        and case.status not in {"ended", "cancelled"}
        and case.stop_status == "none"
    ):
        if case.session_data.get("attempts"):
            from app.modules.outreach.voice import confirm_mock_stop

            case.stop_status = "requested"
            confirm_mock_stop(case)
        case.status = "ended"
        case.stop_status = "confirmed"
        case.session_data = {
            **case.session_data,
            "termination_reason": "duration_limit",
            "decision_status": "stopped",
        }
        case.revision += 1


def voice_catalog(settings=None):
    from app.core.config import get_settings

    settings = settings or get_settings()
    voices = VOLC_VOICES if settings.voice_provider == "volcengine" else VOICES
    if settings.tts_custom_voice_id:
        return [
            *voices,
            {"id": settings.tts_custom_voice_id, "label": settings.tts_custom_voice_label},
        ]
    return voices
