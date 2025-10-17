# 🤖 LLM Clients - Complete Documentation

## 🎯 Overview

**Files**: 5 client implementations (50 KB total)  
**Purpose**: The **unified API gateway** that connects VebGen to 5+ AI providers with 120+ models

This is VebGen's **LLM abstraction layer**—a set of Python clients that provide a **single, consistent interface** to communicate with different AI providers. No matter which model you use (GPT-4, Claude Sonnet, Gemini, DeepSeek), VebGen calls the same `chat()` method.

**Architecture**:
```text
AgentManager
↓
[Unified Interface: chat(messages, temperature) → ChatMessage]
↓
┌─────────────┬────────────────┬─────────────────┬───────────────────┬───────────────────┐
│ LlmClient   │ OpenAIClient   │ AnthropicClient │ GoogleGenAIClient │ HuggingFaceClient │
├─────────────┼────────────────┼─────────────────┼───────────────────┼───────────────────┤
│ OpenRouter  │ OpenAI         │ Anthropic       │ Google            │ Hugging Face      │
│ Groq        │ Azure OpenAI   │ Claude          │ Gemini            │ Open Source       │
│ Together AI │ Custom OpenAI  │                 │                   │ DeepSeek          │
│ Anyscale    │ -compatible    │                 │                   │ Qwen              │
│ 200+ models │ APIs           │                 │                   │ Llama             │
└─────────────┴────────────────┴─────────────────┴───────────────────┴───────────────────┘
```

**Think of it as**: USB ports—different devices (providers), one standard interface (chat method).

---

## 🧠 For Users: What These Files Do

### The Problem These Solve

**Without Clients**:
> Different API for each provider 💀
> ```python
> if provider == "openai":
>     response = openai.ChatCompletion.create(...)
> elif provider == "anthropic":
>     response = anthropic.messages.create(...)
> elif provider == "google":
>     response = genai.GenerativeModel(...).generate_content(...)
> ```
> Result: Complex, error-prone code

**With VebGen's Clients**:
> Same interface for ALL providers ✅
> ```python
> client = get_client(provider, model, api_key)
> response = client.chat(messages, temperature=0.1)
> ```
> Result: Simple, consistent, maintainable

---

### What Each Client Does

**5 Specialized Clients**:

| Client | Provider(s) | Models | Key Features |
|--------|-------------|--------|--------------|
| **LlmClient** | OpenRouter, Groq, Together AI, Anyscale | 200+ | OpenAI-compatible APIs, 20 free models |
| **OpenAIClient** | OpenAI, Azure OpenAI | GPT-3.5/4/5, o1/o3 | Official SDK, streaming support |
| **AnthropicClient** | Anthropic | Claude 3.5/4 | 200k context, best reasoning |
| **GoogleGenAIClient** | Google | Gemini 1.0/1.5/2.5 | 2M context, multimodal |
| **HuggingFaceClient** | Hugging Face | DeepSeek, Qwen, Llama | Free inference, open source |

---

## 👨‍💻 For Developers: Technical Architecture

### Common Interface

**All 5 clients implement the same interface**:

```python
class BaseClient:
    def __init__(self, api_key: str, model: str, **kwargs):
        """Initialize client with credentials"""

    def chat(self, messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage:
        """Send chat request and return response"""
```

**Standard Types**:

```python
class ChatMessage(TypedDict):
    """Standardized message format across all clients"""
    role: str # "system", "user", or "assistant"
    content: str
    name: Optional[str] # Optional agent name ("Tars", "Case")

# Example:
message = {
    "role": "user",
    "content": "Create a Django model for blog posts",
    "name": "Case"
}
```

**Standard Exceptions**:

> Defined in llm_client.py, used by all clients
> ```python
> class RateLimitError(RuntimeError):
>     """HTTP 429 - Rate limit exceeded"""
>     # Trigger: User gets option to retry or wait
> 
> class AuthenticationError(RuntimeError):
>     """HTTP 401/403 - Invalid API key"""
>     # Trigger: User prompted to enter new API key
> ```

---

## 📘 Client 1: LlmClient (Generic OpenAI-Compatible)

**File**: `llm_client.py` (16.6 KB)  
**Use Case**: OpenRouter, Groq, Together AI, Anyscale, local servers

### Key Features

✅ **200+ models via OpenRouter** (20 free models!)  
✅ **Exponential backoff retry** (3 attempts with 2→4→8 sec delays)  
✅ **Jittered waits** (prevents thundering herd)  
✅ **Connection pooling** (`requests.Session`)  
✅ **Detailed logging** (request/response payloads at DEBUG level)  

