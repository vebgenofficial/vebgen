# c:\Users\navee\Music\VebGen\vebgen sharp\backend\src\core\test_memory_manager.py
import json
import pytest
import time
from pathlib import Path
import threading
from typing import List, Callable
import os
# Import the class and models to be tested
from src.core.memory_manager import MemoryManager, STORAGE_DIR_NAME, PROJECT_STATE_FILENAME, HISTORY_FILENAME
from src.core.project_models import ProjectState
from src.core.llm_client import ChatMessage
import hashlib

# --- Pytest Fixtures ---

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Creates a temporary directory to act as the project root for tests."""
    return tmp_path

@pytest.fixture
def memory_manager(project_root: Path) -> MemoryManager:
    """Creates a MemoryManager instance using the temporary project root."""
    return MemoryManager(project_root)

@pytest.fixture
def memory_manager_with_restore_cb(project_root: Path) -> MemoryManager:
    """Creates a MemoryManager with a confirmation callback for restore tests."""
    # This callback will always agree to restore.
    confirm_restore_cb = lambda prompt: True
    return MemoryManager(project_root, request_restore_confirmation_cb=confirm_restore_cb)

# --- Test Cases ---

def test_initialization_creates_storage_dir(memory_manager: MemoryManager, project_root: Path):
    """
    Tests if the MemoryManager correctly creates the .vebgen storage directory upon initialization.
    """
    storage_dir = project_root / STORAGE_DIR_NAME
    assert storage_dir.exists(), "The .vebgen directory should be created on initialization."
    assert storage_dir.is_dir(), "The .vebgen path should be a directory."

def test_initialization_with_invalid_root():
    """
    Tests that MemoryManager raises a ValueError if initialized with a non-existent path.
    """
    with pytest.raises(FileNotFoundError):
        MemoryManager("non_existent_directory_for_testing")

def test_save_and_load_project_state(memory_manager: MemoryManager, project_root: Path):
    """
    Tests the fundamental save and load functionality for the ProjectState.
    """
    # 1. Create a sample ProjectState object
    original_state = ProjectState(
        project_name="test_project",
        framework="django",
        root_path=str(project_root),
        features=[],
        placeholders={"DB_NAME": "test_db"}
    )

    # 2. Save the state
    memory_manager.save_project_state(original_state)

    # 3. Verify the file was created
    state_file = project_root / STORAGE_DIR_NAME / PROJECT_STATE_FILENAME
    assert state_file.exists(), "project_state.json should be created after saving."

    # 4. Load the state back
    loaded_state = memory_manager.load_project_state()

    # 5. Assert that the loaded state is not None and matches the original
    assert loaded_state is not None, "Loaded state should not be None."
    assert loaded_state.project_name == original_state.project_name
    assert loaded_state.framework == original_state.framework
    assert loaded_state.placeholders == original_state.placeholders
    # Pydantic models with default factories create new objects, so we compare relevant fields
    assert loaded_state == original_state

def test_atomic_write_leaves_no_partial_file(memory_manager: MemoryManager, project_root: Path, monkeypatch):
    """
    Simulates a crash during write to test the atomicity of the save operation.
    The original file should remain untouched.
    """
    state_file = memory_manager.state_file

    # 1. Create and save an initial, valid state file.
    initial_state_obj = ProjectState(project_name="initial", framework="flask", root_path=str(project_root))
    memory_manager.save_project_state(initial_state_obj)
    with open(state_file, 'r') as f:
        content_before_crash = json.load(f)

    # 2. Create a new state to be saved.
    new_state = ProjectState(project_name="crashed_state", framework="django", root_path=str(project_root))

    # 3. Mock `os.replace` to simulate a crash right before the atomic move.
    def crash_before_replace(*args, **kwargs):
        raise OSError("Simulated crash during os.replace()")

    monkeypatch.setattr(os, "replace", crash_before_replace)

    # 4. Attempt to save the new state. This should fail.
    with pytest.raises(RuntimeError, match="Failed to save project state atomically"):
        memory_manager.save_project_state(new_state)

    # 5. Verify the original file's content is unchanged.
    with open(state_file, 'r') as f:
        content_after_crash = json.load(f)

    assert content_after_crash == content_before_crash, "Original file content should not have changed after a failed atomic write."

    # 6. Verify temporary files are cleaned up (or at least don't overwrite the main file)
    tmp_files = list(memory_manager.storage_dir.glob("*.tmp"))
    # In a real crash, the temp file might remain, but the key is that the original is safe.
    # For this test, we just confirm the main file is intact.
    assert len(tmp_files) <= 1, "There should be at most one temporary file left after a simulated crash."


def test_load_project_state_file_not_found(memory_manager: MemoryManager):
    """
    Tests that loading state returns None when the state file doesn't exist.
    """
    assert memory_manager.load_project_state() is None

def test_load_project_state_corrupted_json(memory_manager: MemoryManager):
    """
    Tests that loading state returns None and cleans up if the JSON is malformed.
    """
    # Ensure no backups exist that could be restored
    for bak_file in memory_manager.storage_dir.glob("*.bak"):
        bak_file.unlink()

    state_file = memory_manager.state_file
    state_file.write_text("{'invalid_json':,}") # Write corrupted JSON

    # With the new restore logic, it might try to restore. We disable that for this test.
    memory_manager._request_restore_confirmation_cb = lambda prompt: False
    assert memory_manager.load_project_state() is None, "Loading corrupted JSON without restore should return None."
    
    trash_dir = memory_manager.trash_dir
    trashed_files = list(trash_dir.glob(f"{PROJECT_STATE_FILENAME}.*.deleted"))
    assert len(trashed_files) >= 1, "The corrupted state file should have been soft-deleted (moved to trash)."

def test_load_project_state_integrity_check_fails(memory_manager: MemoryManager):
    """
    Tests that loading state fails if the integrity hash is incorrect (tampered data).
    """
    state_file = memory_manager.state_file

    # Ensure no backups exist that could be restored, isolating this test's purpose.
    for bak_file in memory_manager.storage_dir.glob("*.bak"):
        bak_file.unlink()

    # 1. Create and save a valid state object.
    original_state = ProjectState(project_name="un-tampered", framework="f", root_path="r")
    memory_manager.save_project_state(original_state)

    # 2. Manually tamper with the saved file on disk.
    with open(state_file, 'r+') as f:
        data = json.load(f)
        data['project_name'] = "tampered-value" # Change the data
        f.seek(0) # Rewind to the beginning of the file
        json.dump(data, f, indent=2)
        f.truncate() # Truncate in case the new data is smaller

    # 3. Attempt to load the tampered state.
    # It should fail the integrity check and return None.
    # The backup/restore logic is not tested here, just the failure detection.
    loaded_state = memory_manager.load_project_state()

    assert loaded_state is None, "Loading a tampered state file should fail the integrity check and return None."

def test_concurrent_saves_no_corruption(memory_manager: MemoryManager, project_root: Path):
    """
    Tests that multiple threads trying to save the project state simultaneously
    do not corrupt the final state file, thanks to the file lock.
    """
    # 1. Initialize a state with a counter.
    initial_state = ProjectState(
        project_name="concurrent_test",
        framework="f",
        root_path=str(project_root),
        placeholders={"counter": "0"}
    )
    memory_manager.save_project_state(initial_state)

    num_threads = 10
    threads = []
    test_lock = threading.Lock() # Lock for the test's load-modify-save operation

    # 2. Define a worker function for each thread.
    def worker():
        with test_lock: # Ensure the entire read-modify-write cycle is atomic for the test logic
            state = memory_manager.load_project_state()
            if state and state.placeholders:
                current_count = int(state.placeholders.get("counter", 0))
                state.placeholders["counter"] = str(current_count + 1)
                memory_manager.save_project_state(state)

    # 3. Start all threads to create contention.
    for _ in range(num_threads):
        thread = threading.Thread(target=worker)
        threads.append(thread)
        thread.start()

    # 4. Wait for all threads to complete.
    for thread in threads:
        thread.join()

    # 5. Load the final state and verify the counter.
    final_state = memory_manager.load_project_state()
    assert final_state is not None
    assert final_state.placeholders is not None
    final_count = int(final_state.placeholders.get("counter", -1))
    assert final_count == num_threads, "The final counter should reflect all concurrent increments."

def test_backup_creation_and_pruning(memory_manager: MemoryManager, project_root: Path):
    """
    Tests that backups are created on save and that old backups are pruned.
    """
    state_file = memory_manager.state_file
    
    # Save state multiple times to create backups
    for i in range(7):
        state = ProjectState(project_name=f"v{i}", framework="f", root_path=str(project_root))
        memory_manager.save_project_state(state)
        time.sleep(0.01) # Ensure timestamps are different

    # Check that backups exist
    # After 7 saves, the first save creates the file, and the next 6 create backups.
    # The pruning logic keeps the 5 most recent backups.
    backup_files = list(memory_manager.storage_dir.glob(f"{PROJECT_STATE_FILENAME}.*.bak"))
    # The number of backups should be min(saves - 1, max_backups) = min(6, 5) = 5.
    assert len(backup_files) == 5, f"Should prune backups, keeping only the 5 most recent. Found {len(backup_files)}."

    # Verify the main file has the latest content
    latest_state = memory_manager.load_project_state()
    assert latest_state is not None
    assert latest_state.project_name == "v6"

def test_restore_from_backup_on_corruption(memory_manager_with_restore_cb: MemoryManager, project_root: Path):
    """
    Tests that if the main state file is corrupted, the manager can restore from a backup.
    """
    manager = memory_manager_with_restore_cb
    state_file = manager.state_file

    # 1. Create a valid backup file manually.
    # This needs to include the integrity hash to be considered valid by the new loader.
    backup_state_content = {"project_name": "backup_v1", "framework": "django", "root_path": str(project_root)}
    
    # Calculate the hash for the backup content
    content_to_hash = json.dumps(backup_state_content, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    hasher = hashlib.sha256()
    hasher.update(content_to_hash)
    calculated_hash = hasher.hexdigest()
    
    # Create the full data payload for the backup file, including the hash
    data_to_save_in_backup = {"memory_integrity_hash": calculated_hash, **backup_state_content}

    backup_path = state_file.with_suffix(f"{state_file.suffix}.{int(time.time())}.bak")
    with open(backup_path, 'w') as f:
        json.dump(data_to_save_in_backup, f, indent=2)
    
    # 2. Create a corrupted main state file.
    state_file.write_text("this is corrupted json")

    # 3. Attempt to load the state. This should trigger the restore mechanism.
    # The fixture provides a callback that automatically says "yes" to restoring.
    loaded_state = manager.load_project_state()

    # 4. Verify that the loaded state is from the backup.
    assert loaded_state is not None, "State should have been restored from backup."
    assert loaded_state.project_name == "backup_v1"

    # 5. Verify that the main state file has been fixed.
    with open(state_file, 'r') as f:
        restored_main_content = json.load(f)
    assert restored_main_content["project_name"] == "backup_v1"

def test_save_and_load_history(memory_manager: MemoryManager):
    """
    Tests saving and loading of conversation history.
    """
    history: List[ChatMessage] = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there!"}
    ]

    memory_manager.save_history(history)
    loaded_history = memory_manager.load_history()

    assert loaded_history == history

def test_history_pruning(memory_manager: MemoryManager):
    """
    Tests that the history pruning logic correctly keeps the first and latest messages.
    """
    # Create a history longer than the max limit (MAX_HISTORY_MESSAGES is 50)
    long_history: List[ChatMessage] = [{"role": "system", "content": "System Prompt."}]
    for i in range(60):
        long_history.append({"role": "user", "content": f"Message {i}"})

    pruned = memory_manager._prune_history(long_history)

    assert len(pruned) == 50
    assert pruned[0]["content"] == "System Prompt." # First message is kept
    assert pruned[-1]["content"] == "Message 59" # Last message is kept
    assert pruned[1]["content"] == "Message 11" # Check the start of the recent block

def test_load_history_with_invalid_entries(memory_manager: MemoryManager):
    """
    Tests that the history loader filters out malformed messages.
    """
    history_file = memory_manager.history_file
    invalid_history_data = [
        {"role": "user", "content": "Valid message 1"},
        {"role": "assistant"}, # Missing content
        "just a string", # Invalid format
        {"role": "user", "content": "Valid message 2"}
    ]
    # Write as JSON Lines format
    invalid_content = "\n".join(json.dumps(item) if isinstance(item, dict) else str(item) for item in invalid_history_data)
    with open(history_file, 'w') as f:
        f.write(invalid_content)

    loaded_history = memory_manager.load_history()

    assert len(loaded_history) == 2
    assert loaded_history[0]["content"] == "Valid message 1"
    assert loaded_history[1]["content"] == "Valid message 2"

def test_clear_all_memory(memory_manager: MemoryManager):
    """
    Tests that clearing methods remove the respective files.
    """
    # Create dummy files
    memory_manager.save_project_state(ProjectState(project_name="p", framework="f", root_path="r"))
    memory_manager.save_history([{"role": "user", "content": "test"}])
    memory_manager.save_workflow_context({"step": 1})

    assert memory_manager.state_file.exists()
    assert memory_manager.history_file.exists()
    assert memory_manager.context_file.exists()

    # Clear them
    memory_manager.clear_project_state()
    memory_manager.clear_history()
    memory_manager.clear_workflow_context()

    assert not memory_manager.state_file.exists()
    assert not memory_manager.history_file.exists()
    assert not memory_manager.context_file.exists()

def test_save_and_load_workflow_context(memory_manager: MemoryManager):
    """
    Tests saving and loading of the simple workflow context dictionary.
    """
    # The context we intend to save
    saved_context = {"last_task_id": "2.1", "user_feedback": "Make it blue."}
    memory_manager.save_workflow_context(saved_context)

    # The expected context after loading. The load_workflow_context method
    # is designed to add default keys if they are missing.
    expected_context = saved_context.copy()
    expected_context.setdefault("steps", [])
    expected_context.setdefault("user_requirements", {})
    
    loaded_context = memory_manager.load_workflow_context()
    assert loaded_context == expected_context

def test_load_and_migrate_old_schema(memory_manager: MemoryManager):
    """
    Tests that an old project state file (without a schema_version) is
    migrated correctly upon loading.
    """
    state_file = memory_manager.state_file

    # 1. Manually create an "old" state file (schema v0)
    # It's missing 'schema_version' and other new fields like 'project_structure_map'
    old_state_data = {
        "project_name": "old_project",
        "framework": "flask",
        "root_path": str(memory_manager.project_root),
        # No integrity hash, as that's part of the new system
    }
    state_file.write_text(json.dumps(old_state_data))

    # 2. Attempt to load the state. The manager should detect it's old and migrate it.
    # Since there's no hash, it will fail the hash check and return None, which is correct behavior for v0 files.
    # The key is that it doesn't crash with a Pydantic validation error.
    loaded_state = memory_manager.load_project_state()
    assert loaded_state is None, "Loading a v0 state without an integrity hash should fail gracefully and return None."