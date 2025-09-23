<a id="core.config_manager"></a>

# core.config\_manager

<a id="core.config_manager.FrameworkPrompts"></a>

## FrameworkPrompts Objects

```python
@dataclasses.dataclass
class FrameworkPrompts()
```

Dataclass holding the required system prompts for a framework.

<a id="core.config_manager.FrameworkPrompts.system_tars_error_analyzer"></a>

#### system\_tars\_error\_analyzer

Changed to Optional

<a id="core.config_manager.FrameworkPrompts.system_tars_debugger"></a>

#### system\_tars\_debugger

Added for the new debugger prompt

<a id="core.config_manager.FrameworkPrompts.system_tars_triage_engineer"></a>

#### system\_tars\_triage\_engineer

New: For file identification

<a id="core.config_manager.FrameworkPrompts.system_case_code_fixer"></a>

#### system\_case\_code\_fixer

New: For code fixing by Case

<a id="core.config_manager.FrameworkPrompts.system_tars_remediation_planner"></a>

#### system\_tars\_remediation\_planner

New

<a id="core.config_manager.FrameworkPrompts.system_tars_remediation_differ"></a>

#### system\_tars\_remediation\_differ

New

<a id="core.config_manager.FrameworkPrompts.system_case_remediation"></a>

#### system\_case\_remediation

Add this line

<a id="core.config_manager.ConfigManager"></a>

## ConfigManager Objects

```python
class ConfigManager()
```

Manages loading of framework-specific and provider-specific configurations.

This class is responsible for two main types of configuration:
1.  **Framework Prompts**: It dynamically discovers and loads Python modules
    (e.g., `django/prompts.py`) from the `plugins` directory. Each module
    is expected to contain a `FrameworkPrompts` dataclass instance that
    provides the system prompts for AI agents tailored to that framework.
2.  **Provider/Model Info**: It loads `providers.json` to get the list of
    available LLM providers and their models for the UI.

<a id="core.config_manager.ConfigManager.__init__"></a>

#### \_\_init\_\_

```python
def __init__(plugins_dir: Optional[str | Path] = None)
```

Initializes the ConfigManager.

**Arguments**:

- `plugins_dir` - Optional path to the plugins directory. If None, it defaults
  to 'plugins' inside the 'src' directory (relative to this file).

<a id="core.config_manager.ConfigManager.get_available_frameworks"></a>

#### get\_available\_frameworks

```python
def get_available_frameworks() -> List[str]
```

Scans the plugins directory for valid framework subdirectories.
A valid framework directory is a subdirectory that contains both an `__init__.py`
file (making it a package) and a `prompts.py` file.

**Returns**:

  A list of strings, where each string is the name of a valid framework subdirectory.

<a id="core.config_manager.ConfigManager.load_prompts"></a>

#### load\_prompts

```python
def load_prompts(framework: str) -> FrameworkPrompts
```

Dynamically loads the `prompts.py` module for a given framework.

This method constructs the path to the framework's prompt file,
uses `importlib` to load it as a Python module, and extracts the
`FrameworkPrompts` instance (e.g., `django_prompts`) from it.
It temporarily adds the `src` directory to the system path to allow
the prompt modules to use absolute imports (e.g., `from src.core...`).

**Returns**:

  A validated `FrameworkPrompts` dataclass instance for the specified framework.
  

**Raises**:

- `ValueError` - If the framework plugin is not found or is invalid.
- `RuntimeError` - If an unexpected error occurs during module loading.

<a id="core.config_manager.ConfigManager.get_providers"></a>

#### get\_providers

```python
def get_providers() -> Dict[str, str]
```

Gets a list of all configured LLM providers for the UI.
Returns a dictionary of provider IDs and their display names.
Includes an "All" option.

<a id="core.config_manager.ConfigManager.get_models_for_provider"></a>

#### get\_models\_for\_provider

```python
def get_models_for_provider(provider_id: str) -> List[Dict[str, str]]
```

Gets the list of models for a specific provider ID.
Returns a list of models for a given provider ID.
If provider_id is 'all', returns all models formatted with their provider.

