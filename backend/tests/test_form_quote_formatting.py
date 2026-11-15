from app.modules.intake.form_sources import check_form_sources, empty_job_form, source_quote


def test_quote_resolves_markdown_and_spaces_to_exact_original_span():
    text = "**岗位名称：** 高级产品经理（B 端 SaaS 方向）\n地点：深圳"
    quote = source_quote(text, "岗位名称：高级产品经理（B端SaaS方向）")
    assert quote in text and "**" in quote
    form = empty_job_form()
    form.fields["岗位名称"].status = "stated"
    form.fields["岗位名称"].value = "高级产品经理（B 端 SaaS 方向）"
    form.fields["岗位名称"].quote = "岗位名称：高级产品经理（B端SaaS方向）"
    checked = check_form_sources(form, text)
    assert checked.fields["岗位名称"].status == "stated"
    assert checked.fields["岗位名称"].quote in text


def test_quote_does_not_join_separated_claims_or_erase_redaction_and_operators():
    assert source_quote("本人负责方案。团队实现整体增长。", "本人负责整体增长") is None
    assert source_quote("值为3*5", "值为35") is None
    assert source_quote("电话138****0000", "电话1380000") is None
