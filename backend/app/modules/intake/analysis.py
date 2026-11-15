"""Untrusted material is input data. Only the program applies the published predicates."""

import json
import re
import xml.etree.ElementTree as ET
from copy import deepcopy
from io import BytesIO
from zipfile import BadZipFile, ZipFile

import httpx
from json_repair import repair_json
from pypdf import PdfReader

from app.core.config import Settings
from app.core.errors import DomainError
from app.modules.intake.agent_prompts import system_prompt
from app.modules.intake.form_contracts import ScreeningAssessment
from app.modules.intake.schemas import (
    Fact,
    InterviewStandard,
    JobAnalysis,
    ResumeProfile,
    RuleContent,
    ScreeningStandard,
)

ALIASES = {
    "姓名": "name",
    "学历": "education",
    "工作年限": "years_experience",
    "经验年限": "years_experience",
    "技能": "skills",
    "薪资": "salary",
    "地点": "location",
    "试用期目标": "probation_goals",
}


def job_material(job):
    fields = "\n".join(
        f"{key}: {value}" for key, value in job.material_fields.items() if value is not None
    )
    return job.material_text + ("\n\n系统明确提供的岗位字段：\n" + fields if fields else "")


def extract_mock(text: str) -> ResumeProfile:
    """A deliberately narrow, labelled demo parser; never a real model claim."""
    facts: dict[str, Fact] = {}
    for line in text.splitlines():
        match = re.fullmatch(
            r"\s*([a-z][a-z0-9_]*|姓名|学历|工作年限|经验年限|技能|薪资|地点|试用期目标)\s*[:：]\s*(.+)",
            line,
        )
        if not match:
            continue
        key, value = match.groups()
        key = ALIASES.get(key, key)
        parsed = float(value) if re.fullmatch(r"\d+(?:\.\d+)?", value) else value
        if key in facts and facts[key].value != parsed:
            facts[key] = Fact(value=None, quote=None, status="conflict")
        else:
            facts[key] = Fact(value=parsed, quote=line.strip(), status="stated")
    return ResumeProfile(facts=facts)


def validate_quotes(profile: ResumeProfile | JobAnalysis, text: str):
    def validate_fact(fact):
        from app.modules.intake.form_sources import source_quote

        fact.quote = source_quote(text, fact.quote)
        if (
            fact.status != "stated"
            or fact.value is None
            or not fact.quote
            or fact.quote not in text
        ):
            return Fact(
                value=None,
                quote=None,
                status=("conflict" if fact.status == "conflict" else "unknown"),
            )
        # A value must occur in its cited source; citations cannot merely be plausible text.
        value = str(fact.value)
        if isinstance(fact.value, float) and fact.value.is_integer():
            value = str(int(fact.value))
        supported = value.casefold() in fact.quote.casefold()
        if isinstance(fact.value, float):
            number = re.escape(value) + (r"(?:\.0+)?" if fact.value.is_integer() else "")
            supported = bool(re.search(r"(?<![\d.])" + number + r"(?![\d.])", fact.quote))
        if not supported:
            return Fact(value=None, quote=None, status="unknown")
        return fact

    profile.facts = {key: validate_fact(fact) for key, fact in profile.facts.items()}
    from app.modules.intake.form_sources import check_form_sources

    form = getattr(profile, "resume_form", None) or getattr(profile, "job_form", None)
    if form:
        check_form_sources(form, text)
    if isinstance(profile, ResumeProfile):
        for item in profile.research_objects:
            item.name = validate_fact(item.name)
            if item.period:
                item.period = validate_fact(item.period)
            item.facts = {key: validate_fact(fact) for key, fact in item.facts.items()}
    if isinstance(profile, ResumeProfile):
        by_direction = {}
        for item in profile.direction_assignments:
            if item.quote in text and "[[UNREADABLE_" not in item.quote:
                by_direction.setdefault(item.direction_id, item)
        profile.direction_assignments = list(by_direction.values())
    profile.unknown_fields = sorted(
        set(profile.unknown_fields)
        | {key for key, fact in profile.facts.items() if fact.status != "stated"}
    )
    return profile


