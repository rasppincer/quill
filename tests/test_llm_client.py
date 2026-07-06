import pytest
from unittest.mock import patch
from quill.llm import LLMClient
from quill.db import db_session

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

def test_chat_writes_agent_log_to_db():
    from quill.models import Project, DocumentNode, AgentLog
    
    # Setup test project and document node using the database session
    project = Project(id="p-1", title="Test Project")
    node = DocumentNode(id="n-1", project_id="p-1", title="Test Node")
    db_session.add_all([project, node])
    db_session.commit()
    
    client = LLMClient(api_base="http://localhost:1234/v1", api_key="test", model="test-model")
    
    class MockUsage:
        prompt_tokens = 50
        completion_tokens = 25

    class MockMessage:
        content = "Generated text"

    class MockChoice:
        message = MockMessage()

    class MockResponse:
        choices = [MockChoice()]
        usage = MockUsage()
    
    with patch("litellm.completion", return_value=MockResponse()), \
         patch("litellm.completion_cost", return_value=0.0015):
        
        response = client.chat(
            system="Sys prompt",
            user="User prompt",
            piece_id="n-1",
            stage="draft",
            call_type="generate",
            trace_id="tr-999"
        )
        
        assert response == "Generated text"
        
        # Retrieve written AgentLog from the shared db session
        logs = db_session.query(AgentLog).filter_by(trace_id="tr-999").all()
        assert len(logs) == 1
        log = logs[0]
        assert log.project_id == "p-1"
        assert log.document_node_id == "n-1"
        assert log.stage == "draft"
        assert log.call_type == "generate"
        assert log.system_prompt == "Sys prompt"
        assert log.user_prompt == "User prompt"
        assert log.prompt_tokens == 50
        assert log.completion_tokens == 25
        assert log.cost == 0.0015
        assert log.output == "Generated text"
