# src/core/llm_client.py
import time
import logging
import requests.exceptions # Import specific exceptions
import requests
import json
from typing import List, Dict, Any, Optional, TypedDict
import random

# Note: Removed the circular import of AgentManager

logger = logging.getLogger(__name__)

class ChatMessage(TypedDict):
    """
    A standardized dictionary structure for representing a single message in a conversation.
    This is used consistently across all LLM clients.
    """
    role: str  # 'user', 'assistant', or 'system'
    content: str
    name: Optional[str] # Optional field for identifying the sender (e.g., 'Tars', 'Case')

class RateLimitError(RuntimeError):
    """
    Custom exception raised specifically for API rate limit errors (e.g., HTTP 429).
    This allows the WorkflowManager to catch it and trigger a user prompt for retrying.
    """
    pass

class AuthenticationError(RuntimeError):
    """
    Custom exception raised specifically for API authentication errors (e.g., HTTP 401/403).
    This allows the WorkflowManager to catch it and trigger a user prompt for updating the API key.
    """
    pass

class LlmClient:
    """
    A client for interacting with the OpenRouter API.
    Handles communication with a Large Language Model API (specifically OpenRouter).
    Includes features like:
    - Sending chat completion requests.
    - Handling API responses and extracting messages.
    - Implementing retry logic for transient network errors and server errors.
    - Specific handling for rate limit (429) and authentication (401/403) errors.
    - Configurable timeout and retry parameters.
    """
    def __init__(self,
                 api_key: str,
                 model: str,
                 api_base: Optional[str] = None,
                 site_url: Optional[str] = None,
                 site_title: Optional[str] = None
                 ):
        """
        Initializes the LLM client.

        Args:
            api_key: The API key for authenticating with the OpenRouter API.
            model: The specific model identifier to use (e.g., "deepseek/deepseek-chat").
            site_url: Optional URL of the referring site for OpenRouter ranking.
            site_title: Optional title of the referring site for OpenRouter ranking.

        Raises:
            ValueError: If api_key or model is invalid.
        """
        if not api_key or not isinstance(api_key, str):
            raise ValueError("LlmClient requires a valid string API key.")
        if not model or not isinstance(model, str):
            raise ValueError("LlmClient requires a valid string model ID.")

        self.api_key = api_key.strip()
        self.model = model
        self.api_endpoint = api_base or 'https://openrouter.ai/api/v1/chat/completions'
        self.request_timeout = 120 # Increased timeout for potentially long generations (seconds)
        self.max_retries = 3      # Maximum number of retries for transient errors
        self.initial_retry_delay = 2.0 # Initial delay before the first retry (seconds)

        # Use a requests.Session for connection pooling and to persist common headers across requests.
        self.session = requests.Session()
        # Set headers that are common to all requests. Provider-specific auth headers
        # will be added per-request in the chat() method.
        headers = {
            'Content-Type': 'application/json',
        }
        # Add optional headers if provided
        if site_url:
            headers['HTTP-Referer'] = site_url
        if site_title:
            headers['X-Title'] = site_title
        self.session.headers.update(headers)

        logger.info(f"LlmClient instance created for model '{self.model}'. Endpoint: {self.api_endpoint}")

    def chat(self, messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage:
        """
        Sends a chat completion request to the LLM API with validation and retry logic.

        Args:
            messages: A list of ChatMessage dictionaries representing the conversation history.
            temperature: The sampling temperature to use for the request.

        Returns:
            A ChatMessage dictionary representing the assistant's response.

        Raises:
            ValueError: If the messages list is empty or invalid.
            RateLimitError: If the API returns a 429 status code.
            AuthenticationError: If the API returns a 401 or 403 status code.
            RuntimeError: If the request fails after all retries or encounters an unrecoverable error.
        """
        if not messages or not isinstance(messages, list):
            raise ValueError("Cannot send chat request with empty or invalid messages list.")

        # Validate and filter messages to ensure they conform to the ChatMessage structure.
        valid_messages = []
        for i, msg in enumerate(messages):
            if isinstance(msg, dict) and 'role' in msg and 'content' in msg and isinstance(msg['content'], str) and isinstance(msg['role'], str):
                 # Create a new dict to avoid modifying the original input and ensure only valid keys are present
                 valid_msg: ChatMessage = {"role": msg["role"], "content": msg["content"]}
                 # Include 'name' only if it exists and is a non-empty string
                 if msg.get("name") and isinstance(msg.get("name"), str):
                     valid_msg["name"] = msg["name"]
                 valid_messages.append(valid_msg)
            else:
                 logger.warning(f"Skipping invalid message structure at index {i}: {str(msg)[:100]}...")
        if not valid_messages:
            raise ValueError("No valid messages found in the input list to send.")

        # Construct the API request payload
        payload = {
            "model": self.model,
            "messages": valid_messages,
            "temperature": temperature,
        }        
        last_exception: Optional[Exception] = None
        response: Optional[requests.Response] = None

        # Retry loop
        for attempt in range(self.max_retries):
            should_retry = False
            # Calculate exponential backoff delay for retries.
            wait_time = self.initial_retry_delay * (2 ** (attempt - 1))

            logger.info(f"Sending {len(valid_messages)} messages to '{self.model}' (Attempt {attempt}/{self.max_retries})...")
            if logger.isEnabledFor(logging.DEBUG):
                # Log message details only if DEBUG is enabled for performance
                try:
                    payload_str = json.dumps(payload, indent=2)
                    logger.debug(f"Request Payload:\n{payload_str}")
                except TypeError:
                     logger.debug(f"Request Payload (non-serializable): {payload}")


            raw_response_text = "[Raw text not captured]"
            start_time = time.time()

            try:
                # --- FIX: Update last_api_call_time BEFORE the request ---
                # This ensures that even if the call fails, the rate limiter knows an attempt was made.
                self.last_api_call_time = start_time

                # Prepare headers for this specific request, including the API key.
                # --- FIX: Build headers fresh to avoid stale session data ---
                request_headers = {
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json',
                    'HTTP-Referer': self.session.headers.get('HTTP-Referer', ''),
                    'X-Title': self.session.headers.get('X-Title', '')
                }
                response = self.session.post(
                    self.api_endpoint,
                    headers=request_headers, # Use the dynamically prepared headers
                    json=payload,
                    timeout=self.request_timeout
                )
                end_time = time.time()
                duration = end_time - start_time
                logger.debug(f"Attempt {attempt}: API call returned after {duration:.2f} seconds. Status code: {response.status_code}")

                raw_response_text = response.text # Store raw text for debugging

                # Handle specific, known HTTP status codes first.
                if response.status_code == 429:
                    # Rate limit error - treat as a retryable condition within this client's loop.
                    rate_limit_message = "API Rate Limit Exceeded (HTTP 429)"
                    try:
                        error_data = response.json().get('error', {})
                        rate_limit_message = error_data.get('message', rate_limit_message)
                    except (json.JSONDecodeError, AttributeError):
                        pass # Ignore parsing errors for error message
                    last_exception = RateLimitError(f"API Rate Limit Exceeded for {self.model}: {rate_limit_message}")
                    # --- FIX: Raise immediately on the last attempt ---
                    if attempt >= self.max_retries - 1:
                        raise last_exception
                    logger.warning(f"API Rate Limit Exceeded for {self.model}. Will retry. Message: {rate_limit_message}")
                    should_retry = True
                    continue
                elif response.status_code in [401, 403]:
                    # Authentication error - raise specific exception immediately, no retry
                    auth_message = f"Authentication Failed (HTTP {response.status_code})"
                    try:
                        error_data = response.json().get('error', {})
                        auth_message = error_data.get('message', auth_message)
                    except (json.JSONDecodeError, AttributeError): pass
                    logger.error(f"API Authentication Failed for {self.model}. Message: {auth_message}")
                    raise AuthenticationError(f"API Authentication Failed for {self.model}: {auth_message}")
                
                else:
                    # For other non-2xx error codes, raise an HTTPError. For 2xx, this does nothing.
                    response.raise_for_status()

                    # Process a successful (2xx) response.
                    try:
                        data = response.json()
                        logger.debug(f"Attempt {attempt}: Successfully parsed JSON response.")

                        # --- FIX: Add logic to process the successful response and return ---
                        if not isinstance(data, dict) or "choices" not in data or not isinstance(data["choices"], list) or not data["choices"]:
                            logger.error(f"Invalid response structure from LLM ({self.model}): 'choices' array is missing or empty.")
                            last_exception = RuntimeError("Invalid response structure from LLM: 'choices' missing or empty.")
                            should_retry = True
                            continue

                        message_data = data["choices"][0].get("message")
                        if not isinstance(message_data, dict) or "content" not in message_data:
                            logger.error(f"Invalid response structure from LLM ({self.model}): 'message' object or 'content' key is missing.")
                            last_exception = RuntimeError("Invalid response structure from LLM: 'message' or 'content' missing.")
                            should_retry = True
                            continue

                        # Successfully extracted the message, return it to exit the loop.
                        message_data['content'] = message_data.get('content', '').strip()
                        return message_data # type: ignore
                        # --- END FIX ---

                    except json.JSONDecodeError as e: # Handle cases where the 200 OK response is not valid JSON.
                        logger.error(f"Failed to decode JSON response on attempt {attempt} for {self.model}: {e}")
                        logger.error(f"Raw text that failed JSON decoding: {raw_response_text[:1000]}...")
                        last_exception = RuntimeError(f"Failed to decode JSON response from LLM ({self.model}): {e}")
                        should_retry = True

            # Handle exceptions raised during the `requests.post` call.
            except requests.exceptions.Timeout as e:
                 end_time = time.time(); duration = end_time - start_time
                 logger.warning(f"Timeout occurred on attempt {attempt} after {duration:.2f} seconds: {e}")
                 last_exception = e; should_retry = True
            except requests.exceptions.HTTPError as e: # Handles non-2xx responses not caught above
                 end_time = time.time(); duration = end_time - start_time
                 status_code = e.response.status_code if e.response is not None else 'Unknown'
                 logger.warning(f"HTTP error occurred on attempt {attempt} after {duration:.2f} seconds: Status {status_code}")
                 last_exception = e
                 # Retry on server-side errors (5xx) and request timeouts (408).
                 if isinstance(status_code, int) and (status_code == 408 or 500 <= status_code < 600):
                     logger.info(f"Retryable HTTP error encountered (Status: {status_code}).")
                     should_retry = True
                 else:
                     logger.error(f"Non-retryable HTTP error for {self.model}: {e}")
                     if e.response is not None:
                         try: logger.error(f"Non-retryable raw response: {e.response.text[:1000]}...")
                         except Exception: pass
                     # Re-raise the original HTTPError, as it's not a transient issue we should retry.
                     raise
            except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
                 # These are often transient network issues, so we should retry.
                 end_time = time.time(); duration = end_time - start_time
                 logger.warning(f"Connection/Network error on attempt {attempt} after {duration:.2f} seconds: {e}")
                 last_exception = e; should_retry = True
            except requests.exceptions.RequestException as e:
                # Catch any other requests-related exceptions that are not specifically handled above.
                # These are less likely to be transient, so we will not retry them.
                logger.error(f"An unrecoverable network request error occurred: {e}", exc_info=True)
                raise RuntimeError(f"Unrecoverable network error during API call to {self.model}: {e}") from e
            except (RateLimitError, AuthenticationError): raise # Re-raise our custom errors immediately.
            except Exception as e: # Catch any other unexpected errors.
                 end_time = time.time(); duration = end_time - start_time
                 logger.exception(f"Unexpected error during API call attempt {attempt} after {duration:.2f} seconds: {e}")
                 last_exception = e
                 raise RuntimeError(f"Unexpected error during API call to {self.model}: {e}") from e

            # If a retry is warranted, wait with exponential backoff and jitter.
            if should_retry and attempt < self.max_retries - 1:
                # Add jitter to the delay to prevent a "thundering herd" problem in case of concurrent failures.
                jitter_wait_time = random.uniform(0, wait_time)
                logger.info(f"Waiting {jitter_wait_time:.2f} seconds (base backoff: {wait_time:.2f}s) before retry ({attempt + 1}/{self.max_retries})...")
                time.sleep(jitter_wait_time)
            elif should_retry and attempt >= self.max_retries - 1:
                logger.error(f"Max retries ({self.max_retries}) reached for {self.model}.")
                # --- FIX: Re-raise the last specific exception for better error reporting ---
                if last_exception:
                    raise last_exception
                else: raise RuntimeError(f"Max retries reached for {self.model}, but no specific exception recorded.")

        # This block should not be reached with the current logic but serves as a final safeguard.
        final_error_message = f"Failed to get valid response from {self.model} after {self.max_retries} attempts (unexpected loop exit)."
        # --- FIX: Always raise the most specific error available ---
        if last_exception:
            logger.error(f"{final_error_message} Last error: {last_exception}")
            raise last_exception
        else:
            logger.error(final_error_message + " No specific exception recorded.")
            raise RuntimeError(final_error_message)
