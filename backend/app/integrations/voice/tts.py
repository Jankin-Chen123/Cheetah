"""Bounded plain-text Qwen Audio TTS over the confirmed workspace."""

import json
import time
from urllib.parse import urlparse
from uuid import uuid4

from websockets.sync.client import connect

from app.core.config import Settings


def synthesize_question(settings: Settings, text: str):
    if not text.strip() or len(text) > 1000:
        raise ValueError("SPEECH_TEXT_INVALID")
    if not settings.bailian_api_key or not settings.bailian_base_url:
        raise RuntimeError("TTS_NOT_CONFIGURED")
    parsed = urlparse(settings.bailian_base_url)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith(
        ".cn-beijing.maas.aliyuncs.com"
    ):
        raise RuntimeError("CONFIRMED_BEIJING_WORKSPACE_REQUIRED")
    task_id = str(uuid4())
    model = "qwen-audio-3.1-tts-flash"
    chunks = []
    size = 0
    deadline = time.monotonic() + 45
    with connect(
        f"wss://{parsed.hostname}/api-ws/v1/inference",
        additional_headers={
            "Authorization": "Bearer " + settings.bailian_api_key.get_secret_value()
        },
        open_timeout=15,
        close_timeout=3,
        max_size=1500000,
    ) as socket:

        def send(action, payload):
            socket.send(
                json.dumps(
                    {
                        "header": {"action": action, "task_id": task_id, "streaming": "duplex"},
                        "payload": payload,
                    }
                )
            )

        send(
            "run-task",
            {
                "task_group": "audio",
                "task": "tts",
                "function": "SpeechSynthesizer",
                "model": model,
                "input": {},
                "parameters": {
                    "text_type": "PlainText",
                    "voice": "longanhuan_v3.1",
                    "format": "pcm",
                    "sample_rate": 24000,
                },
            },
        )
        started = False
        while time.monotonic() < deadline:
            event = socket.recv(timeout=min(15, max(0.1, deadline - time.monotonic())))
            if isinstance(event, bytes):
                size += len(event)
                if size > 24000 * 2 * 120:
                    raise RuntimeError("TTS_OUTPUT_LIMIT")
                chunks.append(event)
                continue
            data = json.loads(event)
            header = data.get("header", {})
            if header.get("task_id") != task_id:
                raise RuntimeError("TTS_TASK_MISMATCH")
            if header.get("event") == "task-failed":
                raise RuntimeError("TTS_PROVIDER_ERROR")
            if header.get("event") == "task-started" and not started:
                started = True
                send("continue-task", {"input": {"text": text}})
                send("finish-task", {"input": {}})
            if header.get("event") == "task-finished":
                if not started or not size:
                    raise RuntimeError("TTS_EMPTY")
                return {
                    "pcm": b"".join(chunks),
                    "sample_rate": 24000,
                    "model": model,
                    "source_mode": "live",
                    "telephone_line": False,
                }
    raise RuntimeError("TTS_DURATION_LIMIT")
