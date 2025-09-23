<a id="ui.main_window"></a>

# ui.main\_window

<a id="ui.main_window.QUEUE_MSG_UPDATE_UI"></a>

#### QUEUE\_MSG\_UPDATE\_UI

Message type for general UI updates (progress, status, messages)

<a id="ui.main_window.QUEUE_MSG_SHOW_DIALOG"></a>

#### QUEUE\_MSG\_SHOW\_DIALOG

Message type to request showing a modal dialog

<a id="ui.main_window.QUEUE_MSG_DISPLAY_COMMAND"></a>

#### QUEUE\_MSG\_DISPLAY\_COMMAND

Message type to display a command execution task in the UI

<a id="ui.main_window.QUEUE_MSG_COMMAND_RESULT_INTERNAL"></a>

#### QUEUE\_MSG\_COMMAND\_RESULT\_INTERNAL

Internal message type (not used directly by queue put)

<a id="ui.main_window.QUEUE_MSG_REQUEST_API_KEY_UPDATE"></a>

#### QUEUE\_MSG\_REQUEST\_API\_KEY\_UPDATE

New: For API key update dialog

<a id="ui.main_window.QUEUE_MSG_REQUEST_NETWORK_RETRY"></a>

#### QUEUE\_MSG\_REQUEST\_NETWORK\_RETRY

New: For network retry dialog

<a id="ui.main_window.MainWindow"></a>

## MainWindow Objects

```python
class MainWindow()
```

Main application window for the AI Agent Development tool.

Handles UI setup, user interactions (project selection, prompt input, model selection),
and orchestrates the background workflow execution via WorkflowManager. Manages
thread-safe communication between the background workflow and the Tkinter UI thread.

<a id="ui.main_window.MainWindow.__init__"></a>

#### \_\_init\_\_

```python
def __init__(master: tk.Tk)
```

Initializes the main application window.

**Arguments**:

- `master` - The root Tkinter window instance.

<a id="ui.main_window.MainWindow.update_task_in_ui"></a>

#### update\_task\_in\_ui

```python
def update_task_in_ui(task_id: str, updates: Dict[str, Any])
```

Public method for external components like WorkflowManager to send UI updates
for a specific task widget. This is a simplified entry point that queues
a generic update for now.

<a id="ui.main_window.MainWindow.select_project_directory"></a>

#### select\_project\_directory

```python
def select_project_directory()
```

Handles the 'Select Project Directory' menu action. Prompts the user to
choose a folder, then kicks off the two-stage core initialization process.

<a id="ui.main_window.MainWindow.on_framework_selected"></a>

#### on\_framework\_selected

```python
def on_framework_selected(event=None)
```

Callback for when the framework dropdown selection changes.
It shows a "Coming Soon" message for unsupported frameworks and triggers
re-initialization if a valid framework is chosen.

<a id="ui.main_window.MainWindow.on_provider_selected"></a>

#### on\_provider\_selected

```python
def on_provider_selected(event=None)
```

Callback for when the API provider dropdown selection changes.

<a id="ui.main_window.MainWindow.on_model_selected"></a>

#### on\_model\_selected

```python
def on_model_selected(event=None)
```

Callback for when the LLM model selection changes.
This is a critical event that saves the user's preference and triggers
the re-initialization of the `AgentManager` and `WorkflowManager`.

<a id="ui.main_window.MainWindow.handle_send_prompt"></a>

#### handle\_send\_prompt

```python
def handle_send_prompt(event=None)
```

Handles the 'Start' button click or Enter key press in the prompt entry.
It validates all necessary inputs and configurations are ready, then starts
the appropriate workflow (initial or subsequent) in a background thread.

<a id="ui.main_window.MainWindow.add_message"></a>

#### add\_message

```python
def add_message(sender: str, message: str)
```

A public, thread-safe method to add a message to the UI displays.
It determines the correct message type and puts it on the UI queue
for processing.

<a id="ui.main_window.MainWindow.update_progress_safe"></a>

#### update\_progress\_safe

```python
def update_progress_safe(progress_data: Dict[str, Any])
```

Thread-safe method to send progress updates to the UI thread via the queue.
This is the primary way background threads communicate status back to the UI.

<a id="ui.main_window.MainWindow.manage_api_keys"></a>

#### manage\_api\_keys

```python
def manage_api_keys()
```

Handles the 'Manage API Keys' menu action, allowing users to update or clear stored keys.

<a id="ui.main_window.MainWindow.show_about_dialog"></a>

#### show\_about\_dialog

```python
def show_about_dialog()
```

Displays the 'About' dialog box with application information.

<a id="ui.main_window.MainWindow.on_closing"></a>

#### on\_closing

```python
def on_closing()
```

Handles the window close event, confirming with the user if a task is running.

