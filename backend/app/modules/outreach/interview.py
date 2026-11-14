"""Validated interview decisions and program-controlled termination."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InterviewQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    dimension_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=1000)
    method_entry_ids: list[str] = Field(min_length=1, max_length=8)
    evidence_target: str = Field(min_length=1, max_length=1000)


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
        or clause.strip() in {"不聊了", "我不想继续了", "stop interview", "please stop interview"}
        for clause in clauses
    ):
        return "candidate_requested_stop"
    if round_count >= max_rounds:
        return "round_limit"
    if elapsed_seconds >= max_seconds:
        return "duration_limit"
    return None


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
