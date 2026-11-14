"""Conservative salary comparison. Ambiguous currency, tax or pay basis stays unknown."""

import re
from decimal import Decimal


def salary_terms(text):
    currency = (
        "USD"
        if re.search(r"USD|美元", text, re.I)
        else "CNY"
        if re.search(r"CNY|RMB|人民币|元|￥", text, re.I)
        else None
    )
    tax = "gross" if "税前" in text else "net" if "税后" in text else None
    basis = "fixed" if "固定" in text else "total" if "总包" in text else None
    period = (
        12
        if re.search(r"月薪|/月|每月", text)
        else 1
        if re.search(r"年薪|/年|每年", text)
        else None
    )
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:[-—~至]\s*(\d+(?:\.\d+)?))?\s*(万|千|[kK])?\s*(?:元|人民币|CNY|RMB|美元|USD)",
        text,
    )
    if not all((currency, tax, basis, period, match)):
        return None
    factor = {"万": 10000, "千": 1000, "k": 1000, "K": 1000, None: 1}[match[3]] * period
    low, high = Decimal(match[1]) * factor, Decimal(match[2] or match[1]) * factor
    if high <= 0 or high < low:
        return None
    return currency, tax, basis, low, high


def salary_score(budget_text, expectation_text):
    budget, expectation = salary_terms(budget_text), salary_terms(expectation_text)
    if not budget or not expectation or budget[:3] != expectation[:3]:
        return None
    # A range overlapping the budget is not an agreed expectation; leave it for the call.
    if expectation[3] != expectation[4]:
        return None
    ratio = expectation[4] / budget[4] - 1
    for ceiling, score in [
        (Decimal(0), 9),
        (Decimal("0.05"), 8),
        (Decimal("0.15"), 7),
        (Decimal("0.30"), 6),
        (Decimal("0.50"), 4),
    ]:
        if ratio <= ceiling:
            return score
    return 2
