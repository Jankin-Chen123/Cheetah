"""Versioned occupational directions for routing, never hiring eligibility rules."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DirectionId = Literal[
    "frontend",
    "backend",
    "fullstack",
    "mobile",
    "data",
    "ai",
    "devops",
    "qa",
    "product",
    "design",
    "sales",
    "marketing",
    "operations",
    "finance",
    "hr",
    "legal",
    "supply_chain",
    "hardware",
]

TAXONOMY_VERSION = 1
DIRECTIONS = {
    "frontend": ("前端研发", ["前端", "front-end", "frontend", "web developer"]),
    "backend": ("后端研发", ["后端", "服务端", "backend", "back-end", "java开发", "java 开发"]),
    "fullstack": ("全栈研发", ["全栈", "fullstack", "full-stack"]),
    "mobile": ("移动端研发", ["移动端", "android", "ios", "flutter"]),
    "data": ("数据研发与分析", ["数据开发", "数据分析", "大数据", "数据工程"]),
    "ai": ("人工智能与算法", ["算法工程", "机器学习", "人工智能", "大模型"]),
    "devops": ("运维与基础设施", ["运维", "devops", "sre", "基础设施"]),
    "qa": ("测试与质量", ["测试工程", "软件测试", "质量工程"]),
    "product": ("产品", ["产品经理", "产品负责人", "产品设计", "product manager"]),
    "design": ("设计", ["交互设计", "视觉设计", "ui设计", "ux设计"]),
    "sales": ("销售与商务", ["销售", "商务拓展", "客户经理"]),
    "marketing": ("市场营销", ["市场营销", "品牌营销", "市场推广"]),
    "operations": ("运营", ["运营"]),
    "finance": ("财务", ["财务", "会计", "审计"]),
    "hr": ("人力资源", ["人力资源", "招聘专员", "招聘经理", "hrbp"]),
    "legal": ("法务", ["法务", "律师"]),
    "supply_chain": ("供应链与采购", ["供应链", "采购", "物流"]),
    "hardware": ("硬件与嵌入式", ["硬件", "嵌入式", "电子工程"]),
}


class DirectionAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    direction_id: DirectionId
    level: Literal["primary", "secondary"]
    quote: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=1000)


def title_directions(title: str) -> list[str]:
    """Only occupational titles, not incidental tools in a job's requirement paragraph."""
    value = title.casefold()
    return [
        key
        for key, (_, aliases) in DIRECTIONS.items()
        if any(
            re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", value)
            if alias.isascii()
            else alias in value
            for alias in aliases
        )
    ]


def compatible_directions(assignments: list[dict], job_directions: list[str]) -> list[str]:
    directions = {item["direction_id"] for item in assignments}
    if "fullstack" in directions:
        directions.update(["frontend", "backend"])
    # A frontend or backend alone does not imply fullstack ability.
    return sorted(directions & set(job_directions))
