# 🔌 agent_manager.py - Complete Documentation

## 🎯 Overview

**File**: `backend/src/core/agent_manager.py`  
**Size**: 20,429 characters  
**Purpose**: The universal LLM API gateway for VebGen's AI agents

This file is the **bridge between VebGen and any AI model** (GPT-4, Claude, Gemini, Llama, etc.). It handles API authentication, provider switching, error recovery, and secure credential management—making VebGen model-agnostic.

**Think of it as**: The "phone system" that connects TARS and CASE to their "brains" (LLM APIs)

---

## 🧠 For Users: What This File Does

### The Universal API Manager

**Problem**: VebGen needs to work with multiple AI providers:
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude 3.5 Sonnet, Claude 3 Opus)
- Google (Gemini 2.0 Flash, Gemini 1.5 Pro)
- Hugging Face (Open-source models)
- OpenRouter (Access to 200+ models)

**Solution**: AgentManager provides a **single, unified interface** for all of them.

### What Happens When You Change Models

**In the VebGen UI**:
1. You select: "Provider: OpenAI, Model: GPT-4"
2. Click "Apply"

**Behind the scenes**:
> AgentManager:
> - Loads OpenAI API key from secure storage (OS keyring)
> - If not found → Shows password prompt dialog
> - Stores key securely (never in plain text files)
> - Creates `OpenAIClient` instance
> - TARS and CASE now use GPT-4 for all decisions

---

**Switch to Claude**:
> You select: "Provider: Anthropic, Model: Claude 3.5 Sonnet"
>
> AgentManager destroys old OpenAI client
> - Loads Anthropic API key (or prompts if missing)
> - Creates `AnthropicClient` instance
> - TARS and CASE now use Claude for decisions

---

**Zero code changes needed** - just pick a provider and model from dropdowns!

---

## 👨‍💻 For Developers: Technical Architecture

### File Structure

```text
agent_manager.py (20,429 characters)
├── Type Hints (ShowInputPromptCallable, RequestApiKeyUpdateCallable)
├── AgentManager (Main Class)
│   ├── __init__() - Initialize with provider/model
│   ├── _initialize_agent() - Load key & create client
│   ├── _load_or_prompt_key() - Secure credential retrieval
│   ├── _get_client_class() - Factory pattern for client types
│   ├── invoke_agent() - PUBLIC: Make LLM API calls
│   ├── reinitialize_agent() - PUBLIC: Switch provider/model
│   ├── handle_api_error_and_reinitialize() - Error recovery
│   ├── reinitialize_agent_with_new_key() - Update credentials
│   ├── clear_stored_keys() - Delete all API keys
│   └── agent_client (property) - Read-only access to client
└── Imports (5 client types + secure storage + config)
```

---

## 📚 Class Breakdown

### AgentManager

**Purpose**: Centralized LLM client lifecycle management

**Responsibilities**:
1. **Client instantiation** - Create provider-specific clients
2. **Credential management** - Load/store API keys securely
3. **Error handling** - Detect auth/rate-limit errors, prompt for fixes
4. **Provider switching** - Hot-swap between models without restart
5. **Unified interface** - Single `invoke_agent()` method for all providers

---

### Constructor: `__init__()`

```python
def __init__(
    self,
    provider_id: str,
    model_id: str,
    config_manager: ConfigManager,
    show_input_prompt_cb: Optional[ShowInputPromptCallable] = None,
    request_api_key_update_cb: Optional[RequestApiKeyUpdateCallable] = None,
    site_url: Optional[str] = None,
    site_title: Optional[str] = None
):
```

---

**Parameters**:

| Parameter | Type | Purpose | Example |
|-----------|------|---------|---------|
| `provider_id` | str | Provider identifier | `"openai"`, `"anthropic"`, `"google"` |
| `model_id` | str | Specific model name | `"gpt-4"`, `"claude-3-5-sonnet-20240620"` |
| `config_manager` | ConfigManager | Configuration access | Loads `providers.json` |
| `show_input_prompt_cb` | Callable | UI callback for API key prompt | Shows password input dialog |
| `request_api_key_update_cb` | Callable | UI callback for error recovery | Shows "Key invalid, update?" dialog |
| `site_url` | str (optional) | Referring site URL | For OpenRouter ranking |
| `site_title` | str (optional) | Referring site title | For OpenRouter ranking |