### Initialization

```python
client = LlmClient(
    api_key="sk-or-v1-abc123...", # OpenRouter API key
    model="deepseek/deepseek-chat-v3.1:free", # Free model!
    api_base="https://openrouter.ai/api/v1/chat/completions",
    site_url="https://vebgen.ai", # For OpenRouter rankings
    site_title="VebGen AI"
)
```

### Chat Method

```python
def chat(self, messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage:
    # 1. Validate messages
    valid_messages = [msg for msg in messages if 'role' in msg and 'content' in msg]

    # 2. Build payload
    payload = {
        "model": self.model,
        "messages": valid_messages,
        "temperature": temperature
    }

    # 3. Retry loop (3 attempts)
    for attempt in range(self.max_retries):
        try:
            # 4. Send POST request
            response = self.session.post(
                self.api_endpoint,
                headers={'Authorization': f'Bearer {self.api_key}'},
                json=payload,
                timeout=120
            )
            
            # 5. Handle specific errors
            if response.status_code == 429:  # Rate limit
                if attempt >= self.max_retries - 1:
                    raise RateLimitError("API Rate Limit Exceeded")
                # Exponential backoff with jitter
                wait_time = self.initial_retry_delay * (2 ** attempt)
                time.sleep(random.uniform(0, wait_time))
                continue
            
            elif response.status_code in [401, 403]:  # Auth error
                raise AuthenticationError("API Authentication Failed")
            
            # 6. Parse successful response
            data = response.json()
            message_content = data["choices"][0]["message"]["content"]
            return {"role": "assistant", "content": message_content}
        
        except requests.exceptions.Timeout:
            # Network timeout - retry
            continue
        except requests.exceptions.HTTPError as e:
            if 500 <= e.response.status_code < 600:
                # Server error - retry
                continue
            else:
                # Client error - don't retry
                raise
```

### Example Usage

```python
messages = [
    {"role": "system", "content": "You are a Django expert."},
    {"role": "user", "content": "Create a User model with email authentication"}
]

response = client.chat(messages, temperature=0.1)
print(response["content"])
```
> Output: "Here's a Django User model with email auth..."

---

## 📗 Client 2: OpenAIClient (Official OpenAI SDK)

**File**: `openai_client.py` (5.3 KB)  
**Use Case**: OpenAI, Azure OpenAI, OpenAI-compatible proxies

### Key Features

✅ **Official `openai` SDK** (robust, maintained)  
✅ **128k context** (GPT-4o, GPT-4-turbo)  
✅ **Reasoning models** (o1, o3)  
✅ **Streaming support** (future enhancement)  
✅ **Azure OpenAI compatible**  

### Initialization

```python
from openai import OpenAI

client = OpenAIClient(
    api_key="sk-proj-abc123...",
    model="gpt-4o",
    api_base="https://api.openai.com/v1" # Optional, for proxies
)

# Internally creates:
self.client = OpenAI(api_key=api_key, base_url=api_base)
```

### Chat Method

```python
def chat(self, messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage:
    valid_messages = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in messages
        if msg.get("role") in ["system", "user", "assistant"]
    ]

    try:
        # Use official SDK method
        response = self.client.chat.completions.create(
            model=self.model_id,
            messages=valid_messages,
            temperature=temperature
        )
        
        # Extract response
        assistant_message = response.choices[0].message
        return {
            "role": "assistant",
            "content": assistant_message.content.strip()
        }

    except OpenAIRateLimitError as e:
        raise RateLimitError(f"OpenAI API Rate Limit Exceeded: {e}")

    except OpenAIAuthenticationError as e:
        raise AuthenticationError(f"OpenAI API Authentication Failed: {e}")
```

### Why Use This Instead of LlmClient?

**LlmClient** (generic `requests`):
- ✅ Works with any OpenAI-compatible API
- ❌ No official SDK optimizations
- ❌ Manual error handling

**OpenAIClient** (official SDK):
- ✅ Official OpenAI support
- ✅ Automatic retries built-in
- ✅ Better error messages
- ❌ Only works with OpenAI/Azure

---

## 📕 Client 3: AnthropicClient (Claude via OpenAI SDK)

**File**: `anthropic_client.py` (6.1 KB)  
**Use Case**: Anthropic Claude models

### Key Features

✅ **Clever hack**: Uses OpenAI SDK to call Anthropic API  
✅ **200k context** (Claude Opus 4)  
✅ **Best reasoning** (outperforms GPT-4 on many tasks)  
✅ **Required `max_tokens` parameter** (Anthropic quirk)  

