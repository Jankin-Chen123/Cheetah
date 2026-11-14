"""Internal D09 document; never a customer recommendation or delivery approval."""


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
    total = content.get("total_score")
    lines.extend(
        [
            "## 汇总与完整性",
            f"总分：{total if total is not None else '未形成'}",
            f"已评估权重：{content.get('scored_weight_percent', '未记录')}%",
            f"内部结论：{content.get('conclusion', '未记录')}",
        ]
    )
    for key, title in [("gaps", "缺失与待核事项"), ("conflicts", "冲突")]:
        if content.get(key):
            lines.extend([f"## {title}", *content[key]])
    lines.extend(["## 版本与来源", f"来源模式：{artifact.provenance.get('source_mode', '未记录')}"])
    lines.extend(f"输入：{ref.get('id')} · v{ref.get('version')}" for ref in artifact.input_refs)
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
    lines.extend(f"输入：{ref.get('id')} · v{ref.get('version')}" for ref in artifact.input_refs)
    return "\n\n".join(lines)


def minutes_markdown(artifact):
    content = artifact.content
    lines = [
        "# 内部面试信息提取",
        "候选人自述与过程记录，不是评分或客户推荐。",
        f"D08 内容版本：{artifact.version}",
        f"提取状态：{content.get('extraction_status', '历史未记录')}",
    ]
    lines.append("## 实际问答")
    for row in content.get("qa", []):
        question = row.get("question", {})
        question_text = (
            question.get("question", "未记录") if isinstance(question, dict) else str(question)
        )
        lines.extend(
            [
                f"### {question_text}",
                row.get("text", "未记录"),
                f"回答引用：{row.get('id', '未记录')}",
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
    for key, label in [
        ("gaps", "缺失"),
        ("conflicts", "冲突"),
        ("extraction_limitations", "交接限制"),
    ]:
        if content.get(key):
            lines.extend([f"## {label}", *content[key]])
    return "\n\n".join(lines)