def parse_file(name: str, media_type: str, data: bytes, settings: Settings) -> str:
    if not data or len(data) > settings.file_byte_limit:
        raise DomainError("PAYLOAD_TOO_LARGE", "材料为空或超过大小限制", 413)
    suffix = name.rsplit(".", 1)[-1].casefold()
    if suffix == "txt" and media_type in {"text/plain", "application/octet-stream"}:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DomainError("VALIDATION_ERROR", "TXT 必须为 UTF-8 编码", 422) from exc
        if "\x00" in text:
            raise DomainError("UNSUPPORTED_FILE_TYPE", "不是文本文件", 415)
    elif suffix == "pdf" and media_type in {"application/pdf", "application/octet-stream"}:
        if not data.startswith(b"%PDF-"):
            raise DomainError("UNSUPPORTED_FILE_TYPE", "PDF 文件签名无效", 415)
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted or len(reader.pages) > 20:
                raise DomainError("PDF_TEXT_UNAVAILABLE", "不支持加密或超过 20 页的 PDF", 422)
            parts = []
            for number, page in enumerate(reader.pages, 1):
                contents = page.get_contents()
                if contents and len(contents.get_data()) > 10_000_000:
                    raise DomainError("PAYLOAD_TOO_LARGE", "PDF 页面解压内容过大", 413)
                extracted = page.extract_text() or ""
                parts.append(
                    f"[[PAGE:{number}]]\n" + extracted
                    if extracted.strip()
                    else f"[[UNREADABLE_PAGE:{number}]]"
                )
            text = "\n".join(parts)
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError("PDF_TEXT_UNAVAILABLE", "PDF 无法提取文本", 422) from exc
        if all(part.startswith("[[UNREADABLE_PAGE:") for part in parts):
            raise DomainError("PDF_TEXT_UNAVAILABLE", "未提取到文本，暂不支持扫描 PDF OCR", 422)
    elif suffix == "doc" and media_type in {"application/msword", "application/octet-stream"}:
        from app.modules.intake.legacy_word import extract_legacy_word

        text = extract_legacy_word(data)
    elif suffix == "docx" and media_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    }:
        try:
            with ZipFile(BytesIO(data)) as archive:
                if sum(info.file_size for info in archive.infolist()) > 20_000_000:
                    raise DomainError("PAYLOAD_TOO_LARGE", "Word 解压内容过大", 413)
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                parts = ["word/document.xml"] + sorted(
                    name
                    for name in archive.namelist()
                    if re.fullmatch(r"word/(?:header\d+|footer\d+|footnotes|endnotes)\.xml", name)
                )
                paragraphs, unsupported = [], False
                for part in parts:
                    xml = archive.read(part)
                    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                        raise ValueError("Unsupported XML")
                    root = ET.fromstring(xml)
                    unsupported |= root.find(".//w:altChunk", ns) is not None
                    for paragraph in root.findall(".//w:p", ns):
                        paragraphs.append(
                            "".join(
                                element.text or ""
                                if element.tag == "{" + ns["w"] + "}t"
                                else "\t"
                                if element.tag == "{" + ns["w"] + "}tab"
                                else "\n"
                                if element.tag in {"{" + ns["w"] + "}br", "{" + ns["w"] + "}cr"}
                                else ""
                                for element in paragraph.iter()
                            )
                        )
                text = "\n".join(p for p in paragraphs if p.strip())
                if unsupported or any(
                    n.startswith(("word/media/", "word/embeddings/")) for n in archive.namelist()
                ):
                    text += "\n[[UNREADABLE_EMBEDDED_CONTENT]]"
                if not any(p.strip() for p in paragraphs):
                    raise ValueError("No readable text")
        except DomainError:
            raise
        except (
            BadZipFile,
            KeyError,
            ET.ParseError,
            ValueError,
            RuntimeError,
            NotImplementedError,
            OSError,
        ) as exc:
            raise DomainError(
                "DOCUMENT_TEXT_UNAVAILABLE", "Word 无法可靠提取文本，请提供文本版材料", 422
            ) from exc
    else:
        raise DomainError(
            "UNSUPPORTED_FILE_TYPE",
            "支持 DOC/DOCX、文本 PDF 和 UTF-8 TXT；扫描图片需转换为文本",
            415,
        )
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text or len(text) > settings.text_char_limit:
        raise DomainError("PAYLOAD_TOO_LARGE", "材料为空或文本长度超过限制", 413)
    return text


def model_ready(settings: Settings):
    if not (settings.model_endpoint and settings.model_name and settings.model_api_key):
        raise DomainError("DEPENDENCY_NOT_READY", "尚未配置模型接口", 503)
    if not settings.model_endpoint.startswith("https://"):
        raise DomainError("DEPENDENCY_NOT_READY", "模型接口需要 HTTPS", 503)