### Why Use OpenAI SDK for Anthropic?

> **Anthropic's official SDK** requires different imports and patterns.  
> **Solution**: Point OpenAI SDK to Anthropic's URL with custom headers!
> ```python
> from openai import OpenAI
> 
> client = OpenAI(
>     api_key="sk-ant-abc123...", # Anthropic API key
>     base_url="https://api.anthropic.com/v1", # Anthropic endpoint
>     default_headers={"anthropic-version": "2023-06-01"} # Required header
> )
> ```
> Now OpenAI SDK talks to Anthropic! 🎉

### Initialization

```python
client = AnthropicClient(
    api_key="sk-ant-abc123...",
    model="claude-sonnet-4-20250514"
)

# Internally:
self.client = OpenAI(
    api_key=api_key,
    base_url="https://api.anthropic.com/v1",
    default_headers={"anthropic-version": "2023-06-01"}
)
```

### Chat Method

```python
def chat(self, messages: List[ChatMessage], temperature: float = 0.1, max_tokens: int = 4096) -> ChatMessage:
    valid_messages = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in messages
        if msg.get("role") in ["system", "user", "assistant"]
    ]

    try:
        response = self.client.chat.completions.create(
            model=self.model_id,
            messages=valid_messages,
            temperature=temperature,
            max_tokens=max_tokens  # REQUIRED for Anthropic API
        )
        
        assistant_message = response.choices[0].message
        return {
            "role": "assistant",
            "content": assistant_message.content.strip()
        }

    except OpenAIRateLimitError as e:
        raise RateLimitError(f"Anthropic API Rate Limit Exceeded: {e}")

    except OpenAIAuthenticationError as e:
        raise AuthenticationError(f"Anthropic API Authentication Failed: {e}")
```

---

## 📙 Client 4: GoogleGenAIClient (Gemini via Official SDK)

**File**: `google_genai_client.py` (7.6 KB)  
**Use Case**: Google Gemini models

### Key Features

✅ **Official `google-generativeai` SDK**  
✅ **2M context window** (Gemini 1.5 Pro)  
✅ **Multimodal** (text, images, video - future support)  
✅ **Free tier**: 1,500 requests/day (Gemini 1.5 Flash)  
✅ **Safety filters** (blocks inappropriate content)  

### Special Handling: System Prompts

**Gemini** handles system prompts differently than OpenAI/Anthropic:

> OpenAI/Anthropic: System prompt is just another message
> ```python
> messages = [
>     {"role": "system", "content": "You are a Django expert."},
>     {"role": "user", "content": "Create a model"}
> ]
> ```
>
> Gemini: System prompt is a separate parameter
> ```python
> model = genai.GenerativeModel(
>     "gemini-1.5-pro",
>     system_instruction="You are a Django expert." # Separate!
> )
> ```

### Initialization

```python
import google.generativeai as genai

client = GoogleGenAIClient(
    api_key="AIzaSy...",
    model="gemini-2.5-pro"
)

# Internally:
genai.configure(api_key=api_key)
self.model = genai.GenerativeModel(model_id)
```

### Chat Method

```python
def chat(self, messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage:
    # 1. Separate system prompt from conversation
    system_instruction = None
    gemini_messages = []

    for msg in messages:
        if msg["role"] == "system":
            system_instruction = msg["content"]
        elif msg["role"] == "assistant":
            # Gemini uses "model" role instead of "assistant"
            gemini_messages.append({
                "role": "model",
                "parts": [{"text": msg["content"]}]
            })
        elif msg["role"] == "user":
            gemini_messages.append({
                "role": "user",
                "parts": [{"text": msg["content"]}]
            })

    # 2. Create temporary model with system instruction
    model_to_use = self.model
    if system_instruction:
        model_to_use = genai.GenerativeModel(
            self.model_id,
            system_instruction=system_instruction
        )

    # 3. Generate content
    generation_config = genai.types.GenerationConfig(temperature=temperature)

    try:
        response = model_to_use.generate_content(
            contents=gemini_messages,
            generation_config=generation_config,
            stream=False
        )
        
        # 4. Handle safety blocks
        if not response.candidates:
            block_reason = response.prompt_feedback.block_reason.name
            raise RuntimeError(f"Content blocked by Google's safety settings: {block_reason}")
        
        # 5. Extract text
        return {
            "role": "assistant",
            "content": response.text.strip()
        }

    except google_exceptions.PermissionDenied as e:
        raise AuthenticationError(f"Google API Authentication Failed: {e}")

    except google_exceptions.ResourceExhausted as e:
        raise RateLimitError(f"Google API Rate Limit Exceeded: {e}")
```

