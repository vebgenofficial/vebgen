<a id="core.agent_manager"></a>

# core.agent\_manager

<a id="core.agent_manager.RequestApiKeyUpdateCallable"></a>

#### RequestApiKeyUpdateCallable

agent_desc, error_message, key_name

<a id="core.agent_manager.AgentManager"></a>

## AgentManager Objects

```python
class AgentManager()
```

Manages the lifecycle of a single, dynamically configured LLM client.

This class acts as a central point for creating, configuring, and re-initializing
the specific LLM client (like OpenAI, Google, etc.) that the application will use.
It handles the complexities of API key management by interacting with secure
storage and prompting the user for keys when necessary via UI callbacks.
Accepts a provider and model ID dynamically and allows re-initialization.

<a id="core.agent_manager.AgentManager.__init__"></a>

#### \_\_init\_\_

```python
def __init__(provider_id: str,
             model_id: str,
             config_manager: ConfigManager,
             show_input_prompt_cb: Optional[ShowInputPromptCallable] = None,
             request_api_key_update_cb: Optional[
                 RequestApiKeyUpdateCallable] = None,
             site_url: Optional[str] = None,
             site_title: Optional[str] = None)
```

Initializes the AgentManager with a specified provider, model, and UI callbacks.

**Arguments**:

- `provider_id` - The ID of the API provider (e.g., "google", "openai").
- `model_id` - The model ID to use.
- `config_manager` - The application's ConfigManager instance.
- `show_input_prompt_cb` - Callback to prompt user for initial API key input.
- `request_api_key_update_cb` - Callback to prompt user to update API key after an error.
- `site_url` - Optional URL of the referring site, used for OpenRouter ranking.
- `site_title` - Optional title of the referring site, used for OpenRouter ranking.
  

**Raises**:

- `ValueError` - If model IDs are missing or invalid.

<a id="core.agent_manager.AgentManager.reinitialize_agent"></a>

#### reinitialize\_agent

```python
def reinitialize_agent(provider_id: str, model_id: str)
```

Re-initializes the agent with a new provider or model.

This is the public method called by the UI when the user changes the model selection.

**Arguments**:

- `provider_id` - The new provider ID.
- `model_id` - The new model ID.
  

**Raises**:

- `ValueError` - If new model IDs are invalid.
- `RuntimeError` - If re-initialization fails.

<a id="core.agent_manager.AgentManager.handle_api_error_and_reinitialize"></a>

#### handle\_api\_error\_and\_reinitialize

```python
async def handle_api_error_and_reinitialize(error_type_str: str,
                                            error_message: str) -> bool
```

Handles an API error by prompting the user to update keys or retry.

This is called by the WorkflowManager when an API call fails with an
AuthenticationError or RateLimitError. It uses the UI callback to show a dialog.

**Arguments**:

- `error_type_str` - "AuthenticationError" or "RateLimitError".
- `error_message` - The full string of the caught exception.
  

**Returns**:

  True if the issue was resolved (new key provided or user chose to retry),
  False if the user cancelled the update.

<a id="core.agent_manager.AgentManager.clear_stored_keys"></a>

#### clear\_stored\_keys

```python
def clear_stored_keys() -> bool
```

Deletes all stored API keys and tokens defined in the providers config.

**Returns**:

  True if all deletions were successful (or keys didn't exist), False otherwise.

<a id="core.agent_manager.AgentManager.invoke_agent"></a>

#### invoke\_agent

```python
def invoke_agent(system_prompt: ChatMessage,
                 messages: List[ChatMessage],
                 temperature: float = 0.1) -> ChatMessage
```

Invokes the currently configured agent with a system prompt and message history.

**Arguments**:

- `system_prompt` - The system prompt message.
- `messages` - A list of user/assistant messages forming the conversation history.
- `temperature` - The sampling temperature for the LLM.
  

**Returns**:

  The ChatMessage response from the invoked agent.
  

**Raises**:

- `RuntimeError` - If the agent client is not initialized.

<a id="core.agent_manager.AgentManager.agent_client"></a>

#### agent\_client

```python
@property
def agent_client(
) -> Union[LlmClient, HuggingFaceClient, GoogleGenAIClient, OpenAIClient]
```

Provides public, read-only access to the initialized agent client.

Raises a RuntimeError if the agent has not been successfully initialized,
preventing other parts of the application from using a non-functional client.

