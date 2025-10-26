# backend/src/core/tests/test_hf_client.py
import pytest
from unittest.mock import MagicMock, patch
import json
import requests

# Import the client and exceptions to be tested
from src.core.hf_client import HuggingFaceClient, RateLimitError, AuthenticationError
from src.core.llm_client import ChatMessage

# --- Test Fixtures ---

@pytest.fixture
def mock_requests_session():
    """Mocks requests.Session to control API responses and prevent real network calls."""
    with patch('src.core.hf_client.requests.Session') as mock_session_constructor:
        mock_session_instance = MagicMock()
        
        # Default successful response for text-generation
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"generated_text": "  Hello from Hugging Face!  "}]
        mock_response.raise_for_status.return_value = None
        
        mock_session_instance.post.return_value = mock_response
        mock_session_constructor.return_value = mock_session_instance
        yield mock_session_instance

# --- Test Cases for Initialization ---

class TestHuggingFaceClientInitialization:
    """Tests for the initialization logic of the HuggingFaceClient."""

    def test_init_success(self, mock_requests_session: MagicMock):
        """Tests successful initialization with valid parameters."""
        client = HuggingFaceClient(api_token="hf_fake_token", model="test/model")
        assert client.model == "test/model"
        assert client.api_token == "hf_fake_token"
        assert client.api_endpoint == "https://api-inference.huggingface.co/models/test/model"
        
        # Verify that the session headers were updated correctly
        mock_requests_session.headers.update.assert_called_with({
            'Authorization': 'Bearer hf_fake_token',
            'Content-Type': 'application/json',
        })

    @pytest.mark.parametrize("api_token", [None, "", 123])
    def test_init_invalid_api_token_fails(self, api_token):
        """Tests that initialization fails with an invalid or missing API token."""
        with pytest.raises(ValueError, match="requires a valid string API token"):
            HuggingFaceClient(api_token=api_token, model="some/model")

    @pytest.mark.parametrize("model", [None, "", 123])
    def test_init_invalid_model_fails(self, model):
        """Tests that initialization fails with an invalid or missing model ID."""
        with pytest.raises(ValueError, match="requires a valid string model ID"):
            HuggingFaceClient(api_token="hf_fake_token", model=model)

# --- Test Cases for Prompt Formatting ---

class TestHuggingFaceClientFormatting:
    """Tests the internal prompt formatting logic."""

    @pytest.fixture
    def client(self) -> HuggingFaceClient:
        """Provides a client instance for formatting tests without needing mocks."""
        return HuggingFaceClient(api_token="hf_fake_token", model="test/model")

    def test_format_messages_for_hf(self, client: HuggingFaceClient):
        """Tests that messages are formatted into the expected string format."""
        messages: list[ChatMessage] = [
            {"role": "system", "content": "You are a bot."},
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "name": "Tester", "content": "How are you?"}
        ]
        
        expected_prompt = (
            "System: You are a bot.\n"
            "User: Hello!\n"
            "Assistant: Hi there!\n"
            "Tester: How are you?\n" # Should use 'name' if available
            "Assistant:"
        )
        
        formatted_prompt = client._format_messages_for_hf(messages)
        assert formatted_prompt == expected_prompt

# --- Test Cases for the chat() method ---

