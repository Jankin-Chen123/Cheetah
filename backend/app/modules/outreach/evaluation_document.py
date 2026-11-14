"""Internal D07–D09 documents for staff review."""


def source_lines(artifact):
    provenance = artifact.provenance
    return [
        f"来源模式：{provenance.get('source_mode', '未记录')}",
        "继承来源：" + ("、".join(provenance.get("inherited_source_modes", [])) or "未记录"),
        *(f"输入：{ref.get('id')} · v{ref.get('version')}" for ref in artifact.input_refs),
    ]


def preparation_lines(content):
    refs = content.get("preparation_refs", {})
    lines = []
    for kind, ref in refs.items():
        reference = ref.get("standard", ref)
        identifier = reference.get("id") or reference.get("job_id") or "未记录"
        lines.append(f"{kind}：{identifier} · v{reference.get('version', '未记录')}")
    return lines


def evaluation_markdown(artifact):
    content = artifact.content

    def cell(value):
        return (
            str(value if value is not None else "未评估").replace("|", "&#124;").replace("\n", " ")
        )

    lines = [
        "# 内部面试评估",
        "仅供猎头机构内部复核，不是客户推荐报告。",
        f"D09 内容版本：{artifact.version}",
        f"D08 交接状态：{content.get('extraction_status') or '未记录'}",
        f"执行会话：{content.get('interview_session_id') or '未记录'}",
        *preparation_lines(content),
        "## 岗位评估矩阵",
        "| 能力维度 | 指标 | 权重 | 评分锚点 | 得分 | 折算分 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in content.get("dimensions", []):
        anchors = "；".join(
            f"{key}：{value}" for key, value in row.get("scoring_anchors", {}).items()
        )
        lines.append(
            "| "
            + " | ".join(
                cell(value)
                for value in [
                    row.get("label", row.get("dimension_id")),
                    row.get("indicators"),
                    row.get("weight_percent"),
                    anchors,
                    row.get("score"),
                    row.get("weighted_score"),
                ]
            )
            + " |"
        )
    lines.append("## 逐维度评分依据")
    facts = {fact["evidence_id"]: fact for fact in content.get("evidence_items", [])}
    indicators = {}
    for indicator in content.get("indicator_evidence", []):
        indicators.setdefault(indicator["dimension_id"], []).append(indicator)
    for row in content.get("dimensions", []):
        lines.extend(
            [
                f"### {row.get('label', row.get('dimension_id'))}",
                f"依据：{row.get('reason', '未记录')}",
                f"命中档位：{row.get('matched_anchor_band') or '未评估'}",
                f"定分理由：{row.get('anchor_rationale') or '未记录'}",
                "回答引用：" + "、".join(row.get("evidence_ids", [])),
                "事实引用：" + "、".join(row.get("fact_evidence_ids", [])),
            ]
        )
        for indicator in indicators.get(row.get("dimension_id"), []):
            lines.extend(
                [
                    f"指标：{indicator.get('indicator_ref', '未记录')}",
                    f"证据充分性：{indicator.get('evidence_sufficiency', '未记录')}",
                    indicator.get("sufficiency_reason", ""),
                ]
            )
        for evidence_id in row.get("fact_evidence_ids", []):
            fact = facts.get(evidence_id)
            if fact is None:
                lines.append(f"{evidence_id}：未保存对应原话")
                continue
            quote = str(fact.get("quote") or "未记录")
            lines.extend(
                [
                    f"{evidence_id} 候选人原话：“" + "\n> ".join(quote.splitlines()) + "”",
                    f"回答：{fact.get('answer_id', '未记录')} · "
                    f"v{fact.get('answer_version', '未记录')}",
                    "轮次：" + ("、".join(fact.get("turn_ids", [])) or "未记录"),
                ]
            )
    total = content.get("total_score")
    lines.extend(
        [
            "## 汇总与完整性",
            f"总分：{total if total is not None else '未形成'}",
            f"评分状态：{content.get('assessment_status', '未记录')}",
            f"已评估权重：{content.get('scored_weight_percent', '未记录')}%",
            f"内部结论：{content.get('conclusion', '未记录')}",
        ]
    )
    for key, title in [
        ("gaps", "缺失与待核事项"),
        ("conflicts", "冲突"),
        ("extraction_limitations", "提取限制"),
    ]:
        if content.get(key):
            lines.extend([f"## {title}", *content[key]])
    lines.extend(["## 版本与来源", *source_lines(artifact)])
    return "\n\n".join(lines)


def outline_markdown(artifact):
    content = artifact.content
    lines = [
        "# 内部面试准备稿",
        "不代表外呼授权、候选人同意或已完成面试。",
        f"版本：{artifact.version}；状态：{content.get('readiness', '历史未记录')}",
    ]
    lines.extend(content.get("readiness_reasons", []))
    for row in content.get("questions", []):
        lines.extend(
            [
                f"## {row.get('id')} · {row.get('question')}",
                f"维度：{row.get('dimension_id')}；分钟：{row.get('planned_minutes')}",
                f"目标证据：{row.get('evidence_target')}",
            ]
        )
        for followup in row.get("conditional_followups", []):
            lines.append(f"触发：{followup.get('trigger')} → {followup.get('question')}")
        lines.extend(
            [
                f"停止条件：{row.get('stop_rule')}",
                "来源：" + "、".join(row.get("source_refs", [])),
                "方法：" + ("、".join(row.get("method_entry_ids", [])) or "未调用"),
            ]
        )
    lines.extend(["## 待核实事项", *content.get("unknowns", [])])
    lines.extend(["## 版本与来源", *source_lines(artifact)])
    return "\n\n".join(lines)


def minutes_markdown(artifact):
    content = artifact.content
    execution = content.get("execution_session") or {}
    turns = {turn["answer_id"]: turn for turn in execution.get("answer_turns", [])}
    lines = [
        "# 内部面试信息提取",
        "候选人自述与过程记录，不是评分或客户推荐。",
        f"D08 内容版本：{artifact.version}",
        f"提取状态：{content.get('extraction_status', '历史未记录')}",
        f"执行会话：{execution.get('session_id', '未记录')}；"
        f"状态：{execution.get('status', '未记录')}",
        *preparation_lines(content),
    ]
    lines.append("## 实际问答")
    for row in content.get("qa", []):
        question = row.get("question", {})
        question_text = (
            question.get("question", "未记录") if isinstance(question, dict) else str(question)
        )
        turn = turns.get(row.get("id"), {})
        lines.extend(
            [
                f"### {question_text}",
                row.get("text", "未记录"),
                f"回答引用：{row.get('id', '未记录')}",
                f"题号：{turn.get('question_id') or '未记录'}；"
                f"追问父题：{turn.get('parent_question_id') or '未记录'}；"
                f"轮次：{turn.get('turn_id') or '未记录'}；"
                f"回答版本：{row.get('version', 1)}",
            ]
        )
    lines.append("## 逐项事实与原话")
    for fact in content.get("evidence_items", content.get("facts", [])):
        lines.extend(
            [
                f"### {fact.get('evidence_id', '未编号')} · {fact.get('statement', '')}",
                f"原话：{fact.get('quote', '未记录')}",
                f"回答：{fact.get('answer_id', '未记录')}；"
                f"来源：{fact.get('source_type', '未记录')}",
                f"证据类型：{fact.get('evidence_kind', '未分类')}；"
                f"方向：{fact.get('evidence_direction', '未分类')}",
                "指标引用：" + ("、".join(fact.get("indicator_refs", [])) or "无"),
            ]
        )
    lines.append("## 指标证据与充分性")
    for row in content.get("indicator_evidence", []):
        lines.extend(
            [
                f"### {row.get('dimension_id')} · {row.get('indicator_ref')}",
                f"充分性：{row.get('evidence_sufficiency')}；理由：{row.get('sufficiency_reason')}",
                "事实引用：" + "、".join(row.get("evidence_ids", [])),
            ]
        )
    lines.append("## 计划题与实际执行对照")
    for row in content.get("question_execution_coverage", []):
        lines.extend(
            [
                f"### {row.get('question_id')} · {row.get('execution_status')}",
                "主问题回答：" + ("、".join(row.get("answer_ids", [])) or "无记录"),
                "追问回答：" + ("、".join(row.get("followup_answer_ids", [])) or "无记录"),
                row.get("note", ""),
            ]
        )
    if not content.get("question_execution_coverage"):
        lines.append("未记录可核对的计划题。")
    for key, label in [
        ("gaps", "缺失"),
        ("conflicts", "冲突"),
        ("extraction_limitations", "交接限制"),
    ]:
        if content.get(key):
            lines.extend([f"## {label}", *content[key]])
    lines.extend(["## 版本与来源", *source_lines(artifact)])
    return "\n\n".join(lines)
