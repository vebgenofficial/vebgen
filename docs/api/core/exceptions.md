<a id="core.exceptions"></a>

# core.exceptions

<a id="core.exceptions.CoreError"></a>

## CoreError Objects

```python
class CoreError(Exception)
```

Base exception for all custom errors raised within the Vebgen core modules.

<a id="core.exceptions.InterruptedError"></a>

## InterruptedError Objects

```python
class InterruptedError(CoreError)
```

Raised when a workflow is intentionally stopped by the user, for example,
by cancelling a confirmation dialog or an API key prompt.

<a id="core.exceptions.AgentError"></a>

## AgentError Objects

```python
class AgentError(CoreError)
```

Base exception for errors originating from the AgentManager.

<a id="core.exceptions.WorkflowError"></a>

## WorkflowError Objects

```python
class WorkflowError(CoreError)
```

Base exception for errors originating from the WorkflowManager.

<a id="core.exceptions.BlockedCommandException"></a>

## BlockedCommandException Objects

```python
class BlockedCommandException(Exception)
```

Raised by the CommandExecutor when a command is blocked by the security filter.

This exception is used to handle cases where a command matches a pattern
in the blocklist, allowing the system to substitute it with a safer alternative.

<a id="core.exceptions.CommandExecutionError"></a>

## CommandExecutionError Objects

```python
class CommandExecutionError(RuntimeError)
```

Raised when a command executed via CommandExecutor fails (non-zero exit code).

This exception is a structured way to pass the complete context of a command
failure, including its output streams and exit code, to the error handling
and remediation systems.

<a id="core.exceptions.PatchApplyError"></a>

## PatchApplyError Objects

```python
class PatchApplyError(CoreError)
```

Raised by the FileSystemManager when applying a diff patch to a file fails.
This can happen if the patch is malformed or doesn't match the file's content.

<a id="core.exceptions.RemediationError"></a>

## RemediationError Objects

```python
class RemediationError(CoreError)
```

Raised by the RemediationManager when a self-healing attempt fails definitively
after all retries, indicating that the agent could not fix the issue.

<a id="core.exceptions.MergeConflictError"></a>

## MergeConflictError Objects

```python
class MergeConflictError(CoreError)
```

Raised by the FileSystemManager during a three-way merge operation if
unresolvable conflicts are detected between the base, local, and remote versions.