**What Happens**:
1. Stores all parameters as instance variables
2. Sets `self.agent = None` (client not created yet)
3. **Calls `_initialize_agent()`** immediately
4. If initialization fails → Raises `RuntimeError`

**Example Usage**:
```python
from config_manager import ConfigManager

config = ConfigManager(Path("config/"))
agent_mgr = AgentManager(
    provider_id="openai",
    model_id="gpt-4-turbo",
    config_manager=config,
    show_input_prompt_cb=ui.show_password_dialog,
    request_api_key_update_cb=ui.show_api_key_error_dialog
)

# At this point:
# - OpenAI API key loaded (or user prompted)
# - OpenAIClient instance created
# - Ready to make API calls
```

---

### Core Method: `_initialize_agent()`

**Purpose**: Load API key and instantiate the correct client class

**Flow**:
```python
def _initialize_agent(self):
    # 1. Reset agent to None (clean state)
    self.agent = None

    # 2. Load provider config from providers.json
    provider_config = config_manager.providers_config.get(provider_id)
    # Example config:
    # {
    #   "display_name": "OpenAI",
    #   "api_key_name": "openai_api_key",
    #   "client_class": "OpenAIClient",
    #   "client_config": { ... }
    # }

    # 3. Extract required details
    key_name = provider_config["api_key_name"]
    client_class_name = provider_config["client_class"]

    # 4. Load or prompt for API key
    api_key = _load_or_prompt_key(key_name, "OpenAI Agent", ui_callback)

    # 5. Get client class from factory
    ClientClass = _get_client_class(client_class_name)

    # 6. Prepare initialization arguments
    init_args = { "model": model_id, **client_config }

    # 7. Add provider-specific arguments
    if client_class_name == "HuggingFaceClient":
        init_args["api_token"] = api_key
    else:
        init_args["api_key"] = api_key

    # 8. Instantiate client
    self.agent = ClientClass(**init_args)
```

---

**Error Handling**:
```python
try:
    # Initialization logic
except ValueError as e:
    # User cancelled prompt OR invalid key format
    if "not provided by the user" not in str(e):
        delete_credential(key_name) # Clear invalid key
    raise RuntimeError("Failed to initialize agent")
except Exception as e:
    # Client instantiation failed
    raise RuntimeError(f"Failed to create client: {e}")
```

---

### Credential Management: `_load_or_prompt_key()`

**Purpose**: Secure API key retrieval with user fallback

**Flow**:
```python
def _load_or_prompt_key(key_name: str, agent_desc: str, prompt_cb: Callable) -> str:
    # 1. Try to load from OS keyring
    api_key = retrieve_credential(key_name)
    # Uses: Windows Credential Manager, macOS Keychain, Linux Secret Service

    if api_key:
        return api_key

    # 2. Key not found - prompt user
    # 3. Customize prompt for specific providers
    # 4. Call UI callback (blocks until user responds)
    api_key_input = prompt_cb(
        title,
        is_password=True,
        message
    )

    # 5. Validate user input
    if not api_key_input or not api_key_input.strip():
        raise ValueError("Invalid API key (empty)")

    # 6. Store key securely for future sessions
    store_credential(key_name, api_key_input.strip())

    return api_key_input.strip()
```

---

**Why This Approach**:
- **Security**: Keys stored in OS-level keyring, not plain text files
- **User-friendly**: Automatic prompt if key missing
- **Cross-platform**: Works on Windows/macOS/Linux
- **Single source of truth**: One retrieval method for all providers

**Example Scenarios**:

**Scenario 1: Key exists**:
> User previously entered key
> `api_key = _load_or_prompt_key("openai_api_key", ...)`
>
> **Returns**: `"sk-proj-abc123..."` (from keyring)
> **User sees**: Nothing (silent success)

---

