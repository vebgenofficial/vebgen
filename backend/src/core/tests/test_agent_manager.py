# c/Users/USER/Documents/webagent/vebgen sharp updated/backend/src/core/tests/test_agent_manager.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Optional, Tuple, Callable, Awaitable, List

from src.core.agent_manager import AgentManager
from src.core.config_manager import ConfigManager
from src.core.llm_client import ChatMessage, AuthenticationError, RateLimitError

# --- Mock Fixtures ---

@pytest.fixture
def mock_config_manager():
    """Provides a mock ConfigManager with sample provider configurations."""
    mock = MagicMock(spec=ConfigManager)
    mock.providers_config = {
        "openai": {
            "display_name": "OpenAI",
            "api_key_name": "openai_api_key",
            "client_class": "OpenAIClient",
            "client_config": {},
        },
        "google": {
            "display_name": "Google",
            "api_key_name": "google_api_key",
            "client_class": "GoogleGenAIClient",
            "client_config": {},
        },
        "huggingface": {
            "display_name": "Hugging Face",
            "api_key_name": "hf_token",
            "client_class": "HuggingFaceClient",
            "client_config": {},
        },
        "openrouter": {
            "display_name": "OpenRouter",
            "api_key_name": "openrouter_api_key",
            "client_class": "LlmClient",
            "client_config": {"model_prefix": "openrouter/"},
        },
    }
    return mock

@pytest.fixture
def mock_show_input_prompt_cb():
    """Mocks the UI callback for prompting for an API key."""
    return MagicMock(spec=Callable[[str, bool, Optional[str]], Optional[str]])

@pytest.fixture
def mock_request_api_key_update_cb():
    """Mocks the async UI callback for handling API errors."""
    return AsyncMock(spec=Callable[[str, str, str], Awaitable[Tuple[Optional[str], bool]]])

@pytest.fixture(autouse=True)
def mock_llm_clients():
    """Mocks all LLM client classes to prevent real API calls."""
    with patch("src.core.agent_manager.OpenAIClient") as mock_openai, \
         patch("src.core.agent_manager.GoogleGenAIClient") as mock_google, \
         patch("src.core.agent_manager.HuggingFaceClient") as mock_hf, \
         patch("src.core.agent_manager.LlmClient") as mock_openrouter, \
         patch("src.core.agent_manager.AnthropicClient") as mock_anthropic:
        
        # Make the mock clients themselves mock objects
        mock_openai.return_value = MagicMock()
        mock_google.return_value = MagicMock()
        mock_hf.return_value = MagicMock()
        mock_openrouter.return_value = MagicMock()
        mock_anthropic.return_value = MagicMock()

        yield {
            "OpenAIClient": mock_openai,
            "GoogleGenAIClient": mock_google,
            "HuggingFaceClient": mock_hf,
            "LlmClient": mock_openrouter,
            "AnthropicClient": mock_anthropic,
        }

@pytest.fixture(autouse=True)
def mock_secure_storage():
    """Mocks the secure_storage functions."""
    with patch("src.core.agent_manager.retrieve_credential") as mock_retrieve, \
         patch("src.core.agent_manager.store_credential") as mock_store, \
         patch("src.core.agent_manager.delete_credential") as mock_delete:
        yield {"retrieve": mock_retrieve, "store": mock_store, "delete": mock_delete}


# --- Test Cases ---

