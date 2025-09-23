<a id="core.anthropic_client"></a>

# core.anthropic\_client

<a id="core.anthropic_client.AnthropicClient"></a>

## AnthropicClient Objects

```python
class AnthropicClient()
```

Handles communication with the Anthropic (Claude) API.

This client cleverly uses the official 'openai' Python SDK to interact with
Anthropic's API by pointing it to the Anthropic base URL and providing the
necessary headers. This approach allows for consistent error handling and
data structures across different clients.

<a id="core.anthropic_client.AnthropicClient.__init__"></a>

#### \_\_init\_\_

```python
def __init__(api_key: str, model: str, **kwargs)
```

Initializes the Anthropic client via the OpenAI SDK.

This setup configures the OpenAI client object to communicate with the
Anthropic API endpoint instead of OpenAI's.

**Arguments**:

- `api_key` - The Anthropic API key.
- `model` - The specific Claude model identifier (e.g., "claude-3-opus-20240229").

<a id="core.anthropic_client.AnthropicClient.chat"></a>

#### chat

```python
def chat(messages: List[ChatMessage],
         temperature: float = 0.1,
         max_tokens: int = 4096) -> ChatMessage
```

Sends a chat completion request to the Anthropic API.

**Arguments**:

- `messages` - A list of ChatMessage dictionaries representing the conversation.
- `temperature` - The sampling temperature for the model's response.
- `max_tokens` - The maximum number of tokens to generate in the response.
  

**Returns**:

  A ChatMessage dictionary containing the assistant's response.
  

**Raises**:

- `RateLimitError` - If the API rate limit is exceeded.
- `AuthenticationError` - If the API key is invalid.
- `RuntimeError` - For other unexpected API or processing errors.