**Scenario 2: Key missing**:
> First time using OpenAI
> `api_key = _load_or_prompt_key("openai_api_key", ...)`
>
> **User sees**: Password dialog "API Key for OpenAI Agent Required"
> **User enters**: `"sk-proj-abc123..."`
> **System stores** in keyring
> **Returns**: `"sk-proj-abc123..."`

---

**Scenario 3: User cancels**:
> `api_key = _load_or_prompt_key("openai_api_key", ...)`
>
> **User sees**: Password dialog
> **User clicks**: Cancel
> **Raises**: `ValueError("API key was not provided by the user")`

---

### Factory Pattern: `_get_client_class()`

**Purpose**: Dynamic client class resolution (avoids long `if/elif` chains)

**Implementation**:
```python
def _get_client_class(class_name: str) -> Type[LlmClient]:
    # Factory dictionary maps class name → actual class
    client_classes = {
        "LlmClient": LlmClient, # OpenRouter
        "HuggingFaceClient": HuggingFaceClient,
        "GoogleGenAIClient": GoogleGenAIClient,
        "OpenAIClient": OpenAIClient,
        "AnthropicClient": AnthropicClient,
    }

    client_class = client_classes.get(class_name)
    if not client_class:
        raise TypeError(f"Client class '{class_name}' not found")

    return client_class
```

---

**Why Factory Pattern**:
- **Extensible**: Add new providers by updating dictionary
- **Testable**: Can mock individual client classes
- **Clean**: No `if/elif` spaghetti code
- **Type-safe**: Returns proper type hints

**Adding New Provider** (e.g., Cohere):
1. Import the client class
   ```python
   from .cohere_client import CohereClient
   ```
2. Add to factory dictionary
   ```python
   client_classes = {
       ...
       "CohereClient": CohereClient, # NEW
   }
   ```
3. Add to `providers.json`
   ```json
   {
       "cohere": {
           "display_name": "Cohere",
           "api_key_name": "cohere_api_key",
           "client_class": "CohereClient",
           ...
       }
   }
   ```
Done! Users can now select Cohere from dropdown.

---

### Public API: `invoke_agent()`

**Purpose**: Make LLM API calls (used by TARS and CASE)

**Signature**:
```python
def invoke_agent(
    self,
    system_prompt: ChatMessage,
    messages: List[ChatMessage],
    temperature: float = 0.1
) -> ChatMessage:
```

---

**Parameters**:
- `system_prompt`: System instructions (e.g., `TARS_FEATURE_BREAKDOWN_PROMPT`)
- `messages`: Conversation history (user/assistant turns)
- `temperature`: Sampling randomness (0.0 = deterministic, 1.0 = creative)

**Returns**: `ChatMessage` object with LLM response

**Example Usage**:
```python
from llm_client import ChatMessage

# Prepare system prompt
system_prompt = ChatMessage(role="system", content="You are TARS...")

# Prepare user message
user_message = ChatMessage(role="user", content="Break down this feature...")

# Make API call
response = agent_manager.invoke_agent(
    system_prompt=system_prompt,
    messages=[user_message],
    temperature=0.1
)

# Extract response text
feature_list = response.content
# Returns: "1. Create User model\n2. Set up authentication...\n"
```

---

**What Happens Internally**:
```python
def invoke_agent(self, system_prompt, messages, temperature):
    # 1. Validate agent is initialized
    if not self.agent:
        raise RuntimeError("Agent not initialized")

    # 2. Combine system prompt + conversation
    all_messages = [system_prompt] + messages

    # 3. Delegate to specific client
    return self.agent.chat(all_messages, temperature=temperature)
    # self.agent could be OpenAIClient, AnthropicClient, etc.
```

---

**Error Propagation**:
If API call fails, client raises exceptions:
- `RateLimitError` (quota exceeded)
- `AuthenticationError` (invalid key)
- `NetworkError` (connection timeout)

These are caught by `WorkflowManager`, which calls:
`agent_manager.handle_api_error_and_reinitialize(...)`

---

### Error Recovery: `handle_api_error_and_reinitialize()`