class TestAgentManagerInitialization:
    """Tests for the initialization and re-initialization logic."""

    def test_init_success_with_stored_key(self, mock_config_manager, mock_secure_storage, mock_llm_clients):
        """Tests successful initialization when the API key is already in secure storage."""
        mock_secure_storage["retrieve"].return_value = "fake-openai-key"

        manager = AgentManager(
            provider_id="openai",
            model_id="gpt-4",
            config_manager=mock_config_manager
        )

        mock_secure_storage["retrieve"].assert_called_once_with("openai_api_key")
        mock_llm_clients["OpenAIClient"].assert_called_once_with(model="gpt-4", api_key="fake-openai-key")
        assert manager.agent is not None

    def test_init_success_with_user_prompt(self, mock_config_manager, mock_secure_storage, mock_show_input_prompt_cb, mock_llm_clients):
        """Tests successful initialization when the user provides the key via a prompt."""
        mock_secure_storage["retrieve"].return_value = None
        mock_show_input_prompt_cb.return_value = "user-provided-key"

        manager = AgentManager(
            provider_id="openai",
            model_id="gpt-4",
            config_manager=mock_config_manager,
            show_input_prompt_cb=mock_show_input_prompt_cb
        )

        mock_secure_storage["retrieve"].assert_called_once_with("openai_api_key")
        mock_show_input_prompt_cb.assert_called_once()
        mock_secure_storage["store"].assert_called_once_with("openai_api_key", "user-provided-key")
        mock_llm_clients["OpenAIClient"].assert_called_once_with(model="gpt-4", api_key="user-provided-key")
        assert manager.agent is not None

    def test_init_huggingface_client_uses_api_token(self, mock_config_manager, mock_secure_storage, mock_llm_clients):
        """Tests that the HuggingFaceClient is initialized with 'api_token'."""
        mock_secure_storage["retrieve"].return_value = "fake-hf-token"

        AgentManager(
            provider_id="huggingface",
            model_id="mistralai/Mistral-7B-Instruct-v0.1",
            config_manager=mock_config_manager
        )

        mock_llm_clients["HuggingFaceClient"].assert_called_once_with(
            model="mistralai/Mistral-7B-Instruct-v0.1", api_token="fake-hf-token"
        )

    def test_init_openrouter_client_uses_site_url(self, mock_config_manager, mock_secure_storage, mock_llm_clients):
        """Tests that the OpenRouter client (LlmClient) is initialized with site_url and site_title."""
        mock_secure_storage["retrieve"].return_value = "fake-or-key"

        AgentManager(
            provider_id="openrouter",
            model_id="openrouter/google/gemini-flash-1.5",
            config_manager=mock_config_manager,
            site_url="https://my-app.com",
            site_title="My Awesome App"
        )

        mock_llm_clients["LlmClient"].assert_called_once_with(
            model="openrouter/google/gemini-flash-1.5",
            api_key="fake-or-key",
            site_url="https://my-app.com",
            site_title="My Awesome App"
        )

    def test_init_fails_if_user_cancels_prompt(self, mock_config_manager, mock_secure_storage, mock_show_input_prompt_cb):
        """Tests that initialization raises RuntimeError if the user cancels the API key prompt."""
        mock_secure_storage["retrieve"].return_value = None
        mock_show_input_prompt_cb.return_value = None  # Simulate user cancelling

        with pytest.raises(RuntimeError, match="API key for OpenAI Agent was not provided by the user"):
            AgentManager(
                provider_id="openai",
                model_id="gpt-4",
                config_manager=mock_config_manager,
                show_input_prompt_cb=mock_show_input_prompt_cb
            )

    def test_init_fails_with_invalid_provider(self, mock_config_manager):
        """Tests that initialization raises ValueError for an unknown provider ID."""
        with pytest.raises(ValueError, match="Provider 'unknown_provider' not found in configuration."):
            AgentManager(
                provider_id="unknown_provider",
                model_id="any-model",
                config_manager=mock_config_manager
            )

    def test_reinitialize_agent_switches_client(self, mock_config_manager, mock_secure_storage, mock_llm_clients):
        """Tests that re-initializing correctly switches the underlying LLM client."""
        # Initial setup with OpenAI
        mock_secure_storage["retrieve"].side_effect = ["fake-openai-key", "fake-google-key"]
        manager = AgentManager(
            provider_id="openai",
            model_id="gpt-4",
            config_manager=mock_config_manager
        )
        assert isinstance(manager.agent, MagicMock)
        mock_llm_clients["OpenAIClient"].assert_called_once()
        original_agent_instance = manager.agent

        # Re-initialize with Google
        manager.reinitialize_agent(provider_id="google", model_id="gemini-1.5-pro")

        mock_llm_clients["GoogleGenAIClient"].assert_called_once_with(model="gemini-1.5-pro", api_key="fake-google-key")
        assert manager.agent is not original_agent_instance
        assert mock_secure_storage["retrieve"].call_count == 2


