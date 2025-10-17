# c/Users/USER/Documents/webagent/vebgen sharp updated/backend/src/core/tests/test_google_genai_client.py
import pytest
from unittest.mock import MagicMock, patch
from typing import List

# Import the client and exceptions to be tested
from src.core.google_genai_client import GoogleGenAIClient, RateLimitError, AuthenticationError
from src.core.llm_client import ChatMessage

# Import the exceptions from the google library that we expect to be caught
try:
    from google.api_core import exceptions as google_exceptions
except ImportError:
    # Create dummy exceptions if the library isn't installed for test discovery
    class google_exceptions:
        class PermissionDenied(Exception): pass
        class ResourceExhausted(Exception): pass
        class DeadlineExceeded(Exception): pass

# --- Test Fixtures ---

@pytest.fixture
def mock_genai_module():
    """
    Provides a mock for the `google.generativeai` module used by the client.
    This allows us to inspect how the SDK is configured and to mock the
    GenerativeModel it returns.
    """
    # We patch 'src.core.google_genai_client.genai' as that's the import path used by the module under test.
    with patch('src.core.google_genai_client.genai') as mock_genai:
        # Create a mock for the GenerativeModel class
        mock_model_class = MagicMock(name="GenerativeModelClass")
        
        # --- FIX: Create two separate mock instances for the original and the temporary model ---
        # This is the instance for the client's main `self.model`
        mock_original_model_instance = MagicMock(name="OriginalModelInstance")
        # This is the instance created temporarily when a system prompt is used
        mock_new_model_instance = MagicMock(name="NewModelInstance")
        
        # Pre-configure a default successful response for the `generate_content` method
        # Both instances can share the same default response for simplicity.
        default_response = MagicMock(
            text="  Hello from Gemini!  ",
            candidates=[MagicMock()] # Must have at least one candidate to be valid
        )
        mock_original_model_instance.generate_content.return_value = default_response
        mock_new_model_instance.generate_content.return_value = default_response
        
        # --- FIX: Make the mock class return the correct instance based on call arguments ---
        def model_side_effect(*args, **kwargs):
            if 'system_instruction' in kwargs:
                return mock_new_model_instance
            return mock_original_model_instance
        mock_model_class.side_effect = model_side_effect
        mock_genai.GenerativeModel = mock_model_class
        # --- FIX: Mock the GenerationConfig to capture its arguments ---
        mock_genai.types.GenerationConfig = MagicMock(name="GenerationConfig")
        
        yield mock_genai


# --- Test Cases for Initialization ---

class TestGoogleGenAIClientInitialization:
    """Tests for the initialization logic of the GoogleGenAIClient."""

    def test_init_success(self, mock_genai_module: MagicMock):
        """Tests that the client initializes successfully with valid parameters."""
        client = GoogleGenAIClient(api_key="fake-gemini-key", model="gemini-1.5-pro")
        
        # Assert that the genai SDK was configured with the API key
        mock_genai_module.configure.assert_called_once_with(api_key="fake-gemini-key")
        
        # Assert that the GenerativeModel was instantiated with the correct model ID
        mock_genai_module.GenerativeModel.assert_called_once_with("gemini-1.5-pro")
        assert client.model_id == "gemini-1.5-pro"
        assert client.model is not None

    @pytest.mark.parametrize("api_key", [None, "", 123])
    def test_init_invalid_api_key_fails(self, api_key):
        """Tests that initialization fails with an invalid or missing API key."""
        with pytest.raises(ValueError, match="requires a valid string API key"):
            GoogleGenAIClient(api_key=api_key, model="gemini-1.5-pro")

    @pytest.mark.parametrize("model", [None, "", 123])
    def test_init_invalid_model_fails(self, model):
        """Tests that initialization fails with an invalid or missing model ID."""
        with pytest.raises(ValueError, match="requires a valid string model ID"):
            GoogleGenAIClient(api_key="fake-key", model=model)

    def test_init_sdk_configure_fails(self, mock_genai_module: MagicMock):
        """Tests that a failure during genai.configure is wrapped in a RuntimeError."""
        mock_genai_module.configure.side_effect = Exception("SDK internal error")
        with pytest.raises(RuntimeError, match="Failed to initialize Google GenAI client: SDK internal error"):
            GoogleGenAIClient(api_key="fake-key", model="gemini-model")


