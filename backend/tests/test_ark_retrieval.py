import io
import json
from urllib.error import HTTPError

import pytest

from app.core.config import Settings
from app.integrations.bailian import ModelUnavailable, generate_json
from app.integrations.embeddings import embed_text
from app.modules.outreach.retrieval import hybrid_rank


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        return json.dumps(self.payload).encode()


def test_ark_uses_separate_credential_and_disables_thinking(monkeypatch):
    captured = []

    class Opener:
        def open(self, request, timeout):
            captured.append(request)
            return Response(
                {"model": "ark-fixture", "choices": [{"message": {"content": '{"reply":"ok"}'}}]}
            )

    monkeypatch.setattr("app.integrations.bailian.build_opener", lambda *a: Opener())
    result = generate_json(
        Settings(
            text_provider="ark",
            ark_api_key="ark-fixture",
            ark_model="ark-fixture",
            bailian_api_key="different-voice-credential",
        ),
        "JSON",
        {},
    )
    assert result["provider"] == "ark"
    request = captured[0]
    assert request.full_url == "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    assert request.get_header("Authorization") == "Bearer ark-fixture"
    assert json.loads(request.data)["thinking"] == {"type": "disabled"}


def test_ark_unavailable_does_not_silently_call_another_provider(monkeypatch):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request.full_url)
            raise HTTPError(
                request.full_url,
                404,
                "unavailable",
                {},
                io.BytesIO(
                    b'{"error":{"code":"ModelNotOpen","message":"private provider detail"}}'
                ),
            )

    monkeypatch.setattr("app.integrations.bailian.build_opener", lambda *a: Opener())
    with pytest.raises(ModelUnavailable, match="MODEL_HTTP_404_ModelNotOpen"):
        generate_json(Settings(text_provider="ark", ark_api_key="fixture"), "JSON", {})
    assert len(calls) == 1


def test_embedding_multimodal_text_and_normalization(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            body = json.loads(request.data)
            assert body["input"] == [{"type": "text", "text": "test"}]
            assert request.full_url.endswith("/embeddings/multimodal")
            return Response({"data": {"embedding": [3, 4]}})

    monkeypatch.setattr("app.integrations.embeddings.build_opener", lambda *a: Opener())
    assert embed_text(Settings(ark_api_key="fixture"), "test") == [0.6, 0.8]


def test_embedding_redirect_host_is_rejected():
    with pytest.raises(ModelUnavailable, match="ENDPOINT_NOT_ALLOWED"):
        embed_text(Settings(ark_api_key="fixture", ark_base_url="https://example.com"), "test")


def test_semantic_match_without_shared_words_and_cache_invalidation(tmp_path, monkeypatch):
    calls = []

    def vectors(settings, text):
        calls.append(text)
        return [1.0, 0.0] if "accountability" in text or "ownership" in text else [0.0, 1.0]

    monkeypatch.setattr("app.modules.outreach.retrieval.embed_text", vectors)
    settings = Settings(retrieval_cache_dir=tmp_path)
    items = [
        {"entry_id": "relevant", "content": {"topic": "ownership"}},
        {"entry_id": "unrelated", "content": {"topic": "compensation"}},
    ]
    result, trace = hybrid_rank(settings, "accountability", items)
    assert trace["mode"] == "hybrid"
    assert [m["entry_id"] for m in result] == ["relevant"]
    assert result[0]["retrieval"]["lexical_score"] == 0
    count = len(calls)
    hybrid_rank(settings, "accountability", items)
    assert len(calls) == count + 1  # Only the new query, not documents.
    items[0]["content"]["topic"] = "ownership changed"
    hybrid_rank(settings, "accountability", items)
    assert "ownership changed" in calls[-1]


def test_embedding_failure_is_explicit_lexical_degradation(tmp_path, monkeypatch):
    def fail(*a):
        raise ModelUnavailable("EMBEDDING_HTTP_404")

    monkeypatch.setattr("app.modules.outreach.retrieval.embed_text", fail)
    result, trace = hybrid_rank(
        Settings(retrieval_cache_dir=tmp_path),
        "personal contribution",
        [{"entry_id": "m1", "content": {"topic": "personal contribution"}}],
    )
    assert trace["mode"] == "lexical_degraded"
    assert trace["error_code"] == "EMBEDDING_HTTP_404"
    assert result[0]["entry_id"] == "m1"
