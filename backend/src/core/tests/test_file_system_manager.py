# src/core/tests/test_file_system_manager.py
import unittest
import sys
import shutil
from pathlib import Path

# To run these tests, navigate to the 'backend' directory and run:
# python -m unittest discover src/core/tests
# This ensures that 'src' is treated as a top-level package.
 
from src.core.file_system_manager import FileSystemManager

class TestFileSystemManager(unittest.TestCase):
    """
    Unit tests for the FileSystemManager class.
    These tests verify the security sandboxing to ensure that file operations
    are strictly constrained within the project root.
    """

    def setUp(self):
        """
        Set up a temporary, isolated project directory for each test.
        """
        self.test_dir = Path("temp_test_project_for_fs").resolve()
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir()

        # Instantiate the FileSystemManager, pointing it to our safe, temporary directory
        self.fs_manager = FileSystemManager(project_root_path=self.test_dir)
        print(f"\n--- Running test: {self._testMethodName} ---")

    def tearDown(self):
        """
        Clean up the temporary project directory after each test.
        """
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_write_and_read_safe_file(self):
        """
        Verify that writing to and reading from a safe, relative path works correctly.
        """
        relative_path = "safe_dir/my_file.txt"
        content = "This is a test."

        # Write the file
        self.fs_manager.write_file(relative_path, content)

        # Verify the file exists physically
        physical_path = self.test_dir / "safe_dir" / "my_file.txt"
        self.assertTrue(physical_path.is_file())

        # Read the file back and verify content
        read_content = self.fs_manager.read_file(relative_path)
        self.assertEqual(read_content, content)

    def test_block_write_outside_project_root(self):
        """
        Verify that writing to a path outside the project root is blocked.
        """
        # This path attempts to traverse up from the project root
        unsafe_relative_path = "../unsafe_file.txt"
        with self.assertRaises(ValueError) as cm:
            self.fs_manager.write_file(unsafe_relative_path, "This should not be written.")
        
        self.assertIn("resolves outside the project root", str(cm.exception))

    def test_block_read_with_absolute_path(self):
        """
        Verify that reading from an absolute path is blocked.
        """
        # Create a dummy file outside the project root to try to read
        dummy_outside_file = self.test_dir.parent / "dummy_outside.txt"
        dummy_outside_file.write_text("secret")

        absolute_path = str(dummy_outside_file)
        with self.assertRaises(ValueError) as cm:
            self.fs_manager.read_file(absolute_path)
        
        self.assertIn("Absolute paths are not allowed", str(cm.exception))
        
        # Cleanup the dummy file
        dummy_outside_file.unlink()

    def test_create_directory_and_check_existence(self):
        """
        Verify that creating a directory and checking its existence works.
        """
        safe_dir_path = "new_app/templates/new_app"
        self.fs_manager.create_directory(safe_dir_path)

        self.assertTrue(self.fs_manager.dir_exists(safe_dir_path))
        self.assertTrue((self.test_dir / safe_dir_path).is_dir())

    def test_block_directory_creation_outside_root(self):
        """
        Verify that creating a directory outside the project root is blocked.
        """
        unsafe_dir_path = "sub/../../unsafe_dir"
        with self.assertRaises(ValueError) as cm:
            self.fs_manager.create_directory(unsafe_dir_path)
        
        self.assertIn("resolves outside the project root", str(cm.exception))

    def test_delete_file(self):
        """
        Verify that deleting a file works and that deleting a non-existent file doesn't error.
        """
        relative_path = "file_to_delete.txt"
        (self.test_dir / relative_path).write_text("delete me")
        self.assertTrue(self.fs_manager.file_exists(relative_path))

        # Delete the file
        self.fs_manager.delete_file(relative_path)
        self.assertFalse(self.fs_manager.file_exists(relative_path))

        # Deleting again should not raise an error
        try:
            self.fs_manager.delete_file(relative_path)
        except Exception as e:
            self.fail(f"Deleting a non-existent file raised an unexpected exception: {e}")

    def test_get_directory_structure_markdown_exclusion(self):
        """
        Verify that the directory structure markdown excludes common unwanted directories.
        """
        (self.test_dir / ".git").mkdir()
        (self.test_dir / "venv").mkdir()
        (self.test_dir / "subdir").mkdir() # This was missing
        markdown_structure = self.fs_manager.get_directory_structure_markdown()
        self.assertNotIn(".git", markdown_structure)
        self.assertNotIn("venv", markdown_structure)
        self.assertIn("subdir", markdown_structure) # Ensure it still sees valid dirs

if __name__ == '__main__':
    unittest.main()