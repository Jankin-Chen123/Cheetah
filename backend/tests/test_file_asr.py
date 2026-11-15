import io
import json
import wave
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import AudioTranscription, utcnow
from app.integrations.voice import file_asr
from app.modules.intake.audio import run_audio_once


def wav():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as value:
        value.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        value.writeframes(b"\0\0" * 160)
    return stream.getvalue()


def setup(runtime, monkeypatch, responses):
    settings, engine = runtime
    settings.file_asr_provider = "volcengine"
    settings.volc_speech_api_key = SecretStr("fictional-secret-only")
    original = httpx.Client
    calls = []

    def respond(request):
        calls.append(request)
        body = json.loads(request.content)
        assert "url" not in body["audio"] and body["audio"]["data"]
        assert body["request"]["enable_ddc"] is False
        assert request.headers["X-Api-Resource-Id"] == "volc.bigasr.auc_turbo"
        response = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(
        file_asr.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(respond), **kw),
    )
    return settings, engine, calls


def success(text="测试岗位位于深圳"):
    return httpx.Response(
        200,
        headers={"X-Api-Status-Code": "20000000"},
        json={
            "audio_info": {"duration": 1000},
            "result": {
                "text": text,
                "utterances": [{"text": text, "start_time": 0, "end_time": 1000}],
            },
        },
    )


def upload(api, name="fiction.wav", data=None, key=None):
    return api.post(
        "/api/v1/audio-transcriptions",
        files={"file": (name, wav() if data is None else data, "audio/wav")},
        headers={"Idempotency-Key": key or uuid4().hex},
    )


def test_upload_is_persisted_deduplicated_and_linked_to_reviewed_job(api, runtime, monkeypatch):
    settings, engine, calls = setup(runtime, monkeypatch, [success()])
    key = uuid4().hex
    first = upload(api, key=key)
    assert first.status_code == 202
    ref = first.json()
    assert upload(api, key=key).json() == ref
    assert upload(api, name="renamed.wav").json()["id"] == ref["id"]
    assert not calls
    assert run_audio_once(settings, engine)
    assert not run_audio_once(settings, engine)
    value = api.get("/api/v1/audio-transcriptions/" + ref["id"]).json()
    assert value["status"] == "completed" and value["source_mode"] == "live"
    assert value["segments"][0]["end_ms"] == 1000 and len(calls) == 1
    response = api.post(
        "/api/v1/jobs",
        headers={"Idempotency-Key": uuid4().hex},
        json={
            "material_text": value["transcript"] + "，人工补充待确认。",
            "audio_transcription_ref": {"id": value["id"], "revision": value["revision"]},
        },
    )
    assert response.status_code == 201
    assert response.json()["audio_transcription_ref"]["text_edited"]
    assert "fictional-secret-only" not in json.dumps(value)


@pytest.mark.parametrize(
    "code,expected", [("45000030", "ASR_RESOURCE_NOT_GRANTED"), ("20000003", "ASR_NO_SPEECH")]
)
def test_explicit_provider_failure_is_not_success_or_automatic_retry(
    api, runtime, monkeypatch, code, expected
):
    settings, engine, calls = setup(
        runtime, monkeypatch, [httpx.Response(403, headers={"X-Api-Status-Code": code})]
    )
    ref = upload(api).json()
    run_audio_once(settings, engine)
    value = api.get("/api/v1/audio-transcriptions/" + ref["id"]).json()
    assert (
        value["status"] == "failed" and value["error_code"] == expected and not value["transcript"]
    )
    assert not run_audio_once(settings, engine) and len(calls) == 1


