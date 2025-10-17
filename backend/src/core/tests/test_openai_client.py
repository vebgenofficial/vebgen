# c/Users/USER/Documents/webagent/vebgen sharp updated/backend/src/core/tests/test_openai_client.py
import pytest
from unittest.mock import MagicMock, patch
from typing import List

# Import the client and exceptions to be tested
from src.core.openai_client import OpenAIClient, RateLimitError, AuthenticationError
from src.core.llm_client import ChatMessage

# Import the exceptions from the openai library that we expect to be caught
from openai import RateLimitError as OpenAIRateLimitError, AuthenticationError as OpenAIAuthenticationError

# --- Test Fixtures ---

@pytest.fixture
def mock_openai_constructor():
    """
    Provides a mock for the `openai.OpenAI` class constructor.
    This allows us to inspect how the client is instantiated and to mock the
    instance it returns.
    """
    # We patch 'src.core.openai_client.OpenAI' because that's the import path used by the module under test.
    with patch('src.core.openai_client.OpenAI') as mock_constructor:
        # Create a mock instance that the constructor will return.
        mock_instance = MagicMock()
        
        # Pre-configure a default successful response for the `chat` method.
        mock_instance.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="  Hello from OpenAI!  "))]
        )
        
        # Make the constructor return our mock instance.
        mock_constructor.return_value = mock_instance
        yield mock_constructor


# --- Test Cases for Initialization ---

class TestOpenAIClientInitialization:
    """Tests for the initialization logic of the OpenAIClient."""

    def test_init_success(self, mock_openai_constructor: MagicMock):
        """Tests that the client initializes successfully with valid parameters."""
        client = OpenAIClient(api_key="fake-openai-key", model="gpt-4o")
        
        # Assert that the OpenAI client was instantiated with the correct parameters.
        mock_openai_constructor.assert_called_once_with(
            api_key="fake-openai-key",
            base_url=None
        )
        assert client.model_id == "gpt-4o"
        assert client.client is not None

    def test_init_with_api_base(self, mock_openai_constructor: MagicMock):
        """Tests that a custom api_base is correctly passed to the OpenAI constructor."""
        client = OpenAIClient(api_key="fake-key", model="gpt-4", api_base="https://my-proxy.com/v1")
        mock_openai_constructor.assert_called_once_with(
            api_key="fake-key",
            base_url="https://my-proxy.com/v1"
        )

    @pytest.mark.parametrize("api_key", [None, "", 123])
    def test_init_invalid_api_key_fails(self, api_key):
        """Tests that initialization fails with an invalid or missing API key."""
        with pytest.raises(ValueError, match="requires a valid string API key"):
            OpenAIClient(api_key=api_key, model="gpt-4o")

    @pytest.mark.parametrize("model", [None, "", 123])
    def test_init_invalid_model_fails(self, model):
        """Tests that initialization fails with an invalid or missing model ID."""
        with pytest.raises(ValueError, match="requires a valid string model ID"):
            OpenAIClient(api_key="fake-key", model=model)

    def test_init_openai_constructor_fails(self, mock_openai_constructor: MagicMock):
        """Tests that a failure during OpenAI client instantiation is wrapped in a RuntimeError."""
        mock_openai_constructor.side_effect = Exception("SDK internal error")
        with pytest.raises(RuntimeError, match="Failed to initialize OpenAI client: SDK internal error"):
            OpenAIClient(api_key="fake-key", model="gpt-model")


# --- Test Cases for the chat() method ---

class TestOpenAIClientChat:
    """Tests for the chat completion functionality."""

    @pytest.fixture
    def client(self, mock_openai_constructor: MagicMock) -> OpenAIClient:
        """Provides an initialized OpenAIClient instance for chat tests."""
        return OpenAIClient(api_key="fake-key", model="gpt-4o")

    def test_chat_success(self, client: OpenAIClient):
        """Tests a successful chat call, verifying the payload and response handling."""
        messages: List[ChatMessage] = [{"role": "user", "content": "Hello"}]
        
        response = client.chat(messages, temperature=0.5)

        # Verify that the underlying client's method was called with the correct parameters.
        client.client.chat.completions.create.assert_called_once_with(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Hello"}],
            temperature=0.5
        )
        
        # Verify the response is correctly parsed and stripped.
        assert response == {"role": "assistant", "content": "Hello from OpenAI!"}

    def test_chat_with_system_prompt(self, client: OpenAIClient):
        """Tests that system prompts are correctly included in the payload."""
        messages: List[ChatMessage] = [
            {"role": "system", "content": "You are a bot."},
            {"role": "user", "content": "Hello"}
        ]
        client.chat(messages)
        
        # The `create` method should be called with the system prompt as the first message.
        client.client.chat.completions.create.assert_called_once()
        call_args = client.client.chat.completions.create.call_args[1]
        assert call_args['messages'][0] == {"role": "system", "content": "You are a bot."}

    def test_chat_empty_messages_fails(self, client: OpenAIClient):
        """Tests that calling chat with an empty list raises a ValueError."""
        with pytest.raises(ValueError, match="empty or invalid messages list"):
            client.chat([])

    def test_chat_handles_rate_limit_error(self, client: OpenAIClient):
        """Tests that an OpenAIRateLimitError is correctly caught and re-raised as our custom RateLimitError."""
        client.client.chat.completions.create.side_effect = OpenAIRateLimitError("Rate limit exceeded", response=MagicMock(), body=None)
        
        with pytest.raises(RateLimitError, match="OpenAI API Rate Limit Exceeded"):
            client.chat([{"role": "user", "content": "test"}])

    def test_chat_handles_authentication_error(self, client: OpenAIClient):
        """Tests that an OpenAIAuthenticationError is correctly caught and re-raised as our custom AuthenticationError."""
        client.client.chat.completions.create.side_effect = OpenAIAuthenticationError("Invalid API Key", response=MagicMock(), body=None)
        
        with pytest.raises(AuthenticationError, match="OpenAI API Authentication Failed"):
            client.chat([{"role": "user", "content": "test"}])

    def test_chat_handles_no_choices_in_response(self, client: OpenAIClient):
        """Tests that a response with an empty 'choices' list raises a RuntimeError."""
        client.client.chat.completions.create.return_value = MagicMock(choices=[])
        
        with pytest.raises(RuntimeError, match="OpenAI response contained no choices"):
            client.chat([{"role": "user", "content": "test"}])

    def test_chat_handles_other_exceptions(self, client: OpenAIClient):
        """Tests that any other unexpected exception is wrapped in a RuntimeError."""
        client.client.chat.completions.create.side_effect = Exception("A generic network error")
        
        with pytest.raises(RuntimeError, match="Unexpected error during API call to OpenAI"):
            client.chat([{"role": "user", "content": "test"}])