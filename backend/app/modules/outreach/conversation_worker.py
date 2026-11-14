"""Interpret preflight questions without granting consent on behalf of a candidate."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.integrations.bailian import ModelUnavailable, generate_json
from app.modules.outreach.budget import reserve_model_request
from app.modules.outreach.conversation import spoken_prompt
from app.modules.outreach.models import ModelStep, OutreachCase
from app.modules.outreach.preflight import briefing_snapshot
from app.modules.outreach.steps import claim_step, finish_step, result_still_current


class ConversationReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["interest_yes", "interest_no", "confirm_yes", "question", "unclear"] = (
        "question"
    )
    reply: str = Field(min_length=1, max_length=400)


def execute_conversation(engine, settings, task_id):
    with Session(engine) as session, session.begin():
        snapshot = claim_step(session, task_id)
        if snapshot is None:
            return
        task = session.get(ModelStep, task_id)
        case = session.get(OutreachCase, task.case_id)
        try:
            reserve_model_request(case, settings, "followup")
        except ModelUnavailable as error:
            finish_step(task, error_code=str(error))
            return
        context = {
            "required_output_example": {
                "intent": "question",
                "reply": "您好，请问您想了解岗位的哪个方面？",
            },
            "output_schema": ConversationReply.model_json_schema(),
            "dialogue_stage": "confirmation"
            if case.session_data.get("preflight", {}).get("briefing_presented")
            else "interest",
            "utterance": case.session_data.get("conversation_utterance"),
            "previous_prompt": case.session_data.get("conversation_prompt") or spoken_prompt(case),
            "recent_exchanges": case.session_data.get("conversation_history", [])[-8:],
            "material": briefing_snapshot(case),
            "preflight": case.session_data.get("preflight", {}),
        }
    try:
        result = generate_json(
            settings,
            "你负责面试开场的自然语言理解，不是要求候选人背固定口令。"
            "根据dialogue_stage理解意图：interest阶段，明确愿意了解岗位记interest_yes，"
            "明确拒绝记interest_no；confirmation阶段，明确同意开始记confirm_yes。"
            "例如confirmation阶段说‘岗位看过了，开始聊我的经历吧’就是confirm_yes，"
            "不能回复说开始了却把intent写成question。纯粹反问、姓名、犹豫用question或unclear，不能当授权。"
            "直接简短回答岗位问题，没提供的信息说明待确认，不能虚构岗位条件。"
            "只问一个问题，最多80个汉字，不奉承，不重复介绍已说明的所有资料。"
            "返回JSON对象，必须有intent和reply，不是Schema。",
            context,
        )
        reply = ConversationReply.model_validate(result["content"])
        failure = None
    except (ModelUnavailable, ValueError) as error:
        failure = str(error) if isinstance(error, ModelUnavailable) else "MODEL_OUTPUT_INVALID"
    with Session(engine) as session, session.begin():
        task = session.get(ModelStep, task_id, with_for_update=True)
        case = session.get(OutreachCase, task.case_id, with_for_update=True)
        if not result_still_current(task, case) or case.stop_status != "none":
            if task.status == "running":
                task.status = "cancelled"
            return
        if failure:
            reply = ConversationReply(
                reply="刚才我这边处理回复时出了点问题。您可以继续告诉我想了解的岗位信息，我在听。"
            )
            result = {"model": None}
            task.detail = {
                **task.detail,
                "degraded_reason": failure,
                "generator_kind": "program_clarification",
            }
        state = case.session_data.get("preflight", {})
        if reply.intent == "confirm_yes" and not state.get("interested"):
            reply.intent = "interest_yes"
        if (
            reply.intent == "interest_yes"
            and state.get("interested")
            and state.get("briefing_presented")
        ):
            reply.intent = "confirm_yes"
        if not failure and reply.intent == "interest_yes" and not state.get("interested"):
            from app.modules.outreach.preflight import record_interest

            record_interest(case, True, case.session_data.get("conversation_utterance", ""))
        elif not failure and reply.intent == "interest_no":
            case.status = "ended"
            case.stop_status = "confirmed"
            case.session_data = {**case.session_data, "termination_reason": "candidate_declined"}
        elif (
            not failure
            and reply.intent == "confirm_yes"
            and state.get("interested")
            and state.get("briefing_presented")
        ):
            import hashlib
            import json

            from app.modules.outreach.preflight import confirm_preflight

            digest = hashlib.sha256(
                json.dumps(briefing_snapshot(case), sort_keys=True).encode()
            ).hexdigest()
            confirm_preflight(case, case.session_data.get("conversation_utterance", ""), digest)
        case.session_data = {
            **case.session_data,
            "conversation_reply": None
            if not failure and reply.intent in {"interest_yes", "confirm_yes", "interest_no"}
            else reply.reply,
            "voice_clarification": None
            if not failure
            else case.session_data.get("voice_clarification"),
            "conversation_reply_model": result["model"],
            "conversation_history": [
                *case.session_data.get("conversation_history", [])[-7:],
                {
                    "prompt": context["previous_prompt"],
                    "candidate": context["utterance"],
                    "reply": reply.reply,
                },
            ],
            "decision_status": "completed",
        }
        case.revision += 1
        finish_step(task, result_ref={"kind": "conversation_reply"})
