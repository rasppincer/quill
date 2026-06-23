"""Integration test that hits a real LLM.

Requires a local LLM server at 192.168.0.3:1234 (OpenAI-compatible).
Skipped automatically when the server is unreachable.
"""
import json
import os
import pytest
import urllib.request

LLM_BASE = os.environ.get("QUILL_TEST_LLM_BASE", "http://192.168.0.3:1234")
LLM_MODEL = os.environ.get("QUILL_TEST_LLM_MODEL", "google/gemma-4-e4b")


def _llm_available() -> bool:
    """Check if the local LLM server is reachable."""
    try:
        req = urllib.request.Request(f"{LLM_BASE}/v1/models", method="GET")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _llm_available(),
    reason="Local LLM server not available at " + LLM_BASE,
)


class TestLLMIntegration:
    """Smoke tests against a real LLM."""

    def test_generate_returns_content(self):
        """LLM generates non-empty content from a simple prompt."""
        from quill.llm import LLMClient

        client = LLMClient(
            api_base=f"{LLM_BASE}/v1",
            api_key="",
            model=LLM_MODEL,
            temperature=0.7,
            max_tokens=200,
        )
        response = client.chat(
            system="You are a creative writer.",
            user="Write a 3-sentence story about a cat. Return ONLY the story, no JSON.",
        )
        assert len(response) > 50, f"Response too short: {len(response)} chars"

    def test_json_parsing_from_llm(self):
        """LLM returns JSON when asked, and agent parser handles it."""
        from quill.llm import LLMClient
        from quill.agent import parse_agent_response

        client = LLMClient(
            api_base=f"{LLM_BASE}/v1",
            api_key="",
            model=LLM_MODEL,
            temperature=0.3,
            max_tokens=300,
        )
        system = (
            "You are a writing evaluator. Return ONLY a JSON object, nothing else.\n"
            'Format: {"decision": "advance" or "loop_back", "critique": "your analysis"}'
        )
        user = "Critique this text: The cat sat on the mat. It was a sunny day."
        response = client.chat(system=system, user=user)

        result = parse_agent_response(response)
        assert result.decision in ("advance", "loop_back")
        # Critique may be empty if LLM returns minimal JSON
        assert isinstance(result.critique, str)

    def test_prompt_template_rendering(self):
        """Prompt templates render correctly with real content."""
        from quill.prompt_builder import render_prompt

        template = (
            "You are reviewing: {{TITLE}}\n"
            "Genre: {{GENRE}}\n"
            "{% if is_looping %}\n"
            "Previous attempt was rejected. Feedback: {{GENERATED}}\n"
            "{% endif %}\n"
            "Content: {{CONTENT}}"
        )
        ctx = {
            "TITLE": "Test Story",
            "GENRE": "fiction",
            "is_looping": False,
            "CONTENT": "The cat sat on the mat.",
        }
        result = render_prompt(template, ctx)
        assert "Test Story" in result
        assert "fiction" in result
        assert "Previous attempt" not in result

        # Test loop context
        ctx["is_looping"] = True
        ctx["GENERATED"] = "Needs more detail."
        result = render_prompt(template, ctx)
        assert "Previous attempt" in result
        assert "Needs more detail" in result