class TestHuggingFaceClientChat:
    """Tests for the chat completion functionality."""

    @pytest.fixture
    def client(self, mock_requests_session: MagicMock) -> HuggingFaceClient:
        """Provides an initialized HuggingFaceClient instance for chat tests."""
        return HuggingFaceClient(api_token="hf_fake_token", model="test/model")

    def test_chat_success(self, client: HuggingFaceClient, mock_requests_session: MagicMock):
        """Tests a successful chat call, verifying the payload and response handling."""
        messages: list[ChatMessage] = [{"role": "user", "content": "Hello"}]
        
        response = client.chat(messages, temperature=0.5)

        mock_requests_session.post.assert_called_once()
        call_kwargs = mock_requests_session.post.call_args.kwargs
        
        # Verify the payload sent to the API
        assert call_kwargs['json']['inputs'] == "User: Hello\nAssistant:"
        assert call_kwargs['json']['parameters']['temperature'] == 0.5
        assert call_kwargs['json']['parameters']['return_full_text'] is False
        assert call_kwargs['json']['options']['wait_for_model'] is True
        
        # Verify the response is correctly parsed and stripped
        assert response == {"role": "assistant", "content": "Hello from Hugging Face!"}

    def test_chat_empty_messages_fails(self, client: HuggingFaceClient):
        """Tests that calling chat with an empty or invalid list raises a ValueError."""
        with pytest.raises(ValueError, match="empty or invalid messages list"):
            client.chat([])
        with pytest.raises(ValueError, match="No valid messages found"):
            client.chat([{"foo": "bar"}]) # type: ignore

    @patch('time.sleep')
    def test_chat_retries_on_server_error(self, mock_sleep, client: HuggingFaceClient, mock_requests_session: MagicMock):
        """Tests that the client retries on 5xx server errors."""
        mock_response_fail = MagicMock()
        mock_http_error = requests.exceptions.HTTPError("Server Error")
        mock_http_error.response = MagicMock(status_code=503)
        mock_response_fail.raise_for_status.side_effect = mock_http_error

        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = [{"generated_text": "Success!"}]

        mock_requests_session.post.side_effect = [mock_response_fail, mock_response_fail, mock_response_success]

        response = client.chat([{"role": "user", "content": "test"}])

        assert mock_requests_session.post.call_count == 3
        assert response['content'] == "Success!"

    @patch('time.sleep')
    def test_chat_fails_after_max_retries(self, mock_sleep, client: HuggingFaceClient, mock_requests_session: MagicMock):
        """Tests that the client raises the last known error after exhausting all retries."""
        mock_response_fail = MagicMock()
        mock_http_error = requests.exceptions.HTTPError("Service Unavailable")
        mock_http_error.response = MagicMock(status_code=503)
        mock_response_fail.raise_for_status.side_effect = mock_http_error
        mock_requests_session.post.return_value = mock_response_fail

        # The client will retry on the 503 error. After the final attempt, it should
        # re-raise the last known exception, which is the HTTPError.
        with pytest.raises(requests.exceptions.HTTPError, match="Service Unavailable"):
            client.chat([{"role": "user", "content": "test"}])
        
        assert mock_requests_session.post.call_count == client.max_retries

    def test_chat_handles_rate_limit_error(self, client: HuggingFaceClient, mock_requests_session: MagicMock):
        """Tests that an HTTP 429 is correctly raised as our custom RateLimitError."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.json.return_value = {"error": "Rate limit exceeded"}
        mock_requests_session.post.return_value = mock_response

        with pytest.raises(RateLimitError, match="HF API Rate Limit Exceeded"):
            client.chat([{"role": "user", "content": "test"}])

    def test_chat_handles_authentication_error(self, client: HuggingFaceClient, mock_requests_session: MagicMock):
        """Tests that an HTTP 401 is raised as our custom AuthenticationError."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": "Authorization header is invalid"}
        mock_requests_session.post.return_value = mock_response

        with pytest.raises(AuthenticationError, match="HF API Authentication Failed"):
            client.chat([{"role": "user", "content": "test"}])

    @patch('time.sleep')
    def test_chat_handles_model_loading_error(self, mock_sleep, client: HuggingFaceClient, mock_requests_session: MagicMock):
        """Tests that a 200 OK with a 'model is loading' error message triggers a retry."""
        mock_response_loading = MagicMock()
        mock_response_loading.status_code = 200
        mock_response_loading.json.return_value = {"error": "Model test/model is currently loading", "estimated_time": 20.0}

        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = [{"generated_text": "Success!"}]

        mock_requests_session.post.side_effect = [mock_response_loading, mock_response_success]

        response = client.chat([{"role": "user", "content": "test"}])

        assert mock_requests_session.post.call_count == 2
        assert response['content'] == "Success!"
        mock_sleep.assert_called_once()

    @patch('time.sleep')
    def test_chat_handles_invalid_response_structure(self, mock_sleep, client: HuggingFaceClient, mock_requests_session: MagicMock):
        """Tests that a response with an invalid structure is retried and then raises an error."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "wrong_format"} # Missing list or 'generated_text'
        mock_requests_session.post.return_value = mock_response

        # The client will retry on the invalid structure. After the final attempt, it should
        # re-raise the last known exception, which is the ValueError.
        with pytest.raises(ValueError, match="Invalid HF response structure: Unexpected format"):
            client.chat([{"role": "user", "content": "test"}])
        
        assert mock_requests_session.post.call_count == client.max_retries