"""Server-owned spoken preflight; ambiguous consent never grants permission."""

import re

from app.modules.outreach.preflight import briefing_snapshot


def spoken_prompt(case):
    state = case.session_data.get("preflight", {})
    if case.status in {"ended", "cancelled"} or case.stop_status != "none":
        return (
            "本次面试已结束。后续由招聘方核对面试记录并确认是否进入下一环节；"
            "内部评估报告不会自动发送。感谢您的时间，再见。"
        )
    if case.session_data.get("conversation_reply"):
        return case.session_data["conversation_reply"]
    if case.session_data.get("voice_clarification"):
        return "抱歉，我还没有确认您的意愿。您愿意继续了解并参加这次面试吗？"
    if state.get("interested") is not True:
        return "您好，我是AI招聘面试官。请问您目前是否有找工作或了解新机会的需求？"
    if not state.get("confirmed") and state.get("briefing_presented"):
        return "岗位资料已向您介绍，邮件发送状态请看页面提示。您是否已了解材料，并愿意继续面试？"
    if not state.get("confirmed"):
        material = briefing_snapshot(case)

        def describe(value):
            if not value:
                return "暂未提供，具体信息需要招聘方进一步确认"
            if isinstance(value, list):
                value = "；".join(str(item) for item in value)
            if isinstance(value, dict):
                value = "；".join(f"{key}：{value}" for key, value in value.items())
            text = str(value)
            return text if len(text) <= 160 else text[:160] + "。其余细节请向招聘方确认"

        return (
            f"感谢您。本次岗位是{describe(material.get('job_title'))}。"
            f"主要需求：{describe(material.get('requirements'))[:80]}。"
            f"薪资范围：{describe(material.get('salary'))}。"
            "完整资料可在页面查看，也可授权发送到邮箱。未确认的信息不作承诺。"
            "我先处理您已授权的资料邮件，随后再确认是否开始面试。"
        )
    return (case.session_data.get("current_question") or {}).get("question")


def consent(text):
    compact = re.sub(r"[\s，。！？,.!?]", "", text.lower())
    if re.fullmatch(r"(?:有的|有啊|有|是的|好的|可以的|可以继续|愿意)(?:呢|呀|啊|嗯)*", compact):
        return True
    if re.fullmatch(r"(?:有的|有|是的|好的|可以的){2,5}", compact):
        return True
    if compact in {"没有", "没", "不", "不要", "没有啊", "没有呢", "没有谢谢", "no"}:
        return False
    if any(word in compact for word in ("不是不", "并非不", "不能说不")):
        return None
    if re.search(r"没有.{0,12}(?:需求|意愿|兴趣)", compact):
        return False
    negative = (
        "不考虑",
        "没需求",
        "没有需求",
        "不需要",
        "不找",
        "不想",
        "不愿意",
        "没兴趣",
        "不感兴趣",
        "暂时没有",
        "暂不",
        "不同意",
        "不继续",
        "不方便",
    )
    uncertain = (
        "不确定",
        "没听清",
        "没了解",
        "再说一遍",
        "不知道",
        "但是",
        "不过",
        "还没",
        "并非",
        "不是",
        "是否",
        "能不能",
        "可不可以",
    )
    positive = (
        "有需求",
        "有意愿",
        "有兴趣",
        "在找工作",
        "正在找",
        "考虑机会",
        "愿意继续",
        "想了解",
        "没问题",
        "可以开始",
        "可以继续",
        "已经了解",
        "了解了",
        "同意开始",
    )
    if any(word in compact for word in negative):
        return False
    if any(word in compact for word in uncertain) or "？" in text or "?" in text:
        return None
    if compact in {"有", "是", "好的", "好", "可以", "嗯", "愿意", "继续", "同意", "yes", "ok"}:
        return True
    if any(word in compact for word in positive):
        return True
    return None
