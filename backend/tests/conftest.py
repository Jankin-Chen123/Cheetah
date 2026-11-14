"""Keep unit tests isolated from local provider selection and real network calls."""

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def isolate_provider_configuration(monkeypatch):
    monkeypatch.setenv("CHEETA_TEXT_PROVIDER", "bailian")
    monkeypatch.setenv("CHEETA_DIALOGUE_UNDERSTANDING_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
