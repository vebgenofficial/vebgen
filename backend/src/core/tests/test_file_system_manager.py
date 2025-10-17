# c:\Users\navee\Music\VebGen\vebgen sharp\backend\src\core\test_file_system_manager.py
import pytest
import textwrap
from pathlib import Path
import hashlib
import os

from src.core.file_system_manager import FileSystemManager
from src.core.exceptions import PatchApplyError

# --- Pytest Fixtures ---

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Creates a temporary directory to act as the project root for tests."""
    return tmp_path

@pytest.fixture
def fs_manager(project_root: Path) -> FileSystemManager:
    """Creates a FileSystemManager instance using the temporary project root."""
    return FileSystemManager(project_root)

# --- Test Cases ---

def test_initialization(project_root: Path):
    """Tests successful initialization."""
    fs = FileSystemManager(project_root)
    assert fs.project_root == project_root.resolve()

def test_initialization_fails_on_non_existent_path():
    """Tests that initialization fails if the root path doesn't exist."""
    with pytest.raises(FileNotFoundError):
        FileSystemManager("non_existent_directory_for_testing")

def test_initialization_fails_on_file_path(project_root: Path):
    """Tests that initialization fails if the root path is a file, not a directory."""
    file_path = project_root / "a_file.txt"
    file_path.touch()
    with pytest.raises(NotADirectoryError):
        FileSystemManager(file_path)


class TestSafePathResolution:
    """Tests for the critical _resolve_safe_path method."""

    def test_resolve_safe_path_success(self, fs_manager: FileSystemManager, project_root: Path):
        """Tests that valid relative paths resolve correctly."""
        safe_path = "app/models.py"
        resolved = fs_manager._resolve_safe_path(safe_path)
        assert resolved == project_root / "app" / "models.py"

    @pytest.mark.parametrize("unsafe_path", [
        "../secrets.txt",
        "app/../../../../etc/passwd",
        "/etc/passwd",
        "C:\\Windows\\System32",
        "app/../secrets.txt",
        "",
        None,
        "app/./../secrets.txt"
    ])
    def test_resolve_safe_path_traversal_fails(self, fs_manager: FileSystemManager, unsafe_path: str):
        """Tests that various path traversal attempts are blocked."""
        with pytest.raises(ValueError):
            fs_manager._resolve_safe_path(unsafe_path)

    def test_resolve_safe_path_with_symlink_outside_root_fails(self, fs_manager: FileSystemManager, project_root: Path):
        """Tests that a symlink pointing outside the project root is blocked."""
        # This test is platform-dependent (symlinks on Windows require admin rights)
        if os.name != 'nt':
            outside_file = project_root.parent / "outside_file.txt"
            outside_file.write_text("sensitive")
            
            symlink_path = project_root / "my_symlink"
            os.symlink(outside_file, symlink_path)

            with pytest.raises(ValueError, match="resolves outside the project root"):
                fs_manager._resolve_safe_path("my_symlink")
            
            outside_file.unlink()
            symlink_path.unlink()
        else:
            pytest.skip("Symlink test skipped on Windows due to permission requirements.")


class TestFileOperations:
    """Tests for read, write, and create directory operations."""

    def test_write_and_read_file(self, fs_manager: FileSystemManager):
        """Tests writing to a file and then reading it back."""
        path = "data/test.txt"
        content = "Hello, Vebgen!"
        fs_manager.write_file(path, content)

        assert fs_manager.file_exists(path)
        read_content = fs_manager.read_file(path)
        assert read_content == content

    def test_write_creates_parent_dirs(self, fs_manager: FileSystemManager, project_root: Path):
        """Tests that write_file automatically creates necessary parent directories."""
        path = "nested/deep/file.txt"
        fs_manager.write_file(path, "content")
        assert (project_root / "nested" / "deep").is_dir()
        assert (project_root / path).is_file()

    def test_read_non_existent_file_fails(self, fs_manager: FileSystemManager):
        """Tests that reading a non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            fs_manager.read_file("non_existent.txt")

    def test_create_directory(self, fs_manager: FileSystemManager, project_root: Path):
        """Tests directory creation."""
        path = "new_app/static/css"
        fs_manager.create_directory(path)
        assert (project_root / path).is_dir()

    def test_file_and_dir_exists(self, fs_manager: FileSystemManager):
        """Tests the file_exists and dir_exists methods."""
        dir_path = "my_dir"
        file_path = "my_dir/my_file.txt"

        assert not fs_manager.dir_exists(dir_path)
        assert not fs_manager.file_exists(file_path)

        fs_manager.write_file(file_path, "data")

        assert fs_manager.dir_exists(dir_path)
        assert fs_manager.file_exists(file_path)
        assert not fs_manager.dir_exists(file_path) # A file is not a dir
        assert not fs_manager.file_exists(dir_path) # A dir is not a file


class TestPatchOperations:
    """Tests for applying patches."""

    def test_apply_patch_success(self, fs_manager: FileSystemManager):
        """Tests a successful patch application."""
        original_content = "line 1\nline 2\nline 3\n"
        file_path = "patch_test.txt"
        fs_manager.write_file(file_path, original_content)

        # The unified diff format requires a single space ' ' for unchanged context lines.
        # The original test was missing these, making the patch invalid.
        patch = textwrap.dedent("""\