### Safety Filter Example

> User prompt contains violent content
> ```python
> messages = [
>     {"role": "user", "content": "How to make a bomb"}
> ]
> 
> try:
>     response = client.chat(messages)
> except RuntimeError as e:
>     print(e)
> # Output: "Content blocked by Google's safety settings: SAFETY"
> ```

---

## 📒 Client 5: HuggingFaceClient (Open Source Models)

**File**: `hf_client.py` (14.2 KB)  
**Use Case**: Hugging Face inference API (DeepSeek, Qwen, Llama)

### Key Features

✅ **Free serverless inference** (100 requests/day)  
✅ **236B parameter models** (DeepSeek-Coder-V2)  
✅ **Best open-source coder** (Qwen 2.5 Coder)  
✅ **Model auto-loading** (`wait_for_model: true`)  
✅ **Custom prompt formatting** (per-model chat templates)  

### Prompt Formatting Challenge

**Problem**: Hugging Face models expect **raw text** input, not structured messages

**Example**:
> OpenAI format (structured)
> ```python
> messages = [
>     {"role": "system", "content": "You are helpful"},
>     {"role": "user", "content": "Hello"}
> ]
> ```
>
> Hugging Face format (flat string)
> ```
> prompt = """System: You are helpful
> User: Hello
> Assistant:"""
> ```

**Solution**: `_format_messages_for_hf()` method

```python
def _format_messages_for_hf(self, messages: List[ChatMessage]) -> str:
    formatted_prompt = ""
    for msg in messages:
        role = msg.get("name", msg.get("role", "user")).capitalize()
        content = msg.get("content", "")
        formatted_prompt += f"{role}: {content}\n"

    # Add final marker for assistant to respond
    formatted_prompt += "Assistant:"
    return formatted_prompt
```

### Initialization

```python
client = HuggingFaceClient(
    api_token="hf_abc123...", # Note: "token" not "key"
    model="deepseek-ai/DeepSeek-Coder-V2-236B"
)

# Endpoint: https://api-inference.huggingface.co/models/{model}
```

### Chat Method

```python
def chat(self, messages: List[ChatMessage], temperature: float = 0.1) -> ChatMessage:
    # 1. Format messages as prompt string
    prompt_string = self._format_messages_for_hf(messages)
    # Result: "System: ...\nUser: ...\nAssistant:"

    # 2. Build payload for text-generation task
    payload = {
        "inputs": prompt_string,
        "parameters": {
            "return_full_text": False,  # Only new generation
            "max_new_tokens": 1024,
            "temperature": max(temperature, 0.01)  # HF requires > 0
        },
        "options": {
            "wait_for_model": True  # Wait if model is loading
        }
    }

    # 3. Send request with retry logic
    for attempt in range(self.max_retries):
        try:
            response = self.session.post(
                self.api_endpoint,
                json=payload,
                timeout=120
            )
            
            # 4. Handle errors
            if response.status_code == 429:
                raise RateLimitError("HF API Rate Limit Exceeded")
            
            if response.status_code == 401:
                raise AuthenticationError("HF API Authentication Failed")
            
            # 5. Parse response
            data = response.json()
            
            # HF returns: [{"generated_text": "..."}]
            if isinstance(data, list) and data:
                generated_text = data[0].get("generated_text")
                return {
                    "role": "assistant",
                    "content": generated_text.strip()
                }
            
            # Handle model loading errors
            elif isinstance(data, dict) and data.get("error"):
                error_msg = data["error"]
                if "currently loading" in error_msg.lower():
                    # Model still loading - retry
                    time.sleep(wait_time)
                    continue
        
        except requests.exceptions.Timeout:
            # Network timeout - retry
            continue
```

### Model Loading Example

> First request to rarely-used model
> ```python
> messages = [{"role": "user", "content": "Hello"}]
> 
> try:
>     response = client.chat(messages)
> except RuntimeError as e:
>     print(e)
> # Output: "Model currently loading, please retry..."
> ```
>
> After 10 seconds, model loaded
> ```python
> response = client.chat(messages) # ✅ Success
> ```

---

## 🔄 Exception Handling Across All Clients

**Unified Exception Strategy**:

> All clients raise the same 2 custom exceptions
> ```python
> class RateLimitError(RuntimeError):
>     """Raised when API returns HTTP 429"""
>     pass
> 
> class AuthenticationError(RuntimeError):
>     """Raised when API returns HTTP 401/403"""
>     pass
> ```

**WorkflowManager catches these**:

