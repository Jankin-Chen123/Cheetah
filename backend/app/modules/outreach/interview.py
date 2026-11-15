"""Validated interview decisions and program-controlled termination."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConditionalFollowup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger: str = Field(min_length=1, max_length=500)
    question: str = Field(min_length=1, max_length=1000)


class InterviewQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    dimension_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=1000)
    method_entry_ids: list[str] = Field(default_factory=list, max_length=8)
    evidence_target: str = Field(min_length=1, max_length=1000)
    priority: Literal["MUST", "HIGH", "OPTIONAL"] = "HIGH"
    planned_minutes: int = Field(default=0, ge=0, le=30)
    question_type: Literal["BEHAVIORAL", "CIT", "SITUATIONAL", "CHALLENGE"] = "BEHAVIORAL"
    source_refs: list[str] = Field(default_factory=list, max_length=12)
    conditional_followups: list[ConditionalFollowup] = Field(default_factory=list, max_length=5)
    stop_rule: str = Field(default="", max_length=1000)


class Outline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: list[InterviewQuestion] = Field(min_length=1, max_length=12)
    unknowns: list[str] = Field(default_factory=list, max_length=20)


class InterviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["followup", "clarify", "next_topic", "end"]
    question: str | None = Field(default=None, max_length=1000)
    dimension_id: str | None = None
    method_entry_ids: list[str] = Field(default_factory=list, max_length=8)
    answer_evidence_ids: list[str] = Field(default_factory=list, max_length=24)
    reason: str = Field(min_length=1, max_length=1000)


def bounded_topic_decision(data: dict, outline: dict, max_followups: int = 2):
    """Bound repeated probing; this is a program policy, not an evidence sufficiency score."""
    answers = data.get("answers", [])
    if not answers:
        return None
    dimension = answers[-1]["question"].get("dimension_id")
    count = 0
    for decision in reversed(data.get("decisions", [])):
        if decision.get("dimension_id") != dimension or decision.get("action") not in {
            "followup",
            "clarify",
        }:
            break
        count += 1
    if count < max_followups:
        return None
    asked = {a["question"]["question"] for a in answers}
    for question in outline.get("questions", []):
        if question["dimension_id"] != dimension and question["question"] not in asked:
            return InterviewDecision(
                action="next_topic",
                question=question["question"],
                dimension_id=question["dimension_id"],
                method_entry_ids=question["method_entry_ids"],
                answer_evidence_ids=[answers[-1]["id"]],
                reason="程序单维度追问上限：转向未覆盖主题，原维度缺口保留未知。",
            )
    return InterviewDecision(
        action="end",
        answer_evidence_ids=[answers[-1]["id"]],
        reason="程序单维度追问上限且无其他未覆盖主题；保留证据缺口，不推定达标。",
    )


def validate_outline(outline: Outline, methods: list[dict], dimension_ids: set[str]):
    allowed = {item["entry_id"] for item in methods}
    if len({q.id for q in outline.questions}) != len(outline.questions):
        raise ValueError("Duplicate question IDs")
    for question in outline.questions:
        if question.dimension_id not in dimension_ids:
            raise ValueError("Unknown dimension")
        if not set(question.method_entry_ids).issubset(allowed):
            raise ValueError("Unknown method citation")
    return outline


def validate_question_cards(outline: Outline, dimension_ids: set[str], refs: dict):
    if {q.dimension_id for q in outline.questions} != dimension_ids:
        raise ValueError("DIMENSION_COVERAGE_INCOMPLETE")
    allowed = {ref["artifact_id"] for ref in refs.values()}
    if sum(q.planned_minutes for q in outline.questions) != 26 or any(
        not q.source_refs
        or not set(q.source_refs).issubset(allowed)
        or not q.conditional_followups
        or not q.stop_rule.strip()
        or q.planned_minutes <= 0
        for q in outline.questions
    ):
        raise ValueError("QUESTION_CARDS_INCOMPLETE")
    return outline


def allocate_question_minutes(outline: Outline, total_minutes: int = 26):
    """Program-owned time slots never change questions, evidence or competency scores."""
    count = len(outline.questions)
    if total_minutes < count:
        raise ValueError("QUESTION_TIME_BUDGET_INSUFFICIENT")
    minutes, remainder = divmod(total_minutes, count)
    return outline.model_copy(
        update={
            "questions": [
                question.model_copy(update={"planned_minutes": minutes + (index < remainder)})
                for index, question in enumerate(outline.questions)
            ]
        }
    )


def continue_after_acknowledgement(payload, answers, planned):
    """An acknowledgement alone cannot occupy a turn that requires an answer."""
    text = payload.get("question")
    if re.search(r"[?？]|请问|能否|是否|什么意思", answers[-1].get("text", "")):
        return None
    if (
        payload.get("action") == "end"
        or not isinstance(text, str)
        or re.search(r"[?？]|请|能否|是否|什么|哪|怎么|如何|多少|吗|谈谈|说说|介绍|举例|说明", text)
    ):
        return None
    asked = {a["question"]["question"] for a in answers}
    remaining = next((q for q in planned if q["question"] not in asked), None)
    return {
        **payload,
        "action": "next_topic",
        "method_entry_ids": [],
        "question": remaining["question"] if remaining else "您还有什么需要补充的经历或岗位问题？",
        "dimension_id": remaining["dimension_id"]
        if remaining
        else answers[-1]["question"]["dimension_id"],
        "answer_evidence_ids": [answers[-1]["id"]],
        "reason": "模型仅作确认，程序转向未问的准备问题或开放补充，原有证据缺口继续保留。",
    }


def answered_outline_ids(answers, planned):
    return {
        q["id"]
        for q in planned
        for answer in answers
        if q.get("id")
        and q.get("dimension_id")
        and (
            answer["question"].get("id") == q["id"]
            or (
                answer["question"].get("dimension_id") == q["dimension_id"]
                and answer["question"]["question"].endswith(q["question"])
            )
        )
    }


def prefer_unasked_dimension(payload, answers, planned):
    covered = {a["question"].get("dimension_id") for a in answers}
    if payload.get("action") != "next_topic" or payload.get("dimension_id") not in covered:
        return None
    remaining = next((q for q in planned if q["dimension_id"] not in covered), None)
    if remaining is None:
        return None
    return {
        **payload,
        "question": remaining["question"],
        "dimension_id": remaining["dimension_id"],
        "method_entry_ids": [],
        "reason": "转向提纲尚未问到的能力维度，已问维度的证据缺口仍保留。",
    }


def termination_reason(
    answer: str,
    round_count: int,
    elapsed_seconds: float,
    *,
    max_rounds: int = 12,
    max_seconds: int = 1200,
):
    clauses = re.split(r"[，。！？,!?;；\n]", answer.lower())
    stop_request = re.compile(
        r"^(?:请|麻烦|我想|我要|我希望|我要求|我现在要|现在|立即|马上|先|我们|可以|能否|能不能|请你|请您)*"
        r"(?:停止|结束|挂断)(?:这次|本次|这场|当前|这个)?"
        r"(?:面试|访谈|通话|电话|对话|聊天)?(?:吧|了|一下|好吗|可以吗|啊|呀|吗|呢)?$"
    )
    if any(
        stop_request.fullmatch(clause.strip())
        or clause.strip()
        in {
            "不聊了",
            "我不想继续了",
            "不面了",
            "我不面了",
            "我不想面试了",
            "就到这里吧",
            "今天就到这里吧",
            "面试到此为止",
            "我先挂了",
            "先挂了",
            "stop interview",
            "please stop interview",
            "end the interview",
            "stop the interview",
        }
        for clause in clauses
    ):
        return "candidate_requested_stop"
    if round_count >= max_rounds:
        return "round_limit"
    if elapsed_seconds >= max_seconds:
        return "duration_limit"
    return None


def closing_acknowledged(question: str, answer: str) -> bool:
    """Recognize a narrow answer to an explicit invitation for final additions."""
    if not any(
        marker in question for marker in ("想补充", "需要补充", "还有什么问题", "还有其他问题")
    ):
        return False
    return no_final_additions(answer)


def no_final_additions(answer: str) -> bool:
    normalized = re.sub(r"[\s，。！？,!?.；;]+", "", answer)
    return bool(
        re.fullmatch(
            r"(?:没有(?:了|补充|问题)?|没(?:了|有了|什么补充)|不用(?:了)?)(?:谢谢(?:你|您)?)?",
            normalized,
        )
    )


def validate_decision(
    decision: InterviewDecision,
    methods: list[dict],
    answers: list[dict],
    prior_questions: list[str],
    dimension_ids: set[str],
):
    if not answers or answers[-1]["id"] not in decision.answer_evidence_ids:
        raise ValueError("Latest answer evidence required")
    if not set(decision.method_entry_ids).issubset({item["entry_id"] for item in methods}):
        raise ValueError("Unknown method citation")
    if not set(decision.answer_evidence_ids).issubset({item["id"] for item in answers}):
        raise ValueError("Unknown answer evidence")
    if decision.action != "end":
        if not decision.question or not decision.question.strip():
            raise ValueError("Question required")
        if decision.dimension_id not in dimension_ids:
            raise ValueError("Unknown dimension")
        normalized = "".join(decision.question.split()).rstrip("?？。")
        if normalized in {"".join(q.split()).rstrip("?？。") for q in prior_questions}:
            raise ValueError("Repeated question")
    return decision
