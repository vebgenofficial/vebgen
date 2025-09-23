# backend/src/core/error_analyzer.py
import re
from pathlib import Path
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

from .file_system_manager import FileSystemManager
from .project_models import ErrorType, ErrorRecord

logger = logging.getLogger(__name__)

class ErrorAnalyzer:
    """
    Parses raw command output (stdout, stderr) to identify and structure errors.

    This class uses a series of prioritized heuristics to analyze logs from
    command executions. It can identify specific framework errors (like Django test
    failures), common Python tracebacks, and other command-line issues, converting
    them into structured `ErrorRecord` objects for the remediation system.
    """
    def __init__(self, project_root: Path, file_system_manager: FileSystemManager):
        """
        Initializes the ErrorAnalyzer.

        Args:
            project_root: The absolute path to the project's root directory.
            file_system_manager: An instance of FileSystemManager for file system checks.
        """
        self.project_root = project_root
        self.file_system_manager = file_system_manager

    def _normalize_path(self, file_path: str) -> str:
        """
        Converts an absolute path to a relative path if it's within the project root.

        This is a utility function to ensure that file paths stored in `ErrorRecord`
        objects are clean, consistent, and relative to the project, which is better
        for display and for the LLM's context.
        If the path is already relative or not within the project, it's returned as is.
        """
        if not self.project_root or not file_path or file_path == "Unknown":
            return file_path
        
        try:
            path = Path(file_path)
            if path.is_absolute():
                # This will raise ValueError if path is not within project_root
                relative_path = path.relative_to(self.project_root)
                return str(relative_path)
        except (ValueError, TypeError):
            # Not within project root or not a valid path, return as is
            return file_path
        # Return original path if it's already relative
        return file_path

    def _parse_general_traceback(self, logs: str, command: str) -> Optional[ErrorRecord]:
        """
        A helper to parse a standard Python traceback, finding the most relevant
        file within the user's project. It iterates through the stack trace from the
        bottom up to find the deepest frame that belongs to the user's code, as this
        is often the most direct cause of the error.
        """
        # Maps common Python exception names to our internal ErrorType enum.
        error_type_map = {
            'AssertionError': ErrorType.TestFailure,
            'SyntaxError': ErrorType.SyntaxError,
            'IndentationError': ErrorType.SyntaxError,
            'TemplateDoesNotExist': ErrorType.TemplateError,
            'FileNotFoundError': ErrorType.FileNotFound,
            'ImportError': ErrorType.LogicError,
            'ModuleNotFoundError': ErrorType.LogicError,
            'KeyError': ErrorType.LogicError,
            'AttributeError': ErrorType.LogicError,
            'ValueError': ErrorType.LogicError,
            'TypeError': ErrorType.LogicError,
            'NameError': ErrorType.LogicError,
            'IndexError': ErrorType.LogicError,
            'PermissionError': ErrorType.PermissionError,
            'ImproperlyConfigured': ErrorType.LogicError, # Django specific
            'OperationalError': ErrorType.LogicError, # Django DB
            'NoReverseMatch': ErrorType.LogicError, # Django URL
        }

        # This regex is robust for capturing the final error line, which typically
        # follows the format "ExceptionType: The error message."
        final_error_pattern = re.compile(r"^(?:[a-zA-Z0-9_]+\.)*(?P<type>[a-zA-Z_]\w*):\s*(?P<msg>.*)", re.MULTILINE)
        final_error_match = final_error_pattern.search(logs)

        if not final_error_match:
            return None

        error_name, error_message = final_error_match.groups()

        # Find all traceback frames
        traceback_files = re.findall(r'^\s*File "([^"]+)", line (\d+)', logs, re.MULTILINE)
        logger.debug(f"Traceback files found by regex in this block: {traceback_files}")

        if not traceback_files:
            # Handle cases where there's an error but no file traceback (e.g., command not found)
            logger.warning("No traceback file lines found in this log block.")
            return None

        # Find the deepest stack frame that is part of the project code by iterating in reverse.
        for file_path, line_number_str in reversed(traceback_files):
            logger.debug(f"Analyzing traceback frame: file_path='{file_path}'")
            try:
                # Resolve the path to an absolute path to perform reliable checks.
                abs_file_path = Path(file_path)
                if not abs_file_path.is_absolute():
                    abs_file_path = (self.project_root / file_path).resolve()
                else:
                    abs_file_path = abs_file_path.resolve()

                # CRITICAL CHECK: Is the file within the project directory?
                # This prevents us from trying to "fix" files in the Python standard library or site-packages.
                is_in_project = abs_file_path.is_relative_to(self.project_root)
            except (ValueError, Exception):
                is_in_project = False

            # --- NEW: Special handling for PermissionError ---
            if error_name == 'PermissionError':
                # If a PermissionError occurs, it's almost always an environmental issue (antivirus, file locks, OS permissions)
                # and not a code bug the agent can fix by editing Python files. We create a specific
                # error record with hints that can halt the remediation loop and inform the user,
                # preventing the agent from trying to "fix" an unfixable problem.
                logger.warning(f"Detected PermissionError in traceback: {file_path}. This is likely an environmental issue.")
                return ErrorRecord(
                    error_type=ErrorType.PermissionError,
                    file_path=self._normalize_path(file_path), # The file that couldn't be accessed
                    line_number=int(line_number_str),
                    message=logs.strip(),
                    summary=f"{error_name}: {error_message.strip()}",
                    command=command,
                    hints={
                        "diagnosis": "A PermissionError occurred, which is an operating system level issue. This is not a bug in the Python code itself. Common causes include antivirus software locking files, or the application not being run with sufficient privileges (e.g., as an administrator). The agent cannot fix this automatically."
                    }
                )

            if not is_in_project:
                logger.debug(f"Skipping file '{file_path}' as it is outside the project root.")
                continue

            # Now that we know it's a project file, explicitly exclude files inside the virtual environment.
            is_in_venv = False
            try:
                local_venv_path = (self.project_root / "venv").resolve()
                if local_venv_path.exists() and abs_file_path.is_relative_to(local_venv_path):
                    is_in_venv = True
            except Exception: pass
            is_manage_py = abs_file_path.name == 'manage.py'

            # If the file is part of the project and not a venv file or manage.py, we've found our target.
            if not is_in_venv and not is_manage_py:
                logger.debug(f"Found relevant project file: {file_path}. Creating ErrorRecord.")

                # Prioritize the specific error type from the map.
                # Only override with TestFailure for actual assertion errors,
                # allowing other specific types like LogicError (for NoReverseMatch) to pass through.
                error_type_enum = error_type_map.get(error_name, ErrorType.LogicError) # type: ignore

                # Add richer hints for specific errors to guide the RemediationPlanner.
                hints: Dict[str, Any] = {}
                # For NoReverseMatch, we can suggest candidate files to look at.
                if error_name == 'NoReverseMatch':
                    hints['diagnosis'] = "A `NoReverseMatch` error means Django's URL resolver could not find a match for the requested URL name. This is often caused by a typo in a template's `{% url '...' %}` tag, a missing `app_name` variable in an app's urls.py, or the app's URLs not being included in the project's main urls.py."
                    
                    candidate_files: List[str] = []
                    
                    # The file where the error was raised (often a template) is a primary candidate.
                    normalized_file_path = self._normalize_path(file_path)
                    if normalized_file_path and normalized_file_path != "Unknown" and self.file_system_manager.file_exists(normalized_file_path):
                        candidate_files.append(normalized_file_path)

                    # --- FIX: More robustly extract app namespace for NoReverseMatch ---
                    app_namespace = None
                    # First, try to get the namespace from "'app_name' is not a registered namespace"
                    namespace_match = re.search(r"'([^']*)' is not a registered namespace", error_message)
                    if namespace_match:
                        app_namespace = namespace_match.group(1)
                    else:
                        # If that fails, try to get it from "Reverse for 'app_name:view_name' not found"
                        url_name_match = re.search(r"Reverse for '([^']*)' not found", error_message)
                        if url_name_match:
                            url_name = url_name_match.group(1)
                            if ":" in url_name:
                                app_namespace = url_name.split(":", 1)[0]
                    
                    if app_namespace:
                            candidate_files.append(f"{app_namespace}/urls.py")
                            candidate_files.append(f"{app_namespace}/views.py")

                    # Use a set to remove duplicates, then convert back to a list.
                    hints['candidate_files'] = sorted(list(set(candidate_files)))

                # Re-classify as TestFailure if AssertionError is in the message, but NOT for NoReverseMatch.
                if error_name != 'NoReverseMatch' and error_type_enum == ErrorType.LogicError and 'assertionerror' in logs.lower():
                    error_type_enum = ErrorType.TestFailure

                if 'test' in command.lower():
                    # An AssertionError in a test is the definition of a TestFailure.
                    if error_name == 'AssertionError': # type: ignore
                        error_type_enum = ErrorType.TestFailure

                return ErrorRecord(
                    error_type=error_type_enum,
                    file_path=self._normalize_path(file_path),
                    line_number=int(line_number_str),
                    message=logs.strip(), # Store the full log context
                    summary=f"{error_name}: {error_message.strip()}", # Store the specific one-line error
                    command=command,
                    hints=hints if hints else None # Add the hints to the record
                )

        logger.warning("No project-specific file found in traceback. Cannot create ErrorRecord for this block.")

        # If no project file was found, it's likely a configuration or library issue.
        # Check for common Django configuration keywords to create a targeted error record.
        config_error_keywords = ['INSTALLED_APPS', 'DATABASES', 'SECRET_KEY', 'MIDDLEWARE', 'ImproperlyConfigured']
        log_lower = logs.lower()
        if any(keyword.lower() in log_lower for keyword in config_error_keywords):
            return ErrorRecord(
                error_type=ErrorType.LogicError,
                file_path="PROJECT_SETTINGS_FILE", # Special placeholder for the planner
                line_number=None,
                message=f"Configuration Error: {error_name}: {error_message}".strip(),
                summary=f"{error_name}: {error_message.strip()}",
                command=command
            )

        return None # No relevant project file found

    def _parse_test_summary(self, logs: str) -> Optional[Dict[str, int]]:
        """
        Parses the 'FAILED (failures=X, errors=Y)' summary line from unittest output.
        """
        summary_match = re.search(r"FAILED \(failures=(\d+), errors=(\d+)\)", logs)
        if summary_match:
            failures = int(summary_match.group(1))
            errors = int(summary_match.group(2))
            return {"failures": failures, "errors": errors, "total": failures + errors}
        
        summary_match_f = re.search(r"FAILED \(failures=(\d+)\)", logs)
        if summary_match_f:
            failures = int(summary_match_f.group(1))
            return {"failures": failures, "errors": 0, "total": failures}

        summary_match_e = re.search(r"FAILED \(errors=(\d+)\)", logs)
        if summary_match_e:
            errors = int(summary_match_e.group(1))
            return {"failures": 0, "errors": errors, "total": errors}
            
        return None

    def _analyze_test_failure_logs(self, logs: str, command: str) -> List[ErrorRecord]:
        """
        A specialized parser for Django's 'manage.py test' output. It splits the
        log into individual error blocks and analyzes each one.

        This is necessary because the test runner can output multiple, distinct
        tracebacks for different failed tests in a single run.
        """
        # Normalize line endings to prevent splitting issues on Windows
        normalized_logs = logs.replace('\r\n', '\n')

        # Split the log by the '====...====' separator to isolate each error/failure report.
        error_blocks = re.split(r'\n======================================================================\n', normalized_logs)
        # The first block might not be an error, so we check if it contains the test run summary
        # and discard it if so. A more robust check might be needed.
        if error_blocks and ("Ran " in error_blocks[0] or "Creating test database" in error_blocks[0]):
            error_blocks = error_blocks[1:]

        if not error_blocks:
            logger.warning("Could not split logs by separator or no error blocks found after splitting.")
            return []

        logger.info(f"Found {len(error_blocks)} potential error blocks for analysis after splitting.")
        found_errors: List[ErrorRecord] = []

        for block in error_blocks:
            # Each block should start with "ERROR:" or "FAIL:"
            if not block.strip().startswith(("ERROR:", "FAIL:")):
                continue

            test_name_match = re.search(r"^(?:ERROR|FAIL): (test_\w+) \(([\w\.]+)\)", block.strip(), re.MULTILINE)
            test_context_prefix = ""
            if test_name_match:
                test_name = test_name_match.group(1)
                test_class = test_name_match.group(2)
                test_context_prefix = f"Test `{test_name}` in `{test_class}` failed: "

            parsed_error = self._parse_general_traceback(block, command)
            if parsed_error:
                # Prepend the test context to the message to ensure uniqueness if multiple tests fail similarly.
                parsed_error.message = f"{test_context_prefix}{block.strip()}"
                # Avoid adding duplicate errors if multiple tracebacks point to the same root cause
                if not any(err.message.strip() == parsed_error.message.strip() for err in found_errors):
                    found_errors.append(parsed_error)
        
        return found_errors

    def analyze_logs(self, command: str, stdout: str, stderr: str, exit_code: int) -> Tuple[List[ErrorRecord], Optional[Dict[str, int]]]:
        """
        Analyzes command output logs for known error patterns in a prioritized sequence.

        This is the main entry point for the analyzer. It tries different parsing
        strategies, starting with the most specific (like Django test failures) and
        falling back to more general ones.

        Args:
            command: The command that was executed.
            stdout: The standard output from the command.
            stderr: The standard error from the command.
            exit_code: The exit code of the command.

        Returns:
            A list of ErrorRecord objects representing the found errors. An empty list
            if no errors are found or the exit code is 0.
        """
        if exit_code == 0:
            return [], None

        logs = stdout + "\n" + stderr
        test_summary = self._parse_test_summary(logs)

        # --- Heuristic: Django Test Runner Failures (Top Priority) ---
        # Check for the characteristic output of the Django test runner failing.
        if "Ran " in logs and " test" in logs and "FAILED" in logs:
            test_errors = self._analyze_test_failure_logs(logs, command)
            # Return both the list of parsed errors and the summary dictionary
            return test_errors, test_summary

        # --- Heuristic: Command Not Found (OS-level error) ---
        cmd_not_found_match = re.search(r"(?:command not found|not recognized as an internal or external command)", logs, re.IGNORECASE)
        if cmd_not_found_match:
            return [ErrorRecord(
                error_type=ErrorType.CommandNotFound,
                file_path=None,
                line_number=None,
                message=f"The command '{command}' could not be found. It might not be installed or not in the system's PATH.",
                command=command
            )], test_summary

        # --- Heuristic: Stalled Command (Interactive Prompt) ---
        # This looks for a specific error message that indicates a command is waiting for user input.
        if '"errorType": "CommandStalled"' in stderr:
            if re.search(r"define a default value in models\.py", logs, re.IGNORECASE):
                file_path_match = re.search(r'File "([^"]+models\.py)"', logs)
                file_path = file_path_match.group(1) if file_path_match else "Unknown"
                return [ErrorRecord(
                    error_type=ErrorType.LogicError,
                    file_path=self._normalize_path(file_path),
                    line_number=None,
                    message="The command timed out, likely waiting for user input for a database migration.",
                    command=command
                )], test_summary

        # --- Heuristic: Database Not Ready (Common Django issue) ---
        db_error_match = re.search(r"django\.db\.utils\.OperationalError: no such table: (?P<table>\w+)|You have \d+ unapplied migration\(s\)", logs, re.MULTILINE)
        if db_error_match:
            if "no such table" in db_error_match.group(0):
                return [ErrorRecord(
                    error_type=ErrorType.LogicError,
                    file_path="Unknown",
                    line_number=None,
                    message="Database tables do not exist. The most likely cause is that migrations have not been run.",
                    command="python manage.py makemigrations && python manage.py migrate"
                )], test_summary
            else:
                return [ErrorRecord(
                    error_type=ErrorType.LogicError,
                    file_path="Unknown",
                    line_number=None,
                    message="The database schema is out of date. Migrations need to be applied.",
                    command="python manage.py migrate"
                )], test_summary

        # --- Heuristic: TemplateDoesNotExist (High-priority Django error) ---
        # This is a high-priority error because the fix is to create a file,
        # which is a different type of remediation than fixing logic in the view.
        template_error_match = re.search(r"django\.template\.exceptions\.TemplateDoesNotExist: ([a-zA-Z0-9_\-\./]+)", logs)
        if template_error_match:
            template_path = template_error_match.group(1)
            # The traceback points to the view, but the actionable file is the template.
            return [ErrorRecord(
                error_type=ErrorType.TemplateError,
                file_path=self._normalize_path(template_path), # The path of the template to create
                line_number=None,
                message=f"Template '{template_path}' does not exist.",
                command=command
            )], test_summary

        # --- Heuristic: Static Analysis Failure (from a custom script) ---
        static_analysis_match = re.search(r"Static analysis.*?FAILED for '([^']+)'.*?: (.*)", logs, re.DOTALL)
        if static_analysis_match:
            file_path, message = static_analysis_match.groups()
            return [ErrorRecord(
                error_type=ErrorType.SyntaxError,
                file_path=self._normalize_path(file_path),
                line_number=None,
                message=message.strip(),
                command=command
            )], test_summary

        # --- Heuristic: INSTALLED_APPS Configuration Error (Django) ---
        installed_apps_match = re.search(r"ImportError: Module '([^']*)' does not contain a '([^']*)' class", logs)
        if installed_apps_match:
            return [ErrorRecord(
                error_type=ErrorType.LogicError,
                file_path="PROJECT_SETTINGS_FILE",
                line_number=None,
                message=installed_apps_match.group(0).strip(),
                command=command
            )], test_summary

        # --- Heuristic: General Python Traceback Parsing ---
        general_error = self._parse_general_traceback(logs, command)
        if general_error:
            return [general_error], test_summary

        # --- Fallback: Generic Error ---
        if stderr.strip():
            # NEW: Attempt to extract a fallback path from the error message itself
            # This is a last-ditch effort if no other heuristic matched.
            fallback_path = "Unknown"
            path_match = re.search(r'File "([^"]+)"', stderr) # A common pattern in many error types
            if path_match:
                fallback_path = self._normalize_path(path_match.group(1))

            return [ErrorRecord(
                error_type=ErrorType.Unknown,
                file_path=fallback_path, # Use the extracted path
                line_number=None,
                message=stderr.strip(),
                command=command
            )], test_summary

        return [], test_summary