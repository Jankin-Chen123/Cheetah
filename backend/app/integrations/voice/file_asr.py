"""Official Volcengine flash file ASR: private bytes, no public object URL."""

import base64
import json

import httpx


class FileAsrError(Exception):
    def __init__(self, code, *, uncertain=False):
        super().__init__(code)
        self.code, self.uncertain = code, uncertain


def recognize(settings, data: bytes, request_id: str, owner_id: str):
    if settings.file_asr_provider != "volcengine" or not settings.volc_speech_api_key:
        raise FileAsrError("ASR_NOT_CONFIGURED")
    try:
        with httpx.Client(
            timeout=settings.file_asr_timeout_seconds, follow_redirects=False
        ) as client:
            with client.stream(
                "POST",
                "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash",
                headers={
                    "X-Api-Key": settings.volc_speech_api_key.get_secret_value(),
                    "X-Api-Resource-Id": settings.volc_file_asr_resource_id,
                    "X-Api-Request-Id": request_id,
                    "X-Api-Sequence": "-1",
                },
                json={
                    "user": {"uid": owner_id},
                    "audio": {"data": base64.b64encode(data).decode("ascii")},
                    "request": {
                        "model_name": "bigmodel",
                        "show_utterances": True,
                        "enable_ddc": False,
                        "enable_itn": True,
                        "enable_punc": True,
                    },
                },
            ) as response:
                code = response.headers.get("X-Api-Status-Code")
                if code != "20000000":
                    error = {
                        "20000003": "ASR_NO_SPEECH",
                        "45000030": "ASR_RESOURCE_NOT_GRANTED",
                        "45000001": "ASR_INVALID_AUDIO",
                        "45000002": "ASR_INVALID_AUDIO",
                        "45000151": "ASR_UNSUPPORTED_FORMAT",
                    }.get(code, "ASR_PROVIDER_REJECTED")
                    raise FileAsrError(
                        error, uncertain=not code or code in {"20000001", "20000002"}
                    )
                if response.status_code != 200:
                    raise FileAsrError("ASR_RESPONSE_INVALID")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 2_000_000:
                        raise FileAsrError("ASR_RESULT_TOO_LARGE")
                    chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
        return parse_result(payload)
    except FileAsrError:
        raise
    except (httpx.HTTPError, OSError):
        raise FileAsrError("ASR_EXTERNAL_RESULT_UNKNOWN", uncertain=True) from None
    except (ValueError, TypeError, KeyError, AttributeError):
        raise FileAsrError("ASR_RESPONSE_INVALID") from None


def parse_result(payload, *, maximum_duration_ms=7_200_000):
    try:
        result = payload["result"]
        text = result["text"]
        if not isinstance(text, str) or not text.strip():
            raise FileAsrError("ASR_NO_SPEECH")
        if len(text) > 30000:
            raise FileAsrError("ASR_TEXT_TOO_LONG")
        segments = []
        for row in result.get("utterances", []):
            if not isinstance(row, dict) or not isinstance(row.get("text"), str):
                raise FileAsrError("ASR_RESPONSE_INVALID")
            start, end = row.get("start_time"), row.get("end_time")
            if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start <= end:
                raise FileAsrError("ASR_RESPONSE_INVALID")
            segments.append({"text": row["text"], "start_ms": start, "end_ms": end})
        duration = payload.get("audio_info", {}).get("duration")
        if duration is not None and (
            not isinstance(duration, int) or not 0 < duration <= maximum_duration_ms
        ):
            raise FileAsrError("ASR_DURATION_LIMIT")
        return {"transcript": text.strip(), "segments": segments, "duration_ms": duration}
    except FileAsrError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        raise FileAsrError("ASR_RESPONSE_INVALID") from None


def standard_request(settings, request_id, *, audio_url=None, audio_format=None):
    """Submit once; subsequent requests only query that persisted provider request ID."""
    if settings.file_asr_provider != "volcengine" or not settings.volc_speech_api_key:
        raise FileAsrError("ASR_NOT_CONFIGURED")
    phase = "submit" if audio_url is not None else "query"
    body = (
        {
            "audio": {"url": audio_url, "format": audio_format},
            "request": {"model_name": "bigmodel", "show_utterances": True, "enable_ddc": False},
        }
        if audio_url
        else {}
    )
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            with client.stream(
                "POST",
                "https://openspeech.bytedance.com/api/v3/auc/bigmodel/" + phase,
                headers={
                    "X-Api-Key": settings.volc_speech_api_key.get_secret_value(),
                    "X-Api-Resource-Id": settings.volc_file_asr_standard_resource_id,
                    "X-Api-Request-Id": request_id,
                    "X-Api-Sequence": "-1",
                },
                json=body,
            ) as response:
                code = response.headers.get("X-Api-Status-Code")
                if code in {"20000001", "20000002"}:
                    return None
                if code != "20000000":
                    mapped = {
                        "45000030": "ASR_RESOURCE_NOT_GRANTED",
                        "20000003": "ASR_NO_SPEECH",
                        "45000151": "ASR_UNSUPPORTED_FORMAT",
                        "45000001": "ASR_INVALID_AUDIO",
                    }
                    raise FileAsrError(
                        mapped.get(code, "ASR_PROVIDER_REJECTED"), uncertain=not code
                    )
                if response.status_code != 200:
                    raise FileAsrError("ASR_RESPONSE_INVALID")
                if phase == "submit":
                    return None
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 2_000_000:
                        raise FileAsrError("ASR_RESULT_TOO_LARGE")
                    chunks.append(chunk)
        return parse_result(json.loads(b"".join(chunks)), maximum_duration_ms=18_000_000)
    except FileAsrError:
        raise
    except (httpx.HTTPError, OSError):
        raise FileAsrError("ASR_EXTERNAL_RESULT_UNKNOWN", uncertain=True) from None
    except (ValueError, TypeError, KeyError, AttributeError):
        raise FileAsrError("ASR_RESPONSE_INVALID") from None