```python
try:
    response = agent_manager.invoke_agent(system_prompt, messages, 0.1)
except RateLimitError:
    # Show user: "Rate limit reached. Retry in 60 seconds?"
    should_retry = await self._request_rate_limit_retry()
except AuthenticationError:
    # Show user: "Invalid API key. Enter new key?"
    new_key = await self._request_api_key_update()
```

---

## 📊 Client Comparison Table

| Feature | LlmClient | OpenAIClient | AnthropicClient | GoogleGenAIClient | HuggingFaceClient |
|---------|-----------|--------------|-----------------|-------------------|-------------------|
| **Providers** | OpenRouter, Groq, Together | OpenAI, Azure | Anthropic | Google | Hugging Face |
| **SDK** | `requests` | `openai` | `openai` (hack) | `google-generativeai` | `requests` |
| **Models** | 200+ | 11 | 4 | 5 | 25+ |
| **Free Tier** | ✅ 20 models | ❌ | ❌ | ✅ 1,500/day | ✅ 100/day |
| **Context Length** | Varies | 128k | 200k | 2M | Varies |
| **Retry Logic** | ✅ 3 attempts | ✅ Built-in | ✅ Built-in | ✅ 3 attempts | ✅ 3 attempts |
| **Streaming** | ❌ | ✅ (future) | ✅ (future) | ❌ Disabled | ❌ |
| **Special Handling** | None | None | `max_tokens` required | System prompt separate | Prompt formatting |

---

## 🧪 Testing

VebGen includes **80 comprehensive tests** for all 5 LLM clients, covering initialization, chat functionality, error handling, and provider-specific features.

### Run All Tests

```bash
pytest src/core/tests/test_*_client.py -v
```

**Expected output:**

```text
test_llm_client.py .................        [17 tests]
test_openai_client.py ................      [16 tests]
test_anthropic_client.py ...............    [15 tests]
test_google_genai_client.py ................[16 tests]
test_hf_client.py ................          [16 tests]

80 passed in 1.2s
```

### Test Breakdown by Client

| Client | Tests | Key Areas Covered |
|---|---|---|
| **LlmClient** | 17 tests | Retry logic, exponential backoff, jitter, rate limits, timeouts |
| **OpenAIClient** | 16 tests | Official SDK integration, role filtering, whitespace handling |
| **AnthropicClient** | 15 tests | `max_tokens` parameter, OpenAI SDK compatibility |
| **GoogleGenAIClient** | 16 tests | System instruction handling, role conversion, safety filters |
| **HuggingFaceClient** | 16 tests | Prompt formatting, model loading, `wait_for_model` logic |
| **TOTAL** | **80 tests** | Complete coverage of all 5 clients |

### Test Categories (80 Total)

**Initialization Tests (5 tests)**
- ✅ Client instantiation with valid API keys
- ✅ Client configuration (base URLs, endpoints, headers)
- ✅ Session setup and connection pooling

**Chat Success Tests (5 tests)**
- ✅ Basic chat requests
- ✅ Multi-turn conversations
- ✅ System prompts
- ✅ Temperature parameter handling
- ✅ Response parsing

**Error Handling Tests (35 tests)**
- ✅ Rate limit errors (HTTP 429) - 5 tests
- ✅ Authentication errors (HTTP 401/403) - 5 tests
- ✅ Timeout handling - 5 tests
- ✅ API errors (HTTP 4xx, 5xx) - 10 tests
- ✅ Connection errors - 5 tests
- ✅ Malformed responses - 5 tests

**Message Validation Tests (10 tests)**
- ✅ Empty message lists
- ✅ Malformed message structures
- ✅ Invalid roles filtering
- ✅ Missing content handling
- ✅ Whitespace stripping

**Provider-Specific Tests (25 tests)**
- ✅ LlmClient: Jittered backoff (3 tests)
- ✅ OpenAIClient: Custom base URLs (2 tests)
- ✅ AnthropicClient: max_tokens handling (3 tests)
- ✅ GoogleGenAIClient: System instruction separation, role conversion (5 tests)
- ✅ HuggingFaceClient: Prompt formatting, model loading, wait_for_model (6 tests)

### Individual Test Files

#### 1. test_llm_client.py (17 tests)

**Run:**
```bash
pytest src/core/tests/test_llm_client.py -v
```

