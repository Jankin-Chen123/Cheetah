"""Render supplied business forms from validated content; never ask a model for layout."""

from app.modules.intake.form_contracts import DIMENSIONS, JD_FIELDS, JOB_GROUPS, PORTRAIT_FIELDS


def cell(value):
    return (
        str(value if value is not None else "未提及")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "&#124;")
        .replace("\n", "<br>")
    )


def table(headers, rows):
    return [
        "| " + " | ".join(map(cell, headers)) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *["| " + " | ".join(map(cell, row)) + " |" for row in rows],
    ]


def fact_text(fact):
    if fact.get("status") == "stated":
        return fact.get("value")
    return "待确认" if fact.get("status") == "conflict" or fact.get("note") else "未提及"


def render_job(content):
    form = content["job_form"]
    rows = []
    for group, fields in JOB_GROUPS.items():
        rows.append([group, ""])
        rows.extend([key, fact_text(form["fields"][key])] for key in fields)
    rows.append(["招聘 JD 输出｜独立成稿", ""])
    for section in JD_FIELDS:
        items = [fact_text(fact) for fact in form["jd"][section] if fact["status"] == "stated"]
        rows.append(
            [
                "【" + section + "】",
                "\n".join(f"{i}. {text}" for i, text in enumerate(items, 1))
                if items
                else "未提及明确加分条件"
                if section == "加分条件"
                else "未提及，暂无足够信息生成",
            ]
        )
    return "\n".join(["# 岗位画像与招聘 JD", "", *table(["字段", "岗位画像提取内容"], rows)])


def render_interview(content, context):
    rows = []
    for dimension in content["dimensions"]:
        anchors = dimension.get("anchors")
        rubric = (
            "\n".join(
                f"{label}：{anchors[key]}"
                for key, label in [
                    ("low", "1—2分"),
                    ("limited", "3—4分"),
                    ("partial", "5—6分"),
                    ("strong", "7—8分"),
                    ("excellent", "9—10分"),
                ]
            )
            if anchors
            else dimension["rubric"]
        )
        rows.append(
            [
                dimension["label"],
                dimension["rubric"],
                f"{dimension['weight'] * 100:g}%"
                if dimension.get("weight") is not None
                else "待确认",
                rubric,
                "",
                "",
            ]
        )
    return "\n".join(
        [
            "# 岗位面试评估表",
            "",
            "一、客户与岗位信息",
            "",
            *table(
                ["字段", "内容"],
                [
                    [key, context.get(key)]
                    for key in [
                        "客户企业名称",
                        "客户企业简称",
                        "客户所属行业",
                        "对接 HR",
                        "用人部门",
                        "岗位名称",
                    ]
                ],
            ),
            "",
            "二、岗位核心能力面试评估",
            "",
            *table(
                [
                    "考核维度",
                    "考核指标及解析说明",
                    "权重",
                    "评分标准（1—10 分）",
                    "实际得分",
                    "折算得分",
                ],
                rows,
            ),
            "",
            "三、评分汇总",
            "",
            *table(
                ["字段", "内容"],
                [
                    ["维度总数", len(rows)],
                    [
                        "权重合计",
                        f"{sum(d.get('weight') or 0 for d in content['dimensions']) * 100:g}%",
                    ],
                    [
                        "评估状态",
                        {"draft": "待确认", "needs_information": "待补充", "confirmed": "已确认"}[
                            content["confirmation_status"]
                        ],
                    ],
                    ["综合总分", "待面试"],
                    ["候选人姓名", "待面试"],
                    ["已评分权重", "待面试"],
                ],
            ),
            "",
            *[cell(gap) for gap in content.get("gaps", [])],
        ]
    )


def render_resume(content):
    form = content["resume_form"]
    metadata = content.get("document_metadata", {})
    rows = []
    for index, (section, records) in enumerate(form["sections"].items(), 1):
        numeral = "一二三四五六七八九"[index - 1]
        rows.append([f"{numeral}、" + ("候选人基本信息" if section == "基本信息" else section), ""])
        if not records:
            rows.append(["记录", "未提及"])
        for record in records:
            if len(records) > 1:
                rows.append(["记录 " + record["record_id"], ""])
            rows.extend([key, fact_text(fact)] for key, fact in record["fields"].items())
            refs = [
                ref for fact in record["fields"].values() for ref in fact.get("evidence_refs", [])
            ]
            rows.append(
                [
                    "本段记录来源",
                    str(metadata.get("filename", "未提供文件名"))
                    + "；"
                    + "、".join(f"{r['evidence_id']}@{r['version']}" for r in refs),
                ]
            )
    objects = content.get("research_objects", [])
    handoff = [
        [
            {
                "company": "公司",
                "project": "项目",
                "award": "比赛/奖项",
                "paper": "论文",
                "patent": "专利",
                "software_copyright": "软著",
                "open_source": "开源",
                "certification": "认证",
                "professional_work": "作品",
                "other_achievement": "其他成果",
            }[obj["kind"]],
            fact_text(obj["name"]),
            fact_text(obj["period"]) if obj.get("period") else "未提及",
            "；".join(
                str(f["value"]) for f in obj["facts"].values() if f.get("status") == "stated"
            ),
            "主体、公开背景与成果归属",
        ]
        for obj in objects
    ]
    return "\n".join(
        [
            "# 候选人简历结构化信息提取表",
            "",
            *table(
                ["字段", "内容"],
                [
                    ["候选人编号", metadata.get("candidate_id")],
                    ["原始文件名", metadata.get("filename")],
                    ["资料形式", metadata.get("format")],
                    [
                        "解析状态",
                        {
                            "completed": "完成",
                            "partial": "部分完成",
                            "needs_confirmation": "待确认",
                        }[form["parse_status"]],
                    ],
                ],
            ),
            "",
            "以下均为候选人简历自述，未经独立核实。",
            "",
            *table(["字段与提取要求", "结构化提取结果"], rows),
            "",
            "十、A03 联网检索对象清单（独立交接）",
            "",
            *table(["对象类型", "原始名称", "时间/关联信息", "检索线索", "待核实内容"], handoff),
            "",
            *[cell(text) for text in form.get("limitations", [])],
        ]
    )


