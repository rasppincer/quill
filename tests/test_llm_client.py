import pytest
from unittest.mock import patch
from quill.llm import LLMClient

def test_chat_connection_error_on_litellm_failure():
    client = LLMClient(api_base="http://localhost:1234/v1", api_key="test", model="test-model")
    
    with patch("litellm.completion") as mock_completion:
        from litellm.exceptions import APIConnectionError
        mock_completion.side_effect = APIConnectionError(
            message="Connection failed",
            model="test-model",
            llm_provider="openai"
        )
        with pytest.raises(ConnectionError) as exc_info:
            client.chat(system="Sys", user="User")
        assert "LLM connection/API error" in str(exc_info.value)
