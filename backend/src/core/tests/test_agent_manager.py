# src/core/tests/test_agent_manager.py
import unittest
from unittest.mock import patch, MagicMock, ANY

# To run these tests, navigate to the 'backend' directory and run:
# python -m unittest discover src/core/tests
# This ensures that 'src' is treated as a top-level package.

from src.core.agent_manager import AgentManager

class TestAgentManager(unittest.TestCase):
    """
    Unit tests for the AgentManager class.
    These tests verify API key handling, agent instantiation logic, and client selection
    by mocking external dependencies like keyring and the LLM clients.
    """

    def setUp(self):
        """Set up mock objects for each test."""
        self.mock_show_input_prompt_cb = MagicMock()
        self.mock_request_api_key_update_cb = MagicMock()
        # Mock the ConfigManager to provide a predictable provider configuration for tests
        self.mock_config_manager = MagicMock()
        self.mock_config_manager.providers_config = {
            "openai": {
                "display_name": "OpenAI",
                "api_key_name": "OPENAI_API_KEY",
                "client_class": "OpenAIClient",
                "client_config": {"api_base": "https://api.openai.com/v1"},
            },
            "openrouter": {
                "display_name": "OpenRouter",
                "api_key_name": "OPENROUTER_API_KEY",
                "client_class": "LlmClient",
                "client_config": {"api_base": "https://openrouter.ai/api/v1"},
            },
            "huggingface": {
                "display_name": "Hugging Face",
                "api_key_name": "HUGGINGFACE_API_TOKEN",
                "client_class": "HuggingFaceClient",
                "client_config": {},
            }
        } # Corrected: This was missing a closing brace
        print(f"\n--- Running test: {self._testMethodName} ---")

    @patch('src.core.agent_manager.OpenAIClient')
    @patch('src.core.agent_manager.HuggingFaceClient')
    @patch('src.core.agent_manager.LlmClient')
    @patch('src.core.agent_manager.store_credential')
    @patch('src.core.agent_manager.retrieve_credential')
    def test_initialization_with_missing_key_and_callback(self, mock_retrieve, mock_store, mock_llm_client, mock_hf_client, mock_openai_client):
        """
        Verify that if keys are not in storage, the UI callback is used to prompt the user.
        """
        # Arrange: Mock that no keys are found in storage
        mock_retrieve.return_value = None
        # Mock that the user enters keys when prompted
        self.mock_show_input_prompt_cb.return_value = "fake_openai_key"

        # Act
        agent_manager = AgentManager(
            provider_id="openai",
            model_id="gpt-3.5-turbo",
            config_manager=self.mock_config_manager,
            show_input_prompt_cb=self.mock_show_input_prompt_cb
        )

        # Assert
        # Check that the prompt callback was called once for the specified provider
        self.mock_show_input_prompt_cb.assert_called_once_with(ANY, True, ANY)
        # Check that the new key was stored for the correct provider
        mock_store.assert_called_once_with("OPENAI_API_KEY", "fake_openai_key")
        # Check that the correct client was instantiated with the new key
        mock_openai_client.assert_called_once_with(api_key="fake_openai_key", model="gpt-3.5-turbo", api_base="https://api.openai.com/v1")
        mock_llm_client.assert_not_called()
        mock_hf_client.assert_not_called()
        self.assertIsNotNone(agent_manager.agent)

    @patch('src.core.agent_manager.HuggingFaceClient')
    @patch('src.core.agent_manager.LlmClient')
    @patch('src.core.agent_manager.retrieve_credential')
    def test_initialization_with_existing_key(self, mock_retrieve, mock_llm_client, mock_hf_client):
        """
        Verify that if keys exist in storage, they are used and the UI callback is not called.
        """
        # Arrange: Mock that keys ARE found in storage
        mock_retrieve.return_value = "hf_existing_key" # FIX: Provide a valid-looking token

        # Act
        agent_manager = AgentManager(
            provider_id="huggingface",
            model_id="deepseek-ai/deepseek-coder-6.7b-instruct",
            config_manager=self.mock_config_manager,
            show_input_prompt_cb=self.mock_show_input_prompt_cb
        )

        # Assert
        # Check that the prompt callback was NOT called
        self.mock_show_input_prompt_cb.assert_not_called()
        # Check that store was NOT called
        # mock_store is not patched here, but we know it shouldn't be called.
        # Check that clients were instantiated with the existing keys
        mock_hf_client.assert_called_once_with(api_token="hf_existing_key", model="deepseek-ai/deepseek-coder-6.7b-instruct")
        # Ensure the generic LlmClient was not called for this provider
        mock_llm_client.assert_not_called()

    @patch('src.core.agent_manager.retrieve_credential')
    def test_initialization_raises_error_without_callback(self, mock_retrieve):
        """
        Verify that initialization fails if keys are missing and no UI callback is provided.
        """
        # Arrange: Mock that no keys are found
        mock_retrieve.return_value = None

        # Act & Assert
        with self.assertRaises(RuntimeError) as cm:
            AgentManager(
                provider_id="openai",
                model_id="gpt-3.5-turbo",
                config_manager=self.mock_config_manager,
                show_input_prompt_cb=None # No callback provided
            )
        self.assertIn("not found and cannot prompt user", str(cm.exception))

    @patch('src.core.agent_manager.retrieve_credential')
    def test_initialization_fails_on_user_cancel(self, mock_retrieve):
        """
        Verify that initialization fails if the user cancels the API key prompt.
        """
        # Arrange: Mock that no key is found and the user cancels the prompt
        mock_retrieve.return_value = None
        self.mock_show_input_prompt_cb.return_value = None # Simulate user cancelling

        # Act & Assert
        with self.assertRaises(RuntimeError) as cm:
            AgentManager(
                provider_id="openai", model_id="gpt-4",
                config_manager=self.mock_config_manager,
                show_input_prompt_cb=self.mock_show_input_prompt_cb
            )
        self.assertIn("was not provided by the user", str(cm.exception))

    @patch('src.core.agent_manager.HuggingFaceClient')
    @patch('src.core.agent_manager.LlmClient')
    @patch('src.core.agent_manager.retrieve_credential')
    def test_selects_hfclient_for_huggingface_model(self, mock_retrieve, mock_llm_client, mock_hf_client):
        """
        Verify that the HuggingFaceClient is used for Hugging Face model IDs.
        """
        # Arrange: Mock that a HF token is found
        mock_retrieve.return_value = "hf_fake_token_for_hf"

        # Act
        agent_manager = AgentManager(
            provider_id="huggingface",
            model_id="deepseek-ai/deepseek-coder-6.7b-instruct",
            config_manager=self.mock_config_manager,
            show_input_prompt_cb=self.mock_show_input_prompt_cb
        )

        # Assert
        mock_hf_client.assert_called_once_with(api_token="hf_fake_token_for_hf", model="deepseek-ai/deepseek-coder-6.7b-instruct")
        mock_llm_client.assert_not_called()
        self.assertIsInstance(agent_manager.agent, MagicMock) # The mock of HuggingFaceClient

    @patch('src.core.agent_manager.OpenAIClient')
    @patch('src.core.agent_manager.LlmClient')
    @patch('src.core.agent_manager.retrieve_credential')
    def test_reinitialize_agent_switches_client(self, mock_retrieve, mock_llm_client, mock_openai_client):
        """
        Verify that re-initializing the agent with a new provider/model correctly
        instantiates the new client.
        """
        # Arrange: Mock that keys are found for both providers
        def retrieve_side_effect(key_name):
            if key_name == "OPENROUTER_API_KEY":
                return "or_key"
            if key_name == "OPENAI_API_KEY":
                return "oa_key"
            return None
        mock_retrieve.side_effect = retrieve_side_effect

        # Act 1: Initialize with OpenRouter
        agent_manager = AgentManager(
            provider_id="openrouter", model_id="google/gemma-7b-it:free",
            config_manager=self.mock_config_manager
        )

        # Assert 1: Check that LlmClient was used
        mock_llm_client.assert_called_once_with(api_key="or_key", model="google/gemma-7b-it:free", api_base=ANY, site_url=ANY, site_title=ANY)

        # Act 2: Re-initialize with OpenAI
        agent_manager.reinitialize_agent(provider_id="openai", model_id="gpt-4o")

        # Assert 2: Check that OpenAIClient was used for the second call
        mock_openai_client.assert_called_once_with(api_key="oa_key", model="gpt-4o", api_base="https://api.openai.com/v1")

    @patch('src.core.agent_manager.delete_credential')
    @patch('src.core.agent_manager.retrieve_credential')
    def test_clear_stored_keys(self, mock_retrieve, mock_delete):
        """Verify that clear_stored_keys attempts to delete all relevant keys."""
        # Mock retrieve_credential to prevent real keyring calls during AgentManager's __init__
        mock_retrieve.return_value = "dummy_key_for_init" # Needed for the constructor

        agent_manager = AgentManager(
            provider_id="openai", model_id="gpt-4",
            config_manager=self.mock_config_manager,
            show_input_prompt_cb=lambda a,b,c: "key"
        )
        agent_manager.clear_stored_keys()
        # It should iterate through all providers in the mocked config
        mock_delete.assert_any_call("OPENAI_API_KEY")
        mock_delete.assert_any_call("OPENROUTER_API_KEY")
        mock_delete.assert_any_call("HUGGINGFACE_API_TOKEN")
        self.assertEqual(mock_delete.call_count, len(self.mock_config_manager.providers_config))

if __name__ == '__main__':
    unittest.main()