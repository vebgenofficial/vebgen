# src/core/config_manager.py
import importlib
import importlib.util
import json
import re # Added for regex in validation
import logging
import sys # <-- Import sys
import dataclasses # Use dataclasses instead of TypedDict for prompts
from pathlib import Path
from typing import List, Dict, Any, TypedDict, Optional, cast

# Import the ChatMessage type hint for prompt structure validation
from .llm_client import ChatMessage

logger = logging.getLogger(__name__)

# --- Define structure for prompts expected from plugin files ---
# Use a dataclass for better type checking and attribute access
@dataclasses.dataclass
class FrameworkPrompts:
    """Dataclass holding the required system prompts for a framework."""
    system_tars_markdown_planner: ChatMessage
    system_case_executor: ChatMessage
    system_tars_validator: ChatMessage
    system_tars_error_analyzer: Optional[ChatMessage] # Changed to Optional
    system_tars_debugger: Optional[ChatMessage] = None # Added for the new debugger prompt
    system_tars_triage_engineer: Optional[ChatMessage] = None # New: For file identification
    system_case_code_fixer: Optional[ChatMessage] = None      # New: For code fixing by Case
    system_tars_deep_analyzer: Optional[ChatMessage] = None
    system_test_agent_feature_tester: Optional[ChatMessage] = None
    system_tars_feature_identifier: Optional[ChatMessage] = None
    system_tars_remediation_planner: Optional[ChatMessage] = None # New
    system_tars_remediation_differ: Optional[ChatMessage] = None # New
    system_case_remediation: Optional[ChatMessage] = None # Add this line

