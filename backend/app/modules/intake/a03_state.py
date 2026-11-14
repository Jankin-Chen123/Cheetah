"""Deterministic A03 evidence validation around Pi's autonomous investigation decisions."""

import copy
import hashlib
import json
import re

from app.core.errors import DomainError
from app.modules.intake.a03_contracts import FIELDS, Identity, ObjectFindings, ReportFinding

UNSAFE_QUERY = re.compile(
    r"[\w.+-]+@[\w.-]+|(?<!\d)\d{7,}(?!\d)|(?:\+?\d[\s()-]*){9,}|身份证|手机号|电话号码"
)
RECOMMENDATION = re.compile(r"建议录用|建议淘汰|应淘汰|候选人能力很强|总分[：:]|匹配分[：:]")


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def research_objects(d03: dict) -> list[dict]:
    objects = copy.deepcopy(d03.get("research_objects", []))
    if objects:
        return objects
    # Explicit legacy input path, not an assertion that a full resume was extracted.
    for kind, keys in (("company", ("employer", "company")), ("project", ("project",))):
        fact = next((d03["facts"][key] for key in keys if key in d03["facts"]), None)
        if fact:
            period = "employment_period" if kind == "company" else "project_period"
            objects.append(
                {
                    "object_id": "legacy_" + kind,
                    "kind": kind,
                    "name": fact,
                    "period": d03["facts"].get(period),
                    "parent_object_id": None,
                    "facts": {},
                }
            )
    return objects


def get_object(state: dict, object_id: str) -> dict:
    item = next((item for item in state["objects"] if item["object_id"] == object_id), None)
    if item is None:
        raise DomainError("VALIDATION_ERROR", "研究对象不属于本次 D03", 422)
    return item


def validate_goal(state: dict, goal):
    item = get_object(state, goal.object_id)
    if goal.field not in FIELDS[item["kind"]]:
        raise DomainError("VALIDATION_ERROR", "研究目标字段不属于该对象类型", 422)
    if RECOMMENDATION.search(goal.question):
        raise DomainError("VALIDATION_ERROR", "A03 不能设定录用或评分目标", 422)


def validate_search(state: dict, args):
    item = get_object(state, args.object_id)
    fact = item["name"]
    if fact["status"] != "stated" or not isinstance(fact["value"], str):
        raise DomainError("PRECONDITION_NOT_MET", "主体名称未明确，不允许搜索")
    if fact["value"].casefold() not in args.query.casefold():
        raise DomainError("VALIDATION_ERROR", "搜索词必须包含 A04 的原始对象名称", 422)
    # Public record identifiers may contain long numbers, but contact data may not leave the host.
    safe_query = args.query
    for key in ("identifier", "doi", "registration_number"):
        identifier = item["facts"].get(key, {})
        if identifier.get("status") == "stated" and identifier.get("value"):
            safe_query = safe_query.replace(str(identifier["value"]), "PUBLIC_RECORD_ID")
    if UNSAFE_QUERY.search(safe_query):
        raise DomainError("VALIDATION_ERROR", "搜索词包含无关个人信息或未授权标识", 422)
    person_name = state.get("private_name")
    if person_name and person_name in args.query and person_name not in str(fact["value"]):
        raise DomainError("VALIDATION_ERROR", "默认不向搜索工具发送候选人姓名", 422)
    if not any(goal["object_id"] == args.object_id for goal in state.get("goals", [])):
        raise DomainError("PRECONDITION_NOT_MET", "请先为该对象设定研究目标")


def citation_text(state: dict, object_id: str, citation) -> tuple[dict | None, str | None]:
    source = state["sources"].get(citation.source_id)
    if source is None or source["object_id"] != object_id:
        return None, "引用来源不存在或不属于该对象"
    if source["kind"] != "page":
        return None, "搜索摘要不是已读取的原始来源"
    if citation.quote not in source["text"]:
        return None, "引文不在实际读取内容中"
    if citation.source_date and (
        re.fullmatch(
            r"(?:19|20)\d{2}(?:[-年/.]\d{1,2})?(?:[-月/.]\d{1,2}日?)?", citation.source_date
        )
        is None
        or citation.source_date not in source["text"]
    ):
        return None, "资料时间没有正文依据"
    return source, None


