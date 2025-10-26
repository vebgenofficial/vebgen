# backend/src/core/tests/test_llm_client.py
import pytest
from unittest.mock import MagicMock, patch
from typing import List

# Import the client and exceptions to be tested
from src.core.llm_client import LlmClient, RateLimitError, AuthenticationError, ChatMessage

# Import requests exceptions to simulate network errors
import requests

# --- Test Fixtures ---

@pytest.fixture
def mock_requests_session():
    """Mocks requests.Session to control API responses and prevent real network calls."""
    with patch('src.core.llm_client.requests.Session') as mock_session_constructor:
        mock_session_instance = MagicMock()
        
        # Default successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "  Hello from OpenRouter!  "}}]
        }
        # Configure the mock to not raise for status on success
        mock_response.raise_for_status.return_value = None
        
        mock_session_instance.post.return_value = mock_response
        mock_session_constructor.return_value = mock_session_instance
        yield mock_session_instance


# --- Test Cases for Initialization ---

class TestLlmClientInitialization:
    """Tests for the initialization logic of the LlmClient."""

    def test_init_success(self, mock_requests_session: MagicMock):
        """Tests successful initialization with valid parameters."""
        client = LlmClient(api_key="fake-or-key", model="openrouter/model")
        assert client.model == "openrouter/model"
        assert client.api_key == "fake-or-key"
        assert "Bearer fake-or-key" not in client.session.headers.get("Authorization", "")

    def test_init_with_site_details(self, mock_requests_session: MagicMock):
        """Tests that site_url and site_title are correctly set as headers."""
        client = LlmClient(
            api_key="fake-key",
            model="some/model",
            site_url="https://my-app.com",
            site_title="My Awesome App"
        )
        mock_requests_session.headers.update.assert_called_with({
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://my-app.com',
            'X-Title': 'My Awesome App'
        })

    @pytest.mark.parametrize("api_key", [None, "", 123])
    def test_init_invalid_api_key_fails(self, api_key):
        """Tests that initialization fails with an invalid or missing API key."""
        with pytest.raises(ValueError, match="requires a valid string API key"):
            LlmClient(api_key=api_key, model="some/model")

    @pytest.mark.parametrize("model", [None, "", 123])
    def test_init_invalid_model_fails(self, model):
        """Tests that initialization fails with an invalid or missing model ID."""
        with pytest.raises(ValueError, match="requires a valid string model ID"):
            LlmClient(api_key="fake-key", model=model)


# --- Test Cases for the chat() method ---

class TestLlmClientChat:
    """Tests for the chat completion functionality."""

    @pytest.fixture
    def client(self, mock_requests_session: MagicMock) -> LlmClient:
        """Provides an initialized LlmClient instance for chat tests."""
        return LlmClient(api_key="fake-key", model="openrouter/model")

    def test_chat_success(self, client: LlmClient, mock_requests_session: MagicMock):
        """Tests a successful chat call, verifying the payload and response handling."""
        messages: List[ChatMessage] = [{"role": "user", "content": "Hello"}]
        
        response = client.chat(messages, temperature=0.5)

        # Verify that the post method was called with the correct parameters
        mock_requests_session.post.assert_called_once()
        call_kwargs = mock_requests_session.post.call_args.kwargs
        assert call_kwargs['json']['model'] == "openrouter/model"
        assert call_kwargs['json']['messages'] == messages
        assert call_kwargs['headers']['Authorization'] == "Bearer fake-key"
        
        # Verify the response is correctly parsed and stripped
        assert response == {"role": "assistant", "content": "Hello from OpenRouter!"}

    def test_chat_empty_messages_fails(self, client: LlmClient):
        """Tests that calling chat with an empty list raises a ValueError."""
        with pytest.raises(ValueError, match="empty or invalid messages list"):
            client.chat([])

    @patch('time.sleep')
    def test_chat_retries_on_server_error(self, mock_sleep, client: LlmClient, mock_requests_session: MagicMock):
        """Tests that the client retries on 5xx server errors."""
        # Simulate a 500 error twice, then a 200 success
        mock_response_fail = MagicMock()
        mock_http_error = requests.exceptions.HTTPError("Server Error")
        mock_http_error.response = MagicMock(status_code=500)
        mock_response_fail.raise_for_status.side_effect = mock_http_error

        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {"choices": [{"message": {"role": "assistant", "content": "Success!"}}]}

        mock_requests_session.post.side_effect = [mock_response_fail, mock_response_fail, mock_response_success]

        response = client.chat([{"role": "user", "content": "test"}])

        assert mock_requests_session.post.call_count == 3
        assert response['content'] == "Success!"

    @patch('time.sleep')
    def test_chat_fails_after_max_retries(self, mock_sleep, client: LlmClient, mock_requests_session: MagicMock):
        """Tests that the client raises an error after exhausting all retries."""
        mock_response_fail = MagicMock()
        mock_http_error = requests.exceptions.HTTPError("Service Unavailable")
        mock_http_error.response = MagicMock(status_code=503)
        mock_response_fail.raise_for_status.side_effect = mock_http_error

        mock_requests_session.post.return_value = mock_response_fail

        with pytest.raises(requests.exceptions.HTTPError):
            client.chat([{"role": "user", "content": "test"}])
        
        assert mock_requests_session.post.call_count == client.max_retries

    def test_chat_handles_rate_limit_error(self, client: LlmClient, mock_requests_session: MagicMock):
        """Tests that an HTTP 429 is correctly raised as our custom RateLimitError."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.json.return_value = {"error": {"message": "Rate limit exceeded"}}
        mock_requests_session.post.return_value = mock_response

        with pytest.raises(RateLimitError, match="API Rate Limit Exceeded"):
            client.chat([{"role": "user", "content": "test"}])

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_chat_handles_authentication_error(self, status_code, client: LlmClient, mock_requests_session: MagicMock):
        """Tests that HTTP 401 and 403 are raised as our custom AuthenticationError."""
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = {"error": {"message": "Invalid API Key"}}
        mock_requests_session.post.return_value = mock_response

        with pytest.raises(AuthenticationError, match="API Authentication Failed"):
            client.chat([{"role": "user", "content": "test"}])

    def test_chat_handles_invalid_response_structure(self, client: LlmClient, mock_requests_session: MagicMock):
        """Tests that a response with an invalid structure raises a RuntimeError after retries."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "wrong_format"} # Missing 'choices'
        mock_requests_session.post.return_value = mock_response

        # The client retries, then raises the last known specific error.
        with pytest.raises(RuntimeError, match="Invalid response structure from LLM: 'choices' missing or empty."):
            client.chat([{"role": "user", "content": "test"}])
        
        # Verify that the client did retry before failing.
        assert mock_requests_session.post.call_count == client.max_retries

    def test_chat_handles_network_error(self, client: LlmClient, mock_requests_session: MagicMock):
        """Tests that a generic requests.RequestException is wrapped in a RuntimeError."""
        mock_requests_session.post.side_effect = requests.exceptions.RequestException("A generic network error")
        
        with pytest.raises(RuntimeError, match="Unrecoverable network error"):
            client.chat([{"role": "user", "content": "test"}])