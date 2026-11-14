"""Host for a real Pi agent subprocess, with scoped tools and durable effect receipts."""

import copy
import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.artifacts import artifact_ref, latest, save_artifact
from app.core.errors import DomainError
from app.core.models import (
    Artifact,
    Budget,
    Evidence,
    ResearchAction,
    ResearchRun,
    RulePack,
    Task,
    aware,
    utcnow,
)
from app.core.tasks import fence, resume_known_response
from app.integrations.a03_model import invoke_research_model
from app.integrations.search import allowed_domains, get_search_adapter, public_source_url
from app.modules.intake.a03_contracts import FIELDS, TOOL_MODELS
from app.modules.intake.a03_report import build_report
from app.modules.intake.a03_state import (
    RECOMMENDATION,
    checked_findings,
    fingerprint,
    get_object,
    research_objects,
    validate_goal,
    validate_search,
)
from app.modules.intake.content import usage
from app.modules.intake.service import queue_step

AGENT_DIR = Path(__file__).resolve().parents[3] / "agents" / "a03"
RESOURCE_DIR = AGENT_DIR / "resources"
TOOL_DESCRIPTIONS = {
    "load_skill": "加载本任务允许的专业 skill，只接受枚举名称。",
    "set_research_plan": "设定或更新研究目标、字段、优先级和理由；必须先于搜索。",
    "search_public_sources": "围绕一个 A04 对象搜索允许的公开来源，摘要只是线索。",
    "read_public_source": "读取该对象搜索工具已返回的来源正文；source_id 不能自造。",
    "record_object_findings": "提交一个对象的累计发现，程序检查身份、引文、时间和归属。",
    "finish_research": "提交结束意图；程序按 D04 范本生成所有对象的报告与未知项。",
}


