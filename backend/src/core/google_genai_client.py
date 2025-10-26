# backend/src/core/google_genai_client.py
import logging
import google.generativeai as genai
from typing import List, Optional

import json
# --- FIX: Import specific exceptions from the google-genai SDK ---
try:
    from google.api_core import exceptions as google_exceptions
except ImportError:
    # Create dummy exceptions if the library isn't installed, though the main import would fail first.
    class google_exceptions:
        class PermissionDenied(Exception): pass
        class ResourceExhausted(Exception): pass
        class DeadlineExceeded(Exception): pass

# Import exceptions from llm_client for consistency
from .llm_client import RateLimitError, AuthenticationError, ChatMessage

logger = logging.getLogger(__name__)

class GoogleGenAIClient:
    """
    A client for interacting with the Google Gemini series of models.
    Handles communication with the Google Gemini API using the official google-genai SDK.
    """
    def __init__(self, api_key: str, model: str, **kwargs):
        """
        Initializes the Google Gemini client.

        Args:
            api_key: The Google API key.
            model: The specific Gemini model identifier (e.g., "gemini-1.5-pro").
        """
        if not api_key or not isinstance(api_key, str):
            raise ValueError("GoogleGenAIClient requires a valid string API key.")
        if not model or not isinstance(model, str):
            raise ValueError("GoogleGenAIClient requires a valid string model ID.")

        # Store the model ID for use in chat requests.
        self.model_id = model
        try:
            # Configure the SDK with the provided API key
            genai.configure(api_key=api_key)
            # Create a reusable GenerativeModel instance.
            # System prompts are handled per-request to keep this instance stateless.
            self.model = genai.GenerativeModel(self.model_id)
            logger.info(f"GoogleGenAIClient instance created for model '{self.model_id}'.")
        except Exception as e:
            logger.exception("Failed to configure Google GenAI client.")
            raise RuntimeError(f"Failed to initialize Google GenAI client: {e}") from e

    def chat(self, messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage:
        """
        Sends a request to the Google Gemini API.

        This method formats the standard `ChatMessage` list into the format
        expected by the Gemini API, separating the system prompt from the
        user/assistant message history.

        Args:
            messages: A list of ChatMessage dictionaries representing the conversation.
            temperature: The sampling temperature for the model's response.

        Returns:
            A ChatMessage dictionary containing the assistant's response.

        Raises:
            AuthenticationError: If the API key is invalid.
            RateLimitError: If the API rate limit is exceeded.
            RuntimeError: For other unexpected API or processing errors.
        """
        if not messages or not isinstance(messages, list):
            raise ValueError("Cannot send chat request with empty or invalid messages list.")

        # Gemini handles system prompts separately from the main message history.
        system_instruction = None
        gemini_messages = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                system_instruction = content
            elif role == "assistant":
                # The Gemini API uses the role 'model' for assistant messages.
                gemini_messages.append({"role": "model", "parts": [{"text": content}]})
            elif role == "user":
                gemini_messages.append({"role": "user", "parts": [{"text": content}]})

        # If a system prompt is provided, create a temporary model instance for this specific call.
        # This is the recommended approach to avoid modifying the shared client state.
        model_to_use = self.model
        if system_instruction:
            logger.debug("System instruction found. Using a temporary model instance for this call.")
            model_to_use = genai.GenerativeModel(
                self.model_id,
                system_instruction=system_instruction
            )
        
        # Configure the generation parameters for the API call.
        generation_config = genai.types.GenerationConfig(
            temperature=temperature
        )

        try:
            logger.info(f"Sending request to Google Gemini model '{self.model_id}'...")
            if logger.isEnabledFor(logging.DEBUG):
                try:
                    # Use json.dumps for pretty printing the payload
                    payload_str = json.dumps(gemini_messages, indent=2)
                    logger.debug(f"Google GenAI Request Payload:\n{payload_str}")
                except TypeError:
                    logger.debug(f"Google GenAI Request Payload (non-serializable): {gemini_messages}")

            response = model_to_use.generate_content(
                contents=gemini_messages,
                generation_config=generation_config,
                stream=False  # Explicitly disable streaming to prevent hanging issues.
            )

            # The response may be empty if the content was blocked by safety settings.
            if not response.candidates:
                block_reason = response.prompt_feedback.block_reason.name if response.prompt_feedback else "Unknown"
                logger.error(f"Gemini response was blocked. Reason: {block_reason}")
                raise RuntimeError(f"Content blocked by Google's safety settings. Reason: {block_reason}")

            # Extract the text from the response and format it as a standard ChatMessage.
            assistant_message: ChatMessage = {"role": "assistant", "content": response.text.strip()}
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Google GenAI Response Content:\n{assistant_message['content']}")
            logger.info(f"Response received successfully from Gemini model {self.model_id}.")
            return assistant_message

        # Catch specific Google API exceptions and map them to our application's standard exceptions.
        except google_exceptions.PermissionDenied as e:
            # PermissionDenied indicates an authentication problem (e.g., bad API key).
            logger.error(f"Google API Authentication Failed (Permission Denied): {e}")
            raise AuthenticationError(f"Google API Authentication Failed: {e}") from e
        except (google_exceptions.ResourceExhausted, google_exceptions.DeadlineExceeded) as e:
            # Treat both rate limits (ResourceExhausted) and timeouts (DeadlineExceeded)
            # as a RateLimitError, which the WorkflowManager can handle with a retry.
            error_name = "Rate Limit Exceeded" if isinstance(e, google_exceptions.ResourceExhausted) else "Deadline Exceeded"
            logger.error(f"Google API {error_name}: {e}")
            raise RateLimitError(f"Google API {error_name}: {e}") from e
        except Exception as e:
            # Catch any other unexpected errors during the API call.
            logger.exception(f"Unexpected error during API call to Google Gemini: {e}")
            raise RuntimeError(f"Unexpected error during API call to Google Gemini: {e}") from e