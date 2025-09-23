# src/core/exceptions.py
from typing import Optional

class CoreError(Exception):
    """Base exception for all custom errors raised within the Vebgen core modules."""
    pass

class InterruptedError(CoreError):
    """
    Raised when a workflow is intentionally stopped by the user, for example,
    by cancelling a confirmation dialog or an API key prompt.
    """
    pass

class AgentError(CoreError):
    """Base exception for errors originating from the AgentManager."""
    pass

class WorkflowError(CoreError):
    """Base exception for errors originating from the WorkflowManager."""
    pass

# Specific LLM client exceptions (RateLimitError, AuthenticationError) are in llm_client.py
class BlockedCommandException(Exception):
    """
    Raised by the CommandExecutor when a command is blocked by the security filter.

    This exception is used to handle cases where a command matches a pattern
    in the blocklist, allowing the system to substitute it with a safer alternative.
    """
    def __init__(self, original_command: str, safe_alternative: str, description: str):
        self.original_command = original_command
        self.safe_alternative = safe_alternative
        self.description = description
        message = f"Command '{original_command}' was blocked. Safe alternative: '{safe_alternative}'. Description: {description}"
        super().__init__(message)

class CommandExecutionError(RuntimeError):
    """
    Raised when a command executed via CommandExecutor fails (non-zero exit code).

    This exception is a structured way to pass the complete context of a command
    failure, including its output streams and exit code, to the error handling
    and remediation systems.
    """
    def __init__(self, message: str, stdout: Optional[str] = None, stderr: Optional[str] = None, exit_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code

class PatchApplyError(CoreError):
    """
    Raised by the FileSystemManager when applying a diff patch to a file fails.
    This can happen if the patch is malformed or doesn't match the file's content.
    """
    pass

class RemediationError(CoreError):
    """
    Raised by the RemediationManager when a self-healing attempt fails definitively
    after all retries, indicating that the agent could not fix the issue.
    """
    pass

class MergeConflictError(CoreError):
    """
    Raised by the FileSystemManager during a three-way merge operation if
    unresolvable conflicts are detected between the base, local, and remote versions.
    """
    pass
