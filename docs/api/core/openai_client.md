<a id="core.openai_client"></a>

# core.openai\_client

<a id="core.openai_client.OpenAIClient"></a>

## OpenAIClient Objects

```python
class OpenAIClient()
```

Handles communication with the OpenAI API using the official openai SDK.

This provides more robust error handling and compatibility than a generic client.

<a id="core.openai_client.OpenAIClient.__init__"></a>

#### \_\_init\_\_

```python
def __init__(api_key: str,
             model: str,
             api_base: Optional[str] = None,
             **kwargs)
```

Initializes the OpenAI client.

**Arguments**:

- `api_key` - The OpenAI API key.
- `model` - The specific OpenAI model identifier (e.g., "gpt-4o").
- `api_base` - Optional base URL for the API endpoint, for proxies or custom deployments.

<a id="core.openai_client.OpenAIClient.chat"></a>

#### chat

```python
def chat(messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage
```

Sends a chat completion request to the OpenAI API.

**Arguments**:

- `messages` - A list of ChatMessage dictionaries representing the conversation.
- `temperature` - The sampling temperature for the model's response.
  

**Returns**:

  A ChatMessage dictionary containing the assistant's response.
  

**Raises**:

- `RateLimitError` - If the API rate limit is exceeded.
- `AuthenticationError` - If the API key is invalid.
- `RuntimeError` - For other unexpected API or processing errors.

