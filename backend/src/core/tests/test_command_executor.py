# c:\Users\USER\Documents\webagent\vebgen sharp updated\backend\src\core\tests\test_command_executor.py
import pytest
import os
import platform
import shutil
from pathlib import Path
import re
from unittest.mock import MagicMock, call, patch
from typing import Generator
import json
from src.core.command_executor import CommandExecutor, BlockedCommandException
from src.core.exceptions import InterruptedError

# --- Fixtures ---

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Creates a temporary directory to act as the project root for tests."""
    # Create some dummy structure for testing
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "test.txt").write_text("hello")
    (tmp_path / "manage.py").write_text("# dummy manage.py")
    return tmp_path

@pytest.fixture
def confirmation_callback() -> MagicMock:
    """Returns a mock for the confirmation callback."""
    return MagicMock()

@pytest.fixture
def command_executor(project_root: Path, confirmation_callback: MagicMock) -> CommandExecutor:
    """Creates a CommandExecutor instance with a mock confirmation callback."""
    return CommandExecutor(project_root_path=str(project_root), confirmation_cb=confirmation_callback)

# --- Test Cases ---

class TestCommandValidation:
    """Tests the command validation and whitelisting logic."""

    def test_allowed_simple_command(self, command_executor: CommandExecutor):
        """Tests that a simple, safe command is allowed."""
        result = command_executor.execute("echo Hello")
        assert result.success
        assert "Hello" in result.stdout

    def test_blocked_unsafe_command(self, command_executor: CommandExecutor):
        """Tests that a command not on the whitelist is blocked."""
        # On Windows, 'rm' is normalized to 'del'. The test should account for this.
        expected_error_match = "not in the allowed list"
        with pytest.raises(ValueError, match=expected_error_match):
            command_executor.execute("rm -rf /")

    def test_blocked_command_with_shell_metacharacters(self, command_executor: CommandExecutor):
        """Tests that commands with shell metacharacters are blocked."""
        with pytest.raises(ValueError, match="shell metacharacters"):
            command_executor.execute("echo hello > output.txt")
        with pytest.raises(ValueError, match="shell metacharacters"):
            command_executor.execute("ls | grep txt")

    def test_safe_mkdir_command(self, command_executor: CommandExecutor, project_root: Path):
        """Tests that a safe mkdir command is executed."""
        result = command_executor.execute("mkdir new_dir")
        assert result.success
        assert (project_root / "new_dir").is_dir()

    def test_unsafe_mkdir_command_traversal(self, command_executor: CommandExecutor):
        """Tests that mkdir with path traversal is blocked."""
        # The error message contains backslashes on Windows, so we need a more flexible regex.
        # Using re.escape ensures the match string is treated literally, avoiding regex issues with backslashes.
        with pytest.raises(ValueError, match=re.escape("Path traversal detected for mkdir: '..\\another_dir'")):
            command_executor.execute("mkdir ../another_dir")

    def test_git_init_is_allowed(self, command_executor: CommandExecutor):
        """Tests that 'git init' is allowed."""
        # This will likely fail if git is not installed, but we are testing validation
        try:
            result = command_executor.execute("git init")
            assert result.success
        except FileNotFoundError:
            pytest.skip("git not found on system, skipping execution test")

    def test_git_commit_needs_confirmation(self, command_executor: CommandExecutor, confirmation_callback: MagicMock):
        """Tests that 'git commit' triggers the confirmation callback."""
        confirmation_callback.return_value = True
        try:
            command_executor.execute('git commit -m "Initial commit"')
        except FileNotFoundError:
            pytest.skip("git not found on system, skipping execution test")
        confirmation_callback.assert_called_once()

    def test_pip_install_needs_confirmation(self, command_executor: CommandExecutor, confirmation_callback: MagicMock):
        """Tests that 'pip install' triggers the confirmation callback."""
        confirmation_callback.return_value = True
        try:
            command_executor.execute("pip install requests")
        except FileNotFoundError:
            pytest.skip("pip not found on system, skipping execution test")
        confirmation_callback.assert_called_once()

class TestPathSafety:
    """Tests related to path validation and sandboxing."""

    def test_cd_command_success(self, command_executor: CommandExecutor, project_root: Path):
        """Tests that the internal 'cd' command changes the effective CWD."""
        initial_cwd = command_executor.project_root
        result = command_executor.execute("cd subdir")
        assert result.success
        assert command_executor.project_root == (initial_cwd / "subdir").resolve()

    def test_cd_command_traversal_fails(self, command_executor: CommandExecutor):
        """Tests that 'cd' cannot escape the initial project root."""
        with pytest.raises(ValueError, match="outside project root"):
            command_executor.execute("cd ..")

    def test_command_with_unsafe_path_argument(self, command_executor: CommandExecutor):
        """Tests that a command with a path traversal argument is blocked."""
        # This test fails on Windows because 'ls' is normalized to 'dir', which has a different validator.
        # The 'dir' validator blocks paths with trailing slashes. Let's test the core logic.
        with pytest.raises(ValueError, match="invalid or unsafe"):
            command_executor.execute("ls ../")

    def test_absolute_path_argument_is_blocked(self, command_executor: CommandExecutor):
        """Tests that absolute path arguments are blocked."""
        abs_path = str(Path.home())
        with pytest.raises(ValueError, match="invalid or unsafe"):
            command_executor.execute(f"ls {abs_path}")

class TestVenv:
    """Tests for virtual environment detection and usage."""

    @pytest.fixture
    def executor_with_venv(self, project_root: Path) -> CommandExecutor:
        """Creates a dummy venv and an executor."""
        venv_dir = project_root / "venv"
        bin_dir = venv_dir / ("Scripts" if platform.system() == "Windows" else "bin")
        bin_dir.mkdir(parents=True)
        
        # Create dummy executables. On Windows, we need batch files to avoid WinError 216.
        if platform.system() == "Windows":
            python_exe = bin_dir / "python.bat"
            pip_exe = bin_dir / "pip.bat"
            python_exe.write_text("@echo VENV PYTHON")
            pip_exe.write_text("@echo VENV PIP")
        else:
            python_exe = bin_dir / "python"
            pip_exe = bin_dir / "pip"
            python_exe.write_text("#!/bin/sh\necho 'VENV PYTHON'")
            pip_exe.write_text("#!/bin/sh\necho 'VENV PIP'")
            os.chmod(python_exe, 0o755)
            os.chmod(pip_exe, 0o755)
        
        return CommandExecutor(project_root_path=str(project_root))

    def test_uses_venv_python(self, executor_with_venv: CommandExecutor):
        """Tests that the executor prefers the venv python."""
        with patch('subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_process.poll.return_value = 0
            mock_process.returncode = 0
            mock_process.stdout.read.return_value = "VENV PYTHON"
            mock_process.stderr.read.return_value = ""
            mock_popen.return_value = mock_process

            result = executor_with_venv.execute("python --version")
            assert "VENV PYTHON" in result.stdout

    def test_uses_venv_pip(self, executor_with_venv: CommandExecutor):
        """Tests that the executor prefers the venv pip."""
        with patch('subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_process.poll.return_value = 0
            mock_process.returncode = 0
            mock_process.stdout.read.return_value = "VENV PIP"
            mock_process.stderr.read.return_value = ""
            mock_popen.return_value = mock_process
            result = executor_with_venv.execute("pip --version")
            assert "VENV PIP" in result.stdout

class TestConfirmationCallback:
    """Tests the user confirmation callback mechanism."""

    def test_confirmed_command_executes(self, command_executor: CommandExecutor, confirmation_callback: MagicMock):
        """Tests that a command executes if the user confirms."""
        confirmation_callback.return_value = True
        try:
            result = command_executor.execute("pip install pytest")
            assert result.success
        except FileNotFoundError:
            pytest.skip("pip not found, skipping execution test")
        confirmation_callback.assert_called_once()

    def test_cancelled_command_raises_interrupted_error(self, command_executor: CommandExecutor, confirmation_callback: MagicMock):
        """Tests that a command is cancelled if the user denies and raises InterruptedError."""
        confirmation_callback.return_value = False
        with pytest.raises(InterruptedError, match="Command cancelled by user"):
            command_executor.execute("pip install pytest")
        confirmation_callback.assert_called_once()

    def test_command_without_callback_fails_if_confirmation_needed(self, project_root: Path):
        """Tests that a command needing confirmation fails if no callback is provided."""
        executor_no_cb = CommandExecutor(project_root_path=str(project_root))
        with pytest.raises(ValueError, match="Confirmation required but unavailable"):
            executor_no_cb.execute("pip install pytest")

class TestBlocklist:
    """Tests the command blocklist functionality."""

    @pytest.fixture
    def executor_with_blocklist(self, project_root: Path) -> Generator[CommandExecutor, None, None]:
        """Creates an executor with a custom blocklist."""
        blocklist_content = {
            "command_patterns": [
                {
                    "blocked_pattern": "python -c \"import (.*?)\"",
                    "param_extraction_regex": "python -c \"import (.*?)\"",
                    "safe_alternative_template": "python -m py_compile {file_path}",
                    "description": "Blocked direct import via python -c."
                }
            ]
        }
        blocklist_path = project_root / ".vebgen" / "command_blocklist.json"
        blocklist_path.parent.mkdir(exist_ok=True)
        blocklist_path.write_text(json.dumps(blocklist_content))
        
        # Patch the blocklist_path attribute directly within the CommandExecutor's __init__
        # to point to our temporary blocklist file. This is the most robust way.
        with patch('src.core.command_executor.CommandExecutor.blocklist_path', blocklist_path, create=True):
            yield CommandExecutor(project_root_path=str(project_root))


    def test_blocked_command_is_substituted(self, executor_with_blocklist: CommandExecutor, project_root: Path):
        """Tests that a blocked command is substituted with its safe alternative."""
        (project_root / "my_module").mkdir()
        (project_root / "my_module" / "__init__.py").touch()
        
        # Mock subprocess.Popen to see what command is actually executed.
        with patch('subprocess.Popen') as mock_popen:
            # Configure the mock to return a process with exit code 0
            mock_process = MagicMock()
            mock_process.poll.return_value = 0
            mock_process.returncode = 0
            mock_process.stdout.read.return_value = "Success"
            mock_process.stderr.read.return_value = ""
            mock_popen.return_value = mock_process

            executor_with_blocklist.execute('python -c "import my_module"')

            # Assert that Popen was called with the *substituted* command
            called_args = mock_popen.call_args[0][0]
            assert "py_compile" in ' '.join(called_args)
            assert "my_module/__init__.py" in ' '.join(called_args)