def resources() -> tuple[str, dict[str, str], str]:
    skills = {
        name: (RESOURCE_DIR / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        for name in (
            "company-research",
            "professional-achievements",
            "evidence-quality",
            "report-handoff",
        )
    }
    system = (RESOURCE_DIR / "system-v1.md").read_text(encoding="utf-8")
    source = (RESOURCE_DIR / "a03-source-v1.md").read_text(encoding="utf-8")
    digest = fingerprint(
        {
            "system": system,
            "source": source,
            "skills": skills,
            "runner": (AGENT_DIR / "src" / "runner.ts").read_text(encoding="utf-8"),
            "package_lock": (AGENT_DIR / "package-lock.json").read_text(encoding="utf-8"),
        }
    )
    # Mandatory evidence policy is present even if the model forgets its explicit skill call.
    return system + "\n\n" + source + "\n\n" + skills["evidence-quality"], skills, digest


class ResearchHost:
    def __init__(self, settings, engine, task_id, token, context):
        self.settings, self.engine, self.task_id, self.token, self.context = (
            settings,
            engine,
            task_id,
            token,
            context,
        )
        self.started = time.monotonic()
        self.system, self.skills, self.resource_hash = resources()
        self.domains = allowed_domains(settings)
        self.web_source = "live"

    def locked(self, db):
        task = db.get(Task, self.task_id)
        job, application = self.context(db, task)
        task = fence(db, self.task_id, self.token)
        task.lease_until = utcnow() + timedelta(seconds=self.settings.task_lease_seconds)
        return task, job, application

    def initialize(self):
        settings = self.settings
        config = {
            "resource_hash": self.resource_hash,
            "web_backend": settings.a03_web_backend,
            "provider": settings.search_provider,
            "endpoint": settings.search_endpoint,
            "fetch_endpoint": settings.a03_fetch_endpoint,
            "model_endpoint": settings.model_endpoint,
            "model_name": settings.model_name,
            "plugin_provider": settings.a03_plugin_provider,
            "domains": self.domains,
            "turns": settings.a03_max_turns,
            "searches": settings.a03_max_searches,
            "pages": settings.a03_max_pages,
            "per_object": settings.a03_per_object_searches,
            "seconds": settings.a03_max_seconds,
        }
        with Session(self.engine) as db, db.begin():
            task, job, application = self.locked(db)
            d03 = latest(db, job.id, "D03", application.id)
            if d03 is None:
                raise DomainError("PRECONDITION_NOT_MET", "缺少有效 D03")
            run = db.get(ResearchRun, task.id)
            config_hash = fingerprint(config)
            if run and run.configuration_hash != config_hash:
                raise DomainError("PRECONDITION_NOT_MET", "研究配置或专业资源版本已变化")
            if run is None:
                objects = research_objects(d03.content)
                private_name = d03.content["facts"].get("name", {}).get("value")
                run = ResearchRun(
                    task_id=task.id,
                    configuration_hash=config_hash,
                    state={
                        "objects": objects,
                        "goals": [],
                        "sources": {},
                        "records": {},
                        "loaded_skills": [],
                        "private_name": private_name,
                        "d03_ref": artifact_ref(d03),
                        "resource_hash": self.resource_hash,
                        "input_completeness": "structured_objects"
                        if d03.content.get("research_objects")
                        else "legacy_fields",
                        "no_progress": 0,
                        "runtime_started": False,
                    },
                )
                db.add(run)
                db.flush()
            if run.state["d03_ref"] != artifact_ref(d03):
                raise DomainError("PRECONDITION_NOT_MET", "研究绑定的 D03 已改变")
            self.started = time.monotonic() - (utcnow() - aware(run.created_at)).total_seconds()
            mock = "mock" in [d03.source_mode, *d03.inherited_source_modes]
            if settings.a03_web_backend == "normalized":
                adapter = get_search_adapter(settings)
                self.web_source = adapter.source_mode if adapter else "live"
            if mock and self.web_source == "live":
                run.state = {**run.state, "stop_reason": "mock_input_not_sent_to_live_research"}
            elif not run.state["objects"]:
                run.state = {**run.state, "stop_reason": "no_declared_objects"}
            elif settings.a03_web_backend == "disabled" or not self.domains:
                run.state = {**run.state, "stop_reason": "research_provider_unavailable"}
            elif (
                not settings.model_endpoint or not settings.model_name or not settings.model_api_key
            ):
                raise DomainError("DEPENDENCY_NOT_READY", "A03 需要配置支持工具调用的模型接口", 503)
            if (
                not run.state.get("stop_reason")
                and settings.a03_web_backend == "pi_web_access"
                and not settings.a03_plugin_api_key
            ):
                raise DomainError("DEPENDENCY_NOT_READY", "所选搜索插件需要服务端凭据", 503)
            rule = db.get(RulePack, (job.id, application.rule_version))
            d01 = db.get(
                Artifact,
                (rule.d01_ref["artifact_id"], rule.d01_ref["version"]),
            )
            public_input = {
                "objects": run.state["objects"],
                "candidate_id": application.candidate_id,
                "application_id": application.id,
                "job_id": job.id,
                "d03_ref": artifact_ref(d03),
                "job_context": {"fields": d01.content.get("fields", [])} if d01 else {},
                "limits": {
                    k: config[k] for k in ("turns", "searches", "pages", "per_object", "seconds")
                },
                "research_fields": FIELDS,
            }
            return copy.deepcopy(run.state), copy.deepcopy(run.messages), public_input

    def action(self, db, action_id, kind, payload):
        task, _, _ = self.locked(db)
        existing = db.get(ResearchAction, (task.id, action_id))
        digest = fingerprint(payload)
        if existing:
            if existing.request_hash != digest:
                raise DomainError("PRECONDITION_NOT_MET", "原请求标识的内容已改变")
            if existing.status != "settled":
                raise DomainError("EXTERNAL_RESULT_UNKNOWN", "已有研究请求结果不明，禁止重复提交")
            return existing, True
        record = ResearchAction(
            task_id=task.id,
            action_id=action_id,
            kind=kind,
            request_hash=digest,
            request_payload=payload,
            status="submitted",
        )
        db.add(record)
        db.flush()
        return record, False

    def count(self, db, kind, object_id=None):
        records = list(
            db.scalars(
                select(ResearchAction).where(
                    ResearchAction.task_id == self.task_id,
                    ResearchAction.kind == kind,
                )
            )
        )
        return sum(
            1
            for record in records
            if object_id is None or record.request_payload.get("object_id") == object_id
        )

    def model(self, args):
        request = {"messages": args["messages"], "tools": args["tools"]}
        with Session(self.engine) as db, db.begin():
            self.locked(db)
            record, cached = self.action(db, args["call_id"], "model", request)
            if cached:
                return record.result_payload
            if self.count(db, "model") > self.settings.a03_max_turns:
                raise DomainError("A03_TURN_LIMIT", "研究模型轮数达到上限", 429)
            reservation = (
                len(json.dumps(request, ensure_ascii=False).encode())
                + self.settings.model_max_output_tokens
                + 1024
            )
            updated = db.execute(
                update(Budget)
                .where(
                    Budget.job_id == db.get(Task, self.task_id).job_id,
                    Budget.reserved + Budget.used < Budget.call_limit,
                    Budget.tokens_reserved + Budget.tokens_used + reservation <= Budget.token_limit,
                )
                .values(
                    reserved=Budget.reserved + 1,
                    tokens_reserved=Budget.tokens_reserved + reservation,
                )
            )
            if updated.rowcount != 1:
                raise DomainError("BUDGET_EXCEEDED", "研究模型预算不足", 429)
            record.reserved_tokens = reservation
            db.get(Task, self.task_id).external_state = "submitted"
        try:
            response, tokens = invoke_research_model(
                self.settings, request, f"{self.task_id}:{args['call_id']}"
            )
        except Exception:
            self.mark_unknown(args["call_id"])
            raise DomainError("EXTERNAL_RESULT_UNKNOWN", "模型请求结果待核对") from None
        with Session(self.engine) as db, db.begin():
            record = db.get(ResearchAction, (self.task_id, args["call_id"]))
            record.result_payload, record.status = response, "settled"
            record.actual_tokens = tokens or record.reserved_tokens
            task = db.get(Task, self.task_id)
            db.execute(
                update(Budget)
                .where(Budget.job_id == task.job_id)
                .values(
                    reserved=Budget.reserved - 1,
                    used=Budget.used + 1,
                    tokens_reserved=Budget.tokens_reserved - record.reserved_tokens,
                    tokens_used=Budget.tokens_used + record.actual_tokens,
                )
            )
            resume_known_response(task, self.settings)
        return response

    def mark_unknown(self, action_id):
        with Session(self.engine) as db, db.begin():
            record = db.get(ResearchAction, (self.task_id, action_id))
            if record and record.status == "submitted":
                record.status = "unknown"
            task = db.get(Task, self.task_id)
            if task.external_state == "submitted":
                task.external_state = "unknown"

    def dispatch(self, method, args):
        if time.monotonic() - self.started >= self.settings.a03_max_seconds:
            raise DomainError("A03_TIME_LIMIT", "研究时间达到上限", 429)
        if method == "model":
            return self.model(args)
        if method == "checkpoint":
            with Session(self.engine) as db, db.begin():
                self.locked(db)
                db.get(ResearchRun, self.task_id).messages = args["messages"]
            return {"saved": True}
        if method == "plugin_result":
            return self.finish_external(args["call_id"], args["result"])
        if method != "tool" or args.get("name") not in TOOL_MODELS:
            raise DomainError("VALIDATION_ERROR", "未知研究操作", 422)
        name = args["name"]
        try:
            parsed = TOOL_MODELS[name].model_validate(args["arguments"])
        except ValidationError:
            return {"error": "INVALID_TOOL_ARGUMENTS", "message": "请按工具 schema 修正参数"}
        if name in {"search_public_sources", "read_public_source"}:
            return self.external(args["call_id"], name, parsed)
        with Session(self.engine) as db, db.begin():
            self.locked(db)
            record, cached = self.action(db, args["call_id"], name, parsed.model_dump(mode="json"))
            if cached:
                return record.result_payload
            run = db.get(ResearchRun, self.task_id)
            state = copy.deepcopy(run.state)
            if name == "load_skill":
                state["loaded_skills"] = sorted(set(state["loaded_skills"]) | {parsed.name})
                result = {"name": parsed.name, "content": self.skills[parsed.name]}
            elif name == "set_research_plan":
                for goal in parsed.goals:
                    validate_goal(state, goal)
                state["goals"] = parsed.model_dump(mode="json")["goals"]
                result = {"goals": state["goals"]}
            elif name == "record_object_findings":
                checked = checked_findings(state, parsed)
                state["records"][parsed.object_id] = checked
                result = checked
            else:
                if RECOMMENDATION.search(parsed.summary):
                    raise DomainError("VALIDATION_ERROR", "A03 总结不能给录用建议", 422)
                if not state["goals"] and state["objects"]:
                    raise DomainError("PRECONDITION_NOT_MET", "尚未设定研究目标")
                state.update(stop_reason=parsed.reason, summary=parsed.summary, finished=True)
                result = {"finished": True}
            record.result_payload, record.status = result, "settled"
            run.state = state
            return result

    def external(self, call_id, name, parsed):
        kind = "search" if name == "search_public_sources" else "page"
        with Session(self.engine) as db:
            saved = db.get(ResearchAction, (self.task_id, call_id))
            if saved and saved.status == "settled" and "_raw" in saved.result_payload:
                requested = parsed.model_dump(mode="json")
                if kind == "page":
                    requested["url"] = saved.request_payload["url"]
                if saved.request_hash != fingerprint(requested):
                    raise DomainError("PRECONDITION_NOT_MET", "原请求标识的内容已改变")
                raw = saved.result_payload["_raw"]
            else:
                raw = None
        if raw is not None:
            return self.finish_external(call_id, raw)
        with Session(self.engine) as db, db.begin():
            task, _, _ = self.locked(db)
            run = db.get(ResearchRun, self.task_id)
            state = run.state
            # Cache lookup precedes budget checks; successful effects are never repeated on resume.
            record = db.get(ResearchAction, (self.task_id, call_id))
            payload = parsed.model_dump(mode="json")
            if kind == "page":
                source = state["sources"].get(parsed.source_id)
                if not source or source["object_id"] != parsed.object_id:
                    raise DomainError("VALIDATION_ERROR", "来源不属于该研究对象", 422)
                payload["url"] = source["url"]
            if record:
                record, _ = self.action(db, call_id, kind, payload)
                return record.result_payload
            get_object(state, parsed.object_id)
            limit = (
                self.settings.a03_max_searches if kind == "search" else self.settings.a03_max_pages
            )
            if self.count(db, kind) >= limit:
                raise DomainError("A03_RETRIEVAL_LIMIT", "研究检索次数达到上限", 429)
            if kind == "search":
                validate_search(state, parsed)
                if self.count(db, kind, parsed.object_id) >= self.settings.a03_per_object_searches:
                    return {
                        "error": "OBJECT_SEARCH_LIMIT",
                        "message": "该对象查询次数已达上限，请保留未知",
                    }
                if any(
                    r.request_payload.get("query") == parsed.query
                    for r in db.scalars(
                        select(ResearchAction).where(
                            ResearchAction.task_id == task.id, ResearchAction.kind == "search"
                        )
                    )
                ):
                    return {"error": "DUPLICATE_QUERY", "message": "不要重复已提交的查询"}
                updated = db.execute(
                    update(Budget)
                    .where(
                        Budget.job_id == task.job_id,
                        Budget.searches_reserved + Budget.searches_used < Budget.search_limit,
                    )
                    .values(searches_reserved=Budget.searches_reserved + 1)
                )
                if updated.rowcount != 1:
                    raise DomainError("BUDGET_EXCEEDED", "岗位研究检索预算不足", 429)
            else:
                source = state["sources"].get(parsed.source_id)
                if not source or source["object_id"] != parsed.object_id:
                    raise DomainError("VALIDATION_ERROR", "来源不属于该研究对象", 422)
                if source["kind"] == "page":
                    return {"source": source, "cached": True}
                if public_source_url(source["url"], self.domains) is None:
                    raise DomainError("PRECONDITION_NOT_MET", "来源地址不在允许范围")
                payload["url"] = source["url"]
            record, _ = self.action(db, call_id, kind, payload)
            task.external_state = "submitted"
        if self.settings.a03_web_backend == "pi_web_access":
            command = (
                {
                    "name": "web_search",
                    "arguments": {
                        "query": parsed.query,
                        "provider": self.settings.a03_plugin_provider,
                        "numResults": self.settings.search_result_limit,
                        "includeContent": False,
                        "domainFilter": self.domains,
                    },
                }
                if kind == "search"
                else {"name": "fetch_content", "arguments": {"url": payload["url"], "mode": "raw"}}
            )
            return {"plugin": command}
        try:
            if kind == "search":
                adapter = get_search_adapter(self.settings)
                if adapter is None:
                    raise DomainError("DEPENDENCY_NOT_READY", "搜索适配器未配置", 503)
                response = adapter.search(parsed.query, request_id=f"{self.task_id}:{call_id}")
                result = {"results": response.model_dump(mode="json")["results"]}
            else:
                result = self.read_normalized(payload["url"], call_id)
        except Exception:
            self.mark_unknown(call_id)
            raise DomainError("EXTERNAL_RESULT_UNKNOWN", "来源工具请求结果待核对") from None
        return self.finish_external(call_id, result)

    def read_normalized(self, url, call_id):
        endpoint = self.settings.a03_fetch_endpoint
        if not endpoint or urlsplit(endpoint).scheme != "https":
            raise DomainError("DEPENDENCY_NOT_READY", "来源读取适配端需要 HTTPS 配置", 503)
        headers = {"Idempotency-Key": f"{self.task_id}:{call_id}"}
        if self.settings.search_api_key:
            headers["Authorization"] = "Bearer " + self.settings.search_api_key.get_secret_value()
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            with client.stream(
                "POST",
                endpoint,
                json={"url": url, "allowed_domains": self.domains},
                headers=headers,
            ) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 1_000_000:
                        raise ValueError("Page response exceeded limit")
                    chunks.append(chunk)
        return json.loads(b"".join(chunks))

    def finish_external(self, call_id, raw):
        with Session(self.engine) as db, db.begin():
            # First save the known response and settle its budget even if the generation went stale.
            task = db.get(Task, self.task_id)
            record = db.get(ResearchAction, (self.task_id, call_id))
            if record is None or record.status not in {"submitted", "unknown", "settled"}:
                raise DomainError("PRECONDITION_NOT_MET", "研究外部请求记录状态不符")
            settling = record.status in {"submitted", "unknown"}
            if not settling and "_raw" not in record.result_payload:
                return record.result_payload
            record.result_payload, record.status = {"_raw": raw}, "settled"
            if settling and record.kind == "search":
                db.execute(
                    update(Budget)
                    .where(Budget.job_id == task.job_id)
                    .values(
                        searches_reserved=Budget.searches_reserved - 1,
                        searches_used=Budget.searches_used + 1,
                    )
                )
            resume_known_response(task, self.settings)
        with Session(self.engine) as db, db.begin():
            self.locked(db)
            record = db.get(ResearchAction, (self.task_id, call_id))
            run = db.get(ResearchRun, self.task_id)
            state = copy.deepcopy(run.state)
            payload, kind = record.request_payload, record.kind
            plugin_error = bool(raw.get("isError"))
            text = "\n".join(
                part.get("text", "")
                for part in raw.get("content", [])
                if part.get("type") == "text"
            )
            if kind == "search":
                hits = raw.get("results")
                if hits is None:
                    urls = list(dict.fromkeys(re.findall(r'https?://[^\s<>\[\]()"`]+', text)))
                    hits = [
                        {
                            "url": url.rstrip(".,;"),
                            "title": urlsplit(url).hostname or "公开来源",
                            "snippet": text[:6000],
                        }
                        for url in urls
                    ]
                added = []
                for hit in hits[: self.settings.search_result_limit]:
                    url = public_source_url(hit["url"], self.domains)
                    if not url:
                        continue
                    source_id = (
                        "src_" + fingerprint({"object": payload["object_id"], "url": url})[:20]
                    )
                    if source_id not in state["sources"]:
                        state["sources"][source_id] = {
                            "source_id": source_id,
                            "object_id": payload["object_id"],
                            "url": url,
                            "title": str(hit.get("title", url))[:300],
                            "text": str(hit.get("snippet", ""))[:6000],
                            "source_date": hit.get("published_at"),
                            "kind": "snippet",
                            "source_mode": self.web_source,
                        }
                        added.append(state["sources"][source_id])
                state["no_progress"] = 0 if added else state["no_progress"] + 1
                result = {"sources": added, "message": "摘要仅为线索，请读取来源以核实"}
            else:
                source = state["sources"][payload["source_id"]]
                page_text = raw.get("text", text)
                if raw.get("url", source["url"]) != source["url"]:
                    plugin_error = True
                if not isinstance(page_text, str) or not page_text.strip() or plugin_error:
                    state["no_progress"] += 1
                    result = {"error": "PAGE_UNAVAILABLE", "message": "来源读取失败，保留未知"}
                else:
                    source.update(
                        text=page_text[:60000], kind="page", source_date=raw.get("source_date")
                    )
                    result = {"source": source}
                    state["no_progress"] = 0
            if plugin_error:
                state["stop_reason"] = "tool_failed"
            record.result_payload = result
            run.state = state
            return result


def drive_pi(host: ResearchHost, state, messages, public_input):
    with tempfile.TemporaryDirectory(prefix="cheetah-a03-") as directory:
        if host.settings.a03_web_backend == "pi_web_access":
            provider = host.settings.a03_plugin_provider
            if provider not in {"brave", "tavily", "exa"}:
                raise DomainError("DEPENDENCY_NOT_READY", "搜索插件提供者尚未集成验证", 503)
            config = {
                "provider": provider,
                provider + "ApiKey": host.settings.a03_plugin_api_key.get_secret_value(),
                "webSearch": {"allowedProviders": [provider]},
                "autoOpenBrowser": False,
                "fetchRouting": {"allowRemoteHostedProviders": False},
                "fetchContent": {
                    "redirects": "same-origin",
                    "domainPolicy": {"allow": host.domains, "deny": []},
                },
            }
            Path(directory, "web-search.json").write_text(json.dumps(config), encoding="utf-8")
        definitions = [
            {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "parameters": model.model_json_schema(),
            }
            for name, model in TOOL_MODELS.items()
        ]
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "PATHEXT"}
        }
        process = subprocess.Popen(
            [host.settings.a03_node_binary, str(AGENT_DIR / "src" / "runner.ts")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        events = queue.Queue()

        def reader():
            for line in process.stdout:
                events.put(line)
            events.put(None)

        threading.Thread(target=reader, daemon=True).start()

        def send(value):
            process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
            process.stdin.flush()

        try:
            send(
                {
                    "system_prompt": host.system,
                    "tools": definitions,
                    "messages": messages,
                    "input": public_input,
                    "model_name": host.settings.model_name,
                    "max_output_tokens": host.settings.model_max_output_tokens,
                    "plugin_config_dir": directory,
                }
            )
            with Session(host.engine) as db, db.begin():
                host.locked(db)
                run = db.get(ResearchRun, host.task_id)
                run.state = {**run.state, "runtime_started": True}
            while True:
                if time.monotonic() - host.started >= host.settings.a03_max_seconds:
                    raise DomainError("A03_TIME_LIMIT", "研究时间达到上限", 429)
                try:
                    line = events.get(timeout=3)
                except queue.Empty:
                    with Session(host.engine) as db, db.begin():
                        host.locked(db)
                    continue
                if line is None:
                    raise DomainError("A03_RUNTIME_FAILED", "Pi 研究执行器退出")
                if len(line.encode()) > 2_000_000:
                    raise DomainError("A03_RUNTIME_FAILED", "Pi 响应超过限制")
                packet = json.loads(line)
                if packet["type"] == "done":
                    if not packet.get("finished"):
                        raise DomainError("A03_RUNTIME_FAILED", "研究未通过结束工具完成交付")
                    break
                if packet["type"] != "request":
                    raise DomainError("A03_RUNTIME_FAILED", "Pi 研究执行失败")
                try:
                    result = host.dispatch(packet["method"], packet["args"])
                except DomainError as exc:
                    if (
                        exc.code in {"VALIDATION_ERROR", "PRECONDITION_NOT_MET"}
                        and packet["method"] == "tool"
                    ):
                        result = {"error": exc.code, "message": exc.message}
                    else:
                        raise
                send({"id": packet["id"], "result": result})
                with Session(host.engine) as db:
                    current = db.get(ResearchRun, host.task_id).state
                    if current.get("stop_reason") == "tool_failed":
                        break
                    if current["no_progress"] >= host.settings.a03_no_progress_limit:
                        raise DomainError("A03_NO_PROGRESS", "连续查询没有新增有效信息")
        finally:
            process.stdin.close()
            # Give the runner time to close its MCP child when the host disconnects.
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()


def run_pi_research(settings, engine, task_id, token, context, refresh):
    host = ResearchHost(settings, engine, task_id, token, context)
    state, messages, public_input = host.initialize()
    if not state.get("stop_reason") and not state.get("finished"):
        try:
            drive_pi(host, state, messages, public_input)
        except DomainError as exc:
            if exc.code not in {
                "A03_TURN_LIMIT",
                "A03_TIME_LIMIT",
                "A03_NO_PROGRESS",
                "A03_RETRIEVAL_LIMIT",
                "BUDGET_EXCEEDED",
            }:
                raise
            with Session(engine) as db:
                pending = list(
                    db.scalars(
                        select(ResearchAction).where(
                            ResearchAction.task_id == task_id,
                            ResearchAction.status.in_(["submitted", "unknown"]),
                        )
                    )
                )
                pending_ids = [item.action_id for item in pending]
            if pending_ids:
                for action_id in pending_ids:
                    host.mark_unknown(action_id)
                raise DomainError(
                    "EXTERNAL_RESULT_UNKNOWN", "时限已到，外部研究请求仍需核对"
                ) from None
            with Session(engine) as db, db.begin():
                host.locked(db)
                run = db.get(ResearchRun, task_id)
                run.state = {**run.state, "stop_reason": exc.code.lower()}
    with Session(engine) as db, db.begin():
        task, job, application = host.locked(db)
        run = db.get(ResearchRun, task_id)
        state = copy.deepcopy(run.state)
        rule = db.get(RulePack, (job.id, application.rule_version))
        actions = list(db.scalars(select(ResearchAction).where(ResearchAction.task_id == task_id)))
        for record in state["records"].values():
            for finding in record["findings"]:
                refs = []
                for citation in finding["citations"]:
                    source = state["sources"][citation["source_id"]]
                    evidence = Evidence(
                        organization_id=job.organization_id,
                        job_id=job.id,
                        application_id=application.id,
                        source_type="public_web",
                        category=finding["category"],
                        quote=citation["quote"],
                        public_url=source["url"],
                        source_mode=source["source_mode"],
                        location={
                            "field": finding["field"],
                            "object_id": record["object_id"],
                            "title": source["title"],
                            "source_date_label": citation["source_date"],
                        },
                    )
                    db.add(evidence)
                    db.flush()
                    refs.append({"evidence_id": evidence.evidence_id, "version": 1})
                finding["evidence_refs"] = refs
        model_actions = [action for action in actions if action.kind == "model"]
        reported_tokens = [
            (action.result_payload or {}).get("usage", {}).get("totalTokens")
            for action in model_actions
        ]
        execution = {
            "runtime": "pi-agent-core" if state["runtime_started"] else None,
            "runtime_version": "1.5.2",
            "resource_hash": state["resource_hash"],
            "input_completeness": state["input_completeness"],
            "loaded_skills": state["loaded_skills"],
            "model_turns": sum(a.kind == "model" for a in actions),
            "tokens": sum(reported_tokens)
            if model_actions
            and all(isinstance(value, int) and value > 0 for value in reported_tokens)
            else None,
            "charged_tokens": sum(action.actual_tokens or 0 for action in model_actions),
            "searches": sum(a.kind == "search" for a in actions),
            "pages": sum(a.kind == "page" for a in actions),
            "failures": sum(
                a.status != "settled"
                or bool((a.result_payload or {}).get("error"))
                or bool((a.result_payload or {}).get("isError"))
                for a in actions
            ),
            "elapsed_seconds": round(time.monotonic() - host.started, 3),
            "cost": None,
            "fixture_only": application.execution_mode == "mock" or host.web_source == "mock",
        }
        report = build_report(
            state,
            candidate_id=application.candidate_id,
            application_id=application.id,
            job_id=job.id,
            d03_ref=state["d03_ref"],
            d01_ref=rule.d01_ref,
            execution=execution,
        )
        refs = [
            ref
            for record in state["records"].values()
            for finding in record["findings"]
            for ref in finding.get("evidence_refs", [])
        ]
        d03 = latest(db, job.id, "D03", application.id)
        content = {
            "status": report["status"],
            "subjects": [str(item["original_name"]) for item in report["objects"]],
            "findings": [
                {
                    "text": finding["text"],
                    "category": finding["category"],
                    "evidence_refs": finding["evidence_refs"],
                }
                for record in state["records"].values()
                for finding in record["findings"]
            ],
            "conflicts": [
                finding["text"]
                for record in state["records"].values()
                for finding in record["findings"]
                if finding["conflict_with_a04"]
            ],
            "gaps": report["gaps"],
            "stop_reason": {
                "code": report["stop_reason"],
                "message": "研究按证据和边界结束",
                "missing_fields": report["gaps"],
            },
            "usage": usage(tokens=execution["tokens"] or None, search_count=execution["searches"]),
            "report": report,
        }
        d04 = save_artifact(
            db,
            job,
            "D04",
            content,
            application=application,
            source=host.web_source if execution["searches"] or execution["pages"] else "manual",
            inherited=[d03.source_mode, *d03.inherited_source_modes],
            inputs=[artifact_ref(d03), rule.d01_ref],
            evidence=refs,
        )
        application.stage = "screening"
        application.revision += 1
        application.updated_at = utcnow()
        queue_step(
            db, job, application, "screening", input_refs=[artifact_ref(d03), artifact_ref(d04)]
        )
        task.result_refs, task.status, task.finished_at = [artifact_ref(d04)], "completed", utcnow()
        task.revision += 1
        refresh(db, task.id)