--- a/patch_test.txt
+++ b/patch_test.txt
@@ -1,3 +1,4 @@
 line 1
+a new line
 line 2
 line 3
"""
        )
        fs_manager.apply_patch(file_path, patch)

        expected_content = "line 1\na new line\nline 2\nline 3\n"
        read_content = fs_manager.read_file(file_path)
        assert read_content == expected_content

    def test_apply_patch_invalid_format_fails(self, fs_manager: FileSystemManager):
        """Tests that a malformed patch raises an error."""
        fs_manager.write_file("test.txt", "content")
        invalid_patch = "this is not a patch"
        with pytest.raises(PatchApplyError, match="Invalid patch format"):
            fs_manager.apply_patch("test.txt", invalid_patch)

    def test_apply_patch_hunk_fails(self, fs_manager: FileSystemManager):
        """Tests that a patch that doesn't match the content raises an error."""
        fs_manager.write_file("test.txt", "original content")
        
        # This patch expects "line 1", but the file has "original content".
        # It also has no context lines, which the fuzzy patcher should reject.
        mismatched_patch = textwrap.dedent("""\
--- a/test.txt
+++ b/test.txt
@@ -1 +1 @@
-line 1
+line 2
""")
        # With the new fuzzy logic, if a patch has no context lines, the fuzzy patcher
        # will correctly re-raise the original exception from the strict patcher.
        # The test now asserts this expected failure chain.
        with pytest.raises(PatchApplyError, match="No context lines in hunk for fuzzy match"):
            fs_manager.apply_patch("test.txt", mismatched_patch)

    def test_apply_patch_fuzzy_with_indentation(self, fs_manager: FileSystemManager):
        """
        Tests that the fuzzy patch fallback correctly applies a patch while
        preserving indentation, which would fail if context lines were stripped.
        This specifically validates the fix for the fuzzy patch bug.
        """
        # 1. Create a file with significant indentation, like a Python list.
        original_content = textwrap.dedent("""\
            # settings.py
            
            INSTALLED_APPS = [
                'django.contrib.admin',
                'django.contrib.auth',
                'django.contrib.contenttypes',
                'django.contrib.sessions',
                'django.contrib.messages',
                'django.contrib.staticfiles',
            ]
            
            MIDDLEWARE = [
                'django.middleware.security.SecurityMiddleware',
            ]
        """)
        file_path = "settings.py"
        fs_manager.write_file(file_path, original_content)

        # 2. Create a patch with incorrect line numbers to force fuzzy matching.
        # The key is that the context lines have leading whitespace that must be preserved.
        # We set the starting line number to -99 to force the fuzzy match logic.
        patch_with_bad_lines = textwrap.dedent("""\
            --- a/settings.py
            +++ b/settings.py
            @@ -99,4 +99,5 @@
                 'django.contrib.sessions',
                 'django.contrib.messages',
                 'django.contrib.staticfiles',
            +    'corsheaders',
             ]
        """)
        fs_manager.apply_patch(file_path, patch_with_bad_lines)

        # 4. Read the result and verify indentation is preserved.
        read_content = fs_manager.read_file(file_path)
        assert "    'corsheaders'," in read_content, "The new line should be correctly indented."
        assert "    'django.contrib.staticfiles'," in read_content

    def test_fuzzy_patch_rolls_back_on_syntax_error(self, fs_manager: FileSystemManager):
        """
        Tests that a fuzzy patch that introduces a syntax error is automatically rolled back.
        """
        original_content = "def my_function():\n    print('hello')\n"
        file_path = "test.py"
        fs_manager.write_file(file_path, original_content)

        # This patch is intentionally malformed to create a syntax error (missing colon)
        patch_with_syntax_error = textwrap.dedent("""\
            --- a/test.py
            +++ b/test.py
            @@ -1,2 +1,2 @@ 
            -def my_function():
            +def my_function()
             print('hello')
        """)

        with pytest.raises(PatchApplyError, match="Patch created syntax error:"):
            fs_manager.apply_patch(file_path, patch_with_syntax_error)

        read_content = fs_manager.read_file(file_path)
        assert read_content == original_content, "File content should be rolled back to the original after a syntax error."

