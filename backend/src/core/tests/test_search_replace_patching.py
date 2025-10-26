# vscode-disable-next-line merge-conflicts
# backend/src/core/test_file_system_manager.py
import pytest
from pathlib import Path
from src.core.file_system_manager import FileSystemManager
from src.core.exceptions import PatchApplyError


@pytest.fixture
def fs_manager(tmp_path: Path) -> FileSystemManager:
    """Provides a FileSystemManager instance sandboxed to a temporary directory."""
    return FileSystemManager(project_root_path=tmp_path)


def test_exact_match(fs_manager: FileSystemManager):
    """Test Layer 1: Exact matching for SEARCH/REPLACE."""
    # Write test file
    fs_manager.write_file("test.py", """def hello():
    return "world"
""")

    # Apply exact patch
    patch = """<<<<<<< SEARCH
def hello():
    return "world"
=======
def hello():
    return "universe"
>>>>>>> REPLACE"""

    fs_manager.apply_patch("test.py", patch)

    result = fs_manager.read_file("test.py")
    assert 'return "universe"' in result


def test_whitespace_insensitive(fs_manager: FileSystemManager):
    """Test Layer 2: Whitespace-insensitive matching."""
    # File has extra spaces
    fs_manager.write_file("test.py", """def   hello():
    return    "world"
""")

    # Patch has different whitespace
    patch = """<<<<<<< SEARCH
def hello():
    return "world"
=======
def hello():
    return "universe"
>>>>>>> REPLACE"""

    fs_manager.apply_patch("test.py", patch)

    result = fs_manager.read_file("test.py")
    assert 'return "universe"' in result


def test_multiple_blocks(fs_manager: FileSystemManager):
    """Test multiple SEARCH/REPLACE blocks in one patch."""
    fs_manager.write_file("settings.py", """DEBUG = True
ALLOWED_HOSTS = []
""")

    patch = """<<<<<<< SEARCH
DEBUG = True
=======
DEBUG = False
>>>>>>> REPLACE

<<<<<<< SEARCH
ALLOWED_HOSTS = []
=======
ALLOWED_HOSTS = ['example.com']
>>>>>>> REPLACE"""

    fs_manager.apply_patch("settings.py", patch)

    result = fs_manager.read_file("settings.py")
    assert "DEBUG = False" in result
    assert "'example.com'" in result


def test_detailed_error_message(fs_manager: FileSystemManager):
    """Test that error messages are helpful when a search block fails to match."""
    fs_manager.write_file("test.py", """def hello():
    return "world"
""")

    # Wrong SEARCH block
    patch = """<<<<<<< SEARCH
def goodbye():
    return "world"
=======
def goodbye():
    return "universe"
>>>>>>> REPLACE"""

    with pytest.raises(PatchApplyError) as exc_info:
        fs_manager.apply_patch("test.py", patch)

    error_msg = str(exc_info.value)
    assert "SearchReplaceNoExactMatch" in error_msg
    assert "similarity:" in error_msg
    assert "Did you mean to match" in error_msg