<a id="core.memory_manager"></a>

# core.memory\_manager

<a id="core.memory_manager.MAX_HISTORY_MESSAGES"></a>

#### MAX\_HISTORY\_MESSAGES

Max messages in history before pruning

<a id="core.memory_manager.HISTORY_FILENAME"></a>

#### HISTORY\_FILENAME

File to store chat history

<a id="core.memory_manager.PROJECT_STATE_FILENAME"></a>

#### PROJECT\_STATE\_FILENAME

File to store the detailed project state

<a id="core.memory_manager.WORKFLOW_CONTEXT_FILENAME"></a>

#### WORKFLOW\_CONTEXT\_FILENAME

File for non-sensitive workflow state

<a id="core.memory_manager.STORAGE_DIR_NAME"></a>

#### STORAGE\_DIR\_NAME

Hidden directory within user's project for storing these files

<a id="core.memory_manager.MemoryManager"></a>

## MemoryManager Objects

```python
class MemoryManager()
```

Manages the persistence of the application's state to the file system.

This class handles the loading and saving of three key pieces of information,
all stored within a hidden `.vebgen` directory inside the user's project:
1.  **Project State**: The complete, detailed state of the project, including
    features, tasks, and configurations. Managed via Pydantic models for robustness.
2.  **Conversation History**: The ongoing chat history with the AI agents.
3.  **Workflow Context**: Non-sensitive, session-related data like task completion status.

It is designed to be adaptable to different storage backends in the future.

<a id="core.memory_manager.MemoryManager.__init__"></a>

#### \_\_init\_\_

```python
def __init__(project_root_path: str | Path,
             storage_backend_type: str = "filesystem")
```

Initializes the MemoryManager.

**Arguments**:

- `project_root_path` - The absolute path to the root directory of the user's project.
- `storage_backend_type` - The type of storage backend to use.
  (Currently only "filesystem" is implemented).
  

**Raises**:

- `ValueError` - If project_root_path is not provided or invalid.
- `RuntimeError` - If the storage directory cannot be created.

<a id="core.memory_manager.MemoryManager.load_history"></a>

#### load\_history

```python
def load_history() -> List[ChatMessage]
```

Loads conversation history from the history file (conversation_history.json).
Performs basic validation on the loaded data.

**Returns**:

  A list of ChatMessage dictionaries, or an empty list if the file
  doesn't exist, is invalid, or an error occurs.

<a id="core.memory_manager.MemoryManager.save_history"></a>

#### save\_history

```python
def save_history(messages: List[ChatMessage]) -> None
```

Saves the conversation history to the history file (conversation_history.json)
after pruning it to MAX_HISTORY_MESSAGES.

**Arguments**:

- `messages` - The list of ChatMessage dictionaries to save.

<a id="core.memory_manager.MemoryManager.clear_history"></a>

#### clear\_history

```python
def clear_history() -> None
```

Deletes the history file (conversation_history.json).

<a id="core.memory_manager.MemoryManager.load_project_state"></a>

#### load\_project\_state

```python
def load_project_state() -> Optional[ProjectState]
```

Loads the detailed project workflow state from project_state.json.
Validates the loaded structure using Pydantic models.

**Returns**:

  A ProjectState Pydantic model instance if the file exists and is valid, otherwise None.

<a id="core.memory_manager.MemoryManager.save_project_state"></a>

#### save\_project\_state

```python
def save_project_state(state: ProjectState) -> None
```

Saves the entire project workflow state (as a Pydantic model) to project_state.json.

**Arguments**:

- `state` - The ProjectState Pydantic model instance to save.
  

**Raises**:

- `TypeError` - If the provided state is not a ProjectState instance.
- `RuntimeError` - If saving or serialization fails.

<a id="core.memory_manager.MemoryManager.clear_project_state"></a>

#### clear\_project\_state

```python
def clear_project_state() -> None
```

Deletes the project state file (project_state.json).

<a id="core.memory_manager.MemoryManager.load_workflow_context"></a>

#### load\_workflow\_context

```python
def load_workflow_context() -> Dict[str, Any]
```

Loads non-sensitive workflow context (e.g., recent steps, user requirements)
from workflow_context.json.

**Returns**:

  A dictionary containing the loaded context, or a default empty structure
  if the file doesn't exist or is invalid.

<a id="core.memory_manager.MemoryManager.save_workflow_context"></a>

#### save\_workflow\_context

```python
def save_workflow_context(context: Dict[str, Any]) -> None
```

Saves the workflow context dictionary to workflow_context.json.

<a id="core.memory_manager.MemoryManager.clear_workflow_context"></a>

#### clear\_workflow\_context

```python
def clear_workflow_context() -> None
```

Deletes the workflow context file (workflow_context.json).