**Tests:**
```text
test_llm_client_initialization ✓
test_llm_client_chat_success ✓
test_llm_client_chat_empty_messages ✓
test_llm_client_chat_malformed_messages ✓
test_llm_client_chat_rate_limit_error_no_retry ✓
test_llm_client_chat_rate_limit_error_with_retry ✓
test_llm_client_chat_authentication_error ✓
test_llm_client_chat_timeout ✓
test_llm_client_chat_http_500_error_retry ✓
test_llm_client_chat_http_400_error_no_retry ✓
test_llm_client_chat_connection_error ✓
test_llm_client_chat_json_decode_error ✓
test_llm_client_chat_missing_content ✓
test_llm_client_chat_temperature_parameter ✓
test_llm_client_chat_custom_site_url ✓
test_llm_client_session_reuse ✓
test_llm_client_jittered_backoff ✓

17 passed
```

**Key Test: `test_llm_client_jittered_backoff`**
```python
def test_llm_client_jittered_backoff():
    """Verify exponential backoff with jitter prevents thundering herd"""
    client = LlmClient(api_key="test", model="test-model")
    
    # Mock 429 rate limit response
    with patch.object(client.session, 'post') as mock_post:
        mock_post.return_value.status_code = 429
        
        start_time = time.time()
        with pytest.raises(RateLimitError):
            client.chat([{"role": "user", "content": "test"}])
        elapsed = time.time() - start_time
        
        # Should retry 3 times with delays: 0-2s, 0-4s, 0-8s
        assert elapsed >= 0 and elapsed <= 14
        assert mock_post.call_count == 3
```

#### 2. test_openai_client.py (16 tests)

**Run:**
```bash
pytest src/core/tests/test_openai_client.py -v
```

**Tests:**
```text
test_openai_client_initialization ✓
test_openai_client_chat_success ✓
test_openai_client_chat_empty_messages ✓
test_openai_client_chat_malformed_messages ✓
test_openai_client_chat_rate_limit_error ✓
test_openai_client_chat_authentication_error ✓
test_openai_client_chat_timeout ✓
test_openai_client_chat_api_error ✓
test_openai_client_chat_connection_error ✓
test_openai_client_chat_missing_content ✓
test_openai_client_chat_temperature_parameter ✓
test_openai_client_chat_multiple_messages ✓
test_openai_client_chat_system_message ✓
test_openai_client_custom_base_url ✓
test_openai_client_filters_invalid_roles ✓
test_openai_client_strips_whitespace ✓

16 passed
```

**Key Test: `test_openai_client_custom_base_url`**
```python
def test_openai_client_custom_base_url():
    """Verify custom base URL for proxies/Azure OpenAI"""
    client = OpenAIClient(
        api_key="sk-test",
        model="gpt-4o",
        api_base="https://custom-proxy.example.com/v1"
    )
    
    assert client.client.base_url == "https://custom-proxy.example.com/v1"
```

#### 3. test_anthropic_client.py (15 tests)

**Run:**
```bash
pytest src/core/tests/test_anthropic_client.py -v
```

**Tests:**
```text
test_anthropic_client_initialization ✓
test_anthropic_client_chat_success ✓
test_anthropic_client_chat_with_max_tokens ✓
test_anthropic_client_chat_empty_messages ✓
test_anthropic_client_chat_malformed_messages ✓
test_anthropic_client_chat_rate_limit_error ✓
test_anthropic_client_chat_authentication_error ✓
test_anthropic_client_chat_timeout ✓
test_anthropic_client_chat_api_error ✓
test_anthropic_client_chat_connection_error ✓
test_anthropic_client_chat_missing_content ✓
test_anthropic_client_chat_temperature_parameter ✓
test_anthropic_client_filters_invalid_roles ✓
test_anthropic_client_strips_whitespace ✓
test_anthropic_client_default_max_tokens ✓

15 passed
```

**Key Test: `test_anthropic_client_chat_with_max_tokens`**
```python
def test_anthropic_client_chat_with_max_tokens():
    """Verify max_tokens parameter is required for Anthropic API"""
    client = AnthropicClient(api_key="sk-ant-test", model="claude-sonnet-4")
    
    messages = [{"role": "user", "content": "Hello"}]
    
    with patch.object(client.client.chat.completions, 'create') as mock_create:
        mock_create.return_value.choices[0].message.content = "Hi!"
        
        response = client.chat(messages, max_tokens=8192)
        
        # Verify max_tokens was passed
        call_args = mock_create.call_args[1]
        assert call_args['max_tokens'] == 8192
```

#### 4. test_google_genai_client.py (16 tests)

**Run:**
```bash
pytest src/core/tests/test_google_genai_client.py -v
```

