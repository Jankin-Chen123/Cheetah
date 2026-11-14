"""Conservative, local rule-based drafting; never implies professional approval."""


def draft_method(paragraphs: list[tuple[int, str]], position: int) -> dict:
    number, source = paragraphs[position]
    context = paragraphs[max(0, position - 3) : min(len(paragraphs), position + 4)]
    text = "\n".join(value for _, value in context)
    dimension = (
        "results" if any(word in text for word in ("结果", "成果", "业绩")) else "responsibility"
    )
    questions = [value for _, value in context if "？" in value][:4]
    conflicts = []
    if any(word in text for word in ("压力面试", "性格", "情绪", "最高优先级", "薪资、假期")):
        conflicts.append("该片段含需业务复核的压力/主观推断/权限或动机口径；不得直接用于评分或执行")
    return {
        "topic": "成果核实" if dimension == "results" else "职责与行为核实",
        "dimensions": [dimension],
        "tags": sorted(
            {dimension, "detail"}
            | {
                tag
                for word, tag in {
                    "职责": "responsibility",
                    "责任": "responsibility",
                    "结果": "results",
                    "数字": "quantification",
                    "矛盾": "conflict",
                    "停止": "stop",
                    "STAR": "star",
                }.items()
                if word in text
            }
        ),
        "trigger_conditions": ["当前回答缺少该问题涉及的职责、行动或结果证据"],
        "question_examples": questions,
        "followup_strategy": "结合所引原文追问具体行动、数字口径与个人责任；完整回答后换主题",
        "stop_conditions": ["候选人要求结束", "证据充分", "达到程序轮次或时长上限"],
        "exceptions": ["拒答或缺失保留未知", "通用方法不能替代行业知识或正式评估标准"],
        "conflicts": conflicts,
        "source_text": source,
        "source_paragraphs": [n for n, _ in context],
        "source_context": text,
        "extraction_status": "rule_draft_requires_review",
        "method_version": 1,
        "anchor_paragraph": number,
    }