**Purpose**: User-friendly API error handling with automatic recovery

**Signature**:
```python
async def handle_api_error_and_reinitialize(
    self,
    error_type_str: str,
    error_message: str
) -> bool:
```

---

**Parameters**:
- `error_type_str`: `"AuthenticationError"` or `"RateLimitError"`
- `error_message`: Full exception string

**Returns**: `True` if resolved, `False` if user cancelled

**Flow**:
```python
async def handle_api_error_and_reinitialize(error_type_str, error_message):
    # 1. Load provider config
    # 2. Call UI callback to show error dialog
    new_key, retry_current = await request_api_key_update_cb(...)
    # Dialog shows:
    # "OpenAI API Error: Invalid API key (401 Unauthorized)"
    # [Update Key] [Retry] [Cancel]

    # 3. Process user's choice
    if new_key:
        store_credential(key_name, new_key)
        _initialize_agent()  # Re-create client with new key
        return True
    elif retry_current:
        return True
    else:
        return False
```

---

**Example Scenario**:

**Step 1: API call fails**:
```python
# In WorkflowManager
try:
    response = agent_manager.invoke_agent(...)
except AuthenticationError as e:
    # API returned 401 Unauthorized
```

**Step 2: Prompt user to fix**:
```python
    resolved = await agent_manager.handle_api_error_and_reinitialize(
        "AuthenticationError", str(e)
    )

    if resolved:
        # User updated key or chose to retry
        response = agent_manager.invoke_agent(...)
    else:
        # User cancelled - abort workflow
        raise RuntimeError("Cannot proceed without valid API key")
```

---

**UI Dialog** (shown to user):
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
> ⚠️ OpenAI API Error
>
> Invalid API key. Please check your key and try again.
>
> Error details: 401 Unauthorized - Incorrect API key provided
>
> Current key name: `openai_api_key`
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
> [Enter New API Key: _______________]
>
> [Update Key] [Retry Current Key] [Cancel]

---

**This prevents workflows from crashing due to temporary API issues**

---

### Provider Switching: `reinitialize_agent()`

**Purpose**: Hot-swap LLM providers without restarting VebGen

**Signature**:
```python
def reinitialize_agent(self, provider_id: str, model_id: str):
```

---

**Example**:
> Currently using GPT-4
> `agent_manager = AgentManager("openai", "gpt-4-turbo", ...)`
>
> User switches to Claude
> `agent_manager.reinitialize_agent("anthropic", "claude-3-5-sonnet-20240620")`
>
> What happens:
> 1. Destroys `OpenAIClient` instance
> 2. Loads `anthropic_api_key` from keyring (or prompts)
> 3. Creates `AnthropicClient` instance
> 4. All future `invoke_agent()` calls use Claude

---

**Use Case**: Testing different models for quality comparison
```python
models_to_test = [
    ("openai", "gpt-4-turbo"),
    ("anthropic", "claude-3-5-sonnet-20240620"),
    ("google", "gemini-1.5-flash")
]

for provider, model in models_to_test:
    agent_manager.reinitialize_agent(provider, model)

    # Test same prompt with different models
    response = agent_manager.invoke_agent(system_prompt, messages)
    print(f"{provider}/{model}: {len(response.content)} chars")
```

---

### Security: `clear_stored_keys()`

**Purpose**: Delete all API keys from secure storage

**Use Cases**:
- User wants to reset all credentials
- Sharing computer with others
- Testing key re-entry flow

**Implementation**:
```python
def clear_stored_keys(self) -> bool:
    all_cleared = True

    # Iterate through all providers in config
    for provider_id, data in config_manager.providers_config.items():
        key_name = data.get("api_key_name")
        if key_name:
            try:
                if not delete_credential(key_name):
                    all_cleared = False
            except Exception:
                all_cleared = False

    if all_cleared:
        self.agent = None # Invalidate current agent
    return all_cleared
```

---

**Example Usage** (in settings UI):
> User clicks "Clear All API Keys" button
> `result = agent_manager.clear_stored_keys()`
>
> `if result:`
> `    messagebox.showinfo("Success", "All API keys cleared")`
> `else:`
> `    messagebox.showerror("Error", "Failed to clear some keys.")`

