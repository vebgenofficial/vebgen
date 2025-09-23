# Plugin System

The Vebgen AI Agent has an extensible plugin system that allows for the addition of new frameworks and LLM providers.

## Framework Plugins

Framework plugins are used to provide framework-specific prompts to the AI agents. This allows the agents to generate code and commands that are tailored to the specific framework being used.

A framework plugin is a directory in the `backend/src/plugins` directory. The name of the directory is the name of the framework.

### Plugin Structure

A framework plugin directory must contain the following files:

-   `__init__.py`: An empty file that makes the directory a Python package.
-   `prompts.py`: A Python module that contains the framework-specific prompts.

### `prompts.py`

The `prompts.py` file must contain a `FrameworkPrompts` dataclass instance that provides the system prompts for the AI agents. The `FrameworkPrompts` dataclass is defined in `backend/src/core/config_manager.py`.

The following is an example of a `prompts.py` file for a Django plugin:

```python
# src/plugins/django/prompts.py

from src.core.llm_client import ChatMessage
from src.core.config_manager import FrameworkPrompts

# Tars (Planner) System Prompt Content
system_tars_markdown_planner_content = """
# ... (prompt content for the Tars planner)
"""

system_tars_markdown_planner: ChatMessage = {
    "role": "system",
    "name": "Tars",
    "content": system_tars_markdown_planner_content
}

# Case (Executor) System Prompt Content
system_case_executor_content = """
# ... (prompt content for the Case executor)
"""

system_case_executor: ChatMessage = {
    "role": "system",
    "name": "Case",
    "content": system_case_executor_content
}

# ... (other prompts)

django_prompts = FrameworkPrompts(
    system_tars_markdown_planner=system_tars_markdown_planner,
    system_case_executor=system_case_executor,
    # ... (other prompts)
)
```

## Provider/Model Plugins

Provider/model plugins are used to add new LLM providers and models to the application. This is done by adding a new entry to the `backend/src/core/providers.json` file.

The `providers.json` file is a JSON object where each key is a provider ID and the value is an object containing the provider's configuration.

The following is an example of a `providers.json` file:

```json
{
    "openai": {
        "display_name": "OpenAI",
        "api_key_name": "OPENAI_API_KEY",
        "client_class": "OpenAIClient",
        "client_config": {},
        "models": [
            "gpt-4o",
            "gpt-4-turbo",
            "gpt-3.5-turbo"
        ]
    },
    "google": {
        "display_name": "Google",
        "api_key_name": "GOOGLE_API_KEY",
        "client_class": "GoogleGenAIClient",
        "client_config": {},
        "models": [
            "gemini-1.5-pro-latest",
            "gemini-1.0-pro"
        ]
    }
}
```