class TestAgentManagerExecution:
    """Tests for the execution-related methods of AgentManager."""

    @pytest.fixture
    def manager(self, mock_config_manager, mock_secure_storage, mock_request_api_key_update_cb) -> AgentManager:
        """Provides a successfully initialized AgentManager instance."""
        mock_secure_storage["retrieve"].return_value = "fake-key"
        return AgentManager(
            provider_id="openai",
            model_id="gpt-4",
            config_manager=mock_config_manager,
            # Pass the mocked callback during initialization
            request_api_key_update_cb=mock_request_api_key_update_cb
        )

    def test_invoke_agent_success(self, manager: AgentManager):
        """Tests that invoke_agent correctly calls the underlying client's chat method."""
        system_prompt: ChatMessage = {"role": "system", "content": "You are a bot."} # type: ignore
        messages: List[ChatMessage] = [{"role": "user", "content": "Hello"}]
        expected_response: ChatMessage = {"role": "assistant", "content": "Hi!"}

        # Configure the mock client to return a specific response
        manager.agent.chat.return_value = expected_response

        response = manager.invoke_agent(system_prompt, messages, temperature=0.5)

        manager.agent.chat.assert_called_once_with([system_prompt] + messages, temperature=0.5)
        assert response == expected_response

    def test_invoke_agent_fails_if_not_initialized(self):
        """Tests that invoke_agent raises an error if the agent is not initialized."""
        # Create a manager instance that will fail initialization
        with pytest.raises(RuntimeError):
            manager = AgentManager(provider_id="openai", model_id="gpt-4", config_manager=MagicMock())
            manager.agent = None # Manually set agent to None to simulate failure
            manager.invoke_agent([], [])

    @pytest.mark.asyncio
    async def test_handle_api_error_with_new_key(self, manager: AgentManager, mock_request_api_key_update_cb, mock_secure_storage, mock_llm_clients):
        """Tests the API error handling flow where the user provides a new key."""
        mock_request_api_key_update_cb.return_value = ("new-fake-key", False)

        result = await manager.handle_api_error_and_reinitialize("AuthenticationError", "Invalid key")

        assert result is True
        mock_request_api_key_update_cb.assert_awaited_once()
        mock_secure_storage["store"].assert_called_with("openai_api_key", "new-fake-key")
        # _initialize_agent is called, which calls the client constructor again
        assert mock_llm_clients["OpenAIClient"].call_count == 2

    @pytest.mark.asyncio
    async def test_handle_api_error_with_retry(self, manager: AgentManager, mock_request_api_key_update_cb, mock_llm_clients):
        """Tests the API error handling flow where the user chooses to retry."""
        mock_request_api_key_update_cb.return_value = (None, True)

        result = await manager.handle_api_error_and_reinitialize("RateLimitError", "Quota exceeded")

        assert result is True
        mock_request_api_key_update_cb.assert_awaited_once()
        # The client should NOT be re-initialized if the user just retries
        assert mock_llm_clients["OpenAIClient"].call_count == 1

    @pytest.mark.asyncio
    async def test_handle_api_error_with_cancel(self, manager: AgentManager, mock_request_api_key_update_cb):
        """Tests the API error handling flow where the user cancels."""
        mock_request_api_key_update_cb.return_value = (None, False)

        result = await manager.handle_api_error_and_reinitialize("AuthenticationError", "Invalid key")

        assert result is False
        mock_request_api_key_update_cb.assert_awaited_once()


class TestAgentManagerUtilities:
    """Tests for utility methods like clearing keys."""

    def test_clear_stored_keys(self, mock_config_manager, mock_secure_storage):
        """Tests that clear_stored_keys attempts to delete all configured keys."""
        # We don't need a fully initialized manager for this test
        manager = AgentManager.__new__(AgentManager)
        manager.config_manager = mock_config_manager
        manager.agent = None

        mock_secure_storage["delete"].return_value = True

        result = manager.clear_stored_keys()

        assert result is True
        # Should be called for openai, google, huggingface, and openrouter
        assert mock_secure_storage["delete"].call_count == 4
        mock_secure_storage["delete"].assert_any_call("openai_api_key")
        mock_secure_storage["delete"].assert_any_call("google_api_key")
        mock_secure_storage["delete"].assert_any_call("hf_token")
        mock_secure_storage["delete"].assert_any_call("openrouter_api_key")
        assert manager.agent is None

    def test_clear_stored_keys_fails_partially(self, mock_config_manager, mock_secure_storage):
        """Tests that clear_stored_keys returns False if any deletion fails."""
        manager = AgentManager.__new__(AgentManager)
        manager.config_manager = mock_config_manager
        manager.agent = MagicMock() # Simulate an existing agent

        # Simulate one of the deletions failing
        mock_secure_storage["delete"].side_effect = [True, False, True, True]

        result = manager.clear_stored_keys()

        assert result is False
        # The agent should NOT be invalidated if clearing fails
        assert manager.agent is not None