---

### Property: `agent_client`

**Purpose**: Read-only access to the underlying client instance

**Usage**:
```python
# Get direct access to client (for advanced operations)
client = agent_manager.agent_client

# Check client type
if isinstance(client, OpenAIClient):
    print("Using OpenAI")

# Access client-specific methods (if needed)
if hasattr(client, 'stream_chat'):
    for chunk in client.stream_chat(messages):
        print(chunk, end='')
```

---

**Error Handling**:
```python
try:
    client = agent_manager.agent_client
except RuntimeError as e:
    # Agent not initialized yet
    print("Agent not ready. Initialize first.")
```

---

## 🔗 Integration with Other Components

### How TARS Uses AgentManager

In `adaptive_agent.py` (`TarsPlanner` class):
```python
class TarsPlanner:
    def __init__(self, agent_manager: AgentManager, ...):
        self.agent_manager = agent_manager

    def break_down_feature(self, user_request: str) -> List[str]:
        # 1. Format prompt
        # 2. Create system message
        # 3. Call LLM via AgentManager
        response = self.agent_manager.invoke_agent(...)
        # 4. Parse response
        return features
```

### How CASE Uses AgentManager

In `adaptive_agent.py` (`AdaptiveAgent` class):
```python
class AdaptiveAgent:
    def __init__(self, agent_manager: AgentManager, ...):
        self.agent_manager = agent_manager

    async def _execute_feature_steps(self, ...):
        # 1. Build context
        # 2. Format prompt with context
        # 3. Call LLM via AgentManager
        response = self.agent_manager.invoke_agent(...)
        # 4. Parse action from response
        # 5. Execute action
```

### How WorkflowManager Handles Errors

In `workflow_manager.py`:
```python
async def run_workflow(user_request: str):
    try:
        response = agent_manager.invoke_agent(...)
    except AuthenticationError as e:
        # Invalid API key
        resolved = await agent_manager.handle_api_error_and_reinitialize(...)
        if resolved:
            # Retry with new key
            response = agent_manager.invoke_agent(...)
        else:
            raise RuntimeError("Workflow aborted: API key issue")
    except RateLimitError as e:
        # Quota exceeded
        resolved = await agent_manager.handle_api_error_and_reinitialize(...)
        if resolved:
            await asyncio.sleep(60)
            response = agent_manager.invoke_agent(...)
        else:
            raise RuntimeError("Workflow aborted: Rate limit")
```

---

## 🛠️ Supported Providers

### 1. OpenAI

**Config** (in `providers.json`):
```json
{
    "openai": {
        "display_name": "OpenAI",
        "api_key_name": "openai_api_key",
        "client_class": "OpenAIClient",
        "client_config": { ... },
        "models": { ... }
    }
}
```

**Initialization**:
```python
agent_manager = AgentManager("openai", "gpt-4-turbo", config)
# Creates: OpenAIClient(model="gpt-4-turbo", api_key="sk-...")
```

---

### 2. Anthropic (Claude)

**Config**:
```json
{
    "anthropic": {
        "display_name": "Anthropic",
        "api_key_name": "anthropic_api_key",
        "client_class": "AnthropicClient",
        ...
    }
}
```

**Initialization**:
```python
agent_manager = AgentManager("anthropic", "claude-3-5-sonnet-20240620", config)
# Creates: AnthropicClient(model="claude-3-5-sonnet-20240620", api_key="sk-ant-...")
```

---

### 3. Google (Gemini)

**Config**:
```json
{
    "google": {
        "display_name": "Google",
        "api_key_name": "google_api_key",
        "client_class": "GoogleGenAIClient",
        ...
    }
}
```

**Initialization**:
```python
agent_manager = AgentManager("google", "gemini-1.5-flash", config)
# Creates: GoogleGenAIClient(model="gemini-1.5-flash", api_key="AIza...")
```

---

### 4. Hugging Face

