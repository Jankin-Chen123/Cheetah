"""Durable, single-attempt SMTP delivery. Unknown outcomes require reconciliation."""

import json
import re
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.modules.outreach.models import ModelStep, OutreachCase


def validate_email(value):
    if len(value) > 254 or not re.fullmatch(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}",
        value,
    ):
        raise ValueError("EMAIL_INVALID")
    return value


def mail_configured(settings):
    return all(
        (settings.smtp_host, settings.smtp_username, settings.smtp_password, settings.smtp_sender)
    )


def execute_briefing_mail(engine, settings, task_id):
    with Session(engine) as session, session.begin():
        task = session.get(ModelStep, task_id, with_for_update=True)
        if not task or task.status != "queued":
            return
        case = session.get(OutreachCase, task.case_id)
        if case.stop_status != "none" or case.status in {"ended", "cancelled"}:
            task.status = "cancelled"
            return
        if not mail_configured(settings):
            task.status = "failed"
            task.detail = {**task.detail, "error_code": "MAIL_NOT_CONFIGURED"}
            return
        task.status = "running"
        task.detail = {**task.detail, "started_at": datetime.now(UTC).isoformat()}
        recipient = validate_email(task.detail["recipient"])
        material = task.detail["material"]
        fictional = case.snapshot.get("fixture_only", False)
    message = EmailMessage()
    message["From"] = settings.smtp_sender
    message["To"] = recipient
    message["Subject"] = ("【虚构测试资料】" if fictional else "") + "岗位与薪资资料"
    message["Message-ID"] = "<" + task_id + "@" + settings.smtp_sender.split("@")[-1] + ">"
    labels = {
        "job_title": "岗位",
        "requirements": "职责",
        "salary": "薪资",
        "company_introduction": "公司介绍",
        "unknowns": "待确认信息",
    }
    body = ["以下为虚构测试材料。" if fictional else "以下为本次岗位沟通资料。"]
    for key, label in labels.items():
        value = material.get(key)
        body.append(
            label + "：" + (json.dumps(value, ensure_ascii=False) if value else "待招聘方确认")
        )
    message.set_content("\n\n".join(body))
    status, error = "completed", None
    try:
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=20, context=ssl.create_default_context()
        ) as smtp:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        status, error = "failed", "MAIL_OUTCOME_UNKNOWN_DO_NOT_RETRY"
    with Session(engine) as session, session.begin():
        task = session.get(ModelStep, task_id, with_for_update=True)
        task.status = status
        task.detail = {
            **task.detail,
            "error_code": error,
            "delivery_status": "accepted_by_smtp" if not error else "unknown",
        }
