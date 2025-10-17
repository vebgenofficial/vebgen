# c:\Users\rames\WebGen\web_agent7\backend\src\core\command_executor.py
import time
import subprocess
import logging # Keep logging 
import json # Import the json module
import shlex # <--- Import is present
import shutil
import sys
import platform
import threading
import re
import os
from pathlib import Path
from typing import Callable, Optional, List, Union, Tuple, Dict, Set, Literal
from typing import Any, Dict, Optional

from .project_models import CommandResult, CommandOutput
# Assuming FileSystemManager is defined elsewhere and imported correctly
# from .file_system_manager import FileSystemManager # Example import

# Placeholder for FileSystemManager if not available for standalone execution
class FileSystemManager: # Keep this placeholder if you test CommandExecutor standalone
    def __init__(self, root_path): self.project_root = Path(root_path)
    def _resolve_safe_path(self, path_str):
        resolved = (self.project_root / path_str).resolve()
        resolved.relative_to(self.project_root) # Raises ValueError if outside
        if ".." in Path(path_str).parts: raise ValueError("Path contains '..'")
        return resolved

# --- FIX: Import BlockedCommandException ---
from .exceptions import BlockedCommandException, InterruptedError
# --- End FIX ---
logger = logging.getLogger(__name__)
# Basic logging setup if run standalone for testing

# --- Normalization Function ---
def normalize_command_for_platform(command: str) -> str:
    """
    Normalizes a command string for the current platform (primarily Windows).
    Replaces common Linux commands with Windows equivalents and normalizes path separators.
    This allows the AI planner to generate commands in a more OS-agnostic way,
    and the executor will adapt them for the host system.
    """
    import platform # Keep import here for standalone testability
    import re # Keep import here
    normalized_command = command # Start with the original command
    if platform.system() == "Windows":
        # Replace Linux commands with Windows equivalents (using word boundaries)
        normalized_command = re.sub(r'\bls\b', 'dir', normalized_command)
        normalized_command = re.sub(r'\bcp\b', 'copy', normalized_command)
        normalized_command = re.sub(r'\bmv\b', 'move', normalized_command)
        normalized_command = re.sub(r'\brm\b', 'del', normalized_command) # Note: 'del' behavior differs from 'rm'
        # Normalize forward slashes to backslashes for Windows cmd.exe compatibility
        normalized_command = normalized_command.replace('/', '\\')
    return normalized_command

if not logger.hasHandlers():
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


# Type hint for the confirmation callback function provided by the UI/caller.
# Expected signature: func(command_string: str) -> bool
ConfirmationCallback = Callable[[str], bool]

# --- Regular Expressions for Argument Validation ---
# Regex for valid Python/Node identifiers (used for project/app names, package names)
# Allows optional scope like @org/package
IDENTIFIER_REGEX = re.compile(r"^(?:@[a-zA-Z0-9_\-]+\/)?[a-zA-Z_][a-zA-Z0-9_\-]*$")
# Regex for potentially multiple package names separated by spaces (for pip/npm install)
PACKAGE_LIST_REGEX = re.compile(r"^(?:(?:@[a-zA-Z0-9_\-]+\/)?[a-zA-Z_][a-zA-Z0-9_\-]+(?:\s+|$))+")
# Regex for safe-looking relative file paths.
# Allows alphanumeric, underscore, hyphen, dot, forward/back slash (normalized later)
# Does NOT allow chars often used in shell injection like ;, &, |, `, $, (, ), <, >
# It also disallows leading/trailing slashes or dots to prevent path traversal.
SAFE_PATH_REGEX = re.compile(r"^(?![\.\/\\])(?!.*[<>:\"|?*])(?!.*[\.\/\\]$)[a-zA-Z0-9_\-\.\/\\]+$")
# Regex for simple table names (for Django inspectdb)
TABLE_NAME_REGEX = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
# Regex for Git branch names (simple version)
GIT_BRANCH_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.\/]+$")
# Regex for Git commit messages (allows most characters, but avoids shell-problematic ones)
GIT_COMMIT_MSG_REGEX = re.compile(r"^[^$]+$")
# Regex for URLs (simplified)
URL_REGEX = re.compile(r"^https?:\/\/[^\s/$.?#].[^\s]*$")
# Regex for locale codes (e.g., fr, en-us)
LOCALE_REGEX = re.compile(r"^[a-z]{2}(?:-[A-Za-z]{2})?$")
# Regex to detect paths that might have been mangled by an LLM, like 'myappmodels.py'
MANGLED_PATH_REGEX = re.compile(r"^[a-zA-Z0-9_]+[a-zA-Z0-9_]+\.[a-zA-Z]+$")
# --- Regex for React component names (PascalCase) ---
REACT_COMPONENT_NAME_REGEX = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
# ---