**Config**:
```json
{
    "huggingface": {
        "display_name": "Hugging Face",
        "api_key_name": "hf_token",
        "client_class": "HuggingFaceClient",
        ...
    }
}
```

**Special Handling**:
> HuggingFace uses `"api_token"` instead of `"api_key"`
> `if client_class_name == "HuggingFaceClient": init_args["api_token"] = api_key`

---

**User Prompt**:
> Title: "Hugging Face Token Required"
> Message: "Enter your Hugging Face User Access Token. It must start with 'hf_'."

---

### 5. OpenRouter

**Config**:
```json
{
    "openrouter": {
        "display_name": "OpenRouter",
        "api_key_name": "openrouter_api_key",
        "client_class": "LlmClient",
        ...
    }
}
```

---

**Special Handling**:
> OpenRouter requires `site_url` and `site_title` for ranking
> `if client_class_name == "LlmClient": init_args["site_url"] = site_url`

---

**Why OpenRouter**: Access to 200+ models with a single API key.

---

## 🔐 Security Features

### 1. OS-Level Keyring Storage

**How It Works**:
> Windows: Credential Manager
> macOS: Keychain
> Linux: Secret Service (GNOME Keyring, KWallet)
>
> `store_credential("openai_api_key", "sk-proj-abc123...")`
> → Stored securely in OS keyring (not plain text file)
>
> `api_key = retrieve_credential("openai_api_key")`
> → Retrieved from OS keyring

---

**Benefits**:
- **Encrypted at rest** - OS handles encryption
- **Per-user isolation** - Each user has separate keyring
- **Secure retrieval** - Requires user session authentication
- **Cross-platform** - Works on all major OS

---

### 2. No Plain Text Storage

**What's NOT Done**:
> ❌ WRONG:
> ```json
> { "openai_api_key": "sk-proj-abc123..." }
> ```
> ```env
> OPENAI_API_KEY=sk-proj-abc123...
> ```

---

**What's Done Instead**:
> ✅ CORRECT:
> ```json
> {
>   "openai": {
>     "api_key_name": "openai_api_key"
>   }
> }
> ```
> Actual key stored in OS keyring (encrypted)

---

### 3. Validation Before Storage

```python
def _load_or_prompt_key(...):
    api_key_input = prompt_cb(...) # Get from user

    # Validate input
    if not api_key_input or not api_key_input.strip():
        raise ValueError("Invalid API key (empty)")

    # Store only if valid
    store_credential(key_name, api_key_input.strip())
```

---

### 4. Automatic Cleanup on Errors

```python
try:
    api_key = _load_or_prompt_key(...)
    client = OpenAIClient(api_key=api_key)
except ValueError as e:
    # Invalid key format or user cancelled
    if "not provided by the user" not in str(e):
        # Delete potentially invalid key
        delete_credential(key_name)
    raise
```

**This prevents corrupted keys from persisting**

---

## 📊 Key Metrics

| Metric | Value | Reason |
|--------|-------|--------|
| **Supported providers** | 5+ (extensible) | OpenAI, Anthropic, Google, HuggingFace, OpenRouter |
| **Client classes** | 5 | OpenAIClient, AnthropicClient, GoogleGenAIClient, HuggingFaceClient, LlmClient |
| **Default temperature** | 0.1 | Low randomness for consistent code generation |
| **Timeout (default)** | 60-120 seconds | Provider-dependent |
| **Max retries** | None (manual via UI) | User decides when to retry after errors |
| **Key storage** | OS keyring | Secure, encrypted storage |

---

## 🧪 Testing

VebGen includes **14 comprehensive tests** for AgentManager covering initialization, provider switching, error recovery, and credential management.

### Run Tests

```bash
pytest src/core/tests/test_agent_manager.py -v
```

**Expected output:**

```text
test_init_success_with_stored_key ✓
test_init_success_with_user_prompt ✓
test_init_huggingface_client_uses_api_token ✓
test_init_openrouter_client_uses_site_url ✓
test_init_fails_if_user_cancels_prompt ✓
test_init_fails_with_invalid_provider ✓
test_reinitialize_agent_switches_client ✓
test_invoke_agent_success ✓
test_invoke_agent_fails_if_not_initialized ✓
test_handle_api_error_with_new_key ✓
test_handle_api_error_with_retry ✓
test_handle_api_error_with_cancel ✓
test_clear_stored_keys ✓
test_clear_stored_keys_fails_partially ✓

14 passed in 0.12s
```

