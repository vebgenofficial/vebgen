<a id="core.error_analyzer"></a>

# core.error\_analyzer

<a id="core.error_analyzer.ErrorAnalyzer"></a>

## ErrorAnalyzer Objects

```python
class ErrorAnalyzer()
```

Parses raw command output (stdout, stderr) to identify and structure errors.

This class uses a series of prioritized heuristics to analyze logs from
command executions. It can identify specific framework errors (like Django test
failures), common Python tracebacks, and other command-line issues, converting
them into structured `ErrorRecord` objects for the remediation system.

<a id="core.error_analyzer.ErrorAnalyzer.__init__"></a>

#### \_\_init\_\_

```python
def __init__(project_root: Path, file_system_manager: FileSystemManager)
```

Initializes the ErrorAnalyzer.

**Arguments**:

- `project_root` - The absolute path to the project's root directory.
- `file_system_manager` - An instance of FileSystemManager for file system checks.

<a id="core.error_analyzer.ErrorAnalyzer.analyze_logs"></a>

#### analyze\_logs

```python
def analyze_logs(
        command: str, stdout: str, stderr: str,
        exit_code: int) -> Tuple[List[ErrorRecord], Optional[Dict[str, int]]]
```

Analyzes command output logs for known error patterns in a prioritized sequence.

This is the main entry point for the analyzer. It tries different parsing
strategies, starting with the most specific (like Django test failures) and
falling back to more general ones.

**Arguments**:

- `command` - The command that was executed.
- `stdout` - The standard output from the command.
- `stderr` - The standard error from the command.
- `exit_code` - The exit code of the command.
  

**Returns**:

  A list of ErrorRecord objects representing the found errors. An empty list
  if no errors are found or the exit code is 0.

