<a id="core.command_executor"></a>

# core.command\_executor

<a id="core.command_executor.normalize_command_for_platform"></a>

#### normalize\_command\_for\_platform

```python
def normalize_command_for_platform(command: str) -> str
```

Normalizes a command string for the current platform (primarily Windows).
Replaces common Linux commands with Windows equivalents and normalizes path separators.
This allows the AI planner to generate commands in a more OS-agnostic way,
and the executor will adapt them for the host system.

<a id="core.command_executor.CommandExecutor"></a>

## CommandExecutor Objects

```python
class CommandExecutor()
```

Executes whitelisted shell commands securely within a specified project workspace.

Features:
- Whitelist of allowed commands and validation logic for arguments.
- Automatic usage of virtual environment executables (python, pip) if present.
- Path safety checks to ensure commands operate within the project root.
- Optional user confirmation callback for potentially sensitive commands.
- Streaming of command stdout/stderr to logging.
- Internal handling of 'cd' command to change the effective working directory.
- Avoids `shell=True` where possible for security. Blocks redirection operators.
- Platform-aware command parsing (Windows cmd vs. Unix shlex).
- Path normalization and validation before execution.

<a id="core.command_executor.CommandExecutor.__init__"></a>

#### \_\_init\_\_

```python
def __init__(project_root_path: str | Path,
             confirmation_cb: Optional[ConfirmationCallback] = None)
```

Initializes the CommandExecutor.

**Arguments**:

- `project_root_path` - The absolute or relative path to the root directory
  where commands should be executed.
- `confirmation_cb` - An optional callback function to request user confirmation
  before running certain commands. Takes the command string
  as input and should return True to proceed, False to cancel.
  

**Raises**:

- `ValueError` - If project_root_path is not provided or invalid.
- `FileNotFoundError` - If the resolved project_root_path does not exist.
- `NotADirectoryError` - If the resolved project_root_path is not a directory.

<a id="core.command_executor.CommandExecutor.check_command_for_block"></a>

#### check\_command\_for\_block

```python
def check_command_for_block(command_str: str) -> None
```

Checks the command against the blocklist.
If a blocked pattern is found, extracts parameters, forms a safe alternative,
and raises BlockedCommandException.

**Arguments**:

- `command_str` - The command string to check.
  

**Raises**:

- `BlockedCommandException` - If the command matches a blocked pattern.

<a id="core.command_executor.CommandExecutor.execute"></a>

#### execute

```python
def execute(command: str) -> CommandResult
```

Executes a command and returns a structured CommandResult object.
This is a public wrapper around the internal `run_command` method.

<a id="core.command_executor.CommandExecutor.run_command"></a>

#### run\_command

```python
def run_command(command: str) -> 'CommandOutput'
```

Validates and executes a whitelisted shell command within the project root.
Includes enhanced path validation and normalization.
Returns: Tuple (status_code, stdout_str, stderr_str)

<a id="core.command_executor.CommandExecutor.log_command_status"></a>

#### log\_command\_status

```python
def log_command_status(command: str,
                       success: bool,
                       details: Optional[str] = None)
```

Placeholder for logging command status.