def model_messages(kind: str, text: str, *, strict_json: bool = False) -> list[dict]:
    kind = "resume_parse" if kind == "talent_parse" else kind
    schema = {
        "job_analysis": JobAnalysis,
        "resume_parse": ResumeProfile,
        "interview_standard": InterviewStandard,
        "screening_standard": ScreeningStandard,
        "screening": ScreeningAssessment,
    }[kind]
    return [
        {
            "role": "system",
            "content": system_prompt(kind, schema)
            + (
                "\n上一轮返回结构无效。本轮只返回一个符合给定Schema的JSON对象，检查全部闭合括号、引号和分隔符。"
                "提取类任务的facts可为{}、research_objects可为[]，完整表单不得缺模块或字段；未知SourceFact用{}。"
                "引用必须是原始材料的连续原话；不编造数值或出处，不输出解释或Markdown。"
                if strict_json
                else ""
            ),
        },
        {"role": "user", "content": json.dumps({"untrusted_material": text}, ensure_ascii=False)},
    ]


def normalize_extraction_output(data: dict) -> dict:
    """Only downgrade unsupported facts; never repair a missing business value."""
    result = deepcopy(data)

    def normalize(fact, *, summary=False):
        if not isinstance(fact, dict):
            return
        if summary:
            # Legacy summaries have no note field; full forms retain their notes.
            fact.pop("note", None)
        status = fact.get("status")
        if status in {"unknown", "conflict"}:
            if not summary and fact.get("value") is not None and not fact.get("note"):
                fact["note"] = "模型标记此项未知或冲突，不能作为已确认事实"
            fact["value"], fact["quote"] = None, None
        elif status == "stated" and (fact.get("value") is None or not fact.get("quote")):
            fact.update(value=None, quote=None, status="unknown")
            if not summary:
                fact["note"] = "缺少完整原文支持，需核实"

    for fact in result.get("facts", {}).values():
        normalize(fact, summary=True)
    form = result.get("job_form") or result.get("resume_form")
    if isinstance(form, dict):
        if result.get("resume_form"):
            from app.modules.intake.form_contracts import RESUME_FIELDS

            # Research objects are derived from the checked form, never this redundant hint.
            form.pop("research_objects", None)
            sections = form.get("sections")
            if isinstance(sections, dict):
                for section in RESUME_FIELDS:
                    if section in form and section not in sections:
                        sections[section] = form.pop(section)
            if isinstance(result.get("limitations"), list):
                form["limitations"] = [*form.get("limitations", []), *result.pop("limitations")]
        for fact in form.get("fields", {}).values():
            normalize(fact)
        for statements in form.get("jd", {}).values():
            for fact in statements:
                normalize(fact)
        for records in form.get("sections", {}).values():
            for record in records:
                for fact in record.get("fields", {}).values():
                    normalize(fact)
    return result


def _json_values(content: str) -> list:
    """Keep every key, scalar and colon; only container/separator repairs are permitted."""
    pattern = re.compile(
        r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
        r"|true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|:|[{}\[\],]|\s+"
    )
    values, position = [], 0
    for match in pattern.finditer(content):
        if match.start() != position:
            raise ValueError("Invalid or incomplete JSON value")
        position = match.end()
        token = match.group()
        if token.isspace() or token in "{}[],":
            continue
        values.append(("string", json.loads(token)) if token.startswith('"') else token)
    if position != len(content):
        raise ValueError("Invalid or incomplete JSON value")
    return values


def _reject_nonfinite(value):
    raise ValueError("Non-finite JSON number")


def _json_object(content: str) -> dict:
    try:
        data = json.loads(content, parse_constant=_reject_nonfinite)
    except json.JSONDecodeError:
        # A compatible provider may omit braces or separators despite finish_reason=stop.
        # Reject all changes to keys/values and all incomplete values before schema checking.
        if not content or content[-1] in ":,":
            raise
        original = _json_values(content)
        repaired = repair_json(content, ensure_ascii=False, skip_json_loads=True)
        if not isinstance(repaired, str) or _json_values(repaired) != original:
            raise ValueError("JSON repair would change content") from None
        data = json.loads(repaired, parse_constant=_reject_nonfinite)
    if not isinstance(data, dict):
        raise ValueError("Expected an object")
    return data


