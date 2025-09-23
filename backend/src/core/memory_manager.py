# src/core/memory_manager.py
import json
import logging
import re # Added for potential future use in cleaning keys
from pathlib import Path
from typing import List, Dict, Any, Optional, cast
from pydantic import ValidationError

# Import the data models used for state and history
from .project_models import ProjectState, FeatureTask, ProjectStructureMap # Import FeatureTask and ProjectStructureMap
from .llm_client import ChatMessage

logger = logging.getLogger(__name__)

# --- Constants for filenames and directory ---
MAX_HISTORY_MESSAGES = 50 # Max messages in history before pruning
HISTORY_FILENAME = 'conversation_history.json' # File to store chat history
PROJECT_STATE_FILENAME = 'project_state.json'   # File to store the detailed project state
WORKFLOW_CONTEXT_FILENAME = 'workflow_context.json' # File for non-sensitive workflow state
STORAGE_DIR_NAME = '.vebgen' # Hidden directory within user's project for storing these files

class MemoryManager:
    """
    Manages the persistence of the application's state to the file system.

    This class handles the loading and saving of three key pieces of information,
    all stored within a hidden `.vebgen` directory inside the user's project:
    1.  **Project State**: The complete, detailed state of the project, including
        features, tasks, and configurations. Managed via Pydantic models for robustness.
    2.  **Conversation History**: The ongoing chat history with the AI agents.
    3.  **Workflow Context**: Non-sensitive, session-related data like task completion status.

    It is designed to be adaptable to different storage backends in the future.
    """
    def __init__(self, project_root_path: str | Path, storage_backend_type: str = "filesystem"):
        """
        Initializes the MemoryManager.

        Args:
            project_root_path: The absolute path to the root directory of the user's project.
            storage_backend_type: The type of storage backend to use. 
                                  (Currently only "filesystem" is implemented).

        Raises:
            ValueError: If project_root_path is not provided or invalid.
            RuntimeError: If the storage directory cannot be created.
        """
        if not project_root_path:
            raise ValueError("MemoryManager requires a valid project_root_path.")
        self.storage_backend_type = storage_backend_type
        if self.storage_backend_type != "filesystem":
            # Placeholder for future NoSQL or other backend integration
            logger.warning(f"Storage backend type '{self.storage_backend_type}' is not yet fully implemented. Using filesystem fallback.")
            self.storage_backend_type = "filesystem"

        self.project_root = Path(project_root_path).resolve()
        # Ensure the project root provided actually exists and is a directory.
        # Ensure the project root provided actually exists and is a directory.
        if not self.project_root.is_dir():
             # This check should ideally happen before MemoryManager is created,
             # but adding a safeguard here.
             logger.error(f"MemoryManager init failed: Project root path is not a valid directory: {self.project_root}")
             raise ValueError(f"Project root path is not a valid directory: {self.project_root}")

        # Define paths for the storage directory and the files within it.
        # Define paths for the storage directory and the files within it.
        self.storage_dir = self.project_root / STORAGE_DIR_NAME
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
        # Handle the edge case where the history file path exists but is a directory.
        if not self.history_file.is_file():
            # Handle case where the path exists but is not a file (e.g., a directory).
            logger.error(f"History storage path exists but is not a file: {self.history_file}. Resetting history.")
            self.clear_history() # Attempt to remove the non-file entry
            return []

        try:
            logger.info(f"Loading conversation history from {self.history_file.name}...")
            with open(self.history_file, 'r', encoding='utf-8') as f:
                history_data = json.load(f)

            # Validate that the loaded data is a list, as expected for history.
            # Validate that the loaded data is a list.
            if not isinstance(history_data, list):
                 logger.warning(f"History file ({self.history_file.name}) content is invalid (not a list). Resetting history.")
                 self.clear_history()
                 return []

            # Validate individual messages to ensure they conform to the ChatMessage structure.
            # Validate individual messages within the list.
            valid_history: List[ChatMessage] = []
            invalid_count = 0
            for i, msg in enumerate(history_data):
                # Check if it's a dict with required string keys 'role' and 'content'.
                if (isinstance(msg, dict) and
                        'role' in msg and isinstance(msg['role'], str) and
                        'content' in msg and isinstance(msg['content'], str)):
                    # Create a ChatMessage object, including optional 'name' if valid.
                    chat_msg: ChatMessage = {"role": msg["role"], "content": msg["content"]}
                    if "name" in msg and isinstance(msg["name"], str) and msg["name"]:
                        chat_msg["name"] = msg["name"]
                    valid_history.append(chat_msg)
                else:
                    # Log invalid entries but don't stop loading valid ones.
                    logger.warning(f"Invalid message structure at index {i} in history file: {str(msg)[:100]}...")
                    invalid_count += 1

            if invalid_count > 0:
                logger.warning(f"Filtered out {invalid_count} invalid entries from history file.")

            logger.info(f"Loaded {len(valid_history)} valid messages from {self.history_file.name}.")
            return valid_history

        except json.JSONDecodeError:
            # Handle a corrupted JSON file gracefully by resetting history.
            # Handle corrupted JSON file.
            logger.warning(f"History file ({self.history_file.name}) corrupted (JSON parse error). Resetting history.", exc_info=True)
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
        self._ensure_dir_exists() # Ensure directory exists before writing
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
            with open(self.history_file, 'w', encoding='utf-8') as f:
                # Use indent for readability and ensure_ascii=False for non-ASCII characters.
                # Use indent for readability. ensure_ascii=False preserves non-ASCII chars.
                json.dump(valid_messages_to_save, f, indent=2, ensure_ascii=False)
            logger.info(f"History saved successfully.")

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

        try:
            if self.history_file.exists():
                self.history_file.unlink() # Delete the file
                logger.info(f"Cleared history file: {self.history_file}")
            else:
                 logger.info("History file already cleared or does not exist.")
        # Log errors during file deletion but don't make it fatal.
        except OSError as e:
            # Log errors during file deletion.
            logger.exception(f"Error deleting history file {self.history_file}")
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
        self._ensure_dir_exists() # Ensure directory exists before reading
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
                logger.error(f"Project state file ({self.state_file.name}) failed Pydantic validation. Resetting state.")
                # Log detailed validation errors for easier debugging.
                # Log detailed validation errors for debugging
                try:
                    error_details = e.json(indent=2)
                    logger.error(f"Pydantic Validation Errors:\n{error_details}")
                except Exception as json_err:
                    logger.error(f"Could not serialize Pydantic validation errors: {json_err}")
                    logger.error(f"Raw Pydantic validation error: {e}")
                self.clear_project_state()
                return None

        except json.JSONDecodeError:
            # Handle a corrupted JSON file gracefully.
            # Handle corrupted JSON file.
            logger.warning(f"Project state file ({self.state_file.name}) corrupted (JSON parse error). Resetting state.", exc_info=False) # Less verbose
            self.clear_project_state()
            return None
        except Exception as e:
            # Catch any other file reading or validation errors.
            # Catch other file reading or validation errors.
            logger.exception(f"Error loading project state from {self.state_file.name}")
            # Return None to indicate failure to load state.
            return None
    # This part is typically within a method that decides to create a NEW project state,
    # often called from WorkflowManager.initialize_project or as a fallback in load_project_state.
    # Let's assume it's part of a hypothetical _create_new_project_state method for illustration.
    # This part is typically within a method that decides to create a NEW project state,
    # often called from WorkflowManager.initialize_project or as a fallback in load_project_state.
    # Let's assume it's part of a hypothetical _create_new_project_state method for illustration.
    def _create_new_project_state(self, project_name_raw: str, framework: str, project_root: str) -> ProjectState:
        safe_project_name = re.sub(r'\W|^(?=\d)', '_', project_name_raw).lower()
        # ... (other logic for safe_project_name) ...
        try:
            # Method: _create_new_project_state (or similar, during new ProjectState instantiation)
            # Create a new ProjectState instance, relying on Pydantic to set default values.
            new_state = ProjectState(
                project_name=safe_project_name,
                framework=framework,
                root_path=project_root,
                project_structure_map=ProjectStructureMap(), # Initialize new field
                cumulative_docs=f"# {safe_project_name} - Technical Documentation\n\nFramework: {framework}\n",
            )
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

        # Ensure the .vebgen directory exists before writing.
        self._ensure_dir_exists() # Ensure directory exists before writing
        try:
            logger.info(f"Saving project state (Pydantic model) to {self.state_file.name}...")
            with open(self.state_file, 'w', encoding='utf-8') as f:
                # Use Pydantic's model_dump_json for serialization
                f.write(state.model_dump_json(indent=2))
            logger.info(f"Project state saved successfully.")
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
        try:
            if self.state_file.exists():
                self.state_file.unlink() # Delete the file
                logger.info(f"Cleared project state file: {self.state_file}")
            else:
                 # It's not an error if the file is already gone.
                 logger.info("Project state file already cleared or does not exist.")
        except OSError as e:
            # Log errors during file deletion but don't make it fatal.
            logger.exception(f"Error deleting project state file {self.state_file}")
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
        self._ensure_dir_exists() # Ensure directory exists before reading
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
            self.clear_workflow_context()
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
        try:
            logger.info(f"Saving workflow context to {self.context_file.name}...")
            with open(self.context_file, 'w', encoding='utf-8') as f:
                json.dump(context, f, indent=2, ensure_ascii=False)
            logger.info(f"Workflow context saved successfully.")
        except Exception as e:
            logger.exception(f"Error saving workflow context to {self.context_file.name}")

    def clear_workflow_context(self) -> None:
        """Deletes the workflow context file (workflow_context.json)."""

        if self.storage_backend_type != "filesystem":
            logger.warning("clear_workflow_context: Non-filesystem backend not implemented. Skipping clear.")
            return

        try:
            if self.context_file.exists(): self.context_file.unlink()
            logger.info(f"Cleared workflow context file: {self.context_file}")
        except OSError as e:
            logger.exception(f"Error deleting workflow context file {self.context_file}")