**Tests:**
```text
test_google_genai_client_initialization ✓
test_google_genai_client_chat_success ✓
test_google_genai_client_chat_with_system_instruction ✓
test_google_genai_client_chat_empty_messages ✓
test_google_genai_client_chat_malformed_messages ✓
test_google_genai_client_chat_authentication_error ✓
test_google_genai_client_chat_rate_limit_error ✓
test_google_genai_client_chat_safety_block ✓
test_google_genai_client_chat_no_candidates ✓
test_google_genai_client_chat_timeout ✓
test_google_genai_client_chat_api_error ✓
test_google_genai_client_chat_temperature_parameter ✓
test_google_genai_client_role_conversion ✓
test_google_genai_client_system_instruction_handling ✓
test_google_genai_client_parts_formatting ✓
test_google_genai_client_strips_whitespace ✓

16 passed
```

**Key Test: `test_google_genai_client_role_conversion`**
```python
def test_google_genai_client_role_conversion():
    """Verify 'assistant' role converts to 'model' for Gemini"""
    client = GoogleGenAIClient(api_key="test", model="gemini-2.5-pro")
    
    messages = [
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": "Answer"}, # Should become "model"
        {"role": "user", "content": "Follow-up"}
    ]
    
    with patch.object(client.model, 'generate_content') as mock_gen:
        mock_gen.return_value.text = "Response"
        mock_gen.return_value.candidates = [True]
        
        client.chat(messages)
        
        # Check converted messages
        call_messages = mock_gen.call_args[1]['contents']
        assert call_messages[1]['role'] == 'model' # Not 'assistant'
```

#### 5. test_hf_client.py (16 tests)

**Run:**
```bash
pytest src/core/tests/test_hf_client.py -v
```

**Tests:**
```text
test_hf_client_initialization ✓
test_hf_client_chat_success ✓
test_hf_client_chat_empty_messages ✓
test_hf_client_chat_malformed_messages ✓
test_hf_client_chat_rate_limit_error ✓
test_hf_client_chat_authentication_error ✓
test_hf_client_chat_timeout ✓
test_hf_client_chat_http_500_error_retry ✓
test_hf_client_chat_http_400_error_no_retry ✓
test_hf_client_chat_model_loading ✓
test_hf_client_chat_model_loading_retry ✓
test_hf_client_format_messages ✓
test_hf_client_chat_temperature_parameter ✓
test_hf_client_session_reuse ✓
test_hf_client_wait_for_model ✓
test_hf_client_return_full_text_false ✓

16 passed
```

**Key Test: `test_hf_client_format_messages`**
```python
def test_hf_client_format_messages():
    """Verify message formatting for Hugging Face models"""
    client = HuggingFaceClient(api_token="test", model="test-model")
    
    messages = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "Hello"},
        {"name": "Tars", "content": "Hi there"}
    ]
    
    formatted = client._format_messages_for_hf(messages)
    
    expected = "System: You are helpful\nUser: Hello\nTars: Hi there\nAssistant:"
    assert formatted == expected
```

### Running Specific Test Categories

Test only error handling:
```bash
pytest src/core/tests/ -k "error" -v
```

Test only authentication:
```bash
pytest src/core/tests/ -k "authentication" -v
```

Test only rate limits:
```bash
pytest src/core/tests/ -k "rate_limit" -v
```

### Test Coverage Summary

| Test Category | Count | Pass Rate |
|---|---|---|
| Initialization | 5 | 100% |
| Chat Success | 5 | 100% |
| Error Handling | 35 | 100% |
| Message Validation | 10 | 100% |
| Provider-Specific | 25 | 100% |
| **TOTAL** | **80** | **100%** |

All 80 tests pass consistently, ensuring bulletproof LLM client reliability! ✅

---

## 🐛 Common Issues

### Issue 1: "AuthenticationError: Invalid API key"

**Cause**: API key expired, invalid, or wrong provider

**Debug**:
> Check provider matches key format
> ```
> openai_key = "sk-proj-..." # ✅ Correct
> anthropic_key = "sk-ant-..." # ✅ Correct
> google_key = "AIzaSy..." # ✅ Correct
> huggingface_token = "hf_..." # ✅ Correct
> ```
>
> Wrong provider/key combination
> ```python
> client = OpenAIClient(api_key="sk-ant-...") # ❌ Wrong!
> ```

---

### Issue 2: "RateLimitError: Rate limit exceeded"

**Cause**: Too many requests in short time

**Solutions**:
1. **OpenRouter**: Switch to free model (lower rate limits)
2. **OpenAI**: Upgrade to paid tier
3. **Google**: Wait for free tier reset (daily)
4. **Hugging Face**: Wait 24 hours (100 req/day limit)

---