class ConfigManager:
    """
    Manages loading of framework-specific and provider-specific configurations.

    This class is responsible for two main types of configuration:
    1.  **Framework Prompts**: It dynamically discovers and loads Python modules
        (e.g., `django/prompts.py`) from the `plugins` directory. Each module
        is expected to contain a `FrameworkPrompts` dataclass instance that
        provides the system prompts for AI agents tailored to that framework.
    2.  **Provider/Model Info**: It loads `providers.json` to get the list of
        available LLM providers and their models for the UI.
    """
    def __init__(self, plugins_dir: Optional[str | Path] = None):
        """
        Initializes the ConfigManager.

        Args:
            plugins_dir: Optional path to the plugins directory. If None, it defaults
                         to 'plugins' inside the 'src' directory (relative to this file).
        """
        # Determine the base directory ('src') relative to this file's location.
        # This makes the path resolution robust, regardless of where the script is run from.
        base_dir = Path(__file__).resolve().parent.parent

        # If plugins_dir is not provided, default to 'src/plugins'
        if plugins_dir is None:
            self.plugins_dir = (base_dir / "plugins").resolve()
        else:
            # If a path is provided, resolve it. It can be absolute or relative to the current working directory.
            self.plugins_dir = Path(plugins_dir).resolve()

        # Load the central configuration for LLM providers and models.
        self.providers_config_path = self.plugins_dir.parent / "core" / "providers.json"
        self.providers_config = self._load_providers_config()

        if not self.plugins_dir.is_dir():
             # Log a warning if the directory doesn't exist, as no frameworks can be loaded.
             logger.warning(f"Plugins directory not found at '{self.plugins_dir}'. No frameworks will be loaded.")
        else:
             logger.info(f"ConfigManager initialized. Plugins directory: {self.plugins_dir}")

    def get_available_frameworks(self) -> List[str]:
        """
        Scans the plugins directory for valid framework subdirectories.
        A valid framework directory is a subdirectory that contains both an `__init__.py`
        file (making it a package) and a `prompts.py` file.

        Returns:
            A list of strings, where each string is the name of a valid framework subdirectory.
        """
        frameworks: List[str] = []
        if not self.plugins_dir.is_dir():
            # Return empty list if the plugins directory itself doesn't exist.
            return frameworks

        logger.info(f"Scanning for frameworks in '{self.plugins_dir}'...")
        try:
            for entry in self.plugins_dir.iterdir():
                # Check if the entry is a directory
                if entry.is_dir():
                    # Check for the required files within the directory
                    init_file = entry / '__init__.py'
                    if init_file.is_file():
                        # If both files exist, add the directory name to the list of frameworks.
                        frameworks.append(entry.name)
                        logger.info(f"Found valid framework plugin: '{entry.name}'.")
                    else:
                        # Log why a directory might be skipped (useful for debugging).
                        missing = []
                        if not init_file.is_file(): missing.append("'__init__.py'")
                        logger.debug(f"Directory '{entry.name}' skipped. Missing: {', '.join(missing)}.")
        except OSError as e:
            logger.error(f"Error scanning plugins directory '{self.plugins_dir}': {e}")
        except Exception as e:
            logger.exception(f"Unexpected error scanning plugins directory '{self.plugins_dir}'.")


        if frameworks:
            logger.info(f"Available frameworks found: {frameworks}")
        else:
            logger.warning("No valid framework plugins found.")
        return frameworks

    def load_prompts(self, framework: str) -> FrameworkPrompts:
        """
        Dynamically loads the `prompts.py` module for a given framework.

        This method constructs the path to the framework's prompt file,
        uses `importlib` to load it as a Python module, and extracts the
        `FrameworkPrompts` instance (e.g., `django_prompts`) from it.
        It temporarily adds the `src` directory to the system path to allow
        the prompt modules to use absolute imports (e.g., `from src.core...`).

        Returns:
            A validated `FrameworkPrompts` dataclass instance for the specified framework.

        Raises:
            ValueError: If the framework plugin is not found or is invalid.
            RuntimeError: If an unexpected error occurs during module loading.
        """
        framework_dir = self.plugins_dir / framework
        prompts_file_path = framework_dir / 'prompts.py'

        if not framework_dir.is_dir() or not prompts_file_path.is_file():
            # Raise error if the framework directory or prompts file doesn't exist.
            raise ValueError(f"Framework '{framework}' prompts file not found at expected path: {prompts_file_path}")

        # Use importlib.util for robust dynamic module loading from a file path.
        module_name = f"vebgen_plugins.{framework}.prompts"
        # Convention: the variable holding the FrameworkPrompts instance is named like 'django_prompts'
        prompts_var_name = f"{framework}_prompts"

        logger.info(f"Attempting to load prompts for framework '{framework}' from: {prompts_file_path}")
        logger.debug(f"Expecting module name: '{module_name}', variable name: '{prompts_var_name}'")

        # The 'src' directory needs to be on the path for the plugin's imports to work.
        src_dir = self.plugins_dir.parent # Assumes plugins_dir is src/plugins
        src_dir_str = str(src_dir)
        path_added = False
        try:
            # Create a module specification from the file location.
            spec = importlib.util.spec_from_file_location(module_name, prompts_file_path)
            if spec is None or spec.loader is None:
                 raise ImportError(f"Could not create module spec for {prompts_file_path}")

            # Create a new module object based on the specification.
            prompts_module = importlib.util.module_from_spec(spec)

            # Temporarily add the 'src' directory to the Python path. This allows
            # the prompts.py file to use absolute imports like `from src.core.llm_client...`.
            if src_dir_str not in sys.path:
                sys.path.insert(0, src_dir_str)
                path_added = True
                logger.debug(f"Temporarily added '{src_dir_str}' to sys.path for module loading.")

            # Execute the module's code in its own namespace to populate it.
            spec.loader.exec_module(prompts_module) # This is where the ImportError happened
            logger.debug(f"Successfully executed module '{module_name}'.")

            # Get the FrameworkPrompts instance (assuming it follows the naming convention).
            if not hasattr(prompts_module, prompts_var_name):
                 raise AttributeError(f"Variable '{prompts_var_name}' not found in {prompts_file_path}.")

            prompts_data_instance = getattr(prompts_module, prompts_var_name)

            # Validate the structure and content of the loaded prompts data instance.
            # Pass the INSTANCE to the validation function.
            if not self._is_valid_framework_prompts(prompts_data_instance):
                logger.error(f"Loaded prompts data for '{framework}' has invalid structure or missing keys.")
                # The specific error is logged within _is_valid_framework_prompts
                raise ValueError(f"Prompts file for '{framework}' has an invalid structure or missing required prompts.")

            logger.info(f"Successfully loaded and validated prompts for framework '{framework}'.")
            # The loaded data is already the correct FrameworkPrompts type.
            return prompts_data_instance

        except (ImportError, AttributeError, ValueError, TypeError) as e:
             # Catch specific errors related to loading and validation.
             logger.exception(f"Error loading or validating prompts data for '{framework}' from {prompts_file_path}.")
             raise ValueError(f"Invalid prompts data or module for framework '{framework}': {e}") from e
        except Exception as e:
             # Catch any other unexpected errors during the import process.
             logger.exception(f"Unexpected error loading prompts for framework '{framework}'.")
             raise RuntimeError(f"Failed to load prompts for framework '{framework}': {e}") from e

    def _is_valid_framework_prompts(self, data: Any) -> bool:
        """
        Performs basic validation on the structure and content of the loaded prompts object.
        Checks attributes of the FrameworkPrompts dataclass instance.
        This ensures that the loaded prompts conform to the expected contract.

        Args:
            data: The loaded data object (expected to be an instance of FrameworkPrompts).

        Returns:
            True if the data is a valid FrameworkPrompts instance with correct structure, False otherwise.
        """
        # Check if it's an instance of the expected dataclass
        if not isinstance(data, FrameworkPrompts):
            logger.error(f"Validation failed: Prompts data is not an instance of FrameworkPrompts (type: {type(data)}).")
            return False

        # Define the required attribute names (lowercase) based on the FrameworkPrompts dataclass fields.
        # Use dataclasses.fields to get the defined fields accurately.
        required_attributes = {f.name for f in dataclasses.fields(FrameworkPrompts) if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING} # type: ignore


        # Check if all required attributes are present on the instance.
        missing_attributes = [attr for attr in required_attributes if not hasattr(data, attr) or getattr(data, attr) is None]
        if missing_attributes:
            # Log the missing ATTRIBUTES (lowercase)
            logger.error(f"Validation failed: Prompts object missing required attributes: {missing_attributes}. Instance has: {vars(data).keys()}")
            return False

        # Check if the value associated with each required attribute is a dictionary (ChatMessage).
        for attr_name in required_attributes:
            prompt_value = getattr(data, attr_name)
            if not isinstance(prompt_value, dict):
                 logger.error(f"Validation failed: Prompt attribute '{attr_name}' value is not a dictionary (type: {type(prompt_value)}).")
                 return False
            # Further check if the dictionary has the required 'role' and 'content' keys of ChatMessage.
            if not ('role' in prompt_value and 'content' in prompt_value):
                 logger.error(f"Validation failed: Prompt attribute '{attr_name}' dictionary is missing 'role' or 'content'. Keys found: {list(prompt_value.keys())}")
                 return False
            # Check if 'role' and 'content' are strings.
            if not isinstance(prompt_value['role'], str) or not isinstance(prompt_value['content'], str):
                 logger.error(f"Validation failed: Prompt attribute '{attr_name}' has non-string 'role' (type: {type(prompt_value['role'])}) or 'content' (type: {type(prompt_value['content'])}).")
                 return False

        logger.debug("Prompts data structure validation passed.")
        return True

    def _load_providers_config(self) -> Dict[str, Any]:
        """Loads the providers.json configuration file."""
        if not self.providers_config_path.exists():
            logger.error(f"Provider config file not found at {self.providers_config_path}. No models will be available.")
            return {}
        try:
            with open(self.providers_config_path, 'r') as f:
                config = json.load(f)
            logger.info(f"Successfully loaded provider config from {self.providers_config_path}.")
            return config
        except (json.JSONDecodeError, OSError) as e:
            logger.exception(f"Failed to load or parse provider config file: {e}")
            return {}

    def get_providers(self) -> Dict[str, str]:
        """
        Gets a list of all configured LLM providers for the UI.
        Returns a dictionary of provider IDs and their display names.
        Includes an "All" option.
        """
        providers = {"all": "All"}
        for provider_id, data in self.providers_config.items():
            providers[provider_id] = data.get("display_name", provider_id)
        return providers

    def get_models_for_provider(self, provider_id: str) -> List[Dict[str, str]]:
        """
        Gets the list of models for a specific provider ID.
        Returns a list of models for a given provider ID.
        If provider_id is 'all', returns all models formatted with their provider.
        """
        models = []
        if provider_id == "all":
            for pid, data in self.providers_config.items():
                provider_name = data.get("display_name", pid)
                for model_name in data.get("models", []):
                    # The full model ID for the backend needs the provider prefix for some clients
                    full_model_id = f"{data.get('client_config', {}).get('model_prefix', '')}{model_name}"
                    models.append({"display": f"{model_name} - {provider_name}", "id": full_model_id, "provider": pid})
        elif provider_id in self.providers_config:
            data = self.providers_config[provider_id]
            provider_name = data.get("display_name", provider_id)
            for model_name in data.get("models", []):
                full_model_id = f"{data.get('client_config', {}).get('model_prefix', '')}{model_name}"
                # When a specific provider is selected, still show the provider name for clarity, especially for OpenRouter.
                display_name = f"{model_name} - {provider_name}" if provider_id == "openrouter" else model_name
                models.append({"display": display_name, "id": full_model_id, "provider": provider_id})
        return sorted(models, key=lambda x: x['display'])