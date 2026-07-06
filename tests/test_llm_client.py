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

def test_chat_logger_fn_formatting_and_masking():
    from quill.models import Project, DocumentNode
    
    # Setup test project and document node using the database session
    project = Project(id="p-2", title="Test Project 2")
    node = DocumentNode(id="n-2", project_id="p-2", title="Test Node 2")
    db_session.add_all([project, node])
    db_session.commit()
    
    client = LLMClient(
        api_base="http://localhost:1234/v1",
        api_key="sk-mysecretapikey12345",
        model="test-model"
    )
    
    class MockMessage:
        content = "Generated text"

    class MockChoice:
        message = MockMessage()

    class MockResponse:
        choices = [MockChoice()]
        usage = None
    
    with patch("litellm.completion", return_value=MockResponse()) as mock_completion, \
         patch("litellm.completion_cost", return_value=0.0), \
         patch("quill.agent.load_model_config", return_value={"debug_litellm": True}):
        
        client.chat(system="Sys", user="User", piece_id="n-2")
        
        # Ensure completion was called
        assert mock_completion.called
        # Retrieve the logger_fn passed to completion
        logger_fn = mock_completion.call_args.kwargs.get("logger_fn")
        assert logger_fn is not None
        
        # Test logger_fn behavior
        mock_model_call_dict = {
            "log_event_type": "pre_api_call",
            "additional_args": {
                "api_base": "http://localhost:1234/v1",
                "complete_input_dict": {
                    "model": "test-model",
                    "messages": [{"role": "system", "content": "Sys"}, {"role": "user", "content": "User"}]
                }
            },
            "litellm_params": {
                "api_key": "sk-mysecretapikey12345",
                "api_base": "http://localhost:1234/v1"
            }
        }
        
        # Patch the get_piece_logger to check what was logged
        with patch("quill.llm.get_piece_logger") as mock_get_piece_logger:
            logger_fn(mock_model_call_dict)
            
            # Ensure get_piece_logger was called
            mock_get_piece_logger.assert_called_once_with("llm", "n-2")
            mock_logger_instance = mock_get_piece_logger.return_value
            mock_logger_instance.info.assert_called_once()
            
            log_arg = mock_logger_instance.info.call_args[0][0]
            assert "curl -X POST" in log_arg
            assert "http://localhost:1234/v1/chat/completions" in log_arg
            # Ensure the API key is masked in the headers
            assert "Authorization" in log_arg
            assert "sk-m...2345" in log_arg
            assert "sk-mysecretapikey12345" not in log_arg


