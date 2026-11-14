import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.config import Settings
from app.core.database import Base, get_engine
from app.core.models import Identity
from app.main import create_app
from app.worker import run_once


@pytest.fixture
def runtime(tmp_path):
    postgres_url = os.environ.get("CHEETA_TEST_DATABASE_URL")
    schema = "test_" + uuid4().hex
    if postgres_url:
        admin = create_engine(postgres_url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        database_url = (
            make_url(postgres_url)
            .update_query_dict({"options": f"-csearch_path={schema}"})
            .render_as_string(hide_password=False)
        )
        engine = get_engine(database_url)
    else:
        database_url = "sqlite:///" + str(tmp_path / "intake.sqlite")
        engine = get_engine(database_url)
    settings = Settings(
        _env_file=None,
        environment="test",
        allow_mock=True,
        database_url=database_url,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db, db.begin():
        for username, organization in (
            ("fixture-owner", "fixture-org"),
            ("fixture-colleague", "fixture-org"),
            ("fixture-other", "fixture-other-org"),
        ):
            db.add(
                Identity(
                    username=username,
                    organization_id=organization,
                    display_name="虚构测试账号",
                    password_hash=hash_password("fixture-password"),
                )
            )
    yield settings, engine
    engine.dispose()
    if postgres_url:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def api(runtime):
    settings, engine = runtime
    with TestClient(create_app(settings)) as client:
        from app.core.auth import browser_db

        def test_db():
            with Session(engine) as db, db.begin():
                yield db

        client.app.dependency_overrides[browser_db] = test_db
        result = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:5173"},
            json={"username": "fixture-owner", "password": "fixture-password"},
        )
        assert result.status_code == 200, result.text
        client.headers.update(
            {"Origin": "http://localhost:5173", "X-CSRF-Token": result.json()["csrf_token"]}
        )
        yield client


def post(api, path, body, *, key=None, expected=201):
    response = api.post(
        "/api/v1" + path, json=body, headers={"Idempotency-Key": key or uuid4().hex}
    )
    assert response.status_code == expected, response.text
    return response.json()


def drain(runtime):
    settings, engine = runtime
    for _ in range(50):
        if not run_once(settings, engine):
            return
    raise AssertionError("Worker failed to drain")


def published_job(api, runtime, *, research_config="unavailable", execution_mode="mock"):
    job = post(
        api,
        "/jobs",
        {
            "title": "虚构岗位",
            "company": "虚构企业",
            "material_text": "地点：虚构城市\n需要工作经验，薪资待确认",
        },
    )
    post(
        api,
        f"/jobs/{job['id']}/analyze",
        {"expected_revision": job["revision"], "execution_mode": execution_mode},
        expected=202,
    )
    drain(runtime)
    job = api.get(f"/api/v1/jobs/{job['id']}").json()
    content = {
        "screening_text": "工作经验至少三年，缺证据进入信息不足",
        "interview_text": "核实个人贡献",
        "recommendation_text": "依据核实证据人工审核",
        "screening_conditions": [
            {
                "id": "experience",
                "label": "至少三年经验",
                "required_evidence": ["简历陈述的工作年限"],
                "evidence_sources": ["resume"],
                "predicate": {"field": "years_experience", "operator": "gte", "expected": 3},
            }
        ],
        "interview_dimensions": [
            {
                "id": "contribution",
                "label": "个人贡献",
                "rubric": "核实个人承担职责和证据",
                "required_evidence": ["本人贡献的实际访谈回答"],
            }
        ],
        "recommendation_policy": {
            "required_dimension_ids": ["contribution"],
            "decision_method": "rubric",
        },
        "research_config_ref": {"config_id": research_config, "version": 1},
        "phone_config_ref": {"config_id": "disabled", "version": 1},
        "method_config_ref": {"config_id": "predicates", "version": 1},
    }
    saved = api.patch(
        f"/api/v1/jobs/{job['id']}/rules/draft",
        json={"expected_draft_revision": job["draft_revision"], "content": content},
    )
    assert saved.status_code == 200, saved.text
    rule = post(
        api,
        f"/jobs/{job['id']}/rules/publish",
        {
            "expected_draft_revision": saved.json()["draft_revision"],
            "d01_ref": job["d01_ref"],
            "d02_ref": job["d02_ref"],
            "is_test_rule": execution_mode == "mock",
            "confirmation_note": "虚构测试标准，只验证流程",
        },
    )
    return job["id"], rule


@pytest.fixture(autouse=True)
def isolate_provider_configuration(monkeypatch):
    monkeypatch.setenv("CHEETA_TEXT_PROVIDER", "bailian")
    monkeypatch.setenv("CHEETA_VOICE_PROVIDER", "bailian")
    monkeypatch.setenv(
        "CHEETA_ALLOWED_ORIGINS", '["http://localhost:5173","http://127.0.0.1:5173"]'
    )
    monkeypatch.setenv("CHEETA_DIALOGUE_UNDERSTANDING_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