# --- Test Cases for the chat() method ---

class TestGoogleGenAIChat:
    """Tests for the chat completion functionality."""

    @pytest.fixture
    def client(self, mock_genai_module: MagicMock) -> GoogleGenAIClient:
        """Provides an initialized GoogleGenAIClient instance for chat tests."""
        return GoogleGenAIClient(api_key="fake-key", model="gemini-1.5-pro")

    def test_chat_success(self, client: GoogleGenAIClient, mock_genai_module: MagicMock):
        """Tests a successful chat call, verifying the payload and response handling."""
        messages: List[ChatMessage] = [{"role": "user", "content": "Hello"}]
        
        response = client.chat(messages, temperature=0.5)

        # Verify that the underlying client's method was called with the correct parameters
        client.model.generate_content.assert_called_once()
        # Assert that the GenerationConfig class was instantiated with the correct temperature
        mock_genai_module.types.GenerationConfig.assert_called_once_with(temperature=0.5)
        
        # Assert that the generate_content method was called with the correct contents
        client.model.generate_content.assert_called_once()
        called_kwargs = client.model.generate_content.call_args.kwargs
        assert called_kwargs['contents'] == [{"role": "user", "parts": [{"text": "Hello"}]}]
        
        # Verify the response is correctly parsed and stripped
        assert response == {"role": "assistant", "content": "Hello from Gemini!"}

    def test_chat_with_system_prompt(self, client: GoogleGenAIClient, mock_genai_module: MagicMock):
        """Tests that system prompts are correctly handled by creating a temporary model instance."""
        messages: List[ChatMessage] = [
            {"role": "system", "content": "You are a bot."},
            {"role": "user", "content": "Hello"}
        ]
        client.chat(messages)
        
        # The original model instance should NOT be called.
        client.model.generate_content.assert_not_called()
        
        # A new GenerativeModel instance should have been created with the system instruction.
        mock_genai_module.GenerativeModel.assert_any_call("gemini-1.5-pro", system_instruction="You are a bot.")
        # The `generate_content` method of the *new* instance (returned by the side_effect) should have been called.
        new_model_instance = mock_genai_module.GenerativeModel.side_effect(system_instruction="dummy")
        new_model_instance.generate_content.assert_called_once()

    def test_chat_empty_messages_fails(self, client: GoogleGenAIClient):
        """Tests that calling chat with an empty list raises a ValueError."""
        with pytest.raises(ValueError, match="empty or invalid messages list"):
            client.chat([])

    def test_chat_handles_permission_denied(self, client: GoogleGenAIClient):
        """Tests that a PermissionDenied error is re-raised as AuthenticationError."""
        client.model.generate_content.side_effect = google_exceptions.PermissionDenied("Invalid API Key")
        with pytest.raises(AuthenticationError, match="Google API Authentication Failed"):
            client.chat([{"role": "user", "content": "test"}])

    @pytest.mark.parametrize("sdk_error", [
        google_exceptions.ResourceExhausted("Quota exceeded"),
        google_exceptions.DeadlineExceeded("Request timed out")
    ])
    def test_chat_handles_rate_limit_and_timeout(self, client: GoogleGenAIClient, sdk_error):
        """Tests that ResourceExhausted and DeadlineExceeded are re-raised as RateLimitError."""
        client.model.generate_content.side_effect = sdk_error
        with pytest.raises(RateLimitError, match="Google API"):
            client.chat([{"role": "user", "content": "test"}])

    def test_chat_handles_blocked_response(self, client: GoogleGenAIClient):
        """Tests that a response with no candidates (blocked by safety settings) raises a RuntimeError."""
        client.model.generate_content.return_value = MagicMock(candidates=[])
        with pytest.raises(RuntimeError, match="Content blocked by Google's safety settings"):
            client.chat([{"role": "user", "content": "test"}])

    def test_chat_handles_other_exceptions(self, client: GoogleGenAIClient):
        """Tests that any other unexpected exception is wrapped in a RuntimeError."""
        client.model.generate_content.side_effect = Exception("A generic network error")
        with pytest.raises(RuntimeError, match="Unexpected error during API call to Google Gemini"):
            client.chat([{"role": "user", "content": "test"}])