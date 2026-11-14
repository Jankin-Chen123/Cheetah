"""Explicit simulation controls; live telephone transport remains unavailable."""

from typing import Protocol


class VoiceAdapter(Protocol):
    def create_call(self, request_id: str) -> dict: ...
    def get_status(self, session_id: str) -> dict: ...
    def stop_call(self, session_id: str) -> dict: ...


class UnconfiguredVoice:
    def create_call(self, request_id: str) -> dict:
        raise RuntimeError("TELEPHONE_LINE_NOT_CONFIGURED")

    def get_status(self, session_id: str) -> dict:
        raise RuntimeError("TELEPHONE_LINE_NOT_CONFIGURED")

    def stop_call(self, session_id: str) -> dict:
        raise RuntimeError("TELEPHONE_LINE_NOT_CONFIGURED")


class MockVoice:
    """Stateless deterministic transport simulation; caller persists every transition."""

    def create_call(self, request_id: str) -> dict:
        return {"session_id": f"mock-{request_id}", "status": "connected", "source_mode": "mock"}

    def get_status(self, session_id: str) -> dict:
        return {"session_id": session_id, "status": "in_progress", "source_mode": "mock"}

    def stop_call(self, session_id: str) -> dict:
        return {
            "session_id": session_id,
            "stop_status": "confirmed",
            "status": "completed",
            "source_mode": "mock",
        }
