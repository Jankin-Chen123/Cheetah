import io
import json
from urllib.error import HTTPError

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.integrations.bailian import ModelUnavailable, generate_json


@pytest.mark.parametrize("phase", ["open", "read"])
def test_remote_disconnect_is_a_stable_failure_without_automatic_retry(monkeypatch, phase):
    from http.client import RemoteDisconnected

    calls = []

    class BrokenResponse(io.BytesIO):
        def read(self, *args):
            raise RemoteDisconnected("sensitive provider address")

    class Opener:
        def open(self, *args, **kwargs):
            calls.append(True)
            if phase == "open":
                raise RemoteDisconnected("sensitive provider address")
            return BrokenResponse()

    monkeypatch.setattr("app.integrations.bailian.build_opener", lambda *args: Opener())
    settings = Settings(
        text_provider="bailian",
        bailian_api_key=SecretStr("fixture-only"),
        bailian_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        bailian_model="fixture",
        bailian_region="cn-beijing",
    )
    with pytest.raises(ModelUnavailable) as caught:
        generate_json(settings, "test", {})
    assert str(caught.value) == "MODEL_NETWORK_UNAVAILABLE"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "reason,code",
    [
        ("length", "MODEL_OUTPUT_TRUNCATED"),
        ("content_filter", "MODEL_OUTPUT_FILTERED"),
    ],
)
def test_incomplete_provider_output_is_rejected_even_when_json_parses(monkeypatch, reason, code):
    class Response(io.BytesIO):
        pass

    class Opener:
        def open(self, request, timeout):
            return Response(
                json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": reason,
                                "message": {"content": '{"partial":true}'},
                            }
                        ]
                    }
                ).encode()
            )

    monkeypatch.setattr("app.integrations.bailian.build_opener", lambda *args: Opener())
    settings = Settings(
        text_provider="bailian",
        bailian_api_key=SecretStr("fixture-only"),
        bailian_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        bailian_model="fixture",
        bailian_region="cn-beijing",
    )
    with pytest.raises(ModelUnavailable, match=code):
        generate_json(settings, "test", {})


def test_missing_configuration_does_not_fabricate_model_result():
    settings = Settings(
        bailian_api_key=None, bailian_base_url=None, bailian_model=None, bailian_region=None
    )
    with pytest.raises(ModelUnavailable, match="MODEL_NOT_CONFIGURED"):
        generate_json(settings, "test", {})


def test_untrusted_endpoint_rejected_before_credential_transmission():
    settings = Settings(
        bailian_api_key=SecretStr("fixture-only"),
        bailian_base_url="https://example.com/compatible-mode/v1",
        bailian_model="fixture",
        bailian_region="fixture",
    )
    with pytest.raises(ModelUnavailable, match="MODEL_ENDPOINT_NOT_ALLOWED"):
        generate_json(settings, "test", {})


def test_provider_error_exposes_only_safe_code(monkeypatch):
    class FailingOpener:
        def open(self, request, timeout):
            raise HTTPError(
                "https://example.invalid",
                403,
                "denied",
                {},
                io.BytesIO(
                    b'{"error":{"code":"AccessDenied.Unpurchased","message":"sensitive detail"}}'
                ),
            )

    monkeypatch.setattr("app.integrations.bailian.build_opener", lambda *args: FailingOpener())
    settings = Settings(
        bailian_api_key=SecretStr("fixture-only"),
        bailian_base_url="https://fixture.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        bailian_model="fixture",
        bailian_region="cn-beijing",
    )
    with pytest.raises(ModelUnavailable) as caught:
        generate_json(settings, "test", {})
    assert str(caught.value) == "MODEL_HTTP_403_AccessDenied.Unpurchased"
    assert "sensitive" not in str(caught.value)
