<a id="core.google_genai_client"></a>

# core.google\_genai\_client

<a id="core.google_genai_client.GoogleGenAIClient"></a>

## GoogleGenAIClient Objects

```python
class GoogleGenAIClient()
```

A client for interacting with the Google Gemini series of models.
Handles communication with the Google Gemini API using the official google-genai SDK.

<a id="core.google_genai_client.GoogleGenAIClient.__init__"></a>

#### \_\_init\_\_

```python
def __init__(api_key: str, model: str, **kwargs)
```

Initializes the Google Gemini client.

**Arguments**:

- `api_key` - The Google API key.
- `model` - The specific Gemini model identifier (e.g., "gemini-1.5-pro").

<a id="core.google_genai_client.GoogleGenAIClient.chat"></a>

#### chat

```python
def chat(messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage
```

Sends a request to the Google Gemini API.

This method formats the standard `ChatMessage` list into the format
expected by the Gemini API, separating the system prompt from the
user/assistant message history.

**Arguments**:

- `messages` - A list of ChatMessage dictionaries representing the conversation.
- `temperature` - The sampling temperature for the model's response.
  

**Returns**:

  A ChatMessage dictionary containing the assistant's response.
  

**Raises**:

- `AuthenticationError` - If the API key is invalid.
- `RateLimitError` - If the API rate limit is exceeded.
- `RuntimeError` - For other unexpected API or processing errors.