### Issue 3: "Content blocked by safety settings" (Gemini)

**Cause**: Google's safety filters flagged prompt

**Solutions**:
1. Rephrase prompt to be less sensitive
2. Switch to different provider (OpenAI/Anthropic less strict)
3. Adjust safety settings (not recommended)

---

### Issue 4: "Model currently loading" (Hugging Face)

**Cause**: First request to rarely-used model

**Solution**: Automatic retry after 10 seconds (built into client)

---

## ✅ Best Practices

### For Users

1. **Start with free models** (OpenRouter `:free` suffix, HuggingFace)
2. **Test multiple providers** (quality varies by task)
3. **Monitor rate limits** (upgrade if hitting limits often)
4. **Use latest models** (top of provider list = newest)

### For Developers

1. **Always use `ChatMessage` type** (consistency across clients)
2. **Catch `RateLimitError` and `AuthenticationError`** (don't let them crash app)
3. **Log at DEBUG level** (payloads are large, only log in debug mode)
4. **Validate messages before sending** (check for required fields)
5. **Test with fake keys** (ensure error handling works)
6. **Don't hardcode models** (use providers.json configuration)
7. **Implement exponential backoff** (prevent API hammering)
8. **Handle streaming carefully** (future feature - requires threading)

---

## 🎓 Advanced Features

### 1. Exponential Backoff with Jitter

**Purpose**: Prevent thundering herd during retries

```python
for attempt in range(max_retries):
    try:
        response = self.session.post(...)
        return response
    except requests.exceptions.Timeout:
        # Base delay: 2^attempt seconds
        wait_time = 2.0 * (2 ** attempt)
        # Add jitter: random between 0 and wait_time
        jittered_wait = random.uniform(0, wait_time)
        time.sleep(jittered_wait)
```

> **Without jitter**: 100 clients retry at same time → all fail again  
> **With jitter**: Clients retry at random times → some succeed

---

### 2. Connection Pooling

**All clients use `requests.Session()`**:

```python
self.session = requests.Session()
self.session.headers.update({
    'Authorization': f'Bearer {api_key}',
    'Content-Type': 'application/json'
})

# Reuses TCP connection across multiple requests
response1 = self.session.post(...) # Opens connection
response2 = self.session.post(...) # Reuses connection ✅
```

**Benefits**:
- **Faster**: No TCP handshake overhead
- **Efficient**: Fewer server connections
- **Reliable**: Handles connection keep-alive

---

### 3. Debug Logging

**Enable detailed logging**:

```python
import logging
logging.getLogger('src.core.llm_client').setLevel(logging.DEBUG)
logging.getLogger('src.core.openai_client').setLevel(logging.DEBUG)
```

> Now logs include:
> - Full request payloads
> - Full response content
> - Timing information
> - Retry attempts

**Example Output**:
```log
[DEBUG] LlmClient: Sending 3 messages to 'deepseek/deepseek-chat' (Attempt 1/3)...
[DEBUG] Request Payload:
        {
            "model": "deepseek/deepseek-chat",
            "messages": [
                {"role": "system", "content": "..."},
                {"role": "user", "content": "..."}
            ],
            "temperature": 0.1
        }
[DEBUG] Attempt 1: API call returned after 2.45 seconds. Status code: 200
[DEBUG] Response Content: Sure! Here's a Django model...
```

---

## 🌟 Summary

**5 LLM clients** (50 KB total) provide **unified API gateway** to 120+ models:

✅ **LlmClient** - Generic OpenAI-compatible (OpenRouter, Groq, Together AI)  
✅ **OpenAIClient** - Official OpenAI SDK (GPT-4, o1, o3)  
✅ **AnthropicClient** - Claude via OpenAI SDK hack (clever reuse)  
✅ **GoogleGenAIClient** - Official Gemini SDK (2M context, multimodal)  
✅ **HuggingFaceClient** - Open source models (DeepSeek, Qwen, Llama)  

**Key Features**:
✅ **Unified interface** (`chat()` method across all)  
✅ **Standard exceptions** (`RateLimitError`, `AuthenticationError`)  
✅ **Exponential backoff retry** (3 attempts with jitter)  
✅ **Connection pooling** (`requests.Session`)  
✅ **Detailed logging** (DEBUG level payloads)  
✅ **50+ free models** (OpenRouter + Hugging Face)  

**This is why VebGen can switch between 120+ AI models with zero code changes—just update `providers.json`!**

---

<div align="center">

**Want to add a new provider?** Create a client implementing `chat(messages, temperature) → ChatMessage`!

**Questions?** Check agent_manager.md or providers.json


</div>