class CommandExecutor:
    """
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

    """
    def _is_safe_type_command(self, args: List[str]) -> bool:
        """Validates arguments for the 'type' command (Windows)."""
        # The 'type' command is the Windows equivalent of 'cat'.
        # We only allow it to be run on a single, safe file path.
        if len(args) == 1 and not args[0].startswith('-'):
            file_path = args[0]
            # Use the helper for validation
            if self._validate_path_for_command(file_path):
                return True
        logger.warning(f"Blocked unsafe or invalid 'type' command: type {' '.join(args)}")
        return False

    def _validate_path_for_command(self, path_arg: str) -> bool:
        """
        A reusable helper for command validators to check if a path argument is safe.
        Validates a path argument used within a command validator.
        Checks for safe characters and ensures it's within the project root.
        """
        if not isinstance(path_arg, str) or not path_arg:
            logger.warning("Blocked command: Path argument is empty or not a string.")
            return False
        # Use SAFE_PATH_REGEX for character validation
        if not SAFE_PATH_REGEX.match(path_arg):
            logger.warning(f"Blocked command: Path argument '{path_arg}' contains unsafe characters or format.")
            return False
        # Use the main containment check to prevent path traversal.
        if not self._is_path_within_root(path_arg):
            # _is_path_within_root already logs the warning
            return False
        return True

    def __init__(self, project_root_path: str | Path, confirmation_cb: Optional[ConfirmationCallback] = None, stop_event: Optional[threading.Event] = None):
        """
        Initializes the CommandExecutor.

        Args:
            project_root_path: The absolute or relative path to the root directory
                               where commands should be executed.
            confirmation_cb: An optional callback function to request user confirmation
                             before running certain commands. Takes the command string
                             as input and should return True to proceed, False to cancel.

        Raises:
            ValueError: If project_root_path is not provided or invalid.
            FileNotFoundError: If the resolved project_root_path does not exist.
            NotADirectoryError: If the resolved project_root_path is not a directory.
        """
        if not project_root_path:
            raise ValueError("CommandExecutor requires a valid project_root_path.")

        # Resolve the project root path rigorously.
        try:
            # Ensure the path exists before resolving strictly if it's relative
            # This handles cases where the directory might be created later but we need the object now
            # However, for command execution, it MUST exist. Let's keep strict=True for init.
            self.project_root = Path(project_root_path).resolve(strict=True)
            self.initial_project_root = self.project_root # Store the initial root for sandboxing 'cd'
            if not self.project_root.is_dir():
                raise NotADirectoryError(f"Project root path exists but is not a directory: {self.project_root}")
            logger.info(f"CommandExecutor initialized. Effective CWD set to: {self.project_root}")
        except FileNotFoundError:
            logger.error(f"Project root path does not exist: {Path(project_root_path).resolve()}")
            raise
        except Exception as e:
            logger.exception(f"Error resolving project root path '{project_root_path}'.")
            raise ValueError(f"Invalid project root path: {e}") from e
            
        # --- Load Command Blocklist ---
        # If self.blocklist_path is already set (e.g., by a test fixture), use it.
        # Otherwise, default to the standard location. This makes the class more testable.
        if not hasattr(self, 'blocklist_path'):
            self.blocklist_path = Path(__file__).parent / 'command_blocklist.json'

        if self.blocklist_path.exists():
            with open(self.blocklist_path, 'r') as f:
                self.blocklist = json.load(f)
        else:
            self.blocklist = {"command_patterns": []}
            # Only log the warning if we are using the default path.
            if not hasattr(self, 'blocklist_path'):
                logger.warning(f"Command blocklist file not found at {self.blocklist_path}. No commands will be dynamically blocked/substituted by this mechanism.")

        self.confirmation_cb = confirmation_cb
        self.stop_event = stop_event

        # --- Whitelist Configuration ---
        # Structure: command_key: (validator_function, needs_confirmation_check_function)
        # validator_function(args: List[str]) -> bool  -- Returns True if the command's arguments are safe.
        # needs_confirmation_check_function(command_parts: List[str]) -> bool
        self.allowed_commands: Dict[str, Tuple[Callable[[List[str]], bool], Callable[[List[str]], bool]]] = {
            # Python/Pip will be handled specially to use venv if available
            "python": (self._is_safe_python_command, self._needs_confirm_python),
            "py": (self._is_safe_python_command, self._needs_confirm_python), # Alias for Windows
            "python3": (self._is_safe_python_command, self._needs_confirm_python),
            "pip": (self._is_safe_pip_command, self._needs_confirm_pip),
            "pip3": (self._is_safe_pip_command, self._needs_confirm_pip),
            # Framework-specific commands
            "django-admin": (self._is_safe_django_admin, self._needs_confirm_never),
            "gunicorn": (self._is_safe_gunicorn_command, self._needs_confirm_gunicorn),
            # Node.js commands
            "npm": (self._is_safe_npm_command, self._needs_confirm_npm),
            "npx": (self._is_safe_npx_command, self._needs_confirm_never), # Add npx
            "node": (self._is_safe_node_command, self._needs_confirm_never),
            # Basic file system commands
            "mkdir": (self._is_safe_mkdir_command, self._needs_confirm_never),
            "copy": (self._is_safe_copy_move_command, self._needs_confirm_never), # Windows copy
            "cp": (self._is_safe_copy_move_command, self._needs_confirm_never),   # Linux/macOS copy alias
            "move": (self._is_safe_copy_move_command, self._needs_confirm_never), # Windows move
            "mv": (self._is_safe_copy_move_command, self._needs_confirm_never),   # Linux/macOS move alias
            # Basic informational commands (run with shell=True for compatibility)
            "echo": (self._is_safe_echo_command, self._needs_confirm_never),
            "ls": (self._is_safe_ls_dir_command, self._needs_confirm_never), # Linux/macOS
            "dir": (self._is_safe_ls_dir_command, self._needs_confirm_never), # Windows
            "type": (self._is_safe_type_command, self._needs_confirm_never), # Windows
            # Version Control
            "git": (self._is_safe_git_command, self._needs_confirm_git),
            # 'cd' is handled internally, not via subprocess, so not in this dict.
        }

        # --- Django manage.py Specific Configuration ---
        # Subcommands that require confirmation by default
        self.conditional_manage_py: Set[str] = {
            "migrate", "collectstatic", "createsuperuser", "loaddata",
            "changepassword",
            # Removed flush, sqlflush as they are too dangerous
        }
        # Subcommands that are explicitly blocked for security
        self.restricted_manage_py: Set[str] = {
            "dbshell", "shell", "runserver", # Ensure runserver and shell are here
            "sqlsequencereset", "clearsessions", "remove_stale_contenttypes",
            "flush", "sqlflush", # Added flush, sqlflush
            # Add other potentially dangerous commands here
        }
        # Subcommands generally considered safe and don't need confirmation
        self.safe_manage_py: Set[str] = {
            "startapp", "makemigrations", "showmigrations", "sqlmigrate", "check",
            "test", "makemessages", "compilemessages", "dumpdata", "findstatic",
            "diffsettings", "inspectdb", "createcachetable", "version", "help",
            "sendtestemail",
            # Django Extensions (add cautiously)
            "show_urls", "validate_templates", "pipchecker", "print_settings",
            "generateschema", # DRF
            # Add other safe commands as needed
        }
        # --- End Django manage.py Config ---

    def _is_path_within_root(self, path_to_check: str | Path) -> bool:
        """
        Checks if a given path resolves safely and strictly within the project root.
        Prevents path traversal attacks. Accepts relative paths only.

        Args:
            path_to_check: The relative path string or Path object to validate.

        Returns:
            True if the path is safe and within the root, False otherwise.
        """
        try:
            # Convert Path object to string if necessary
            path_str = str(path_to_check) if isinstance(path_to_check, Path) else path_to_check

            # --- Stricter Input Validation ---
            if not path_str or not isinstance(path_str, str):
                logger.warning(f"Path safety check failed: Input path is empty or not a string ('{path_str}').")
                return False
            if Path(path_str).is_absolute():
                logger.warning(f"Path safety check failed: Input path must be relative, but received absolute path ('{path_str}').")
                return False
            if path_str.startswith(os.sep) or (os.altsep and path_str.startswith(os.altsep)):
                logger.warning(f"Path safety check failed: Input path starts with separator ('{path_str}').")
                return False
            if ".." in Path(path_str).parts:
                logger.warning(f"Path safety check failed: Input path contains '..' component ('{path_str}').")
                return False
            # --- End of Stricter Input Validation ---

            # Resolve the path relative to the *current* project root.
            absolute_path = (self.project_root / path_str).resolve()

            # Final crucial check: Ensure the resolved absolute path is within the project root.
            absolute_path.relative_to(self.project_root)

            logger.debug(f"Path safety check passed for '{path_str}' (resolved to '{absolute_path}').")
            return True

        except ValueError as e: # Catches errors from Path(), resolve(), or relative_to()
            logger.warning(f"Path safety check failed: Path resolves outside project root or is invalid. Input: '{path_str}', Error: {e}")
            return False
        except Exception as e: # Catch any other unexpected errors during path manipulation
            logger.error(f"Unexpected error during path safety check for '{path_str}': {e}")
            return False

    # --- Validator Functions (for the `allowed_commands` dictionary) ---

    def _is_safe_python_command(self, args: List[str]) -> bool:
        """Validates arguments for 'python', 'py', 'python3' commands."""
        if not args: return True # Allow just 'python' (e.g., for version check)

        # Allow creating virtual environment relative to project root
        if args == ["-m", "venv", "venv"]:
            return True

        # Allow running manage.py, but delegate to a more specific validator.
        if args and args[0] == "manage.py":
            manage_py_path = self.project_root / "manage.py"
            if not manage_py_path.is_file():
                logger.warning(f"Blocked manage.py command: 'manage.py' not found at {manage_py_path}")
                return False
            return self._is_safe_python_manage_py(args)

        # Allow running specific utility scripts if they are in a 'utils' subdirectory.
        if args and args[0].endswith(".py"):
            # Check if the script is in a "utils" subdirectory.
            # Path(args[0]) will handle both '/' and '\' separators correctly.
            script_path_obj = Path(args[0])
            # Ensure it's a relative path and its first component is 'utils'
            if not script_path_obj.is_absolute() and script_path_obj.parts and script_path_obj.parts[0] == "utils":
                script_path_str = args[0] # Keep original string for validation helper
                script_args = args[1:]
                if self._validate_path_for_command(script_path_str): # _validate_path_for_command uses SAFE_PATH_REGEX and _is_path_within_root
                    # Basic validation on script arguments: avoid shell metacharacters
                    for arg_val in script_args: # Renamed arg to arg_val
                        if any(char_val in arg_val for char_val in ['>', '<', '|', '&', ';', '`', '$', '(', ')', '#']):
                            logger.warning(f"Blocked utility script execution: Argument '{arg_val}' contains potentially unsafe characters.")
                            return False
                    logger.debug(f"Allowing execution of utility script: python {' '.join(args)}")
                    return True
                else:
                    # _validate_path_for_command already logged the reason
                    return False

        # Allow simple, safe checks like getting the version or compiling a file.
        if args == ["--version"]: return True
        if len(args) == 2 and args[0] == "-m" and args[1] == "py_compile":
             logger.warning("Blocked 'python -m py_compile' without file argument.")
             return False
        if len(args) == 3 and args[0] == "-m" and args[1] == "py_compile":
             file_path = args[2]
             # Use the helper for validation
             if self._validate_path_for_command(file_path):
                 return True
             else:
                 # _validate_path_for_command already logged the reason
                 return False
        
        # Allow running simple code strings with '-c', but block potentially harmful modules.
        if len(args) == 2 and args[0] == "-c":
            code_str = args[1]
            # Basic check for obviously harmful patterns in the -c string
            harmful_patterns = ['subprocess', 'os.system', 'shutil', 'requests', 'urllib', 'socket', 'eval', 'exec', 'open(', 'write(', 'import os']
            code_str_lower = code_str.lower()
            if any(pattern in code_str_lower for pattern in harmful_patterns):
                logger.warning(f"Blocked potentially unsafe python -c command: Code contains restricted pattern. Code: {code_str[:100]}...")
                return False
            # Allow simple print/import checks for verification purposes.
            if code_str.strip().startswith(('print(', 'import ')):
                return True

        # Block anything else
        logger.warning(f"Blocked potentially unsafe or unrecognized python command: python {' '.join(args)}")
        return False

    def _is_safe_python_manage_py(self, args: List[str]) -> bool:
        """Validates arguments for 'python manage.py ...'."""
        if not args or args[0] != "manage.py" or len(args) < 2:
            logger.warning(f"Invalid manage.py structure: {args}")
            return False

        sub_command = args[1]
        remaining_args = args[2:]

        # Block explicitly restricted commands
        if sub_command in self.restricted_manage_py:
            logger.warning(f"Blocked restricted manage.py command: {sub_command}")
            return False

        # Check against the lists of safe and conditionally-allowed subcommands.
        if sub_command in self.safe_manage_py or sub_command in self.conditional_manage_py:
            # --- Add specific argument validation ---
            if sub_command == "startapp":
                app_name_to_check = None
                # Allow 'startapp <appname>' or 'startapp <appname> <directory>'
                if len(remaining_args) == 1 and IDENTIFIER_REGEX.match(remaining_args[0]):
                    app_name_to_check = remaining_args[0]
                elif len(remaining_args) == 2 and IDENTIFIER_REGEX.match(remaining_args[0]) and self._validate_path_for_command(remaining_args[1]):
                    # In 'startapp <app_name> <directory>', app_name_to_check is the first argument.
                    # Django creates <directory>/<app_name>.
                    # For the common case 'startapp <app_name>', Django creates a directory <app_name>.
                    app_name_to_check = remaining_args[0]
                else:
                    logger.warning(f"Blocked invalid manage.py startapp arguments: {remaining_args}"); return False
                if app_name_to_check and (self.project_root / app_name_to_check).exists() and not (len(remaining_args) == 2 and self._validate_path_for_command(remaining_args[1])):
                    # This warning applies if 'startapp <app_name>' is used and '<app_name>' dir exists.
                    logger.warning(f"Executing 'manage.py startapp {app_name_to_check}' but directory '{app_name_to_check}' already exists. This often leads to a 'conflicts with existing Python module' error from Django. The planner should ideally use 'startapp' directly without a preceding 'mkdir' for the same app name.")
                return True
            elif sub_command == "makemigrations":
                app_name_arg = None
                allowed_flags = {"--check", "--dry-run", "--noinput", "--empty", "--merge"}
                for arg in remaining_args:
                    if arg.startswith("-"):
                        if arg not in allowed_flags: logger.warning(f"Blocked invalid manage.py {sub_command} flag: {arg}"); return False
                    elif app_name_arg is None:
                        if IDENTIFIER_REGEX.match(arg): app_name_arg = arg
                        else: logger.warning(f"Blocked invalid manage.py {sub_command} app name argument: {arg}"); return False
                    else: logger.warning(f"Blocked manage.py {sub_command}: Too many non-flag arguments."); return False
                return True
            elif sub_command == "sqlmigrate":
                if len(remaining_args) == 2 and IDENTIFIER_REGEX.match(remaining_args[0]) and re.match(r"^[0-9a-zA-Z_]+$", remaining_args[1]): return True
                logger.warning(f"Blocked invalid manage.py sqlmigrate arguments: {remaining_args}"); return False
            elif sub_command == "inspectdb":
                if not remaining_args: return True
                if all(TABLE_NAME_REGEX.match(arg) for arg in remaining_args): return True
                logger.warning(f"Blocked invalid manage.py inspectdb arguments: {remaining_args}"); return False
            elif sub_command == "dumpdata":
                allowed_flags_prefixes = {"--exclude=", "--format=", "--indent=", "--natural-foreign", "--natural-primary", "-e", "-n", "-a"}
                for arg in remaining_args:
                    if arg.startswith("-"):
                        is_allowed_flag = False
                        for prefix in allowed_flags_prefixes:
                            if arg.startswith(prefix): is_allowed_flag = True; break
                        if not is_allowed_flag: logger.warning(f"Blocked invalid manage.py dumpdata flag: {arg}"); return False
                    elif not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?$", arg):
                        logger.warning(f"Blocked invalid manage.py dumpdata argument: {arg}"); return False
                return True
            elif sub_command == "loaddata":
                # Use helper for path validation
                if remaining_args and all(self._validate_path_for_command(arg) for arg in remaining_args): return True
                logger.warning(f"Blocked invalid manage.py loaddata arguments (unsafe path?): {remaining_args}"); return False
            elif sub_command == "createsuperuser":
                allowed_flags = {"--noinput", "--username", "--email"}
                has_noinput = False
                for arg in remaining_args:
                    if arg == "--noinput": has_noinput = True
                    if arg.startswith("--") and arg.split("=")[0] not in allowed_flags: logger.warning(f"Blocked invalid manage.py createsuperuser flag: {arg}"); return False
                if has_noinput: return True
                logger.warning("Blocked interactive 'createsuperuser'. Use '--noinput'."); return False
            elif sub_command == "test":
                allowed_flags = {"-v", "-v0", "-v1", "-v2", "-v3", "--failfast", "--keepdb", "--parallel", "--noinput"}
                test_labels = []
                for arg in remaining_args:
                    if arg.startswith("-"):
                        if arg not in allowed_flags and not arg.startswith("--settings="): logger.warning(f"Blocked invalid manage.py test flag: {arg}"); return False
                    else:
                        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*$", arg): logger.warning(f"Blocked invalid manage.py test label: {arg}"); return False
                        test_labels.append(arg)
                return True
            elif sub_command == "collectstatic":
                allowed_flags = {"--noinput", "--no-input", "--clear", "--dry-run", "--ignore", "--link", "-i", "-n", "-c", "-l"}
                for arg in remaining_args:
                    if arg.startswith("-"):
                        if arg not in allowed_flags and not arg.startswith("--settings="): logger.warning(f"Blocked invalid manage.py collectstatic flag: {arg}"); return False
                    else: logger.warning(f"Blocked manage.py collectstatic with unexpected positional argument: {arg}"); return False
                if sub_command in self.conditional_manage_py and "--noinput" not in remaining_args and "--no-input" not in remaining_args:
                     logger.warning(f"Blocked interactive 'collectstatic'. Use '--noinput'."); return False
                return True
            elif sub_command == "makemessages":
                allowed_flags = {"-l", "-d", "--ignore", "-e", "--no-location", "--no-wrap"}
                locale_found = False
                for i, arg in enumerate(remaining_args):
                    if arg == "-l":
                        if i + 1 < len(remaining_args) and LOCALE_REGEX.match(remaining_args[i+1]): locale_found = True
                        else: logger.warning(f"Blocked invalid manage.py makemessages locale flag usage."); return False
                    elif arg.startswith("-"):
                        flag_base = arg.split("=")[0]
                        if flag_base not in allowed_flags: logger.warning(f"Blocked invalid manage.py makemessages flag: {arg}"); return False
                if not locale_found and "-a" not in remaining_args and "--all" not in remaining_args:
                    logger.warning(f"Blocked manage.py makemessages without locale (-l) or --all (-a) flag."); return False
                return True
            elif sub_command == "compilemessages":
                allowed_flags = {"-l", "--ignore", "-f", "--force"}
                for i, arg in enumerate(remaining_args):
                    if arg == "-l":
                        if i + 1 >= len(remaining_args) or not LOCALE_REGEX.match(remaining_args[i+1]): logger.warning(f"Blocked invalid manage.py compilemessages locale flag usage."); return False
                    elif arg.startswith("-"):
                        flag_base = arg.split("=")[0]
                        if flag_base not in allowed_flags: logger.warning(f"Blocked invalid manage.py compilemessages flag: {arg}"); return False
                return True
            elif sub_command == "findstatic":
                 if not remaining_args: logger.warning("Blocked manage.py findstatic without file arguments."); return False
                 # Use helper for path validation
                 if all(self._validate_path_for_command(arg) for arg in remaining_args): return True
                 logger.warning(f"Blocked invalid manage.py findstatic arguments: {remaining_args}"); return False
            elif sub_command == "check":
                 allowed_flags = {"--deploy", "--tag", "-t"}
                 for arg in remaining_args:
                     if arg.startswith("-"):
                         if arg not in allowed_flags and not arg.startswith("--settings="): logger.warning(f"Blocked invalid manage.py check flag: {arg}"); return False
                     else: # Allow app labels
                         if not IDENTIFIER_REGEX.match(arg): logger.warning(f"Blocked invalid manage.py check app label: {arg}"); return False
                 return True

            # Default allow for other safe/conditional commands (basic check)
            for arg in remaining_args:
                 if arg.startswith("-"): continue # Allow flags for now
                 # Basic check for positional args (identifiers or paths)
                 if not IDENTIFIER_REGEX.match(arg) and not self._validate_path_for_command(arg):
                     logger.warning(f"Blocked manage.py {sub_command}: Argument '{arg}' is not a valid identifier or safe path."); return False
            logger.debug(f"Allowing manage.py command '{sub_command}' with args: {remaining_args}")
            return True
        else:
            # Block any subcommand not explicitly allowed
            logger.warning(f"Blocked unknown or unsafe manage.py command: {sub_command}")
            return False

    def _is_safe_pip_command(self, args: List[str]) -> bool:
        """Validates arguments for 'pip' or 'pip3' commands."""
        if not args: return False # 'pip' alone is not useful here

        # Allow 'pip install -r <requirements_file>'
        if len(args) >= 3 and args[0] == "install" and args[1] == "-r":
            req_file_index = 2
            allowed_pre_r_flags = {"--no-cache-dir"}
            while req_file_index < len(args) and args[req_file_index].startswith('-'): # Allow flags before the file
                 if args[req_file_index] not in allowed_pre_r_flags: logger.warning(f"Blocked 'pip install -r': Unrecognized flag '{args[req_file_index]}'"); return False
                 req_file_index += 1
            if req_file_index >= len(args) or req_file_index != len(args) - 1:
                 logger.warning(f"Blocked 'pip install -r': Incorrect arguments structure."); return False
            req_file = args[req_file_index]
            # Use helper for path validation
            if self._validate_path_for_command(req_file): return True
            else: return False # Validation helper already logged

        # Allow 'pip install <package(s)> [--upgrade]' etc.
        if args and args[0] == "install" and (len(args) == 1 or args[1] != "-r"):
            packages = []
            allowed_flags = {"--upgrade", "--no-cache-dir", "--force-reinstall", "--no-deps", "-U"}
            valid = True
            for arg in args[1:]: # Iterate through arguments after 'install'
                if arg.startswith('-'):
                    if "=" in arg and not arg.startswith(("--index-url=", "--trusted-host=")): logger.warning(f"Blocked 'pip install': Flags with values are generally disallowed ('{arg}')"); valid = False; break
                    if arg not in allowed_flags: logger.warning(f"Blocked 'pip install': Unrecognized flag '{arg}'"); valid = False; break
                else:
                    # Regex to validate package specifiers, e.g., 'django', 'django==4.2', 'package[extra]'
                    pkg_match = re.match(r"^[a-zA-Z0-9_\-\.]+(?:\[[a-zA-Z0-9_\-,]+\])?(?:[<>=!~]=?[0-9a-zA-Z\.\-\_\*]+)?$", arg)
                    if not pkg_match: logger.warning(f"Blocked 'pip install': Argument '{arg}' doesn't look like a safe package specifier."); valid = False; break
                    packages.append(arg)
            if not valid: return False
            if not packages: logger.warning("Blocked 'pip install' with flags but no package names specified."); return False
            return True

        # Allow informational commands.
        if args == ["list"] or args == ["--version"]: return True
        if len(args) == 2 and args[0] == "show" and IDENTIFIER_REGEX.match(args[1]): return True

        # Allow 'pip freeze' (redirection handled elsewhere)
        if args == ["freeze"]: return True

        # Block everything else
        logger.warning(f"Blocked unsafe or unrecognized pip command: pip {' '.join(args)}")
        return False

    def _is_safe_django_admin(self, args: List[str]) -> bool:
        """Validates arguments for the 'django-admin' command."""
        if not args: return False

        # Allow 'django-admin startproject <name> .'
        if len(args) == 3 and args[0] == "startproject" and args[2] == "." and IDENTIFIER_REGEX.match(args[1]): return True
        # Allow 'django-admin startproject <name>'
        elif len(args) == 2 and args[0] == "startproject" and IDENTIFIER_REGEX.match(args[1]): logger.debug(f"Allowing 'django-admin startproject {args[1]}'."); return True
        # Allow 'django-admin startapp <name>' or 'startapp <name> <directory>'
        if len(args) == 2 and args[0] == "startapp" and IDENTIFIER_REGEX.match(args[1]): return True
        elif len(args) == 3 and args[0] == "startapp" and IDENTIFIER_REGEX.match(args[1]) and self._validate_path_for_command(args[2]): return True
        # Allow simple info commands
        if len(args) == 1 and args[0] in ["version", "help"]: return True

        logger.warning(f"Blocked unsafe or unrecognized django-admin command: django-admin {' '.join(args)}")
        return False

    def _is_safe_npm_command(self, args: List[str]) -> bool:
        """Validates arguments for the 'npm' command."""
        if not args: return False

        # Allow 'npm init -y'
        if args == ["init", "-y"]: return True

        # Allow 'npm install' (no args)
        if args == ["install"]: return True

        # Allow 'npm install <package(s)> [--save-dev|--save|--save-optional|-g]'
        if args and args[0] == "install" and len(args) > 1:
            packages = []
            allowed_flags = {"--save-dev", "--save", "--save-optional", "-g", "--no-save", "--save-exact", "--force", "--legacy-peer-deps", "--omit=dev"}
            valid = True
            for arg in args[1:]:
                if arg.startswith('-'): # It's a flag
                    if "=" in arg: logger.warning(f"Blocked 'npm install': Flags with values are currently disallowed ('{arg}')"); valid = False; break
                    if arg not in allowed_flags: logger.warning(f"Blocked 'npm install': Unrecognized flag '{arg}'"); valid = False; break
                else:
                    if not PACKAGE_LIST_REGEX.match(arg): logger.warning(f"Blocked 'npm install': Argument '{arg}' doesn't look like a safe package specifier."); valid = False; break
                    packages.append(arg)
            if not valid: return False
            if not packages: logger.warning("Blocked 'npm install' with flags but no package names."); return False
            return True

        # Allow 'npm run <script_name>' where script_name is simple identifier
        if len(args) >= 2 and args[0] == "run" and IDENTIFIER_REGEX.match(args[1]): # e.g., npm run build
            # Allow common script names like lint, build, test, start, dev
            # For other scripts, ensure no unsafe characters in additional arguments
            # Example: npm run lint -- --fix (args[2:] would be ['--', '--fix'])
            for arg in args[2:]:
                if any(char in arg for char in ['>', '<', '|', '&', ';', '`', '$', '(', ')', '#']):
                    logger.warning(f"Blocked 'npm run': Script argument contains potentially unsafe characters: '{arg}'")
                    return False
            return True
        # Allow 'npm start', 'npm test', 'npm build', 'npm dev' (no additional args for these simple ones)
        if len(args) == 1 and args[0] in ["start", "test", "build", "dev"]: return True

        # Allow 'npm --version' or 'npm -v'
        if args == ["--version"] or args == ["-v"]: return True

        # Allow 'npm list'
        if args == ["list"]: return True

        # Block everything else
        logger.warning(f"Blocked unsafe or unrecognized npm command: npm {' '.join(args)}")
        return False

    def _is_safe_npx_command(self, args: List[str]) -> bool:
        """Validates arguments for the 'npx' command, specifically for create-react-app."""
        if not args: return False

        # Allow 'npx create-react-app .' (target directory is current, which is frontend/)
        # This check is CRITICAL for security and correct operation, ensuring we don't
        # run this command in the wrong directory.
        if args == ["create-react-app", "."] and Path(self.project_root).name == "frontend":
            return True
        # Add other safe npx commands here if needed, e.g., npx some-linter --fix
        # Example:
        # if args and args[0] == "eslint" and all(not any(c in a for c in "&|;$`") for a in args[1:]):
        #     return True

        logger.warning(f"Blocked unsafe or unrecognized npx command: npx {' '.join(args)}")
        return False

    def _is_safe_node_command(self, args: List[str]) -> bool:
        """Validates arguments for the 'node' command."""
        if not args: return False # 'node' alone starts REPL, block for now

        # Allow running a JS file within the project root with safe args
        if args and (args[0].endswith(".js") or args[0].endswith(".mjs") or args[0].endswith(".cjs")):
            script_path = args[0]
            script_args = args[1:]
            # Use helper for validation
            if not self._validate_path_for_command(script_path): return False
            for arg in script_args:
                 if any(char in arg for char in ['>', '<', '|', '&', ';', '`', '$', '(', ')', '#']): logger.warning(f"Blocked 'node': Script argument contains potentially unsafe characters: '{arg}'"); return False
            return True

        # Allow 'node --version' or 'node -v'
        if args == ["--version"] or args == ["-v"]: return True

        # Allow 'node -c <file.js>' or 'node --check <file.js>' for syntax checking
        if len(args) == 2 and (args[0] == "-c" or args[0] == "--check") and \
           (args[1].endswith(".js") or args[1].endswith(".mjs") or args[1].endswith(".cjs")):
            # Use helper for validation
            if self._validate_path_for_command(args[1]): return True
            else: return False

        # Block everything else
        logger.warning(f"Blocked unsafe or unrecognized node command: node {' '.join(args)}")
        return False

    def _is_safe_mkdir_command(self, args: List[str]) -> bool:
        """Validates arguments for the 'mkdir' command."""
        path_part = None
        if len(args) == 2 and args[0] == '-p': path_part = args[1]
        elif len(args) == 1 and not args[0].startswith('-'): path_part = args[0]

        # Use helper for validation
        if path_part and self._validate_path_for_command(path_part):
            return True

        logger.warning(f"Blocked unsafe mkdir command: mkdir {' '.join(args)}")
        return False

    def _is_safe_echo_command(self, args: List[str]) -> bool:
        """Allows simple echo commands, preventing redirection or execution."""
        # This is to allow simple "echo 'message'" for manual verification steps.
        full_command_str = ' '.join(args)
        for arg in args:
            if any(char in arg for char in ['&', ';', '`', '$(']):
                logger.warning(f"Blocked potentially unsafe 'echo' argument containing shell metacharacters: {arg}")
                return False
            if '$' in arg and not re.match(r'^\$?[a-zA-Z_][a-zA-Z0-9_]*$', arg):
                 if '(' in arg or '{' in arg:
                     logger.warning(f"Blocked potentially unsafe 'echo' argument with complex expansion/substitution: {arg}")
                     return False
        return True

    def _is_safe_ls_dir_command(self, args: List[str]) -> bool:
        """Allows simple 'ls' or 'dir' commands with safe flags and optional safe path."""
        allowed_flags = {'-l', '-a', '-h', '-t', '-r', '-d', '-1', '-R', # ls flags
                        '/a', '/b', '/d', '/o', '/p', '/q', '/s', '/t', '/w', '/-c', '/4'} # dir flags
        path_arg = None

        # Handle quoted path argument for dir on Windows, e.g., dir "my folder"
        if platform.system() == "Windows":
            # Check for quoted path first
            if len(args) == 1 and args[0].startswith('"') and args[0].endswith('"'):
                path_arg_quoted = args[0].strip('"')
                if path_arg_quoted.endswith(("\\", "/")): # dir "path\" is invalid
                    logger.warning(f"Blocked 'dir' command: Quoted path '{args[0]}' has trailing slash.")
                    return False
                # Use the helper for validation on the unquoted path
                if self._validate_path_for_command(path_arg_quoted):
                    return True
                return False

        for arg in args:
            if arg.startswith('-') or arg.startswith('/'):
                flag_to_check = arg.lower()
                if flag_to_check not in allowed_flags:
                    logger.warning(f"Blocked potentially unsafe 'ls/dir' flag: {arg}")
                    return False
            elif path_arg is None and arg != '.': # Allow '.' as a path argument
                path_arg = arg
            else:
                logger.warning(f"Blocked potentially unsafe 'ls/dir' command: Multiple path arguments ('{path_arg}', '{arg}')")
                return False

        if path_arg:
            # For Windows 'dir', path should not end with a separator
            if platform.system() == "Windows" and path_arg.endswith(("\\", "/")):
                logger.warning(f"Blocked 'dir' command: Path argument '{path_arg}' has trailing slash.")
                return False
            # Use helper for validation
            if not self._validate_path_for_command(path_arg):
                return False # _validate_path_for_command already logged

        return True

    def _is_safe_copy_move_command(self, args: List[str]) -> bool:
        """Validates arguments for 'copy', 'cp', 'move', 'mv' commands."""
        if len(args) != 2:
            logger.warning(f"Blocked copy/move command: Requires exactly two arguments (source, destination). Got: {args}")
            return False

        source, destination = args[0], args[1]

        # Use helper for path validation
        if not self._validate_path_for_command(source): return False
        if not self._validate_path_for_command(destination): return False

        logger.debug(f"Allowing copy/move command: {' '.join(['copy/move'] + args)}")
        return True

    def _is_safe_git_command(self, args: List[str]) -> bool:
        """Validates arguments for the 'git' command."""
        if not args: return False # 'git' alone is not useful

        sub_command = args[0]
        remaining_args = args[1:]

        # Allow 'git init'
        if sub_command == "init" and not remaining_args: return True

        # Allow 'git add <pathspec>' where pathspec is safe or '.'
        if sub_command == "add":
            if not remaining_args:
                logger.warning("Blocked 'git add' with no pathspec.")
                return False
            for pathspec in remaining_args:
                # Allow '.' for adding all changes
                if pathspec == '.':
                    continue
                # For other paths, remove any surrounding quotes that might have been
                # added by the LLM and then validate the raw path.
                # The execution logic will handle quoting for the shell.
                unquoted_pathspec = pathspec.strip("'\"")
                if not self._validate_path_for_command(unquoted_pathspec):
                    return False  # _validate_path_for_command logs the reason
            return True

        # Allow 'git commit -m "message"'
        if sub_command == "commit":
            m_index = -1
            try:
                m_index = remaining_args.index("-m")
            except ValueError:
                logger.warning("Blocked 'git commit': Missing '-m' flag for message.")
                return False

            if m_index + 1 >= len(remaining_args):
                logger.warning("Blocked 'git commit': Missing message after '-m' flag.")
                return False

            message = remaining_args[m_index + 1]
            if not GIT_COMMIT_MSG_REGEX.match(message):
                logger.warning(f"Blocked 'git commit': Message '{message[:50]}...' contains potentially unsafe characters.")
                return False
            # Allow other simple flags like --allow-empty, --no-edit, -a
            allowed_commit_flags = {"--allow-empty", "--no-edit", "-a"}
            for i, arg in enumerate(remaining_args):
                if i == m_index or i == m_index + 1: # Skip -m and the message itself
                    continue
                if arg.startswith("-") and arg not in allowed_commit_flags:
                    logger.warning(f"Blocked 'git commit': Unrecognized or disallowed flag '{arg}'.")
                    return False
                elif not arg.startswith("-"): # Unexpected positional argument
                    logger.warning(f"Blocked 'git commit': Unexpected positional argument '{arg}'.")
                    return False
            return True
        # Allow 'git status', 'git log' (with simple flags)
        if sub_command in ["status", "log"]:
            allowed_flags = {"-s", "--short", "--oneline", "--graph", "--decorate", "--all"}
            for arg in remaining_args:
                if not arg.startswith("-") or arg not in allowed_flags: logger.warning(f"Blocked 'git {sub_command}' with invalid argument: {arg}"); return False
            return True

        # Allow 'git checkout -b <branch>', 'git checkout <branch>'
        if sub_command == "checkout":
            if len(remaining_args) == 1 and GIT_BRANCH_REGEX.match(remaining_args[0]): return True
            if len(remaining_args) == 2 and remaining_args[0] == "-b" and GIT_BRANCH_REGEX.match(remaining_args[1]): return True
            logger.warning(f"Blocked invalid 'git checkout' arguments: {remaining_args}"); return False

        # Allow 'git merge <branch>'
        if sub_command == "merge":
            if len(remaining_args) == 1 and GIT_BRANCH_REGEX.match(remaining_args[0]): return True
            logger.warning(f"Blocked invalid 'git merge' arguments: {remaining_args}"); return False

        # Allow 'git clone <url>' (URL validation)
        if sub_command == "clone":
            if len(remaining_args) == 1 and URL_REGEX.match(remaining_args[0]): return True
            if len(remaining_args) == 2 and URL_REGEX.match(remaining_args[0]) and remaining_args[1] == ".": return True
            logger.warning(f"Blocked invalid 'git clone' arguments: {remaining_args}"); return False

        # Block 'git push -f' explicitly
        if sub_command == "push" and "-f" in remaining_args or "--force" in remaining_args:
            logger.warning("Blocked 'git push --force'. Use standard push."); return False
        # Allow simple 'git push' or 'git push origin <branch>'
        if sub_command == "push":
            if not remaining_args: return True # git push
            if len(remaining_args) == 2 and remaining_args[0] == "origin" and GIT_BRANCH_REGEX.match(remaining_args[1]): return True
            logger.warning(f"Blocked potentially unsafe 'git push' arguments: {remaining_args}"); return False

        # Block other git commands for now
        logger.warning(f"Blocked unsafe or unrecognized git command: git {' '.join(args)}")
        return False

    def _is_safe_gunicorn_command(self, args: List[str]) -> bool:
        """Validates arguments for the 'gunicorn' command."""
        if not args: return False # 'gunicorn' alone is not useful

        module_variable_arg = None
        allowed_flags = {"--workers", "-w", "--bind", "-b"} # Add other safe flags if needed

        for arg in args:
            if arg.startswith("-"):
                flag_base = arg.split("=")[0]
                if flag_base not in allowed_flags: logger.warning(f"Blocked invalid gunicorn flag: {arg}"); return False
            elif module_variable_arg is None:
                if re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*:[a-zA-Z_][a-zA-Z0-9_]*$", arg): module_variable_arg = arg
                else: logger.warning(f"Blocked invalid gunicorn module:variable argument: {arg}"); return False
            else: logger.warning(f"Blocked gunicorn: Too many positional arguments."); return False

        if module_variable_arg is None: logger.warning("Blocked gunicorn: Missing module:variable argument."); return False
        return True

    # --- Confirmation Check Functions (for the `allowed_commands` dictionary) ---

    def _needs_confirm_never(self, command_parts: List[str]) -> bool: return False
    def _needs_confirm_python(self, command_parts: List[str]) -> bool:
        args = command_parts[1:]
        # Require confirmation for potentially destructive manage.py commands.
        if args and args[0] == "manage.py" and len(args) > 1:
            sub_command = args[1]
            if sub_command in self.conditional_manage_py:
                if sub_command == "createsuperuser" and "--noinput" in args[2:]: return False
                if sub_command == "collectstatic" and ("--noinput" in args[2:] or "--no-input" in args[2:]): return False
                return True
        return False
        
    def _needs_confirm_pip(self, command_parts: List[str]) -> bool:
        args = command_parts[1:]
        # Require confirmation for installing new packages.
        if args and args[0] == "install":
            if len(args) >= 3 and args[1] == "-r": return False
            is_upgrading_pip = any(not arg.startswith('-') and arg.lower() == 'pip' for arg in args[1:])
            if is_upgrading_pip and ("--upgrade" in args or "-U" in args): return False
            if any(not arg.startswith('-') for arg in args[1:]): return True
        return False
    def _needs_confirm_npm(self, command_parts: List[str]) -> bool:
        # Require confirmation for installing new npm packages.
        args = command_parts[1:]
        if args and args[0] == "install" and len(args) > 1:
            if any(not arg.startswith('-') for arg in args[1:]): return True
        return False
    def _needs_confirm_git(self, command_parts: List[str]) -> bool:
        # Require confirmation for commands that change the repository state.
        args = command_parts[1:]
        return args and args[0] in ["commit", "merge", "push", "clone"]
    def _needs_confirm_gunicorn(self, command_parts: List[str]) -> bool: return True


    def _get_venv_executable(self, command_name: str) -> Optional[Path]:
        """Finds the path to an executable inside the project's 'venv'."""
        if command_name in ["python3", "py"]: command_name = "python"
        if command_name == "pip3": command_name = "pip"
        venv_dir = self.project_root / "venv"
        if not venv_dir.is_dir(): logger.debug(f"Venv directory not found at {venv_dir}"); return None
        exe_path = venv_dir / ("Scripts" if platform.system() == "Windows" else "bin") / (f"{command_name}.exe" if platform.system() == "Windows" else command_name)
        if exe_path.is_file() and os.access(exe_path, os.X_OK): logger.debug(f"Found venv executable: {exe_path}"); return exe_path
        else: logger.debug(f"Venv executable not found or not executable at primary path: {exe_path}"); return None # Simplified fallback

    def _get_base_command_key(self, command_part_zero: str) -> str:
        """Gets the lowercased base command name, handling paths/quotes."""
        # This helps identify 'python' even if the command is 'venv/Scripts/python.exe'.
        potential_path = command_part_zero.strip('"\'')
        base_name = Path(potential_path).stem
        if base_name.startswith("python"): return "python"
        if base_name.startswith("pip"): return "pip"
        if base_name == "cp": return "copy"
        if base_name == "mv": return "move"
        return base_name.lower()

    def check_command_for_block(self, command_str: str) -> None:
        """
        Checks the command against the blocklist.
        If a blocked pattern is found, extracts parameters, forms a safe alternative,
        and raises BlockedCommandException.

        Args:
            command_str: The command string to check.

        Raises:
            BlockedCommandException: If the command matches a blocked pattern.
        """
        for pattern_info in self.blocklist.get("command_patterns", []):
            if re.search(pattern_info["blocked_pattern"], command_str):
                safe_alternative = "No specific safe alternative determined."
                description = pattern_info.get("description", "Blocked command pattern matched.")
                param_extraction_regex = pattern_info.get("param_extraction_regex")
                safe_alternative_template = pattern_info.get("safe_alternative_template")

                if param_extraction_regex and safe_alternative_template:
                    param_match = re.search(param_extraction_regex, command_str)
                    if param_match and len(param_match.groups()) > 0:
                        # Assuming the first captured group is the module path
                        module_path = param_match.group(1)
                        # Convert module path like 'auth.urls' to file path 'auth/urls.py'
                        file_path_candidate = Path(module_path.replace('.', '/'))
                        
                        potential_dir = self.project_root / file_path_candidate
                        if potential_dir.is_dir():
                            file_path = str(file_path_candidate / '__init__.py')
                        else:
                            file_path = str(file_path_candidate.with_suffix('.py'))

                        safe_alternative = safe_alternative_template.format(file_path=file_path)

                raise BlockedCommandException(command_str, safe_alternative, description)


    def _parse_windows_command(self, command_str: str) -> List[str]:
        """Parses a Windows command line string respecting quotes."""
        # This is important because Windows paths can contain spaces.
        # Using shlex with posix=False is generally preferred now
        try:
            return shlex.split(command_str, posix=False)
        except ValueError as e:
             logger.warning(f"shlex parsing failed for Windows command '{command_str}': {e}. Falling back to simple split.")
             # Very basic fallback if shlex fails
             return command_str.split()

    def execute(self, command: str) -> CommandResult:
        """
        Executes a command and returns a structured CommandResult object.
        This is a public wrapper around the internal `run_command` method.
        """
        try:
            command_output = self.run_command(command)
            success = command_output['exit_code'] == 0
            structured_error = None # Analysis should happen in ErrorAnalyzer
            return CommandResult(
                success=success,
                exit_code=command_output['exit_code'],
                stdout=command_output['stdout'],
                stderr=command_output['stderr'],
                structured_error=structured_error,
                command_str=command
            )
        except (ValueError, FileNotFoundError, InterruptedError, BlockedCommandException) as validation_error:
            # These are validation or user-interrupt errors, not execution errors.
            # The tests expect these to be raised, so we re-raise them.
            logger.error(f"Command validation/pre-check failed for '{command}': {validation_error}")
            raise
        except Exception as e:
            logger.exception(f"CommandExecutor.execute failed unexpectedly for command: '{command}'")
            return CommandResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                structured_error={"errorType": type(e).__name__, "message": str(e), "stack": []},
                command_str=command
            )

    def run_command(self, command: str) -> 'CommandOutput': # Modified to return CommandOutput object
        """
        Validates and executes a whitelisted shell command within the project root.
        Includes enhanced path validation and normalization.
        Returns: Tuple (status_code, stdout_str, stderr_str)
        """
        trimmed_command = command.strip()
        if not trimmed_command:
            raise ValueError("CommandExecutor: Received empty command.")

        # Normalize command for the current OS BEFORE parsing/validation.
        original_command_for_log = trimmed_command
        normalized_command = normalize_command_for_platform(trimmed_command)
        if normalized_command != original_command_for_log:
            logger.info(f"Normalized command '{original_command_for_log}' to '{normalized_command}' for {platform.system()}.")
            trimmed_command = normalized_command

        # --- Check against command blocklist (after normalization) ---
        try: # This allows us to intercept and replace commands like `python -c "import ..."`
            self.check_command_for_block(trimmed_command)
        except BlockedCommandException as e:
            logger.warning(f"Command '{e.original_command}' blocked. Executing safe alternative: '{e.safe_alternative}'. Reason: {e.description}")
            # Replace the original command with the safe alternative for execution
            trimmed_command = e.safe_alternative
            # Log this substitution so it's clear in the execution flow
            self.log_command_status(e.original_command, success=False, details=f"Blocked. Substituted with: {e.safe_alternative}")
            # Continue to parse and execute the safe_alternative

        # Block redirection and other shell metacharacters. We always use shell=False for security.
        if any(char in trimmed_command for char in ['>', '<', '|', '&', ';', '&&', '||']):
            error_msg = f"Command blocked: Contains shell metacharacters (e.g., >, <, |, &). Command: '{trimmed_command}'"
            logger.error(error_msg)
            self.log_command_status(trimmed_command, success=False, details=error_msg)
            raise ValueError("Commands with shell metacharacters (e.g., >, <, |, &) are not allowed when shell=False.")

        # 1. Parse the command string into a list of arguments.
        try:
            # Use the correct parsing mode for the OS.
            # Always use posix=False for Windows to handle paths correctly,
            # and posix=True for other systems.
            if platform.system() == "Windows": command_parts = shlex.split(trimmed_command, posix=False)
            else: command_parts = shlex.split(trimmed_command, posix=True)
        except ValueError as e:
            error_msg = f"Command parsing failed: {e}. Command: '{trimmed_command}'"
            logger.error(error_msg)
            self.log_command_status(trimmed_command, success=False, details=error_msg)
            raise ValueError(f"Invalid command format: {e}") from e
        if not command_parts:
            error_msg = "Command string resulted in empty parts after parsing."
            self.log_command_status(trimmed_command, success=False, details=error_msg)
            raise ValueError(error_msg)

        main_command_raw = command_parts[0] # Keep this
        args = command_parts[1:]
        command_key_to_check = self._get_base_command_key(main_command_raw)

        # 2. Handle 'cd' internally by changing the executor's CWD, not by spawning a process.
        if command_key_to_check == "cd":
            if not args:
                error_msg = "Command 'cd' requires a target directory."
                self.log_command_status(trimmed_command, success=False, details=error_msg)
                raise ValueError(error_msg)
            if len(args) > 1:
                error_msg = "Command 'cd' takes only one argument."
                self.log_command_status(trimmed_command, success=False, details=error_msg)
                raise ValueError(error_msg)
            
            target_dir = args[0]
            
            try:
                # Resolve the potential new path against the *current* working directory
                potential_new_path = (self.project_root / target_dir).resolve()

                # CRITICAL SECURITY CHECK: Ensure the resolved path is within the initial sandbox.
                # This allows `cd ..` but prevents escaping the original project root.
                potential_new_path.relative_to(self.initial_project_root)

                if not potential_new_path.is_dir():
                    error_msg = f"Target for 'cd' is not a directory: {potential_new_path}"
                    self.log_command_status(trimmed_command, success=False, details=error_msg)
                    raise NotADirectoryError(error_msg)
                
                # If all checks pass, update the current working directory
                self.project_root = potential_new_path
                logger.info(f"Internal 'cd': Changed effective CWD to {self.project_root}")
                self.log_command_status(trimmed_command, success=True); return CommandOutput(command=trimmed_command, exit_code=0, stdout="Changed directory successfully.", stderr="")
            except (ValueError, NotADirectoryError) as cd_e: # ValueError is raised by relative_to()
                error_msg = f"Command 'cd' target '{target_dir}' is invalid or outside project root. Error: {cd_e}"
                self.log_command_status(trimmed_command, success=False, details=error_msg)
                raise ValueError(error_msg) from cd_e

        # Special validation for mkdir to provide better error messages for path traversal.
        if command_key_to_check == "mkdir":
            path_part = None
            args_copy = list(args)
            if '-p' in args_copy:
                args_copy.remove('-p')
            if len(args_copy) == 1:
                path_part = args_copy[0]
            
            if path_part and not self._is_path_within_root(path_part):
                # Raise a specific error for path traversal attempts with mkdir
                error_msg = f"Path traversal detected for mkdir: '{path_part}' resolves outside project root."
                self.log_command_status(trimmed_command, success=False, details=error_msg)
                raise ValueError(error_msg)

        # 3. Validate the command and its arguments against the configured whitelist.
        validator_info = self.allowed_commands.get(command_key_to_check)
        if not validator_info:
            error_msg = f"Command blocked: '{main_command_raw}' (base '{command_key_to_check}') is not in the allowed list."
            self.log_command_status(trimmed_command, success=False, details=error_msg)
            raise ValueError(error_msg)
        validator_func, needs_confirm_func = validator_info

        # --- FIX: Strip quotes from git add pathspecs before validation ---
        if command_key_to_check == "git" and args and args[0] == "add":
            # This addresses an issue where shlex.split on Windows preserves quotes
            # around path arguments, which then causes git to fail.
            for i in range(1, len(args)): # Iterate through args of 'git'
                 # Get the original part from command_parts and modify it
                 original_index = i + 1
                 command_parts[original_index] = command_parts[original_index].strip("'\"")
            # Re-create the args slice for the validator function with the cleaned parts
            args = command_parts[1:]
        # --- END FIX ---

        if not validator_func(args):
            error_msg = f"Command blocked: Arguments for '{main_command_raw}' are invalid or unsafe."
            self.log_command_status(trimmed_command, success=False, details=error_msg)
            raise ValueError(error_msg)
        logger.debug(f"Command validation passed for: {command_parts}")

        # 4. Check for a virtual environment and use its executables if available.
        venv_executable_path: Optional[Path] = None
        # --- FIX #4: Better Venv Fallback & Pre-validation ---
        if command_key_to_check in ["python", "pip", "django-admin", "gunicorn"]:
            venv_executable_path = self._get_venv_executable(command_key_to_check)
            if venv_executable_path:
                logger.info(f"Using venv executable for '{command_key_to_check}': {venv_executable_path}")
                command_parts[0] = str(venv_executable_path)
            else:
                logger.debug(f"Venv executable for '{command_key_to_check}' not found. Checking system PATH.")
                # --- FIX #2: Validate Command EXISTS Before Running ---
                if not shutil.which(command_key_to_check):
                    err_msg = f"Command not found: '{command_key_to_check}' is not in the system's PATH and a venv executable was not found."
                    logger.error(err_msg)
                    self.log_command_status(trimmed_command, success=False, details=err_msg)
                    raise FileNotFoundError(err_msg)

        # 5. Prepare Command (Resolve relative paths to absolute paths for robustness).
        try:
            command_parts = self._resolve_paths_in_command_args(command_parts)
        except Exception as prep_e:
            error_msg = f"Failed to prepare command: {prep_e}"
            self.log_command_status(trimmed_command, success=False, details=error_msg)
            raise RuntimeError(error_msg) from prep_e

        # 6. Prompt the user for confirmation if the command is potentially destructive.
        if needs_confirm_func(command_parts):
            logger.warning(f"Command requires user confirmation: '{trimmed_command}'")
            if self.confirmation_cb:
                try: user_confirmed = self.confirmation_cb(trimmed_command)
                except Exception as cb_e:
                    error_msg = f"Failed to get user confirmation: {cb_e}"
                    self.log_command_status(trimmed_command, success=False, details=error_msg)
                    raise RuntimeError(error_msg) from cb_e
                if not user_confirmed:
                    error_msg = f"Command cancelled by user: '{trimmed_command}'"
                    self.log_command_status(trimmed_command, success=False, details=error_msg)
                    raise InterruptedError(error_msg)
                else: logger.info("User confirmed command execution.")
            else:
                error_msg = f"Confirmation required but unavailable for command: '{trimmed_command}'"
                self.log_command_status(trimmed_command, success=False, details=error_msg)
                raise ValueError(error_msg)

        # Pre-execution Path Validation (Enhanced checks for path arguments).
        for i, arg in enumerate(command_parts):
            if i == 0 or arg.startswith('-'): continue

            is_potential_path = False
            try:
                p = Path(arg)
                if p.is_absolute() or os.sep in arg or (os.altsep and os.altsep in arg) or (p.suffix and len(p.stem) > 0):
                    is_potential_path = True
            except Exception: pass

            # Check for mangled paths like 'myappmodels.py' which lack a separator.
            if is_potential_path:
                if MANGLED_PATH_REGEX.match(arg) and os.sep not in arg and (not os.altsep or os.altsep not in arg):
                    error_msg = f"Command blocked: Argument '{arg}' appears to be a mangled path (missing separator)."
                    logger.error(error_msg)
                    self.log_command_status(trimmed_command, success=False, details=error_msg)
                    raise ValueError(error_msg)

                if not Path(arg).is_absolute():
                    if not self._is_path_within_root(arg):
                        error_msg = f"Command blocked: Argument '{arg}' resolves outside project root."
                        self.log_command_status(trimmed_command, success=False, details=error_msg)
                        raise ValueError(error_msg)

                # For certain commands, ensure the path argument actually exists before running.
                commands_requiring_existing_path = {"type", "py_compile"}
                is_py_compile_check = command_key_to_check == "python" and "-m" in command_parts and "py_compile" in command_parts and i == command_parts.index("py_compile") + 1
                if command_key_to_check == "type" or is_py_compile_check:
                    try:
                        path_obj = Path(arg)
                        expected_path = path_obj.resolve() if path_obj.is_absolute() else (self.project_root / arg).resolve()
                        expected_path.relative_to(self.project_root)
                        if not expected_path.exists():
                            error_msg = f"Command blocked: Required input path not found at '{expected_path}' (from argument '{arg}')"
                            self.log_command_status(trimmed_command, success=False, details=error_msg)
                            raise FileNotFoundError(error_msg)
                    except ValueError as ve:
                        error_msg = f"Command blocked: Argument '{arg}' resolves outside project root after resolving. Error: {ve}"
                        self.log_command_status(trimmed_command, success=False, details=error_msg)
                        raise ValueError(error_msg) from ve
                    except FileNotFoundError: raise
                    except Exception as path_val_e:
                        error_msg = f"Command blocked: Error validating path argument '{arg}': {path_val_e}"
                        self.log_command_status(trimmed_command, success=False, details=error_msg)
                        raise ValueError(error_msg) from path_val_e

        # 7. Execute the Command using subprocess.
        logger.info(f"Executing command: {' '.join(map(shlex.quote, command_parts))} in CWD: {self.project_root}")
        process = None
        stdout_lines: List[str] = []
        stderr_lines: List[str] = []
        try:
            popen_args: List[str] = command_parts
            startupinfo = None; creationflags = 0
            is_windows = platform.system() == "Windows"
            windows_builtins = {"dir", "type", "echo", "copy", "move", "del", "mkdir", "rmdir"}
            if is_windows and command_key_to_check in windows_builtins:
                logger.info(f"Prepending 'cmd /c' for Windows built-in command: {command_key_to_check}")
                # Prepend 'cmd' and '/c' to the beginning of the argument list
                popen_args = ['cmd', '/c'] + popen_args

            if platform.system() == "Windows":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW

            process = subprocess.Popen(
                popen_args, shell=False, cwd=self.project_root,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding=sys.stdout.encoding or 'utf-8', errors='replace', bufsize=1,
                startupinfo=startupinfo, creationflags=creationflags
            )
            
            # --- FIX #3: Check If Process Actually Started ---
            # Give it a moment to start, then check if it has already exited.
            time.sleep(0.1)
            if process.poll() is not None:
                # Process exited immediately, likely due to "command not found" or a quick error.
                returncode = process.returncode
                logger.error(f"Process for command '{trimmed_command}' exited immediately with code {returncode}.")
                # Don't start threads; read streams directly to avoid hanging.
                stdout_full = process.stdout.read() if process.stdout else ""
                stderr_full = process.stderr.read() if process.stderr else ""
                logger.error(f"Immediate exit STDERR: {stderr_full}")
                self.log_command_status(trimmed_command, success=False, details=stderr_full or stdout_full)
                return CommandOutput(command=trimmed_command, exit_code=returncode, stdout=stdout_full, stderr=stderr_full)

            # Read stdout and stderr streams in separate threads to prevent deadlocks.
            def read_stream(stream, output_list, log_prefix, log_level):
                try:
                    if stream:
                        for line in iter(stream.readline, ''):
                            stripped_line = line.strip()
                            logger.log(log_level, f"[{log_prefix}] {stripped_line}")
                            output_list.append(stripped_line)
                        stream.close()
                except Exception as e_thread: logger.error(f"Error reading stream ({log_prefix}): {e_thread}", exc_info=False)

            stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, stdout_lines, "CMD OUT", logging.INFO), daemon=True)
            stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, stderr_lines, "CMD ERR", logging.WARNING), daemon=True)

            log_cmd_str = ' '.join(map(shlex.quote, command_parts))
            # Log the start and end of the command's output for clarity in logs.
            logger.debug(f"--- Command Output Start: {log_cmd_str} ---")
            stdout_thread.start(); stderr_thread.start()

            # --- NEW: Polling loop for responsive stop ---
            while process.poll() is None:
                if self.stop_event and self.stop_event.is_set():
                    logger.warning(f"Stop event received. Terminating process {process.pid} for command: '{trimmed_command}'")
                    # Terminate the process gracefully first
                    process.terminate()
                    try:
                        # Wait for a short period for the process to terminate
                        process.wait(timeout=5)
                        logger.info(f"Process {process.pid} terminated gracefully.")
                    except subprocess.TimeoutExpired:
                        # If it doesn't terminate, kill it
                        logger.warning(f"Process {process.pid} did not terminate gracefully. Killing.")
                        process.kill()
                        process.wait() # Wait for the kill to complete
                    raise InterruptedError(f"Command execution stopped by user: {trimmed_command}")
                time.sleep(0.2) # Poll every 200ms

            # --- END NEW ---

            # The process has finished, join the threads to gather all output
            # --- FIX #1: Add Timeouts to Thread Joins ---
            join_timeout = 60.0 # seconds
            stdout_thread.join(timeout=join_timeout)
            stderr_thread.join(timeout=join_timeout)
            logger.debug(f"--- Command Output End: {log_cmd_str} ---")

            if stdout_thread.is_alive() or stderr_thread.is_alive():
                logger.error(f"Threads for command '{trimmed_command}' did not finish within {join_timeout}s. Process will be killed.")
                if process.poll() is None: process.kill()
                raise TimeoutError(f"Command execution timed out after {join_timeout} seconds: {trimmed_command}")

            return_code = process.returncode
            stdout_full = "\n".join(stdout_lines).strip()
            stderr_full = "\n".join(stderr_lines).strip()

            # Check the command's exit code to determine success or failure.
            if return_code != 0:
                error_msg = f"Command '{log_cmd_str}' failed with exit code {return_code}."
                if stderr_full: error_msg += f"\nStderr:\n{stderr_full}"
                elif stdout_full: error_msg += f"\nStdout:\n{stdout_full}"
                logger.error(error_msg)
                self.log_command_status(trimmed_command, success=False, details=error_msg)
                return CommandOutput(command=trimmed_command, exit_code=return_code, stdout=stdout_full, stderr=stderr_full) # Return failure
            else:
                logger.info(f"Command '{log_cmd_str}' finished successfully.")
                details = stdout_full or "No output."
                if stderr_full: details += f"\nStderr (warnings):\n{stderr_full}"
                self.log_command_status(trimmed_command, success=True, details=details)
                return CommandOutput(command=trimmed_command, exit_code=0, stdout=stdout_full, stderr=stderr_full) # Return success

        except FileNotFoundError:
            err_msg = f"Command not found: '{command_parts[0]}'. Is it installed and in PATH, or is the venv active/correct?"
            logger.error(err_msg)
            self.log_command_status(trimmed_command, success=False, details=err_msg)
            raise FileNotFoundError(err_msg) from None
        except InterruptedError:
            self.log_command_status(trimmed_command, success=False, details="Cancelled by user.")
            raise
        except Exception as e:
            err_msg = f"Unexpected error executing command '{trimmed_command}': {e}"
            logger.exception(err_msg)
            stderr_full = "\n".join(stderr_lines).strip()
            details = f"{err_msg}\nStderr (if available):\n{stderr_full}" if stderr_full else err_msg
            self.log_command_status(trimmed_command, success=False, details=details)
            raise RuntimeError(err_msg) from e
        finally:
            # Ensure the subprocess is terminated if it's still running after completion.
            if process and process.poll() is None:
                try:
                    logger.warning(f"Command '{trimmed_command}' process did not terminate cleanly. Attempting to kill.")
                    process.kill(); process.wait(timeout=2)
                except Exception as kill_e: logger.error(f"Error trying to kill lingering process for command '{trimmed_command}': {kill_e}")


    def log_command_status(self, command: str, success: bool, details: Optional[str] = None):
        """Placeholder for logging command status."""
        # This could be expanded to send status updates to a UI or a more structured log.
        status_str = "SUCCESS" if success else "FAILED"
        log_level = logging.INFO if success else logging.ERROR
        max_details_len = 500
        details_str = (details[:max_details_len] + '...' if details and len(details) > max_details_len else details) or 'N/A'
        logger.log(log_level, f"COMMAND_STATUS: {status_str} | Command: '{command}' | Details: {details_str}")

    def _resolve_paths_in_command_args(self, original_command_parts: List[str]) -> List[str]:
        """
        Resolves potential relative path arguments to absolute paths within the project root.
        This helps ensure that commands which expect full paths (especially when run
        without a shell) receive them correctly.
        """
        if not original_command_parts: return []

        prepared_parts = list(original_command_parts)  # Create a copy
        command_key = self._get_base_command_key(prepared_parts[0])
        is_windows = platform.system() == "Windows"

        is_py_compile = (command_key == "python" and len(prepared_parts) >= 3 and prepared_parts[1] == "-m" and
                         "py_compile" in prepared_parts)

        for i, arg in enumerate(prepared_parts):
            # Skip the command itself and any flags.
            if i == 0 or arg.startswith('-'): continue

            is_potential_path = False
            try:
                p = Path(arg)
                # For React, allow .jsx and .tsx extensions when passed to npm scripts
                if command_key == "npm" and (arg.endswith(".jsx") or arg.endswith(".tsx")):
                    is_potential_path = True # Tentatively allow as a path-like argument for npm
                elif os.sep in arg or (os.altsep and os.altsep in arg) or (p.suffix and len(p.stem) > 0):
                    if SAFE_PATH_REGEX.match(arg): # Ensure it's a safe-looking path first
                        is_potential_path = True
            except Exception:
                pass

            # If the argument looks like a path, attempt to resolve it.
            if is_potential_path:
                is_py_compile_path_arg = is_py_compile and i > 0 and prepared_parts[i-1] == "py_compile"

                if is_py_compile_path_arg:
                    try:
                        if self._is_path_within_root(arg):
                            normalized_relative_path = str(Path(arg)).replace('\\', '/')
                            prepared_parts[i] = normalized_relative_path
                            logger.debug(f"Normalized py_compile path argument '{arg}' to relative: '{prepared_parts[i]}'")
                        else:
                             logger.warning(f"py_compile path '{arg}' is outside root. Using original (will likely fail).")
                    except Exception as norm_e: logger.warning(f"Could not normalize py_compile path '{arg}': {norm_e}. Using original.")
                elif command_key == "npm" and (arg.endswith(".jsx") or arg.endswith(".tsx")):
                    # For npm scripts with .jsx/.tsx, keep them relative if they are safe
                    # The main validation is that they are within the project root (frontend/)
                    try:
                        if self._is_path_within_root(arg): # This ensures it's within project_root (which should be frontend/ for npm)
                            # Keep it as is, npm will handle it relative to its CWD (frontend/)
                            logger.debug(f"Keeping npm script argument '{arg}' as relative path within frontend context.")
                        else:
                            logger.warning(f"npm script argument '{arg}' is outside current project_root. Using original (may fail).")
                    except Exception as npm_path_e:
                        logger.warning(f"Error processing npm path argument '{arg}': {npm_path_e}. Using original.")
                else:
                    try:
                        if not Path(arg).is_absolute() and self._is_path_within_root(arg):
                            absolute_path = (self.project_root / arg).resolve()
                            prepared_parts[i] = str(absolute_path)
                            logger.debug(f"Resolved path argument '{arg}' to absolute: '{prepared_parts[i]}'")
                        elif Path(arg).is_absolute():
                            abs_p = Path(arg).resolve()
                            abs_p.relative_to(self.project_root) # Check if absolute path is within root
                            logger.debug(f"Argument '{arg}' is already absolute and within root.")
                    except ValueError:
                        logger.warning(f"Argument '{arg}' resolved outside project root. Using original.")
                    except Exception as resolve_e:
                        logger.warning(f"Could not resolve path '{arg}': {resolve_e}. Using original.")

        # Special handling for Windows 'dir' command, which doesn't like trailing slashes on paths.
        if is_windows and command_key == "dir":
            for i, arg in enumerate(prepared_parts):
                # Only apply to path arguments, not flags
                if not arg.startswith(('-', '/')) and (os.sep in arg or (os.altsep and os.altsep in arg)):
                    # Remove trailing slash for 'dir' command path arguments on Windows
                    prepared_parts[i] = arg.rstrip(os.sep + (os.altsep or ''))
                    break # Assuming only one path argument for dir after flags

        return prepared_parts

