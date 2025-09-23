<a id="core.hf_client"></a>

# core.hf\_client

<a id="core.hf_client.HuggingFaceClient"></a>

## HuggingFaceClient Objects

```python
class HuggingFaceClient()
```

Handles communication with the Hugging Face Inference API for text-generation models.

This client uses the `requests` library to send POST requests to the HF API.
It includes a retry mechanism with exponential backoff for transient network
or server-side issues, and specific error handling for common HTTP status codes.
Includes retry logic and error handling similar to LlmClient.

<a id="core.hf_client.HuggingFaceClient.__init__"></a>

#### \_\_init\_\_

```python
def __init__(api_token: str, model: str)
```

Initializes the Hugging Face client.

**Arguments**:

- `api_token` - The Hugging Face User Access Token (hf_...).
- `model` - The specific Hugging Face model identifier (e.g., "deepseek-ai/DeepSeek-V3-0324").
  

**Raises**:

- `ValueError` - If api_token or model is invalid.

<a id="core.hf_client.HuggingFaceClient.chat"></a>

#### chat

```python
def chat(messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage
```

Sends a request to the Hugging Face Inference API text-generation task.

**Arguments**:

- `messages` - A list of ChatMessage dictionaries.
- `temperature` - The sampling temperature to use for the request.
  

**Returns**:

  A ChatMessage dictionary representing the assistant's response.
  

**Raises**:

- `ValueError` - If messages are invalid.
- `RateLimitError` - If rate limited (HTTP 429).
- `AuthenticationError` - If token is invalid (HTTP 401).
- `RuntimeError` - If the request fails after retries or other errors occur.