def render_screening(portrait, report):
    lines = [
        "# 候选人画像与简历初筛评估表",
        "",
        "一、客户、岗位与候选人归属",
        "",
        *table(["字段", "内容"], list(portrait.get("form_context", {}).items())),
        "",
        *table(
            ["产物", "输入版本"],
            [
                [key, f"{ref['artifact_id']}@{ref['version']}"]
                for key, ref in portrait.get("assessment_refs", {}).items()
            ],
        ),
        "",
        f"岗位评分规则版本：{report.get('rule_version', '待确认')}",
        "",
        "二、D05｜候选人初步画像",
        "",
        *table(
            ["画像字段", "相关履历与事实"],
            [[key, portrait.get("portrait", {}).get(key)] for key in PORTRAIT_FIELDS],
        ),
    ]
    rubric = report["screening_rubric"]
    lines += [
        "",
        "三、D06｜岗位级初筛评分规则",
        "",
        *table(
            ["评估维度", "岗位权重", "岗位考察重点", "五档评分锚点"],
            [
                [
                    DIMENSIONS[d["id"]][0],
                    f"{d['weight']:g}%",
                    d["requirement"],
                    "\n".join(
                        f"{band}：{d['anchors'][key]}"
                        for key, band in [
                            ("low", "1—2分"),
                            ("limited", "3—4分"),
                            ("partial", "5—6分"),
                            ("strong", "7—8分"),
                            ("excellent", "9—10分"),
                        ]
                    ),
                ]
                for d in rubric["dimensions"]
            ],
        ),
        "",
        cell(rubric["routing_policy"]),
        "",
        "四、D06｜逐候选人匹配评分与证据",
        "",
    ]
    rows = []
    for row in report["score_summary"]["rows"]:
        refs = "；".join(
            f"{use['category']} {use['evidence_id']}@{use['version']}：{use['purpose']}"
            for use in row["evidence"]
        )
        rows.append(
            [
                row["label"],
                f"{row['weight']:g}%",
                row["requirement"] + "\n" + refs,
                f"{row['score']}/10"
                if row["score"] is not None
                else "不适用"
                if row["status"] == "not_applicable"
                else "未评估",
                row["weighted_score"] if row["weighted_score"] is not None else "",
                row["reason"] + "\n" + "；".join(row["questions"]),
            ]
        )
    lines += table(
        [
            "评分维度",
            "权重",
            "D01要求 / D03履历 / D04背景（适用时）",
            "评分状态",
            "折算得分",
            "理由及待核实",
        ],
        rows,
    )
    summary = report["score_summary"]
    lines += [
        "",
        "五、评分汇总与初筛决定",
        "",
        *table(
            ["岗位级权重合计", "已评权重覆盖 C", "已评分贡献 P", "正式总分"],
            [
                [
                    "100%",
                    f"{summary['coverage']:g}%",
                    f"{summary['contribution']:g} 分",
                    f"{summary['total']:g}/100" if summary["total"] is not None else "待核实",
                ]
            ],
        ),
        "",
        "初筛结论："
        + {
            "passed": "进入 AI 电话",
            "manual_review": "信息不足待人工复核",
            "rejected": "暂不推荐",
            "unknown": "信息不足待人工复核",
        }[report["result"]],
        "",
        *[
            f"- {cell(text)}"
            for text in report["assessment"]["reasons"] + report.get("safety_notes", [])
        ],
        "",
        "六、交给 A06 的电话核实重点",
        "",
        *table(
            ["对应维度", "待核实事实", "D03 / D04 线索", "优先级"],
            [
                [
                    DIMENSIONS[q["dimension_id"]][0],
                    q["fact"],
                    q["clue"],
                    {"high": "高", "normal": "普通", "low": "低"}[q["priority"]],
                ]
                for q in report["assessment"]["handoff"]
            ],
        ),
    ]
    if report.get("review"):
        lines += ["", "人工复核说明：" + cell(report["review"]["reason"])]
    return "\n".join(lines)