# Example Usage (for standalone testing - requires creating a dummy directory)
if __name__ == "__main__":
    test_dir_name = "executor_test_project"
    test_dir = Path(test_dir_name)
    try:
        test_dir.mkdir(exist_ok=True)
        print(f"Created test directory: {test_dir.resolve()}")

        # Create dummy files for testing 'cd' and path checks
        (test_dir / "subdir").mkdir(exist_ok=True)
        (test_dir / "subdir" / "dummy.txt").touch()
        (test_dir / "requirements.txt").touch()
        (test_dir / "manage.py").touch() # Dummy manage.py for validation tests
        (test_dir / "script.js").touch()
        (test_dir / "my app with spaces").mkdir(exist_ok=True)
        (test_dir / "my app with spaces" / "file in space.txt").touch()


        # --- Test Setup ---
        def confirm_yes(cmd): print(f"CONFIRM? '{cmd}' -> YES"); return True
        def confirm_no(cmd): print(f"CONFIRM? '{cmd}' -> NO"); return False

        executor = CommandExecutor(project_root_path=test_dir_name, confirmation_cb=confirm_yes)
        executor_no_confirm = CommandExecutor(project_root_path=test_dir_name, confirmation_cb=confirm_no)
        executor_no_cb = CommandExecutor(project_root_path=test_dir_name)

        # --- Basic Commands ---
        print("\n--- Testing ls/dir ---")
        executor.run_command("ls -l" if platform.system() != "Windows" else "dir /w")
        print("\n--- Testing dir with spaces ---")
        executor.run_command('dir "my app with spaces"') # Test quoted path for dir

        print("\n--- Testing mkdir ---")
        executor.run_command("mkdir test_subdir_new")

        print("\n--- Testing echo ---")
        executor.run_command("echo Hello World Test")

        print("\n--- Testing cd ---")
        print(f"Current CWD: {executor.project_root}")
        executor.run_command("cd subdir")
        print(f"New CWD: {executor.project_root}")
        executor.run_command("ls" if platform.system() != "Windows" else "dir")
        executor.run_command("cd ..")
        print(f"CWD after 'cd ..': {executor.project_root}")

        # --- Venv related ---
        print("\n--- Testing Venv Creation ---")
        try:
            # Use sys.executable which should be absolute and correctly quoted if needed
            executor.run_command(f'"{sys.executable}" -m venv venv')
        except Exception as e: print(f"Venv creation failed: {e}")

        # --- pip ---
        print("\n--- Testing pip install -r ---")
        try: executor.run_command("pip install -r requirements.txt")
        except Exception as e: print(f"Pip install -r failed: {e}")

        # --- Path Validation Tests ---
        print("\n--- Testing Pre-execution Path Exists Check (type) ---")
        try: executor.run_command("type subdir\\dummy.txt") # Use backslash for Windows
        except Exception as e: print(f"type command failed: {e}")
        print("\n--- Testing Pre-execution Path Does Not Exist Check (type) ---")
        try: executor.run_command("type subdir\\nonexistent.txt") # Use backslash for Windows
        except FileNotFoundError as e: print(f"Caught FileNotFoundError (expected): {e}")
        except Exception as e: print(f"type nonexistent failed unexpectedly: {e}")

        print("\n--- Testing Pre-execution Mangled Path Check ---")
        try: executor.run_command("python -m py_compile myappapps.py") # Simulate mangled path
        except ValueError as e: print(f"Caught ValueError (expected): {e}")
        except Exception as e: print(f"Mangled path check failed unexpectedly: {e}")

        # --- Unsafe/Blocked Commands ---
        print("\n--- Testing unsafe path (mkdir) ---")
        try: executor.run_command("mkdir ..\\outside_project") # Use backslash for Windows
        except ValueError as e: print(f"Caught ValueError (expected): {e}")

        print("\n--- Testing unsafe command (rm) ---")
        try: executor.run_command("rm -rf /")
        except ValueError as e: print(f"Caught ValueError (expected): {e}")

        print("\n--- Testing redirection block (echo) ---")
        try: executor.run_command("echo hello > output.txt")
        except ValueError as e: print(f"Caught ValueError (expected): {e}")

        # --- Copy/Move Commands ---
        print("\n--- Testing copy ---")
        try: executor.run_command("copy requirements.txt requirements_copy.txt")
        except Exception as e: print(f"copy failed: {e}")
        print("\n--- Testing move ---")
        try: executor.run_command("move requirements_copy.txt subdir\\requirements_moved.txt") # Use backslash for Windows
        except Exception as e: print(f"move failed: {e}")
        print("\n--- Testing unsafe copy (outside root) ---")
        try: executor.run_command("copy subdir\\requirements_moved.txt ..\\unsafe_copy.txt") # Use backslash for Windows
        except ValueError as e: print(f"Caught ValueError (expected): {e}")


    finally:
        # Clean up the test directory
        import shutil
        if test_dir.exists():
            print(f"\nCleaning up test directory: {test_dir.resolve()}")
            shutil.rmtree(test_dir)
        # pass # Comment out cleanup for inspection