def checked_findings(state: dict, args: ObjectFindings) -> dict:
    item = get_object(state, args.object_id)
    if any(f.field not in FIELDS[item["kind"]] for f in args.findings):
        raise DomainError("VALIDATION_ERROR", "报告字段不属于该对象类型", 422)
    texts = [f.text for f in args.findings] + args.gaps + args.verification_questions
    if any(RECOMMENDATION.search(text) for text in texts):
        raise DomainError("VALIDATION_ERROR", "A03 不能输出评分或录用建议", 422)
    identity = args.identity.model_copy(deep=True)
    identity_quotes, identity_valid, valid_identity_citations = [], bool(identity.citations), []
    for citation in identity.citations:
        _, error = citation_text(state, args.object_id, citation)
        if error:
            identity_valid = False
        else:
            identity_quotes.append(citation.quote)
            valid_identity_citations.append(citation)
    identity.citations = valid_identity_citations
    identity_text = "\n".join(identity_quotes).casefold()
    name = str(item["name"].get("value") or "")
    anchor_values = [
        str(item["facts"][key]["value"])
        for key in identity.a04_anchor_fields
        if key in item["facts"]
        and item["facts"][key]["status"] == "stated"
        and item["facts"][key].get("value") is not None
        and key not in {"role", "contribution", "metrics", "authors", "ownership"}
    ]
    if identity.status == "confirmed" and not (
        identity_valid
        and name
        and name.casefold() in identity_text
        and any(value.casefold() in identity_text for value in anchor_values)
    ):
        identity.status = "uncertain"
        identity.rationale += "；程序校验：缺少名称及非名称身份线索的正文依据"
    findings = []
    for finding in args.findings:
        checked = ReportFinding(**finding.model_dump())
        valid_citations = []
        for citation in finding.citations:
            _, error = citation_text(state, args.object_id, citation)
            if error:
                checked.validation_notes.append(error)
            else:
                valid_citations.append(citation)
        checked.citations = valid_citations
        if finding.category == "E1":
            if not any(finding.text in citation.quote for citation in valid_citations):
                checked.validation_notes.append("E1 必须直接摘录来源；解释性改写应使用 E3")
            if identity.status != "confirmed":
                checked.validation_notes.append("主体身份尚未确认")
            if not valid_citations or any(c.source_date is None for c in valid_citations):
                checked.validation_notes.append("公开事实缺少正文引文或资料时间")
            if finding.field in {"contribution", "ownership"}:
                personal_text = "\n".join(c.quote for c in valid_citations).casefold()
                identifiers = [
                    str(item["facts"][key]["value"])
                    for key in finding.personal_identity_fields
                    if key
                    in {
                        "author_identifier",
                        "orcid",
                        "contributor_handle",
                        "certificate_number",
                        "author_url",
                    }
                    and item["facts"].get(key, {}).get("status") == "stated"
                    and item["facts"][key].get("value") is not None
                ]
                person = str(state.get("private_name") or "")
                if not (
                    person
                    and person.casefold() in personal_text
                    and any(identifier.casefold() in personal_text for identifier in identifiers)
                ):
                    checked.validation_notes.append(
                        "个人归属缺少姓名及已提供的独立身份标识，不能由组织资料推断"
                    )
            if finding.field == "competitiveness":
                checked.validation_notes.append("竞争力评价属于解释，不能自动认定为客观事实")
            if finding.historical_applicability == "confirmed":
                period = item.get("period") or {}
                if not period.get("value") or finding.applicable_period != str(period["value"]):
                    checked.validation_notes.append("历史适用期间与 A04 不匹配")
                elif not any(str(period["value"]) in c.quote for c in valid_citations):
                    checked.validation_notes.append("引用没有覆盖任职或成果期间")
        if finding.conflict_with_a04:
            checked.validation_notes.append("与 A04 自述冲突，保留双方并待核实")
        if finding.category == "E3":
            if any(key not in item["facts"] for key in finding.a04_fields):
                checked.validation_notes.append("分析引用了不存在的 A04 字段")
            if not valid_citations and not any(
                item["facts"].get(key, {}).get("status") == "stated" for key in finding.a04_fields
            ):
                checked.validation_notes.append("解释性分析缺少依据")
        if checked.validation_notes:
            checked.category = "U"
        findings.append(checked.model_dump(mode="json"))
    result = args.model_dump(mode="json")
    result["identity"] = identity.model_dump(mode="json")
    result["findings"] = findings
    return result


def unknown_identity(reason: str) -> dict:
    return Identity(status="uncertain", rationale=reason).model_dump(mode="json")
