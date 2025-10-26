# backend/src/core/agent_manager.py
import logging
from typing import Optional, Callable, Dict, Tuple, Union, Awaitable, List, Literal, Any, Type
import re 
import asyncio
import json
import time
# Import required components
from .llm_client import LlmClient, ChatMessage, RateLimitError, AuthenticationError
from .hf_client import HuggingFaceClient # <-- Import the new client
from .google_genai_client import GoogleGenAIClient
from .openai_client import OpenAIClient
from .anthropic_client import AnthropicClient
from .secure_storage import retrieve_credential, store_credential, delete_credential # Keep this
from .config_manager import ConfigManager
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Type hint for the callback function provided by the UI ---
ShowInputPromptCallable = Callable[[str, bool, Optional[str]], Optional[str]]
RequestApiKeyUpdateCallable = Callable[[str, str, str], Awaitable[Tuple[Optional[str], bool]]] # agent_desc, error_message, key_name


class AgentManager:
    """
    Manages the lifecycle of a single, dynamically configured LLM client instance.

    This class acts as a central point for creating, configuring, and re-initializing
    the specific LLM client (like OpenAI, Google, etc.) that the application will use.
    It handles the complexities of API key management by interacting with secure
    storage and prompting the user for keys when necessary via UI callbacks.
    """
    def __init__(self,
                 provider_id: str,
                 model_id: str,
                 config_manager: ConfigManager,
                 show_input_prompt_cb: Optional[ShowInputPromptCallable] = None,
                 request_api_key_update_cb: Optional[RequestApiKeyUpdateCallable] = None,
                 site_url: Optional[str] = None,
                 site_title: Optional[str] = None
                 ):
        """
        Initializes the AgentManager with a specified provider, model, and UI callbacks.

        Args:
            provider_id: The ID of the API provider (e.g., "google", "openai").
            model_id: The specific model ID to use for the selected provider.
            config_manager: The application's ConfigManager instance.
            show_input_prompt_cb: Callback to prompt user for initial API key input.
            request_api_key_update_cb: Callback to prompt user to update API key after an error.
            site_url: Optional URL of the referring site, used for OpenRouter ranking.
            site_title: Optional title of the referring site, used for OpenRouter ranking.
        """
        logger.info(f"Initializing AgentManager for provider '{provider_id}' and model '{model_id}'...")
        if not provider_id or not model_id:
            raise ValueError("AgentManager requires a valid provider_id and model_id.")
        # Store initial configuration and callbacks

        self.provider_id = provider_id
        self.model_id = model_id
        self.config_manager = config_manager
        self._show_input_prompt_cb = show_input_prompt_cb
        self._request_api_key_update_cb = request_api_key_update_cb
        self.site_url = site_url
        self.site_title = site_title

        # The actual LLM client instance will be stored here after initialization.
        self.agent: Optional[Union[LlmClient, HuggingFaceClient, GoogleGenAIClient, OpenAIClient]] = None
        # --- NEW: Rate Limiting ---
        # Track the time of the last API call to enforce a minimum interval.
        self.last_api_call_time: Optional[float] = None
        self.min_request_interval_seconds: int = 30 # Enforce a 30-second delay between requests

        # Trigger the initialization process upon creation.
        self._initialize_agent()

    def _get_client_class(self, class_name: str) -> Type[Union[LlmClient, HuggingFaceClient, GoogleGenAIClient, OpenAIClient, AnthropicClient]]:
        """
        Dynamically retrieves a client class type from a factory dictionary.

        This approach avoids a large if/elif/else block and makes it easy to add
        new client types. It also helps with testing by allowing these classes to be
        mocked individually.
        """
        client_classes: Dict[str, Type[Union[LlmClient, HuggingFaceClient, GoogleGenAIClient, OpenAIClient, AnthropicClient]]] = {
            "LlmClient": LlmClient,
            "HuggingFaceClient": HuggingFaceClient,
            "GoogleGenAIClient": GoogleGenAIClient,
            "OpenAIClient": OpenAIClient,
            "AnthropicClient": AnthropicClient,
        }
        
        client_class = client_classes.get(class_name)
        if not client_class:
            raise TypeError(f"Client class '{class_name}' not found in client factory.")
        return client_class

    def _initialize_agent(self):
        """
        Loads the required API key and initializes the appropriate LLM client based
        on the currently configured provider and model.

        Raises:
            ValueError: If the configuration is invalid or the user cancels an API key prompt.
            RuntimeError: If the client class fails to instantiate.
        """
        logger.debug(f"Attempting to load key and initialize agent for provider '{self.provider_id}'...")
        # Reset the agent to ensure a clean state before initialization
        self.agent = None

        # Retrieve the configuration for the selected provider (e.g., 'openai')
        provider_config = self.config_manager.providers_config.get(self.provider_id)
        if not provider_config:
            raise ValueError(f"Provider '{self.provider_id}' not found in configuration.")

        # Extract necessary details from the provider's configuration
        key_name = provider_config.get("api_key_name")
        client_class_name = provider_config.get("client_class")
        client_config = provider_config.get("client_config", {})
        provider_display_name = provider_config.get("display_name", self.provider_id)

        # Ensure the configuration is complete
        if not key_name or not client_class_name:
            raise ValueError(f"Provider config for '{self.provider_id}' is missing 'api_key_name' or 'client_class'.")

        try:
            # This helper method will first try to load the key from secure storage.
            # If it's not found, it will use the provided UI callback to prompt the user.
            api_key = self._load_or_prompt_key(
                key_name=key_name,
                agent_desc=f"{provider_display_name} Agent",
                prompt_cb=self._show_input_prompt_cb
            )

            # Get the actual client class (e.g., OpenAIClient) based on the name from the config.
            ClientClass = self._get_client_class(client_class_name)
            logger.info(f"Instantiating {client_class_name} for model '{self.model_id}'...")
 
            # Prepare the arguments for instantiating the client class.
            # Start with common arguments from the provider's configuration in providers.json.
            init_args: Dict[str, Any] = {
                "model": self.model_id,
                **client_config
            }
            # The 'model_prefix' is a config-only key and not a client argument, so remove it.
            init_args.pop("model_prefix", None) # Remove config-only key not used by clients
 
            # Add client-specific arguments that are not part of the generic config.
            if client_class_name == "HuggingFaceClient":
                init_args["api_token"] = api_key
            elif client_class_name == "LlmClient": # This is the OpenRouter client
                init_args["api_key"] = api_key
                init_args["site_url"] = self.site_url
                init_args["site_title"] = self.site_title
            else: # Handles other standard clients like OpenAI, Google, Anthropic
                init_args["api_key"] = api_key
 
            # Create the client instance with the prepared arguments.
            self.agent = ClientClass(**init_args)
            logger.info(f"Agent client initialized successfully for model '{self.model_id}'.")
        except ValueError as e:
            # If a ValueError occurs (e.g., user cancels prompt, invalid key format),
            # we delete the potentially invalid key from storage to avoid repeated errors.
            logger.error(f"Failed to initialize agent for {self.provider_id}: {e}")
            if "not provided by the user" not in str(e):
                logger.warning(f"The API key for '{key_name}' may be invalid. Deleting it.")
                delete_credential(key_name)
            raise RuntimeError(f"Failed to initialize agent. The API key for {provider_display_name} may be invalid or was not provided. Error: {e}") from e
        except Exception as e:
            logger.exception(f"Failed to create client instance for {self.provider_id} ({self.model_id}).")
            raise RuntimeError(f"Failed to initialize LLM agent for {self.provider_id}: {e}") from e

    def reinitialize_agent(self, provider_id: str, model_id: str):
        """
        Public method to re-initialize the agent with a new provider or model.
        This is typically called by the UI when the user changes the model selection.

        Args:
            provider_id: The new provider ID.
            model_id: The new model ID.
        """
        logger.info(f"Re-initializing AgentManager with Provider='{provider_id}', Model='{model_id}'...")
        if not provider_id or not model_id:
            raise ValueError("Re-initialization requires a valid provider and model ID.")

        # Update the instance's provider and model, then run the full initialization again.
        self.provider_id = provider_id
        self.model_id = model_id
        self._initialize_agent()
        logger.info("AgentManager re-initialized successfully.")

    async def handle_api_error_and_reinitialize(self, error_type_str: str, error_message: str) -> bool:
        """
        Handles an API error by prompting the user for action (e.g., update key, retry).

        This is called by the WorkflowManager when an LLM call fails with a recoverable
        API error. It uses a UI callback to show a dialog and acts on the user's response.

        Args:
            error_type_str: "AuthenticationError" or "RateLimitError".
            error_message: The full string of the caught exception.

        Returns:
            True if the issue was resolved (new key provided or user chose to retry),
            False if the user cancelled the update.
        """
        if not self._request_api_key_update_cb:
            logger.error("Cannot handle API error: No API key update callback provided.")
            return False

        # Get the configuration for the provider that failed.
        provider_config = self.config_manager.providers_config.get(self.provider_id)
        if not provider_config:
            logger.error(f"Cannot handle API error: Provider '{self.provider_id}' not found in config.")
            return False

        key_name_in_use = provider_config.get("api_key_name")
        provider_display_name = provider_config.get("display_name", self.provider_id)

        if not key_name_in_use:
            logger.error(f"Cannot handle API error: Provider config for '{self.provider_id}' is missing 'api_key_name'.")
            return False

        # Call the UI callback to show the dialog and wait for the user's response.
        logger.info(f"Requesting API key update for {provider_display_name} due to {error_type_str}.")
        new_key, retry_current = await self._request_api_key_update_cb(
            f"{provider_display_name} ({self.model_id})",
            error_message,
            key_name_in_use
        )

        # Process the user's choice from the dialog.
        if new_key:
            # User provided a new key. Store it and re-initialize the agent.
            logger.info(f"User provided new key for {provider_display_name}. Storing and re-initializing client.")
            store_credential(key_name_in_use, new_key)
            self._initialize_agent() # Re-initialize with the new key
            return True
        elif retry_current:
            # User chose to retry with the same key.
            logger.info(f"User chose to retry with current key for {provider_display_name}.")
            return True
        else:
            logger.error(f"User cancelled API key update for {provider_display_name}.")
            return False

    def clear_stored_keys(self) -> bool:
        """
        Deletes all API keys and tokens defined in the providers config from secure storage.

        Returns:
            True if all deletions were successful (or keys didn't exist), False otherwise.
        """
        logger.warning("Attempting to clear all stored API keys/tokens.")
        all_cleared = True
        for provider_id, data in self.config_manager.providers_config.items():
            key_name = data.get("api_key_name")
            if key_name:
                try:
                    if not delete_credential(key_name):
                        all_cleared = False
                except Exception as e:
                    logger.exception(f"Error clearing key '{key_name}' for provider '{provider_id}'.")
                    all_cleared = False

        if all_cleared:
            # After clearing keys, the current agent instance is no longer valid.
            logger.info("Successfully cleared (or confirmed absence of) stored API keys/tokens.")
            self.agent = None
            return True
        else:
            logger.error("Failed to clear one or more stored API keys/tokens. Check previous logs or keyring backend status.")
            return False

    def reinitialize_agent_with_new_key(self, new_api_key: str):
        """
        Stores a new API key provided by the user and re-initializes the agent.
        This is part of the error recovery flow after an authentication failure.
        """
        if not self.provider_id or not self.model_id:
            raise RuntimeError("Cannot re-initialize agent with new key: provider or model ID is not set.")

        provider_config = self.config_manager.providers_config.get(self.provider_id)
        if not provider_config:
            raise RuntimeError(f"Provider configuration for '{self.provider_id}' not found.")

        api_key_name = provider_config.get("api_key_name")
        if not api_key_name:
            raise RuntimeError(f"Provider '{self.provider_id}' does not have an 'api_key_name' defined in its configuration.")

        store_credential(api_key_name, new_api_key)
        self.reinitialize_agent(self.provider_id, self.model_id)

    def invoke_agent(self, system_prompt: ChatMessage, messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage:
        """
        The main public method to make an LLM call using the currently configured agent.

        Args:
            system_prompt: The system prompt message.
            messages: A list of user/assistant messages forming the conversation history.
            temperature: The sampling temperature for the LLM.

        Returns:
            The ChatMessage response from the invoked agent.
        """
        logger.debug(f"Invoking agent with temperature: {temperature}") 

        # --- NEW: Enforce a delay between API calls to avoid rate limiting ---
        if self.last_api_call_time:
            elapsed = time.time() - self.last_api_call_time
            if elapsed < self.min_request_interval_seconds:
                wait_time = self.min_request_interval_seconds - elapsed
                logger.info(f"Waiting for {wait_time:.2f} seconds to respect API rate limit interval...")
                time.sleep(wait_time)
        # Update the last call time *before* making the new request.
        self.last_api_call_time = time.time()

        # Ensure the agent has been initialized before trying to use it.
        if not self.agent:
            raise RuntimeError("Agent client is not initialized.")
        all_messages: List[ChatMessage] = [system_prompt] + messages
        
        # Delegate the actual chat call to the specific client instance (e.g., OpenAIClient, GoogleGenAIClient).
        logger.debug(f"Using {type(self.agent).__name__} with model {self.model_id} and temp {temperature}")
        return self.agent.chat(all_messages, temperature=temperature)

    def _load_or_prompt_key(self, key_name: str, agent_desc: str, prompt_cb: Optional[ShowInputPromptCallable]) -> str:
        """
        Loads an API key or token from secure storage. If not found or invalid,
        it attempts to prompt the user using the provided callback function.

        Args:
            key_name: The identifier used for storing/retrieving the key/token.
            agent_desc: A user-friendly description of the agent for the prompt.
            prompt_cb: The callback function to show the input dialog.

        Returns:
            The retrieved or newly entered API key/token.
        """
        key_type_prompt = f"API Key for {agent_desc}"

        # First, try to retrieve the key from secure storage.
        api_key = retrieve_credential(key_name)

        if api_key:
            logger.info(f"Retrieved API key for {agent_desc} from secure storage.")
            return api_key
        else:
            # If not found, we need to prompt the user.
            logger.warning(f"API key for {agent_desc} ('{key_name}') not found in secure storage. Attempting to prompt user.")

        # Check if a UI callback for prompting is available.
        if prompt_cb:
            try:
                # Customize the prompt for Hugging Face tokens to guide the user better.
                prompt_title = f"API Key for {agent_desc} Required"
                prompt_message = f"Please enter the API Key for {agent_desc}."
                if self.provider_id == "huggingface":
                    prompt_title = "Hugging Face Token Required"
                    prompt_message = "Please enter your Hugging Face User Access Token.\nIt must start with 'hf_'."

                # Call the UI callback, which will block this thread until the user responds.
                # This call will block the current thread until the user responds to the dialog.
                api_key_input = prompt_cb(
                    prompt_title, # Use the more specific title
                    True, # is_password = True
                    prompt_message # Use adjusted prompt message
                )
            except Exception as cb_e:
                 logger.exception(f"Error occurred during input prompt callback for {key_type_prompt}.")
                 raise ValueError(f"Failed to get {key_type_prompt} due to callback error: {cb_e}") from cb_e


            # Process the user's input from the dialog.
            if api_key_input:
                api_key_stripped = api_key_input.strip()
                if api_key_stripped:
                    try:
                        # Store the valid, new key for future sessions.
                        store_credential(key_name, api_key_stripped)
                        logger.info(f"Stored new API key for {agent_desc} securely.")
                        return api_key_stripped
                    except RuntimeError as store_e:
                         logger.error(f"Failed to store newly entered API key for {agent_desc}: {store_e}")
                         raise ValueError(f"Failed to store API key for {agent_desc}. Secure storage unavailable.") from store_e
                else:
                     logger.error(f"Invalid API key (empty after stripping) entered by user for {agent_desc}.")
                     raise ValueError(f"Invalid API key format entered for {agent_desc}.")
            else:
                # User cancelled the dialog or entered nothing.
                logger.error(f"User cancelled or provided no API key entry for {agent_desc}.")
                raise ValueError(f"API key for {agent_desc} was not provided by the user.")
        else:
            # This is a critical failure: key not found and no UI to ask the user for it.
            logger.error(f"Cannot prompt for API key for {agent_desc}: No input callback provided.")
            raise ValueError(f"API key for {agent_desc} not found and cannot prompt user.")

    @property
    def agent_client(self) -> Union[LlmClient, HuggingFaceClient, GoogleGenAIClient, OpenAIClient]:
        """
        Provides public, read-only access to the initialized agent client, raising
        an error if the agent has not been successfully initialized.
        """
        if self.agent is None:
            logger.error("Attempted to access agent client before successful initialization.")
            raise RuntimeError("Agent client is not initialized. Check API keys/tokens and logs.")
