# src/core/openai_client.py
import logging
from typing import List, Optional

try:
    from openai import OpenAI, RateLimitError as OpenAIRateLimitError, AuthenticationError as OpenAIAuthenticationError
except ImportError:
    raise ImportError("The 'openai' package is required to use the OpenAIClient. Please install it with 'pip install openai'.")

# Import exceptions from the shared llm_client for consistency
from .llm_client import RateLimitError, AuthenticationError, ChatMessage

logger = logging.getLogger(__name__)

class OpenAIClient:
    """
    Handles communication with the OpenAI API using the official openai SDK.

    This provides more robust error handling and compatibility than a generic client.
    """
    def __init__(self, api_key: str, model: str, api_base: Optional[str] = None, **kwargs):
        """
        Initializes the OpenAI client.

        Args:
            api_key: The OpenAI API key.
            model: The specific OpenAI model identifier (e.g., "gpt-4o").
            api_base: Optional base URL for the API endpoint, for proxies or custom deployments.
        """
        if not api_key or not isinstance(api_key, str):
            raise ValueError("OpenAIClient requires a valid string API key.")
        if not model or not isinstance(model, str):
            raise ValueError("OpenAIClient requires a valid string model ID.")

        self.model_id = model
        # Instantiate the official OpenAI client.
        try:
            self.client = OpenAI(
                api_key=api_key,
                base_url=api_base,
            )
            logger.info(f"OpenAIClient instance created for model '{self.model_id}'.")
        except Exception as e:
            logger.exception("Failed to configure OpenAI client.")
            raise RuntimeError(f"Failed to initialize OpenAI client: {e}") from e

    def chat(self, messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage:
        """
        Sends a chat completion request to the OpenAI API.

        Args:
            messages: A list of ChatMessage dictionaries representing the conversation.
            temperature: The sampling temperature for the model's response.

        Returns:
            A ChatMessage dictionary containing the assistant's response.

        Raises:
            RateLimitError: If the API rate limit is exceeded.
            AuthenticationError: If the API key is invalid.
            RuntimeError: For other unexpected API or processing errors.
        """
        if not messages or not isinstance(messages, list):
            raise ValueError("Cannot send chat request with empty or invalid messages list.")

        # The application's internal ChatMessage format is already compatible with the OpenAI SDK.
        valid_messages = [{"role": msg["role"], "content": msg["content"]} for msg in messages if msg.get("role") in ["system", "user", "assistant"]]

        try:
            logger.info(f"Sending request to OpenAI model '{self.model_id}'...")
            # Call the chat completion endpoint using the configured client.
            response = self.client.chat.completions.create(model=self.model_id, messages=valid_messages, temperature=temperature)

            # Ensure the response contains choices before trying to access them.
            if not response.choices:
                raise RuntimeError("OpenAI response contained no choices.")

            # Extract the message content from the first choice.
            assistant_message_obj = response.choices[0].message
            assistant_message: ChatMessage = {"role": "assistant", "content": assistant_message_obj.content.strip() if assistant_message_obj.content else ""}
            logger.info(f"Response received successfully from OpenAI model {self.model_id}.")
            return assistant_message
        except OpenAIRateLimitError as e:
            # Catch the OpenAI SDK's rate limit error and re-raise it as our app's standard RateLimitError.
            raise RateLimitError(f"OpenAI API Rate Limit Exceeded: {e}") from e
        except OpenAIAuthenticationError as e:
            # Catch the OpenAI SDK's authentication error and re-raise it as our app's standard AuthenticationError.
            logger.error(f"OpenAI API Authentication Failed. This is expected if using a fake key. Base URL: {self.client.base_url}. Error: {e}")
            raise AuthenticationError(f"OpenAI API Authentication Failed: {e}") from e
        except Exception as e:
            # Catch any other unexpected errors during the API call.
            logger.exception(f"Unexpected error during API call to OpenAI: {e}")
            raise RuntimeError(f"Unexpected error during API call to OpenAI: {e}") from e