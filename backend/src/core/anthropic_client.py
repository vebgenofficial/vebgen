# backend/src/core/anthropic_client.py
import logging
import json
from typing import List, Optional

try:
    from openai import OpenAI, RateLimitError as OpenAIRateLimitError, AuthenticationError as OpenAIAuthenticationError
except ImportError:
    raise ImportError("The 'openai' package is required to use the AnthropicClient. Please install it with 'pip install openai'.")

# Import exceptions from the shared llm_client for consistency
from .llm_client import RateLimitError, AuthenticationError, ChatMessage

logger = logging.getLogger(__name__)

class AnthropicClient:
    """
    Handles communication with the Anthropic (Claude) API.

    This client cleverly uses the official 'openai' Python SDK to interact with
    Anthropic's API by pointing it to the Anthropic base URL and providing the
    necessary headers. This approach allows for consistent error handling and
    data structures across different clients.
    """
    def __init__(self, api_key: str, model: str, **kwargs):
        """
        Initializes the Anthropic client via the OpenAI SDK.

        This setup configures the OpenAI client object to communicate with the
        Anthropic API endpoint instead of OpenAI's.
        Args:
            api_key: The Anthropic API key.
            model: The specific Claude model identifier (e.g., "claude-3-opus-20240229").
        """
        if not api_key or not isinstance(api_key, str):
            raise ValueError("AnthropicClient requires a valid string API key.")
        if not model or not isinstance(model, str):
            raise ValueError("AnthropicClient requires a valid string model ID.")

        # Store the model ID for use in chat requests.
        self.model_id = model
        try:
            # Instantiate the OpenAI client, but override the target URL and add Anthropic-specific headers.
            self.client = OpenAI(
                api_key=api_key,
                base_url="https://api.anthropic.com/v1",
                default_headers={"anthropic-version": "2023-06-01"} # This header is required by the Anthropic API.
            )
            logger.info(f"AnthropicClient instance created for model '{self.model_id}'.")
        except Exception as e:
            logger.exception("Failed to configure Anthropic client.")
            raise RuntimeError(f"Failed to initialize Anthropic client: {e}") from e

    def chat(self, messages: List[ChatMessage], temperature: float = 0.1, max_tokens: int = 4096) -> ChatMessage:
        """
        Sends a chat completion request to the Anthropic API.

        Args:
            messages: A list of ChatMessage dictionaries representing the conversation.
            temperature: The sampling temperature for the model's response.
            max_tokens: The maximum number of tokens to generate in the response.

        Returns:
            A ChatMessage dictionary containing the assistant's response.

        Raises:
            RateLimitError: If the API rate limit is exceeded.
            AuthenticationError: If the API key is invalid.
            RuntimeError: For other unexpected API or processing errors.
        """
        if not messages or not isinstance(messages, list):
            raise ValueError("Cannot send chat request with empty or invalid messages list.")

        # The application's internal ChatMessage format is compatible with the OpenAI SDK's expected format.
        valid_messages = [{"role": msg["role"], "content": msg["content"]} for msg in messages if msg.get("role") in ["system", "user", "assistant"]]

        try:
            logger.info(f"Sending request to Anthropic model '{self.model_id}'...")
            if logger.isEnabledFor(logging.DEBUG):
                try:
                    payload_str = json.dumps(valid_messages, indent=2)
                    logger.debug(f"Anthropic Request Payload:\n{payload_str}")
                except TypeError:
                    logger.debug(f"Anthropic Request Payload (non-serializable): {valid_messages}")

            # Call the chat completion endpoint using the configured client.
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=valid_messages,
                temperature=temperature,
                max_tokens=max_tokens # Anthropic requires this parameter.
            )

            # Ensure the response contains choices before trying to access them.
            if not response.choices:
                raise RuntimeError("Anthropic response contained no choices.")

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Anthropic Response Content:\n{response.choices[0].message.content}")

            # Extract the message content from the first choice.
            assistant_message_obj = response.choices[0].message
            assistant_message: ChatMessage = {"role": "assistant", "content": assistant_message_obj.content.strip() if assistant_message_obj.content else ""}
            logger.info(f"Response received successfully from Anthropic model {self.model_id}.")
            return assistant_message
        except OpenAIRateLimitError as e:
            # Catch the OpenAI SDK's rate limit error and re-raise it as our app's standard RateLimitError.
            raise RateLimitError(f"Anthropic API Rate Limit Exceeded: {e}") from e
        except OpenAIAuthenticationError as e:
            # Catch the OpenAI SDK's authentication error and re-raise it as our app's standard AuthenticationError.
            logger.error(f"Anthropic API Authentication Failed. This is expected if using a fake key. Base URL: {self.client.base_url}. Error: {e}")
            raise AuthenticationError(f"Anthropic API Authentication Failed: {e}") from e
        except Exception as e:
            # Catch any other unexpected errors during the API call.
            logger.exception(f"Unexpected error during API call to Anthropic: {e}")
            raise RuntimeError(f"Unexpected error during API call to Anthropic: {e}") from e