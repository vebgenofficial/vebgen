# src/core/memory_manager.py
import json
import logging
import os
import re # Added for potential future use in cleaning keys
from pathlib import Path
import hashlib
import shutil
import tempfile
import threading
import time
from typing import List, Dict, Any, Optional, cast, Callable
from pydantic import ValidationError, BaseModel

# Import the data models used for state and history
from .project_models import ProjectState, FeatureTask, ProjectStructureMap # Import FeatureTask and ProjectStructureMap
from .llm_client import ChatMessage

logger = logging.getLogger(__name__)

# --- Constants for filenames and directory ---
MAX_HISTORY_MESSAGES = 50 # Max messages in history before pruning
HISTORY_FILENAME = 'conversation_history.jsonl' # File to store chat history as JSON Lines
PROJECT_STATE_FILENAME = 'project_state.json'   # File to store the detailed project state
WORKFLOW_CONTEXT_FILENAME = 'workflow_context.json' # File for non-sensitive workflow state
STORAGE_DIR_NAME = '.vebgen' # Hidden directory within user's project for storing these files

class MemoryManager:
    """
    Manages the persistence of the application's state to the file system.

    This class handles the loading and saving of three key pieces of information,
    all stored within a hidden `.vebgen` directory inside the user's project:
    1.  **Project State**: The complete, detailed state of the project, including
        features, tasks, and configurations. Managed via Pydantic models for robustness. This
        file is automatically backed up before saving to prevent corruption.
    2.  **Conversation History**: The ongoing chat history with the AI agents. This file is
        pruned to a maximum size but is not backed up as it is less critical than the
        project state.
    2.  **Conversation History**: The ongoing chat history with the AI agents.
    3.  **Workflow Context**: Non-sensitive, session-related data like task completion status.

    It is designed to be adaptable to different storage backends in the future.
    """
    def __init__(self,
                 project_root_path: str | Path,
                 storage_backend_type: str = "filesystem",
                 request_restore_confirmation_cb: Optional[Callable[[str], bool]] = None
                 ):
        """
        Initializes the MemoryManager.

        Args:
            project_root_path: The absolute path to the root directory of the user's project.
            storage_backend_type: The type of storage backend to use.
            request_restore_confirmation_cb: A UI callback to ask the user if they want to restore from a backup.
            storage_backend_type: The type of storage backend to use. 
                                  (Currently only "filesystem" is implemented).

        Raises:
            ValueError: If project_root_path is not provided or invalid.
            RuntimeError: If the storage directory cannot be created.
        """
        if not project_root_path:
            raise ValueError("MemoryManager requires a valid project_root_path.")
        self.storage_backend_type = storage_backend_type
        self._request_restore_confirmation_cb = request_restore_confirmation_cb
        if self.storage_backend_type != "filesystem":
            # Placeholder for future NoSQL or other backend integration
            logger.warning(f"Storage backend type '{self.storage_backend_type}' is not yet fully implemented. Using filesystem fallback.")
            self.storage_backend_type = "filesystem"

        # --- Race Condition Lock ---
        self._file_op_lock = threading.Lock()

        try:
            # Resolve the path to an absolute path and ensure it exists and is a directory.
            # `strict=True` is a crucial part of the setup, confirming the sandbox exists.
            self.project_root = Path(project_root_path).resolve(strict=True)
        except FileNotFoundError:
            logger.error(f"MemoryManager init failed: Project root path does not exist: {Path(project_root_path).resolve()}")
            raise

        # Define paths for the storage directory and the files within it.
        # Define paths for the storage directory and the files within it.
        self.storage_dir = self.project_root / STORAGE_DIR_NAME
        self.trash_dir = self.storage_dir / "trash" # Directory for soft-deleted files
        self.history_file = self.storage_dir / HISTORY_FILENAME
        self.state_file = self.storage_dir / PROJECT_STATE_FILENAME
        self.context_file = self.storage_dir / WORKFLOW_CONTEXT_FILENAME # Path for the new context file

        logger.info(f"MemoryManager initialized with backend '{self.storage_backend_type}'.")
        
        # For filesystem backend, ensure storage directory exists.
        # For other backends, this might involve connecting to a database.
        # For filesystem backend, ensure storage directory exists.
        # For other backends, this might involve connecting to a DB.
        # For now, only filesystem logic is present.
        self._ensure_dir_exists()

    def _ensure_dir_exists(self) -> None:
        """
        Ensures the `.vebgen` storage directory exists, creating it if necessary.
        This is a private helper to guarantee a write location for state files.
        """
        try:
            # Create the directory. parents=True creates intermediate dirs if needed.
            # exist_ok=True prevents an error if the directory already exists.
            self.trash_dir.mkdir(parents=True, exist_ok=True)
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Storage directory ensured: {self.storage_dir}")
        except OSError as e:
            logger.exception(f"Failed to create storage directory {self.storage_dir}")
            raise RuntimeError(f"Failed to create storage directory: {e}") from e
        except Exception as e:
             logger.exception(f"Unexpected error creating storage directory {self.storage_dir}")
             raise RuntimeError(f"Unexpected error creating storage directory: {e}") from e

        # A final check to ensure the path is a directory, not a file.
        # Final check to ensure it's actually a directory after creation attempt.
        if not self.storage_dir.is_dir():
             logger.error(f"Storage path exists but is not a directory: {self.storage_dir}")
             raise RuntimeError(f"Storage path exists but is not a directory: {self.storage_dir}")

    def _soft_delete_file(self, file_to_delete: Path):
        """Moves a file to a timestamped location in the trash directory instead of permanently deleting it."""
        if not file_to_delete.exists() or not file_to_delete.is_file():
            return # Nothing to do

        self._ensure_dir_exists() # Ensure trash directory is present
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            trash_filename = f"{file_to_delete.name}.{timestamp}.deleted"
            trash_path = self.trash_dir / trash_filename

            # Ensure the trash filename is unique to prevent overwriting trashed files
            counter = 0
            while trash_path.exists():
                counter += 1
                trash_filename = f"{file_to_delete.name}.{timestamp}_{counter}.deleted"
                trash_path = self.trash_dir / trash_filename

            shutil.move(str(file_to_delete), trash_path)
            logger.info(f"Soft deleted '{file_to_delete.name}' to trash directory as '{trash_path.name}'.")
        except Exception as e:
            logger.exception(f"Failed to soft delete file {file_to_delete}. It might not be recoverable. Error: {e}")

    # --- Conversation History Management ---

    def load_history(self) -> List[ChatMessage]:
        """
        Loads conversation history from the history file (conversation_history.json).
        Performs basic validation on the loaded data.

        Returns:
            A list of ChatMessage dictionaries, or an empty list if the file
            doesn't exist, is invalid, or an error occurs.
        """
        if self.storage_backend_type != "filesystem":
            logger.warning("load_history: Non-filesystem backend not implemented. Returning empty history.")
            return []

        # Ensure the .vebgen directory exists before trying to read from it.
        self._ensure_dir_exists() # Ensure directory exists before reading
        if not self.history_file.exists():
            logger.info(f"History file ({self.history_file.name}) not found. Starting fresh history.")
            return []

        with self._file_op_lock:
            # Handle the edge case where the history file path exists but is a directory.
            if not self.history_file.is_file():
                # Handle case where the path exists but is not a file (e.g., a directory).
                logger.error(f"History storage path exists but is not a file: {self.history_file}. Resetting history.")
                self.clear_history() # Attempt to remove the non-file entry
                return []

            try:
                logger.info(f"Loading conversation history from {self.history_file.name}...")
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    valid_history: List[ChatMessage] = []
                    invalid_count = 0
                    for i, line in enumerate(f):
                        if not line.strip(): continue # Skip empty lines
                        try:
                            msg = json.loads(line)
                            # Check if it's a dict with required string keys 'role' and 'content'.
                            if not (isinstance(msg, dict) and
                            'role' in msg and isinstance(msg['role'], str) and
                            'content' in msg and isinstance(msg['content'], str)):
                                raise ValueError("Invalid message structure")
                            # Create a ChatMessage object, including optional 'name' if valid.
                            chat_msg: ChatMessage = {"role": msg["role"], "content": msg["content"]}
                            if "name" in msg and isinstance(msg["name"], str) and msg["name"]:
                                chat_msg["name"] = msg["name"]
                            valid_history.append(chat_msg)
                        except (json.JSONDecodeError, ValueError) as line_e:
                            # Log invalid entries but don't stop loading valid ones.
                            logger.warning(f"Invalid JSON or message structure on line {i+1} in history file: {line_e}")
                            invalid_count += 1

                if invalid_count > 0:
                    logger.warning(f"Filtered out {invalid_count} invalid entries from history file.")

                logger.info(f"Loaded {len(valid_history)} valid messages from {self.history_file.name}.")
                return valid_history

            except (json.JSONDecodeError, IOError) as e:
                # This might catch a file-level error if the file is not just line-corrupted but fully broken.
                # Handle a corrupted file gracefully by resetting history.
                logger.warning(f"History file ({self.history_file.name}) is unreadable or globally corrupted. Resetting history.", exc_info=True)
                self.clear_history()
                return []
            except Exception as e:
                # Catch other file reading errors and return an empty list for safety.
                # Catch other file reading errors.
                logger.exception(f"Error loading history from {self.history_file.name}")
                # Decide whether to raise or return empty list. Returning empty might be safer for UX.
                # raise RuntimeError(f"Failed to load conversation history: {e}") from e
                return []

    def save_history(self, messages: List[ChatMessage]) -> None:
        """
        Saves the conversation history to the history file (conversation_history.json)
        after pruning it to MAX_HISTORY_MESSAGES.

        Args:
            messages: The list of ChatMessage dictionaries to save.
        """
        if self.storage_backend_type != "filesystem":
            logger.warning("save_history: Non-filesystem backend not implemented. Skipping save.")
            return
        if not isinstance(messages, list):
            logger.error("Attempted to save invalid (non-list) history. Skipping save.")
            return

        # Ensure the .vebgen directory exists before writing.
        self._ensure_dir_exists()
        with self._file_op_lock:
            try:
                # Prune the history before saving.
                pruned_messages = self._prune_history(messages)

                # A final validation check before writing to disk.
                # Filter again just before saving to ensure no invalid items slipped through.
                valid_messages_to_save = [
                    msg for msg in pruned_messages
                    if isinstance(msg, dict) and 'role' in msg and 'content' in msg
                ]
                if len(valid_messages_to_save) != len(pruned_messages):
                     logger.warning(f"Attempted to save history containing invalid items. Filtered {len(pruned_messages) - len(valid_messages_to_save)} items before final save.")

                logger.info(f"Saving {len(valid_messages_to_save)} history messages to {self.history_file.name}...")
                # --- ATOMIC WRITE: Write to a temporary file first ---
                temp_file_path = ""
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, dir=self.storage_dir, suffix=".tmp") as temp_f:
                    temp_file_path = temp_f.name
                    # Write each message as a new line (JSON Lines format)
                    for message in valid_messages_to_save:
                        # Use compact separator for smaller file size
                        temp_f.write(json.dumps(message, ensure_ascii=False, separators=(',', ':')) + '\n')
                
                # --- ATOMIC WRITE: Atomically replace the old file with the new one ---
                if temp_file_path:
                    os.replace(temp_file_path, self.history_file)
                    logger.info(f"History saved successfully to {self.history_file.name}.")
                else:
                    # This case should ideally not be reached.
                    raise RuntimeError("Failed to create a temporary file for saving history.")

            except (OSError, IOError) as e:
                logger.exception(f"Atomic write failed for history file {self.history_file.name}: {e}")

            except Exception as e:
                # Log errors during saving but don't necessarily stop the application.
                # A failure to save history is generally not a fatal error.
                logger.exception(f"Error saving history to {self.history_file.name}")
                # Consider if this should raise an error if saving history is critical.

    def clear_history(self) -> None:
        """Deletes the history file (conversation_history.json)."""
        if self.storage_backend_type != "filesystem":
            logger.warning("clear_history: Non-filesystem backend not implemented. Skipping clear.")
            return
        with self._file_op_lock:
            try:
                self._soft_delete_file(self.history_file)
                logger.info(f"Soft-deleted history file: {self.history_file.name}")
            # Log errors during file deletion but don't make it fatal.
            except OSError as e:
                # Log errors during file deletion.
                logger.exception(f"Error soft-deleting history file {self.history_file.name}")
                raise RuntimeError(f"Failed to clear history: {e}") from e
            except Exception as e:
                 logger.exception(f"Unexpected error clearing history file {self.history_file}")


    def _prune_history(self, messages: List[ChatMessage]) -> List[ChatMessage]:
        """
        Prunes the message history list to MAX_HISTORY_MESSAGES.
        Keeps the first message (often a system prompt) and the most recent messages.

        Args:
            messages: The list of ChatMessage dictionaries.

        Returns:
            The pruned list of ChatMessage dictionaries.
        """
        if len(messages) <= MAX_HISTORY_MESSAGES:
            # No pruning needed if the list is already within the limit.
            return messages

        
        logger.info(f"Pruning history from {len(messages)} to ~{MAX_HISTORY_MESSAGES} messages.")
        # Handle the edge case of an empty list.
        if not messages: return [] # Handle empty list case
        if not messages: 
            return [] # Handle empty list case

        # Calculate how many recent messages to keep (excluding the first one).
        keep_recent_count = MAX_HISTORY_MESSAGES - 1
        # Ensure the count is not negative.
        if keep_recent_count < 0: keep_recent_count = 0 # Ensure non-negative

        # Keep the very first message (index 0).
        first_message = messages[:1]
        # Keep the last 'keep_recent_count' messages.
        recent_messages = messages[-keep_recent_count:]

        pruned = first_message + recent_messages
        logger.debug(f"Pruned history length: {len(pruned)}")
        return pruned

    # --- Backup and Restore Logic ---

    def _create_backup(self, file_path: Path):
        """Creates a timestamped backup of a given file if it exists."""
        if not file_path.exists() or not file_path.is_file():
            return # No file to back up

        try:
            timestamp = int(time.time())
            # Add a counter to the backup name to prevent collisions if saves happen in the same second.
            counter = 0
            backup_path = file_path.with_suffix(f"{file_path.suffix}.{timestamp}_{counter}.bak")
            while backup_path.exists():
                counter += 1
                backup_path = file_path.with_suffix(f"{file_path.suffix}.{timestamp}_{counter}.bak")
            shutil.copy2(file_path, backup_path)
            logger.info(f"Created backup for {file_path.name} at {backup_path.name}")
            self._prune_backups(file_path)
        except Exception as e:
            logger.error(f"Failed to create backup for {file_path.name}: {e}")

    def _prune_backups(self, original_file_path: Path, max_backups: int = 5):
        """Deletes the oldest backups for a file, keeping only the most recent `max_backups`."""
        try:
            backup_pattern = f"{original_file_path.name}.*.bak"
            backups = sorted(
                self.storage_dir.glob(backup_pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )

            if len(backups) > max_backups:
                logger.info(f"Found {len(backups)} backups for {original_file_path.name}. Pruning to keep the latest {max_backups}.")
                for old_backup in backups[max_backups:]:
                    old_backup.unlink()
                    logger.debug(f"Deleted old backup: {old_backup.name}")
        except Exception as e:
            logger.error(f"Failed to prune backups for {original_file_path.name}: {e}")

    def _find_and_restore_backup(self, corrupted_file_path: Path, load_func: Callable[[Path], Optional[BaseModel]]) -> Optional[BaseModel]:
        """Finds the latest valid backup and prompts the user to restore it."""
        backup_pattern = f"{corrupted_file_path.name}.*.bak"
        backups = sorted(self.storage_dir.glob(backup_pattern), key=lambda p: p.stat().st_mtime, reverse=True)

        if not backups:
            logger.warning(f"No backups found for corrupted file {corrupted_file_path.name}.")
            return None

        if self._request_restore_confirmation_cb:
            prompt = (f"The state file '{corrupted_file_path.name}' is corrupted or invalid.\n\n"
                      f"A recent backup was found. Would you like to attempt to restore from it?\n\n"
                      "(If you choose 'No', the corrupted file will be removed and you will start with a fresh state.)")
            if not self._request_restore_confirmation_cb(prompt):
                logger.info("User declined to restore from backup.")
                return None
        else:
            logger.warning("No restore confirmation callback provided. Cannot ask user to restore.")
            return None

        for backup_path in backups:
            logger.info(f"Attempting to restore from backup: {backup_path.name}")
            try:
                loaded_data = load_func(backup_path)
                if loaded_data:
                    shutil.copy2(backup_path, corrupted_file_path)
                    logger.info(f"Successfully restored {corrupted_file_path.name} from {backup_path.name}.")
                    return loaded_data
            except Exception as e:
                logger.warning(f"Backup file {backup_path.name} also failed to load: {e}")

        logger.error("All available backups failed to load.")
        return None

    # --- Project Workflow State Management ---

    def load_project_state(self) -> Optional[ProjectState]:
        """
        Loads the detailed project workflow state from project_state.json.
        Validates the loaded structure using Pydantic models.

        Returns:
            A ProjectState Pydantic model instance if the file exists and is valid, otherwise None.
        """
        if self.storage_backend_type != "filesystem":
            logger.warning("load_project_state: Non-filesystem backend not implemented. Returning None.")
            return None

        # Ensure the .vebgen directory exists before trying to read.
        self._ensure_dir_exists()
        with self._file_op_lock:
            if not self.state_file.exists():
                logger.info(f"Project state file ({self.state_file.name}) not found. No existing state to load.")
                return None # Indicate no existing state
            # Handle the edge case where the path exists but is a directory.
            if not self.state_file.is_file():
                 # Handle case where the path exists but is not a file.
                 logger.error(f"Project state path exists but is not a file: {self.state_file}. Resetting state.")
                 self.clear_project_state()
                 return None

            try:
                logger.info(f"Loading project state from {self.state_file.name}...")
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)

                # Validate that the loaded data is a dictionary.
                if not isinstance(state_data, dict):
                     logger.warning(f"Project state file ({self.state_file.name}) content is invalid (not a dict). Resetting state.")
                     self.clear_project_state()
                     return None

                # --- Data Integrity: Verify SHA-256 hash ---
                stored_hash = state_data.pop("memory_integrity_hash", None)
                if stored_hash is None:
                    logger.warning("Project state file is missing 'memory_integrity_hash'. Treating as invalid.")
                    raise ValidationError.from_exception_data("Missing integrity hash", [{"type": "value_error", "loc": ("memory_integrity_hash",), "msg": "Missing integrity hash"}])

                # Recalculate hash of the remaining data using the same canonical format.
                content_to_hash = json.dumps(state_data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                hasher = hashlib.sha256()
                hasher.update(content_to_hash)
                calculated_hash = hasher.hexdigest()

                if stored_hash != calculated_hash:
                    logger.error(f"Data integrity check FAILED! Project state file may be corrupted or tampered with. Stored: {stored_hash}, Calculated: {calculated_hash}")
                    raise ValidationError.from_exception_data("Integrity hash mismatch", [{"type": "value_error", "loc": ("memory_integrity_hash",), "msg": "Integrity hash mismatch"}])
                
                logger.info("Project state data integrity check passed.")

                # --- Schema Migration ---
                state_data = self._migrate_project_state(state_data)

                try:
                    # Validate the loaded dictionary using the Pydantic model
                    # This will automatically handle missing fields by using their defaults.
                    project_state_model = ProjectState.model_validate(state_data)
                    logger.info(f"Loaded and validated project state from {self.state_file.name} using Pydantic.")

                    # Ensure new fields exist on loaded state
                    # This is a safeguard for older state files that might not have these fields.
                    if not hasattr(project_state_model, 'code_summaries') or project_state_model.code_summaries is None:
                        project_state_model.code_summaries = {}
                    if not hasattr(project_state_model, 'historical_notes') or project_state_model.historical_notes is None:
                        project_state_model.historical_notes = []
                    # Ensure project_structure_map exists
                    if not hasattr(project_state_model, 'project_structure_map') or project_state_model.project_structure_map is None:
                        # If loading an old state, initialize project_structure_map
                        logger.info(f"Initializing 'project_structure_map' for older project state: {self.state_file.name}")
                        project_state_model.project_structure_map = ProjectStructureMap()

                    # Initialize remediation_attempts if loading an older state file.
                    # Initialize remediation_attempts if missing from loaded tasks (using attribute access)
                    for feature in project_state_model.features: # Assuming project_state_model is the loaded state
                        if not hasattr(feature, 'status'): feature.status = "identified" 
                        if not hasattr(feature, 'tasks'): feature.tasks = []
                        for task in feature.tasks:
                            if not hasattr(task, 'remediation_attempts') or task.remediation_attempts is None:
                                task.remediation_attempts = 0
                            if not hasattr(task, 'status'): task.status = "pending" # Default if missing
                    # Return the validated Pydantic model instance
                    return project_state_model
                except ValidationError as e:
                    logger.error(f"Project state file ({self.state_file.name}) failed Pydantic validation. Reason: {e}. Attempting to restore from backup.")
                    restored_state = self._find_and_restore_backup(self.state_file, self._load_state_from_path)
                    if restored_state:
                        return cast(ProjectState, restored_state)
                    else:
                        logger.warning(f"Backup restore failed or was declined. Soft-deleting corrupted state file due to validation error: {e}")
                        self._soft_delete_file(self.state_file)
                        return None

            except json.JSONDecodeError:
                logger.warning(f"Project state file ({self.state_file.name}) corrupted (JSON parse error). Attempting to restore from backup.", exc_info=False)
                restored_state = self._find_and_restore_backup(self.state_file, self._load_state_from_path)
                if restored_state:
                    return cast(ProjectState, restored_state)
                else:
                    logger.warning("Backup restore failed or was declined. Soft-deleting corrupted state file due to JSON decode error.")
                    # Soft delete the corrupted file
                    self._soft_delete_file(self.state_file)
                    return None
            except Exception as e:
                # Catch any other file reading or validation errors.
                # Catch other file reading or validation errors.
                logger.exception(f"Error loading project state from {self.state_file.name}")
                # Return None to indicate failure to load state.
                return None
    # This part is typically within a method that decides to create a NEW project state,

    def _load_state_from_path(self, file_path: Path) -> Optional[ProjectState]:
        """Helper to load and validate a ProjectState from a specific file path."""
        if not file_path.is_file():
            logger.debug(f"Attempted to load state from non-existent file: {file_path}")
            return None
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Perform integrity check on the loaded data, even from a backup.
        stored_hash = data.pop("memory_integrity_hash", None)
        if stored_hash is None:
            logger.warning(f"Backup file {file_path.name} is missing 'memory_integrity_hash'. Treating as invalid.")
            return None

        content_to_hash = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        hasher = hashlib.sha256()
        hasher.update(content_to_hash)
        calculated_hash = hasher.hexdigest()

        if stored_hash != calculated_hash:
            logger.error(f"Data integrity check FAILED for backup file {file_path.name}. Stored: {stored_hash}, Calculated: {calculated_hash}")
            return None

        return ProjectState.model_validate(data) # Validate the remaining data with Pydantic

    def restore_from_latest_backup(self) -> Optional[ProjectState]:
        """
        Finds the most recent, valid backup file, restores it to the main state file,
        and returns the loaded state.
        """
        # Find all backups and sort by modification time, newest first.
        backup_pattern = f"{self.state_file.name}.*.bak"
        backups = sorted(
            self.storage_dir.glob(backup_pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        if not backups:
            logger.warning("Restore requested, but no backup files were found.")
            return None

        # Try each backup in order (newest first)
        for backup_path in backups:
            logger.info(f"Attempting to restore from backup: {backup_path.name}")
            restored_state = self._load_state_from_path(backup_path)
            
            # ✅ FIX: Validate that restored state has actual data
            if restored_state:
                # Check if the backup has meaningful data
                has_data = (restored_state.features or 
                           restored_state.registered_apps or 
                           restored_state.defined_models)
                
                if has_data:
                    # Copy the good backup over the corrupted file
                    shutil.copy2(backup_path, self.state_file) # Overwrite corrupted file with good backup
                    logger.info(f"Successfully restored state with data from {backup_path.name}.")
                    return restored_state
                else:
                    logger.warning(f"Backup {backup_path.name} loaded but is empty. Trying next...")
            else:
                logger.warning(f"Backup {backup_path.name} was invalid or unreadable. Trying next...")
        
        logger.error(f"Restore failed: Found {len(backups)} backup(s), but all are empty or invalid.")
        return None

    def _migrate_project_state(self, state_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Applies sequential migrations to an older project state dictionary in-memory.
        This allows for graceful upgrades as the ProjectState model evolves.
        """
        current_version = state_data.get("schema_version", 0)
        target_version = ProjectState.model_fields["schema_version"].default

        if current_version >= target_version:
            return state_data # No migration needed

        logger.info(f"Migrating project state from version {current_version} to {target_version}...")

        # --- Migration from v0 to v1 ---
        if current_version < 1:
            logger.debug("Applying migration v0 -> v1...")
            # In v1, we formally introduced several fields. This ensures they exist.
            state_data.setdefault('code_summaries', {})
            state_data.setdefault('historical_notes', [])
            state_data.setdefault('project_structure_map', {})
            state_data.setdefault('security_feedback_history', [])
            
            # Ensure tasks have 'remediation_attempts' and 'status'
            for feature in state_data.get('features', []):
                for task in feature.get('tasks', []):
                    task.setdefault('remediation_attempts', 0)
                    task.setdefault('status', 'pending')

        state_data['schema_version'] = target_version
        return state_data
    # often called from WorkflowManager.initialize_project or as a fallback in load_project_state.
    # Let's assume it's part of a hypothetical _create_new_project_state method for illustration.
    # This part is typically within a method that decides to create a NEW project state,
    # often called from WorkflowManager.initialize_project.
    @staticmethod
    def create_new_project_state(project_name_raw: str, framework: str, project_root: str) -> ProjectState:
        """A static factory method to create a new, default ProjectState object."""
        safe_project_name = re.sub(r'\W|^(?=\d)', '_', project_name_raw).lower()
        try:
            # Create a new ProjectState instance, relying on Pydantic to set default values.
            new_state = ProjectState(
                project_name=safe_project_name,
                framework=framework,
                root_path=project_root,
                project_structure_map=ProjectStructureMap(),
                cumulative_docs=f"# {safe_project_name} - Technical Documentation\n\nFramework: {framework}\n",
            )
            logger.info(f"Created new ProjectState in-memory for '{safe_project_name}'.")
            return new_state
        except ValidationError as val_e:
            logger.error(f"Failed to create initial ProjectState model: {val_e}")
            raise RuntimeError(f"Failed to create initial project state: {val_e}") from val_e

    def save_project_state(self, state: ProjectState) -> None:
        """
        Saves the entire project workflow state (as a Pydantic model) to project_state.json.

        Args:
            state: The ProjectState Pydantic model instance to save.

        Raises:
            TypeError: If the provided state is not a ProjectState instance.
            RuntimeError: If saving or serialization fails.
        """

        if self.storage_backend_type != "filesystem":
            logger.warning("save_project_state: Non-filesystem backend not implemented. Skipping save.")
            return

        # Ensure the provided state is a valid Pydantic model instance.
        # Check if the input is a Pydantic ProjectState model instance
        if not isinstance(state, ProjectState):
            logger.error(f"Attempted to save invalid project state (not a ProjectState model): {type(state)}. Skipping save.")
            raise TypeError("Project state must be a Pydantic ProjectState model instance.")

        # ✅ CHECK 1: Don't save if the new state is suspiciously empty and the old one isn't.
        is_new_state_empty = not state.features and not state.registered_apps and not state.defined_models
        if is_new_state_empty:
            # Load the current state from disk to compare.
            current_state_on_disk = self.load_project_state()
            if current_state_on_disk and (current_state_on_disk.features or current_state_on_disk.registered_apps or current_state_on_disk.defined_models):
                logger.error("BLOCKED SAVE: Attempted to save an empty state over a non-empty state. This would destroy project history. Aborting save operation.")
                # --- BUG FIX #9: Raise an exception instead of silently failing ---
                raise ValueError("BLOCKED SAVE: Attempted to save an empty state over a non-empty one, which would cause data loss.")

        # Ensure the .vebgen directory exists before writing.
        self._ensure_dir_exists()
        with self._file_op_lock:
            try:
                # --- Data Integrity: Calculate SHA-256 hash ---
                # 1. Dump model to a JSON-compatible dict. Using mode='json' ensures
                #    that types like `set` are converted to `list` for serialization.
                #    This is the fix for the "Object of type set is not JSON serializable" error.
                state_dict = state.model_dump(mode='json')

                # 2. Serialize to a compact, sorted JSON string for a canonical hash.
                content_to_hash = json.dumps(state_dict, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')

                # 3. Calculate the hash.
                hasher = hashlib.sha256()
                hasher.update(content_to_hash)
                integrity_hash = hasher.hexdigest()

                # 4. Create the final payload including the hash.
                data_to_save = {"memory_integrity_hash": integrity_hash, **state_dict}
                logger.debug(f"Calculated integrity hash for project state: {integrity_hash}")

                # ✅ CHECK 2: Create backup BEFORE saving.
                if self.state_file.exists():
                    self._create_backup(self.state_file)
                    logger.info(f"Created backup before saving new project state.")

                logger.info(f"Saving project state (Pydantic model) to {self.state_file.name}...")
                # --- ATOMIC WRITE: Write to a temporary file first ---
                temp_file_path = ""
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, dir=self.storage_dir, suffix=".tmp") as temp_f:
                    temp_file_path = temp_f.name
                    json.dump(data_to_save, temp_f, indent=2)

                # --- ATOMIC WRITE: Atomically replace the old file with the new one ---
                if temp_file_path:
                    os.replace(temp_file_path, self.state_file)
                    logger.info(f"Project state saved successfully to {self.state_file.name}.")
                else:
                    raise RuntimeError("Failed to create a temporary file for saving project state.")

            except (OSError, IOError) as e:
                logger.exception(f"Atomic write failed for project state file {self.state_file.name}: {e}")
                raise RuntimeError(f"Failed to save project state atomically: {e}") from e
            except TypeError as e:
                 # Catch errors if the state model contains non-serializable types.
                 # Catch errors if the state model contains non-serializable types (less likely with Pydantic).
                 logger.exception(f"Error serializing project state Pydantic model to JSON: {e}.")
                 raise RuntimeError(f"Failed to serialize project state: {e}") from e
            except Exception as e:
                # Catch other file writing errors.
                # Catch other file writing errors.
                logger.exception(f"Error saving project state to {self.state_file.name}")
                raise RuntimeError(f"Failed to save project state: {e}") from e


    def clear_project_state(self) -> None:
        """Deletes the project state file (project_state.json)."""

        if self.storage_backend_type != "filesystem":
            logger.warning("clear_project_state: Non-filesystem backend not implemented. Skipping clear.")
            return
        with self._file_op_lock:
            try:
                # Soft delete the main state file
                self._soft_delete_file(self.state_file)
                # Also soft delete all backups associated with this file
                for backup_file in self.storage_dir.glob(f"{self.state_file.name}.*.bak"):
                    self._soft_delete_file(backup_file)
                logger.info(f"Soft-deleted project state file and all its backups: {self.state_file.name}")
            except OSError as e:
                # Log errors during file deletion but don't make it fatal.
                logger.exception(f"Error soft-deleting project state file {self.state_file.name}")
                raise RuntimeError(f"Failed to clear project state: {e}") from e
            except Exception as e:
                 logger.exception(f"Unexpected error clearing project state file {self.state_file}")


    # --- Workflow Context Management (New) ---

    def load_workflow_context(self) -> Dict[str, Any]:
        """
        Loads non-sensitive workflow context (e.g., recent steps, user requirements)
        from workflow_context.json.

        Returns:
            A dictionary containing the loaded context, or a default empty structure
            if the file doesn't exist or is invalid.
        """
        if self.storage_backend_type != "filesystem":
            logger.warning("load_workflow_context: Non-filesystem backend not implemented. Returning default context.")
            return {"steps": [], "user_requirements": {}}

        # Ensure the .vebgen directory exists before reading.
        self._ensure_dir_exists()
        with self._file_op_lock:
            default_context = {"steps": [], "user_requirements": {}} # Default structure

            # Handle cases where the file doesn't exist or is a directory.
            if not self.context_file.exists():
                logger.info(f"Workflow context file ({self.context_file.name}) not found. Using default context.")
                return default_context
            if not self.context_file.is_file():
                 logger.error(f"Workflow context path exists but is not a file: {self.context_file}. Using default context.")
                 self.clear_workflow_context()
                 return default_context

            try:
                logger.info(f"Loading workflow context from {self.context_file.name}...")
                with open(self.context_file, 'r', encoding='utf-8') as f:
                    context_data = json.load(f)

                # Basic validation to ensure the loaded data is a dictionary.
                # Basic validation: Ensure it's a dictionary
                if not isinstance(context_data, dict):
                     logger.warning(f"Workflow context file ({self.context_file.name}) content is invalid (not a dict). Using default context.")
                     self.clear_workflow_context()
                     return default_context

                # Ensure the core keys exist to prevent KeyErrors later.
                # Ensure core keys exist, add defaults if missing
                if "steps" not in context_data or not isinstance(context_data["steps"], list):
                    logger.warning("Workflow context missing or invalid 'steps' list. Resetting steps.")
                    context_data["steps"] = []
                if "user_requirements" not in context_data or not isinstance(context_data["user_requirements"], dict):
                    logger.warning("Workflow context missing or invalid 'user_requirements' dict. Resetting requirements.")
                    context_data["user_requirements"] = {}

                # A security check to remove any sensitive keys that might have been accidentally saved.
                # **SECURITY**: Explicitly remove any sensitive keys that might have been accidentally saved previously.
                sensitive_keys = ["api_keys", "passwords", "secrets"]
                keys_removed = [key for key in sensitive_keys if key in context_data]
                if keys_removed:
                     logger.warning(f"Removed potentially sensitive keys {keys_removed} found in workflow context file.")
                     for key in keys_removed: context_data.pop(key)

                logger.info(f"Loaded workflow context from {self.context_file.name}.")
                return context_data

            except json.JSONDecodeError:
                # Handle corrupted JSON file gracefully.
                logger.warning(f"Workflow context file ({self.context_file.name}) corrupted (JSON parse error). Using default context.", exc_info=False)
                self.clear_project_state()
                return default_context
            except Exception as e:
                # Catch any other file reading errors.
                logger.exception(f"Error loading workflow context from {self.context_file.name}")
                return default_context # Return default on other errors

    def save_workflow_context(self, context: Dict[str, Any]) -> None:
        """Saves the workflow context dictionary to workflow_context.json."""

        if self.storage_backend_type != "filesystem":
            logger.warning("save_workflow_context: Non-filesystem backend not implemented. Skipping save.")
            return

        # Ensure the context is a dictionary before saving.
        if not isinstance(context, dict):
            logger.error("Attempted to save invalid (non-dict) workflow context. Skipping save.")
            return

        self._ensure_dir_exists()
        with self._file_op_lock:
            try:
                logger.info(f"Saving workflow context to {self.context_file.name}...")
                # --- ATOMIC WRITE: Write to a temporary file first ---
                temp_file_path = ""
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, dir=self.storage_dir, suffix=".tmp") as temp_f:
                    temp_file_path = temp_f.name
                    json.dump(context, temp_f, indent=2, ensure_ascii=False)

                # --- ATOMIC WRITE: Atomically replace the old file with the new one ---
                if temp_file_path:
                    os.replace(temp_file_path, self.context_file)
                    logger.info(f"Workflow context saved successfully to {self.context_file.name}.")
                else:
                    raise RuntimeError("Failed to create a temporary file for saving workflow context.")
            except (OSError, IOError) as e:
                logger.exception(f"Atomic write failed for workflow context file {self.context_file.name}: {e}")
            except Exception as e:
                logger.exception(f"Error saving workflow context to {self.context_file.name}")

    def clear_workflow_context(self) -> None:
        """Deletes the workflow context file (workflow_context.json)."""

        if self.storage_backend_type != "filesystem":
            logger.warning("clear_workflow_context: Non-filesystem backend not implemented. Skipping clear.")
            return

        with self._file_op_lock:
            try:
                self._soft_delete_file(self.context_file)
                logger.info(f"Soft-deleted workflow context file: {self.context_file.name}")
            except OSError as e:
                logger.exception(f"Error soft-deleting workflow context file {self.context_file.name}")
                raise RuntimeError(f"Failed to clear workflow context: {e}") from e