class ModelOutputError(ValueError):
    """A confirmed response whose output is unusable, rather than an unknown call."""

    def __init__(self, code: str, tokens: int, payload=None):
        super().__init__(code)
        self.code = code
        self.tokens = tokens
        self.payload = payload


def parse_model_payload(payload: dict) -> tuple[dict, int]:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    total = usage.get("total_tokens", 0) if isinstance(usage, dict) else 0
    tokens = total if isinstance(total, int) and not isinstance(total, bool) and total > 0 else 0
    try:
        choice = payload["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ModelOutputError("MODEL_OUTPUT_TRUNCATED", tokens, payload)
        if choice.get("finish_reason") not in {None, "stop"}:
            raise ModelOutputError("MODEL_OUTPUT_INVALID", tokens, payload)
        content = choice["message"]["content"].strip()
        fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", content, flags=re.DOTALL)
        data = _json_object(fenced.group(1).strip() if fenced else content)
    except ModelOutputError:
        raise
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError) as exc:
        raise ModelOutputError("MODEL_OUTPUT_INVALID", tokens, payload) from exc
    return data, tokens


def invoke_model(
    settings: Settings, kind: str, text: str, request_id: str, *, strict_json: bool = False
) -> tuple[dict, int]:
    model_ready(settings)
    body = {
        "model": settings.model_name,
        "messages": model_messages(kind, text, strict_json=strict_json),
        "response_format": {"type": "json_object"},
        "max_tokens": settings.model_max_output_tokens,
        "temperature": 0,
    }
    thinking = settings.model_thinking
    if thinking is None and settings.model_name.casefold().startswith("deepseek"):
        thinking = "disabled"
    if thinking is not None:
        body["thinking"] = {"type": thinking}
    with httpx.Client(
        timeout=httpx.Timeout(settings.model_timeout_seconds), follow_redirects=False
    ) as client:
        with client.stream(
            "POST",
            settings.model_endpoint,
            headers={
                "Authorization": "Bearer " + settings.model_api_key.get_secret_value(),
                "Idempotency-Key": request_id,
            },
            json=body,
        ) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 1_000_000:
                    raise ValueError("Model response too large")
                chunks.append(chunk)
            payload = json.loads(b"".join(chunks))
        return parse_model_payload(payload)


def mock_analysis(kind: str, text: str) -> dict:
    from app.modules.intake.form_sources import empty_job_form, empty_resume_form

    if kind == "interview_standard":
        return {"dimensions": [], "gaps": ["模拟模式不制定真实面试标准，请人工补充"]}
    if kind == "screening_standard":
        return {"rubric": None, "gaps": ["模拟模式不制定真实评分标准，请人工补充"]}
    if kind == "screening":
        from app.modules.intake.form_contracts import DIMENSIONS, PORTRAIT_FIELDS

        return {
            "portrait": {key: "模拟模式未评估，需人工核实" for key in PORTRAIT_FIELDS},
            "scores": [
                {"dimension_id": key, "score": None, "reason": "模拟执行未进行真实模型证据分析"}
                for key in DIMENSIONS
            ],
            "proposed_result": "manual_review",
            "reasons": ["当前为隔离模拟执行", "未进行真实模型分析", "需要人工核实核心证据"],
            "core_evidence_sufficient": False,
        }
    profile = extract_mock(text)
    if kind == "job_analysis":
        for key in ("salary", "probation_goals"):
            if key not in profile.facts:
                profile.facts[key] = Fact(value=None, status="unknown")
        return JobAnalysis(
            **profile.model_dump(
                exclude={"research_objects", "resume_form", "direction_assignments"}
            ),
            rules=RuleContent(),
            job_form=empty_job_form(),
        ).model_dump(mode="json")
    from app.modules.intake.directions import DirectionAssignment, title_directions

    # Explicitly simulated, narrow title classifier; never a fallback for live model errors.
    for line in text.splitlines():
        if line.startswith(("职能：", "职位：", "current_role:", "擅长方向：")):
            profile.direction_assignments.extend(
                DirectionAssignment(
                    direction_id=key,
                    level="primary",
                    quote=line,
                    reason="模拟模式仅按显式职能名称归类",
                )
                for key in title_directions(line)
            )
    profile.resume_form = empty_resume_form()
    return profile.model_dump(mode="json")