def test_unknown_network_outcome_stays_reconciling_and_cannot_retry(api, runtime, monkeypatch):
    settings, engine, calls = setup(
        runtime, monkeypatch, [httpx.ReadTimeout("private credentials or address")]
    )
    ref = upload(api).json()
    run_audio_once(settings, engine)
    value = api.get("/api/v1/audio-transcriptions/" + ref["id"]).json()
    assert value["status"] == "reconciling" and not value["retryable"]
    assert "private" not in json.dumps(value)
    r = api.post(
        "/api/v1/audio-transcriptions/" + ref["id"] + "/retry",
        json={"expected_revision": value["revision"]},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert r.status_code == 409 and len(calls) == 1


def test_permission_activation_allows_one_explicit_idempotent_retry(api, runtime, monkeypatch):
    settings, engine, calls = setup(
        runtime,
        monkeypatch,
        [httpx.Response(403, headers={"X-Api-Status-Code": "45000030"}), success()],
    )
    ref = upload(api).json()
    run_audio_once(settings, engine)
    value = api.get("/api/v1/audio-transcriptions/" + ref["id"]).json()
    key = uuid4().hex
    path = "/api/v1/audio-transcriptions/" + ref["id"] + "/retry"
    for _ in range(2):
        assert (
            api.post(
                path,
                json={"expected_revision": value["revision"]},
                headers={"Idempotency-Key": key},
            ).status_code
            == 202
        )
    run_audio_once(settings, engine)
    assert api.get("/api/v1/audio-transcriptions/" + ref["id"]).json()["status"] == "completed"
    assert len(calls) == 2


def test_ownership_csrf_validation_and_budget_are_enforced(api, runtime, monkeypatch):
    settings, engine, _ = setup(runtime, monkeypatch, [success()])
    assert upload(api, name="fake.wav", data=b"not audio").status_code == 422
    assert upload(api, name="fake.m4a").status_code == 422
    settings.file_asr_byte_limit = 1024
    assert upload(api, data=wav() + b"x" * 2048).status_code == 422
    settings.file_asr_daily_limit = 1
    ref = upload(api).json()
    assert upload(api, name="another.wav", data=wav() + b"next").status_code == 429
    assert run_audio_once(settings, engine)
    login = api.post(
        "/api/v1/auth/login", json={"username": "fixture-other", "password": "fixture-password"}
    ).json()
    api.headers["X-CSRF-Token"] = login["csrf_token"]
    assert api.get("/api/v1/audio-transcriptions/" + ref["id"]).status_code == 404
    assert (
        api.post(
            "/api/v1/jobs",
            headers={"Idempotency-Key": uuid4().hex},
            json={
                "material_text": "材料",
                "audio_transcription_ref": {"id": ref["id"], "revision": 3},
            },
        ).status_code
        == 404
    )


def test_worker_restart_preserves_unknown_request_without_resubmission(api, runtime, monkeypatch):
    settings, engine, calls = setup(runtime, monkeypatch, [success()])
    ref = upload(api).json()
    with Session(engine) as db, db.begin():
        item = db.get(AudioTranscription, ref["id"])
        item.status = "running"
        item.started_at = utcnow() - timedelta(seconds=600)
        item.provider_request_id = "original-request"
    assert not run_audio_once(settings, engine)
    with Session(engine) as db:
        item = db.scalar(select(AudioTranscription))
        assert item.status == "reconciling"
        assert item.provider_request_id == "original-request" and not calls


def test_standard_url_is_submitted_once_and_queries_same_request_until_complete(
    api, runtime, monkeypatch
):
    settings, engine = runtime
    settings.file_asr_provider = "volcengine"
    settings.volc_speech_api_key = SecretStr("fixture-secret")
    original = httpx.Client
    requests = []

    def respond(request):
        requests.append(request)
        assert request.headers["X-Api-Resource-Id"] == "volc.seedasr.auc"
        if request.url.path.endswith("/submit"):
            return httpx.Response(200, headers={"X-Api-Status-Code": "20000000"}, json={})
        assert request.headers["X-Api-Request-Id"] == requests[0].headers["X-Api-Request-Id"]
        if len(requests) == 2:
            return httpx.Response(200, headers={"X-Api-Status-Code": "20000001"}, json={})
        return success()

    monkeypatch.setattr(
        file_asr.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(respond), **kw),
    )
    body = {"audio_url": "https://example.com/audio.mp3", "audio_format": "mp3"}
    received = api.post(
        "/api/v1/audio-transcriptions/from-url", json=body, headers={"Idempotency-Key": uuid4().hex}
    )
    assert received.status_code == 202
    ref = received.json()
    for index in range(3):
        if index:
            with Session(engine) as db, db.begin():
                db.get(AudioTranscription, ref["id"]).finished_at = utcnow() - timedelta(seconds=10)
        assert run_audio_once(settings, engine)
    final = api.get("/api/v1/audio-transcriptions/" + ref["id"]).json()
    assert final["status"] == "completed"
    assert sum(r.url.path.endswith("/submit") for r in requests) == 1
    with Session(engine) as db:
        assert db.get(AudioTranscription, ref["id"]).attempts == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/a.mp3",
        "https://127.0.0.1/a.mp3",
        "https://localhost/a.mp3",
        "https://x:y@example.com/a.mp3",
        "https://example.com/a.mp3?api_key=secret",
    ],
)
def test_remote_audio_rejects_private_and_credential_urls(api, runtime, url):
    runtime[0].file_asr_provider = "volcengine"
    runtime[0].volc_speech_api_key = SecretStr("fixture")
    r = api.post(
        "/api/v1/audio-transcriptions/from-url",
        json={"audio_url": url, "audio_format": "mp3"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert r.status_code == 422


def test_postgres_workers_claim_one_file_once(api, runtime, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    if runtime[1].dialect.name != "postgresql":
        pytest.skip("Row locking requires isolated PostgreSQL schema")
    settings, engine, calls = setup(runtime, monkeypatch, [success()])
    ref = upload(api).json()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: run_audio_once(settings, engine), range(8)))
    assert len(calls) == 1
    with Session(engine) as db:
        item = db.get(AudioTranscription, ref["id"])
        assert item.status == "completed" and item.attempts == 1
