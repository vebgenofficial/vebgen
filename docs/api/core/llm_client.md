<a id="core.llm_client"></a>

# core.llm\_client

<a id="core.llm_client.ChatMessage"></a>

## ChatMessage Objects

```python
class ChatMessage(TypedDict)
```

A standardized dictionary structure for representing a single message in a conversation.
This is used consistently across all LLM clients.

<a id="core.llm_client.ChatMessage.role"></a>

#### role

'user', 'assistant', or 'system'

<a id="core.llm_client.ChatMessage.name"></a>

#### name

Optional field for identifying the sender (e.g., 'Tars', 'Case')

<a id="core.llm_client.RateLimitError"></a>

## RateLimitError Objects

```python
class RateLimitError(RuntimeError)
```

Custom exception raised specifically for API rate limit errors (e.g., HTTP 429).
This allows the WorkflowManager to catch it and trigger a user prompt for retrying.

<a id="core.llm_client.AuthenticationError"></a>

## AuthenticationError Objects

```python
class AuthenticationError(RuntimeError)
```

Custom exception raised specifically for API authentication errors (e.g., HTTP 401/403).
This allows the WorkflowManager to catch it and trigger a user prompt for updating the API key.

<a id="core.llm_client.LlmClient"></a>

## LlmClient Objects

```python
class LlmClient()
```

A client for interacting with the OpenRouter API.
Handles communication with a Large Language Model API (specifically OpenRouter).
Includes features like:
- Sending chat completion requests.
- Handling API responses and extracting messages.
- Implementing retry logic for transient network errors and server errors.
- Specific handling for rate limit (429) and authentication (401/403) errors.
- Configurable timeout and retry parameters.

<a id="core.llm_client.LlmClient.__init__"></a>

#### \_\_init\_\_

```python
def __init__(api_key: str,
             model: str,
             api_base: Optional[str] = None,
             site_url: Optional[str] = None,
             site_title: Optional[str] = None)
```

Initializes the LLM client.

**Arguments**:

- `api_key` - The API key for authenticating with the OpenRouter API.
- `model` - The specific model identifier to use (e.g., "deepseek/deepseek-chat").
- `site_url` - Optional URL of the referring site for OpenRouter ranking.
- `site_title` - Optional title of the referring site for OpenRouter ranking.
  

**Raises**:

- `ValueError` - If api_key or model is invalid.

<a id="core.llm_client.LlmClient.chat"></a>

#### chat

```python
def chat(messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage
```

Sends a chat completion request to the LLM API with validation and retry logic.

**Arguments**:

- `messages` - A list of ChatMessage dictionaries representing the conversation history.
- `temperature` - The sampling temperature to use for the request.
  

**Returns**:

  A ChatMessage dictionary representing the assistant's response.
  

**Raises**:

- `ValueError` - If the messages list is empty or invalid.
- `RateLimitError` - If the API returns a 429 status code.
- `AuthenticationError` - If the API returns a 401 or 403 status code.
- `RuntimeError` - If the request fails after all retries or encounters an unrecoverable error.

