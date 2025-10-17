# src/core/hf_client.py
import logging
import requests
import requests.exceptions # Import specific exceptions
import json
import time
from typing import List, Dict, Any, Optional, TypedDict

# Import exceptions from llm_client for consistency
from .llm_client import RateLimitError, AuthenticationError, ChatMessage

logger = logging.getLogger(__name__)

# Base URL for Hugging Face Inference API
HF_API_BASE_URL = "https://api-inference.huggingface.co/models/"

class HuggingFaceClient:
    """
    Handles communication with the Hugging Face Inference API for text-generation models.

    This client uses the `requests` library to send POST requests to the HF API.
    It includes a retry mechanism with exponential backoff for transient network
    or server-side issues, and specific error handling for common HTTP status codes.
    Includes retry logic and error handling similar to LlmClient.
    """
    def __init__(self, api_token: str, model: str):
        """
        Initializes the Hugging Face client.

        Args:
            api_token: The Hugging Face User Access Token (hf_...).
            model: The specific Hugging Face model identifier (e.g., "deepseek-ai/DeepSeek-V3-0324").

        Raises:
            ValueError: If api_token or model is invalid.
        """
        if not api_token or not isinstance(api_token, str):
            raise ValueError("HuggingFaceClient requires a valid string API token.")
        if not model or not isinstance(model, str):
            raise ValueError("HuggingFaceClient requires a valid string model ID.")

        self.api_token = api_token.strip()
        self.model = model
        # Construct the specific endpoint URL for the chosen model.
        self.api_endpoint = f"{HF_API_BASE_URL}{self.model}"
        self.request_timeout = 120 # Seconds
        self.max_retries = 3
        self.initial_retry_delay = 2.0

        # Use a requests.Session to persist headers and benefit from connection pooling.
        self.session = requests.Session()
        headers = {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json',
        }
        self.session.headers.update(headers)

        logger.info(f"HuggingFaceClient instance created for model '{self.model}'. Endpoint: {self.api_endpoint}")

    def _format_messages_for_hf(self, messages: List[ChatMessage]) -> str:
        """
        Formats a list of chat messages into a single string suitable for
        many Hugging Face text-generation models.

        Note: This is a basic approach. Some models require a more specific chat template.

        Args:
            messages: List of ChatMessage dictionaries.

        Returns:
            A formatted string representing the conversation.
        """
        # Simple concatenation, assuming the model understands roles prepended to the content.
        formatted_prompt = ""
        for msg in messages:
            role = msg.get("name", msg.get("role", "user")).capitalize() # Use name if available
            content = msg.get("content", "")
            # Format as "Role: Content" followed by a newline.
            formatted_prompt += f"{role}: {content}\n"
        # Add a final marker for the assistant to respond
        formatted_prompt += "Assistant:"
        return formatted_prompt

    def chat(self, messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage:
        """
        Sends a request to the Hugging Face Inference API text-generation task.

        Args:
            messages: A list of ChatMessage dictionaries.
            temperature: The sampling temperature to use for the request.

        Returns:
            A ChatMessage dictionary representing the assistant's response.

        Raises:
            ValueError: If messages are invalid.
            RateLimitError: If rate limited (HTTP 429).
            AuthenticationError: If token is invalid (HTTP 401).
            RuntimeError: If the request fails after retries or other errors occur.
        """
        if not messages or not isinstance(messages, list):
            raise ValueError("Cannot send chat request with empty or invalid messages list.")

        # Filter for valid messages to ensure they have the required structure.
        valid_messages = [
            msg for msg in messages
            if isinstance(msg, dict) and 'role' in msg and 'content' in msg
        ]
        if not valid_messages:
            raise ValueError("No valid messages found in the input list.")
        
        # Format the message history into a single prompt string.
        prompt_string = self._format_messages_for_hf(valid_messages)
        
        # Construct the API request payload for text-generation
        # Parameters might need adjustment based on model (e.g., max_new_tokens)
        payload = {
            "inputs": prompt_string,
            "parameters": {
                "return_full_text": False, # Usually want only the generated part
                "max_new_tokens": 1024, # Example limit
                "temperature": max(temperature, 0.01), # Temperature must be > 0 for HF API
            },
            "options": {
                "wait_for_model": True # Wait if the model is still loading on the server
            }
        }

        last_exception: Optional[Exception] = None
        response: Optional[requests.Response] = None

        # Retry loop (similar to LlmClient)
        for attempt in range(self.max_retries):
            should_retry = False
            wait_time = self.initial_retry_delay * (2 ** (attempt - 1))

            logger.info(f"Sending request to Hugging Face model '{self.model}' (Attempt {attempt}/{self.max_retries})...")
            logger.debug(f"HF Request Payload (Input Prompt):\n{prompt_string[:500]}...") # Log prompt start

            raw_response_text = "[Raw text not captured]"
            start_time = time.time()

            try:
                response = self.session.post(
                    self.api_endpoint,
                    json=payload,
                    timeout=self.request_timeout
                )
                end_time = time.time()
                duration = end_time - start_time
                logger.debug(f"Attempt {attempt}: HF API call returned after {duration:.2f} seconds. Status code: {response.status_code}")

                raw_response_text = response.text

                # Handle specific, known HTTP status codes first.
                if response.status_code == 429:
                    rate_limit_message = "Hugging Face API Rate Limit Exceeded (HTTP 429)"
                    try: rate_limit_message = response.json().get('error', rate_limit_message)
                    except Exception: pass
                    logger.error(f"HF API Rate Limit Exceeded for {self.model}. Message: {rate_limit_message}")
                    raise RateLimitError(f"HF API Rate Limit Exceeded for {self.model}: {rate_limit_message}")

                if response.status_code == 401:
                    auth_message = "Hugging Face Authentication Failed (HTTP 401)"
                    try: auth_message = response.json().get('error', auth_message)
                    except Exception: pass
                    logger.error(f"HF API Authentication Failed for {self.model}. Message: {auth_message}")
                    raise AuthenticationError(f"HF API Authentication Failed for {self.model}: {auth_message}")

                # For other non-2xx codes, raise an HTTPError to be caught below.
                response.raise_for_status() # Raises HTTPError for 4xx/5xx

                # Process Successful (2xx) Response
                try:
                    data = response.json()
                    logger.debug(f"Attempt {attempt}: Successfully parsed HF JSON response.")

                    # HF text-generation typically returns a list with one dictionary
                    if isinstance(data, list) and data and isinstance(data[0], dict):
                        generated_text = data[0].get('generated_text')
                        if isinstance(generated_text, str):
                            # Successfully extracted generated text
                            assistant_message: ChatMessage = {
                                "role": "assistant",
                                "content": generated_text.strip()
                                # HF API doesn't typically return a 'name'
                            }
                            logger.info(f"Response received successfully from HF model {self.model}.")
                            return assistant_message
                        else:
                            logger.error("Invalid HF response structure: 'generated_text' key missing or not a string.")
                            last_exception = ValueError("Invalid HF response structure: Invalid 'generated_text'.")
                            should_retry = True # Retry if structure is wrong
                    elif isinstance(data, dict) and (error_msg := data.get('error')): # type: ignore
                         # Handle error messages within a 200 OK response
                         logger.error(f"HF API returned error in 200 OK payload: {error_msg}")
                         # Check if it's a model loading error (often 503 logic in disguise)
                         if "currently loading" in str(error_msg).lower():
                             logger.warning("Model is loading, will retry...")
                             last_exception = RuntimeError(f"Model loading error: {error_msg}")
                             should_retry = True
                         else:
                             last_exception = RuntimeError(f"HF API error in 200 OK payload: {error_msg}")
                             should_retry = False # Don't retry other payload errors usually
                    else:
                        logger.error(f"Invalid HF response structure: Unexpected format - {str(data)[:200]}...")
                        last_exception = ValueError("Invalid HF response structure: Unexpected format.")
                        should_retry = True # Retry if structure is wrong

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode HF JSON response on attempt {attempt}: {e}")
                    logger.error(f"Raw text that failed JSON decoding: {raw_response_text[:1000]}...")
                    last_exception = RuntimeError(f"Failed to decode JSON response from HF ({self.model}): {e}")
                    should_retry = True

            # Handle exceptions raised during the request.
            except requests.exceptions.Timeout as e:
                 end_time = time.time(); duration = end_time - start_time
                 logger.warning(f"HF Timeout occurred on attempt {attempt} after {duration:.2f} seconds: {e}")
                 last_exception = e; should_retry = True
            except requests.exceptions.HTTPError as e:
                 end_time = time.time(); duration = end_time - start_time
                 status_code = e.response.status_code if e.response is not None else 'Unknown'
                 logger.warning(f"HF HTTP error occurred on attempt {attempt} after {duration:.2f} seconds: Status {status_code}")
                 last_exception = e
                 # --- FIX: Raise immediately on the last attempt ---
                 if attempt >= self.max_retries - 1:
                     raise
                 if isinstance(status_code, int) and (status_code == 408 or 500 <= status_code < 600): # Retry 5xx and 408
                     logger.info(f"Retryable HF HTTP error encountered (Status: {status_code}).")
                     should_retry = True
                 else:
                     logger.error(f"Non-retryable HF HTTP error for {self.model}: {e}")
                     if e.response is not None:
                         try: logger.error(f"Non-retryable raw response: {e.response.text[:1000]}...")
                         except Exception: pass
                     raise RuntimeError(f"Non-retryable HTTP error from HF {self.model} (Status: {status_code}): {e}") from e
            except requests.exceptions.RequestException as e:
                 end_time = time.time(); duration = end_time - start_time
                 logger.warning(f"HF Network request failed on attempt {attempt} after {duration:.2f} seconds: {e}")
                 last_exception = e; should_retry = True
            except (RateLimitError, AuthenticationError): raise # Re-raise specific errors
            except Exception as e:
                 end_time = time.time(); duration = end_time - start_time
                 logger.exception(f"Unexpected error during HF API call attempt {attempt} after {duration:.2f} seconds: {e}")
                 last_exception = e
                 raise RuntimeError(f"Unexpected error during API call to HF {self.model}: {e}") from e

            # Retry Logic
            if should_retry and attempt < self.max_retries -1:
                logger.info(f"Waiting {wait_time:.2f} seconds before HF retry ({attempt + 1}/{self.max_retries})...")
                time.sleep(wait_time)
            elif should_retry and attempt >= self.max_retries - 1:
                logger.error(f"Max retries ({self.max_retries}) reached for HF model {self.model}.")
                # --- FIX: Re-raise the last specific exception for better error reporting ---
                if last_exception:
                    raise last_exception
                else: raise RuntimeError(f"Max retries reached for HF model {self.model}, but no specific exception recorded.")

        # Fallback if loop finishes unexpectedly
        final_error_message = f"Failed to get valid response from HF model {self.model} after {self.max_retries} attempts."
        if last_exception:
            logger.error(f"{final_error_message} Last error: {last_exception}")
            raise RuntimeError(final_error_message) from last_exception
        else:
            logger.error(final_error_message + " No specific exception recorded.")
            raise RuntimeError(final_error_message)
