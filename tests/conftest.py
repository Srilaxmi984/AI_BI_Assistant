"""
conftest.py - keeps every test off the real Gemini API.

Without this, any test that sends an unrecognised question calls Gemini whenever a
real key is present in .env. That makes the tests slow (each call waits for a reply),
unpredictable (the model's wording changes) and dependent on the network.

Here the Gemini client is replaced by one that fails immediately, exactly like an
unreachable API. Tests that need a model reply mock it themselves (for example by
patching LLMClient or LLMClient.generate_sql), and those patches still work.
"""
from unittest.mock import patch

import pytest


class _OfflineGenAIClient:
    """Stands in for google.genai.Client: every request fails at once."""

    def __init__(self, *args, **kwargs):
        self.models = self

    def generate_content(self, *args, **kwargs):
        raise ConnectionError("Gemini is not reachable in tests")


@pytest.fixture(autouse=True)
def no_real_gemini_calls():
    with patch("src.llm_client.genai.Client", _OfflineGenAIClient), \
         patch("src.llm_client.GOOGLE_API_KEY", "test-key"), \
         patch("src.llm_client.LLM_ENABLED", True):
        yield