### Test Coverage Breakdown

**Initialization Tests (7 tests):**
- Loading API keys from secure storage
- Prompting users for missing keys
- HuggingFace-specific initialization (api_token)
- OpenRouter-specific initialization (site_url)
- User cancellation handling
- Invalid provider detection
- Provider switching

**Execution Tests (3 tests):**
- Successful LLM invocation
- Uninitialized agent error handling
- Temperature parameter passing

**Error Recovery Tests (3 tests):**
- Authentication error with new key
- Rate limit error with retry
- User cancellation handling

**Utility Tests (1 test):**
- Clearing all stored credentials

### Key Test Scenarios

**Test 1: Initialization with stored key**
```python
def test_init_success_with_stored_key():
    # Verifies: API key retrieved from OS keyring
    # Creates: OpenAIClient instance
    # No user interaction needed
```

**Test 2: Provider switching**
```python
def test_reinitialize_agent_switches_client():
    # Starts with: OpenAI GPT-4
    # Switches to: Google Gemini
    # Verifies: New client instance created
```

**Test 3: Error recovery**
```python
async def test_handle_api_error_with_new_key():
    # Simulates: 401 Authentication Error
    # User action: Provides new API key
    # Result: Client re-initialized successfully
```

---

## 🐛 Common Issues

### Issue 1: "Agent client is not initialized"

**Cause**: API key missing and no UI callback provided

**Solution**:
```python
# Provide show_input_prompt_cb during initialization
agent_mgr = AgentManager(..., show_input_prompt_cb=ui.show_password_dialog)
```

---

### Issue 2: "Client class 'XYZClient' not found"

**Cause**: Provider config references non-existent client class

**Solution**:
1. Check `providers.json`: `"client_class": "XYZClient"`
2. Import the client in `agent_manager.py`: `from .xyz_client import XYZClient`
3. Add to factory dictionary: `"XYZClient": XYZClient`

---

### Issue 3: KeyError when accessing provider config

**Cause**: `provider_id` doesn't exist in `providers.json`

**Solution**:
```python
if provider_id not in config_manager.providers_config:
    raise ValueError(f"Provider '{provider_id}' not found")
```

---

## ✅ Best Practices

### For Users

1. **Store API keys once** - They persist across sessions
2. **Test connectivity** - Run a simple prompt after setup
3. **Clear keys before sharing** - Use Settings → Clear API Keys
4. **Check rate limits** - Each provider has different quotas

### For Developers

1. **Always provide UI callbacks** - Enable user interaction
2. **Log initialization steps** - Use `logger.debug()` for troubleshooting
3. **Handle all error types** - Auth, rate limit, network
4. **Test with multiple providers** - Ensure cross-provider compatibility
5. **Validate config format** - Use schema validation for `providers.json`
6. **Mock clients in tests** - Don't make real API calls during testing

---

## 🌟 Summary

**agent_manager.py** is the **universal LLM gateway** for VebGen:

✅ **Multi-provider support** (OpenAI, Anthropic, Google, HuggingFace, OpenRouter)  
✅ **Secure credential management** (OS keyring, encrypted storage)  
✅ **Hot-swappable models** (switch without restart)  
✅ **User-friendly error recovery** (automatic prompts, retry logic)  
✅ **Factory pattern design** (extensible, testable)  
✅ **Single API interface** (`invoke_agent()` for all providers)  
✅ **UI integration** (callbacks for prompts and error dialogs)  
✅ **Production-ready** (error handling, logging, validation)

**This file makes VebGen model-agnostic—you can use any LLM provider with zero code changes.**

---

<div align="center">

**Want to add a new provider?** Update `providers.json` and import the client class!

**Questions?** Check the main README or adaptive_agent.py documentation

</div>