class TestDeletionAndHashing:
    """Tests for file deletion and hashing."""

    def test_delete_file_soft_deletes(self, fs_manager: FileSystemManager, project_root: Path):
        """Tests that delete_file moves the file to the .vebgen/trash directory."""
        file_path = "to_be_deleted.txt"
        fs_manager.write_file(file_path, "some data")

        assert fs_manager.file_exists(file_path)
        
        fs_manager.delete_file(file_path)

        assert not fs_manager.file_exists(file_path)
        
        trash_dir = project_root / ".vebgen" / "trash"
        assert trash_dir.is_dir()
        
        # Check that a file with the original name exists in the trash --- FIX
        trashed_files = list(trash_dir.glob(f"{file_path}*.deleted"))
        assert len(trashed_files) == 1

    def test_get_file_hash(self, fs_manager: FileSystemManager):
        """Tests the SHA256 file hashing functionality."""
        file_path = "hash_me.txt"
        content = "calculate my hash" # --- FIX added content
        fs_manager.write_file(file_path, content)

        # Known SHA256 hash for "calculate my hash"
        expected_hash = "a406e0d6f2e98bcd4934838120afea3815e18a6dd837f5f123923125acb4fdde"
        
        actual_hash = fs_manager.get_file_hash(file_path)
        assert actual_hash == expected_hash

    def test_get_hash_for_non_existent_file(self, fs_manager: FileSystemManager):
        """Tests that hashing a non-existent file returns None."""
        assert fs_manager.get_file_hash("non_existent.txt") is None

@pytest.mark.asyncio
class TestSnapshotOperations:
    """Tests for the create_snapshot and write_snapshot methods."""

    async def test_create_snapshot_empty_project(self, fs_manager: FileSystemManager):
        """Tests that creating a snapshot of an empty project results in an empty snapshot."""
        snapshot = await fs_manager.create_snapshot()
        assert isinstance(snapshot, dict)
        assert not snapshot, "Snapshot of an empty project should be empty."

    async def test_create_snapshot_with_content(self, fs_manager: FileSystemManager):
        """Tests creating a snapshot with various files and ensuring content and hashes are correct."""
        # 1. Setup initial project state
        fs_manager.write_file("file1.txt", "content1")
        fs_manager.write_file("subdir/file2.py", "content2")
        fs_manager.write_file(".venv/ignored.txt", "ignored")  # Should be ignored
        fs_manager.write_file("file.log", "ignored log")  # Should be ignored
        fs_manager.write_file("__pycache__/cache.pyc", "ignored cache") # Should be ignored

        # 2. Create the snapshot
        snapshot = await fs_manager.create_snapshot()

        # 3. Assertions
        assert len(snapshot) == 2, "Snapshot should contain two files."
        assert "file1.txt" in snapshot
        assert "subdir/file2.py" in snapshot

        # Check content and hash for file1.txt
        assert snapshot["file1.txt"]["content"] == "content1"
        expected_hash1 = hashlib.sha256("content1".encode('utf-8')).hexdigest()
        assert snapshot["file1.txt"]["sha256"] == expected_hash1

        # Check content and hash for file2.py
        assert snapshot["subdir/file2.py"]["content"] == "content2"
        expected_hash2 = hashlib.sha256("content2".encode('utf-8')).hexdigest()
        assert snapshot["subdir/file2.py"]["sha256"] == expected_hash2

    async def test_write_snapshot_restores_state(self, fs_manager: FileSystemManager, project_root: Path):
        """
        An end-to-end test for creating a snapshot, modifying the file system,
        and then writing the snapshot back to restore the original state.
        """
        # 1. Setup initial project state
        fs_manager.write_file("file1.txt", "content1")
        fs_manager.write_file("subdir/file2.py", "content2")

        # 2. Create the snapshot of the original state
        original_snapshot = await fs_manager.create_snapshot()
        assert len(original_snapshot) == 2

        # 3. Modify the file system
        fs_manager.write_file("file1.txt", "modified content")  # Modify a file
        fs_manager.delete_file("subdir/file2.py")  # Delete a file
        fs_manager.write_file("new_file.txt", "this should be deleted")  # Add a new file

        # Verify the modified state
        assert fs_manager.read_file("file1.txt") == "modified content"
        assert not fs_manager.file_exists("subdir/file2.py")
        assert fs_manager.file_exists("new_file.txt")

        # 4. Write the original snapshot back to disk
        await fs_manager.write_snapshot(original_snapshot)

        # 5. Verify the state has been restored
        assert fs_manager.file_exists("file1.txt")
        assert fs_manager.read_file("file1.txt") == "content1", "File content should be restored."
        
        assert fs_manager.file_exists("subdir/file2.py"), "Deleted file should be restored."
        assert fs_manager.read_file("subdir/file2.py") == "content2"

        assert not fs_manager.file_exists("new_file.txt"), "Newly added file should be deleted by write_snapshot."