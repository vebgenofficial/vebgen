# src/core/tests/test_command_executor.py
import unittest
import sys
import os
import platform
import shutil
import time
from pathlib import Path

# To run these tests, navigate to the 'backend' directory and run:
# python -m unittest discover src/core/tests
# This ensures that 'src' is treated as a top-level package.

from src.core.command_executor import CommandExecutor
from src.core.exceptions import BlockedCommandException

class TestCommandExecutor(unittest.TestCase):
    """
    Unit tests for the CommandExecutor class.
    These tests verify the security sandboxing, command whitelisting,
    and path validation features.
    """

    def setUp(self):
        """
        Set up a temporary, isolated project directory for each test.
        This prevents tests from affecting the actual file system.
        """
        self.test_dir = Path("temp_test_project_for_executor").resolve()
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir()

        # Create some dummy files and directories for testing commands like 'ls' and 'cd'
        (self.test_dir / "subdir").mkdir()
        (self.test_dir / "dummy_file.txt").write_text("hello world")

        # Instantiate the CommandExecutor, pointing it to our safe, temporary directory
        self.executor = CommandExecutor(project_root_path=self.test_dir)
        print(f"\n--- Running test: {self._testMethodName} ---")

    def tearDown(self):
        """
        Clean up the temporary project directory after each test.
        """
        if self.test_dir.exists():
            # Add a small delay and retry mechanism for Windows file locking issues
            for _ in range(3):
                try:
                    shutil.rmtree(self.test_dir)
                    break
                except PermissionError:
                    time.sleep(0.1)
            else: # If loop finishes without break
                shutil.rmtree(self.test_dir) # Try one last time and let it fail if it must

    def test_execute_safe_allowed_command(self):
        """
        Verify that a simple, whitelisted command executes successfully.
        """
        command = "dir" if platform.system() == "Windows" else "ls"
        result = self.executor.execute(command)

        self.assertTrue(result.success, f"Command '{command}' should succeed.")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("dummy_file.txt", result.stdout, "Command output should contain the dummy file.")

    def test_block_command_not_in_whitelist(self):
        """
        Verify that a command not on the whitelist is blocked.
        """
        # 'rm' is not in the whitelist (though 'del' is for Windows normalization)
        # A more explicit example is something like 'format' or 'fdisk'
        dangerous_command = "fdisk"
        with self.assertRaises(ValueError) as cm:
            self.executor.execute(dangerous_command)
        self.assertIn("not in the allowed list", str(cm.exception))

    def test_block_path_traversal_attack(self):
        """
        Verify that commands attempting to operate outside the project root are blocked.
        """
        # This command tries to create a directory outside the sandboxed `self.test_dir`
        traversal_command = "mkdir ../evil_dir"
        with self.assertRaises(ValueError) as cm:
            self.executor.execute(traversal_command)
        self.assertIn("outside project root", str(cm.exception))

    def test_block_shell_metacharacters(self):
        """
        Verify that commands with shell redirection or chaining are blocked.
        """
        command_with_redirect = "echo hello > output.txt"
        with self.assertRaises(ValueError) as cm:
            self.executor.execute(command_with_redirect)
        self.assertIn("shell metacharacters", str(cm.exception))

        command_with_pipe = "ls | grep dummy"
        with self.assertRaises(ValueError) as cm:
            self.executor.execute(command_with_pipe)
        self.assertIn("shell metacharacters", str(cm.exception))

    def test_internal_cd_command_works_and_is_sandboxed(self):
        """
        Verify that the internal 'cd' command changes the executor's CWD
        but cannot escape the project root.
        """
        initial_root = self.executor.project_root

        # Test successful cd into a subdirectory
        result = self.executor.execute("cd subdir")
        self.assertTrue(result.success)
        self.assertEqual(self.executor.project_root, (initial_root / "subdir").resolve())

        # Test cd back to the parent
        self.executor.execute("cd ..")
        self.assertEqual(self.executor.project_root, initial_root)

        # Test attempt to cd outside the root
        with self.assertRaises(ValueError) as cm:
            self.executor.execute("cd ..") # We are already at the root, this should fail
        self.assertIn("outside project root", str(cm.exception))
        # Ensure the CWD did not change after the failed attempt
        self.assertEqual(self.executor.project_root, initial_root)

    def test_dynamic_blocklist_interception_and_substitution(self):
        """
        Verify that a command matching a pattern in command_blocklist.json
        is intercepted and replaced with its safe alternative.
        """
        # This command is blocked by the regex in command_blocklist.json
        blocked_command = "python -c \"import importlib; importlib.import_module('my_app.views')\""

        # Create the dummy file that the safe alternative will check
        (self.test_dir / "my_app").mkdir()
        (self.test_dir / "my_app" / "views.py").write_text("print('hello')")

        # The `execute` method should catch the BlockedCommandException and run the safe alternative
        result = self.executor.execute(blocked_command)

        # The command should succeed because the safe alternative (`python -m py_compile ...`) is valid
        self.assertTrue(result.success, "The safe alternative command should have executed successfully.")
        self.assertEqual(result.exit_code, 0)
        # We can't easily check which command was *run*, but we can infer it from the success.
        # A more advanced test could mock subprocess.Popen to see what it was called with.

if __name__ == '__main__':
    unittest.main()