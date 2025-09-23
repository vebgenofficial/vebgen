<a id="core.remediation_manager"></a>

# core.remediation\_manager

<a id="core.remediation_manager.InterruptedError"></a>

## InterruptedError Objects

```python
class InterruptedError(Exception)
```

Custom exception raised when a workflow is intentionally stopped by the user,
for example, by cancelling a confirmation dialog or an API key prompt.

<a id="core.remediation_manager.RemediationCycleStatus"></a>

## RemediationCycleStatus Objects

```python
class RemediationCycleStatus(Enum)
```

Defines the possible outcomes of a single attempt to fix a set of errors.

<a id="core.remediation_manager.RemediationManager"></a>

## RemediationManager Objects

```python
class RemediationManager()
```

Orchestrates the automated, multi-step remediation of code errors.

This class is responsible for the entire self-healing loop. It takes a set of
analyzed errors, creates a plan to fix them using an LLM, executes that plan
(which may involve modifying multiple files), and then verifies if the fix was
successful by re-running the original command that failed.

<a id="core.remediation_manager.RemediationManager.__init__"></a>

#### \_\_init\_\_

```python
def __init__(agent_manager: AgentManager,
             file_system_manager: FileSystemManager,
             command_executor: CommandExecutor,
             prompts: FrameworkPrompts,
             progress_callback: ProgressCallback,
             request_network_retry_cb: Optional[RequestNetworkRetryCallable],
             test_command: Optional[str] = None,
             remediation_config: dict = None)
```

Initializes the RemediationManager.

**Arguments**:

- `agent_manager` - Manages interaction with the LLM clients.
- `file_system_manager` - Handles safe file system operations.
- `command_executor` - Executes shell commands securely.
- `prompts` - Contains the system prompts for the AI agents.
- `progress_callback` - A thread-safe callback to send UI updates.
- `request_network_retry_cb` - A callback to ask the user to retry network errors.
- `test_command` - The original command that failed, used for verification.
- `remediation_config` - A dictionary controlling which remediation actions are allowed.

<a id="core.remediation_manager.RemediationManager.remediate"></a>

#### remediate

```python
async def remediate(command: str, initial_error_records: List[ErrorRecord],
                    project_state: ProjectState) -> bool
```

Orchestrates an iterative remediation process. It repeatedly analyzes errors,
applies fixes, and verifies them until the command succeeds, no progress is made,
or the maximum number of cycles is reached.

This is the main public method of the manager. It controls the high-level
remediation loop, deciding whether to continue to another cycle or to give up
and roll back changes.

