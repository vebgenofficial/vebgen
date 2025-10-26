# backend/src/core/workflow_manager.py
import logging
import asyncio
import threading
import re
import html
import platform
import requests
import sys # Import sys
import json
import time
import shlex # For parsing command strings safely
import os
from typing import List, Dict, Any, Callable, Optional, Tuple, Awaitable, Union, cast, Literal
import ast # For Python syntax validation
from types import TracebackType # Import TracebackType
import importlib
from pathlib import Path
import bs4
from markdown_it import MarkdownIt
from bs4 import BeautifulSoup, FeatureNotFound # Already imported, good for XML parsing
import huggingface_hub # Added for potential Hugging Face token management
from .project_models import FeatureTask, FileStructureInfo
from pydantic import ValidationError

# Import core components
from .agent_manager import AgentManager
from .memory_manager import MemoryManager # Keep MemoryManager
from .config_manager import ConfigManager, FrameworkPrompts # Keep FrameworkPrompts
from .file_system_manager import FileSystemManager
from .command_executor import CommandExecutor, ConfirmationCallback, IDENTIFIER_REGEX
# Import project data models, including the new FeatureStatusEnum
from .project_models import (ProjectState, ProjectFeature, FeatureTask, FeatureStatusEnum, TaskStatus, AppStructureInfo, ProjectStructureMap, FrontendValidationReport) # type: ignore
# Import LLM client specifics
from .llm_client import RateLimitError, ChatMessage, AuthenticationError
# Import secure storage for placeholder handling and APIContract
from .exceptions import BlockedCommandException # Import the new exception
from .secure_storage import store_credential, retrieve_credential, delete_credential
# Import CodeIntelligenceService
from .code_intelligence_service import CodeIntelligenceService
from .security_utils import sanitize_and_validate_input
from .exceptions import RemediationError, PatchApplyError, CommandExecutionError, InterruptedError
from .validators.frontend_validator import FrontendValidator

# New Adaptive Workflow Imports
from .adaptive_agent import AdaptiveAgent
from .adaptive_prompts import TARS_FEATURE_BREAKDOWN_PROMPT, TARS_VERIFICATION_PROMPT, TARS_REMEDIATION_PROMPT, CASE_NEXT_STEP_PROMPT
# --- NEW: Import performance monitor ---
from .performance_monitor import performance_monitor


# --- Constants ---
MAX_REMEDIATION_ATTEMPTS = 3    # Max attempts for TARS to remediate a feature
RETRY_DELAY_SECONDS = 2.0       # Default delay for retries (seconds)
MAX_PLANNING_ATTEMPTS = 3       # Max attempts for Tars to generate a valid plan
MAX_IMPLEMENTATION_ATTEMPTS = 3 # Max attempts for Case to generate code for a single task
MAX_REMEDIATION_ATTEMPTS_FOR_TASK = 2 # Max attempts for a task to be remediated
MAX_VALIDATION_ATTEMPTS = 2     # Max attempts to validate a task before failing
LOG_PROMPT_SUMMARY_LENGTH = 200 # Max length for logging prompt summaries
MAX_FEATURE_TEST_ATTEMPTS = 3   # Max attempts to generate and pass feature-level tests


logger = logging.getLogger(__name__)

# --- Helper function to build planner prompt ---
def _build_planner_prompt_content_for_feature(feature_name: str, feature_id: str, feature_description: str,
                                              project_goal: str, project_context: str, framework_version: str, # Keep framework_version
                                              needs_frontend: bool,
                                              related_api_contracts_summary: Optional[str] = None) -> str:
    """Constructs the detailed prompt content for the Tars planner."""
    frontend_instruction = ""
    api_contract_instruction = ""

    if needs_frontend:
        # Add specific instructions for the planner if the feature involves a UI.
        frontend_instruction = (
            f"**IMPORTANT UI/Frontend Consideration ({framework_version}):** This is a web application requiring a user interface. "
            "Your plan **MUST** include tasks for:\n"
            "- Creating necessary HTML templates (e.g., `app_name/templates/app_name/file.html`).\n"
            "- Creating basic CSS files (e.g., `app_name/static/app_name/css/style.css`).\n"
            "- **Crucially, if client-side interactivity is needed (button clicks, dynamic updates): Plan tasks to create/modify JavaScript files (`app_name/static/app_name/js/main.js`). The `Requirements` for these JS tasks MUST detail event listeners, DOM manipulation, and any `fetch` API calls to the backend.**\n"
            "- Modifying views in `views.py` to render these templates, passing appropriate context, and to handle API requests from the frontend JavaScript if planned.\n"
            "- Ensuring `settings.py` has `APP_DIRS: True` in `TEMPLATES` and `STATIC_URL` configured.\n"
            "- Using `{{% load static %}}` and `{{% static 'app_name/path/to/file.css' %}}` (or JS file) in templates.\n"
            "- For CSS tasks, the `styling_details` field in the task should describe the visual appearance and layout needed.\n"
        )
    # Add context about any related API contracts to ensure the plan adheres to them.
    if related_api_contracts_summary:
        api_contract_instruction = (
            f"\n**API Contract Reference:**\n"
            f"This feature relates to the following API contract(s). Ensure backend views and frontend calls adhere to these definitions:\n"
            f"{related_api_contracts_summary}\n"
            f"Tasks implementing or consuming these API endpoints MUST explicitly state the contract ID and expected data structures in their `Requirements`.\n"
        )
    return f'''
Generate a detailed, step-by-step Markdown plan to implement the following feature, considering the current project state and type.

**Feature Name:** {feature_name}
**Feature ID:** {feature_id}
**Overall Project Goal:** {project_goal}
**Current Feature Description:** {feature_description}

**Project Context & Map:**
{project_context}

{api_contract_instruction}
{frontend_instruction}

**Chain of Thought Instructions (Follow this logic):**
- **Dependencies First:** Before planning a task, ask "What other files, database models, or configurations must exist first for this task to succeed?" For example, a `urls.py` file needs a `views.py` to import from, so the `views.py` task must come first and be listed as a dependency.
- **Configuration before Usage:** Plan tasks to modify configuration files (like `settings.py` or `urls.py` to register an app or include its URLs) *before* planning any command that relies on that configuration (like `python manage.py check` or `python manage.py test <app>`).
- **Models -> Views -> URLs -> Templates:** For a typical web feature, the logical order is: create/modify models, then the views that use them, then the URL patterns that point to the views, and finally the templates that are rendered by the views. Use dependencies to enforce this flow.
- **Test After Implementation:** For every piece of new logic (e.g., a new function in a view, a new model method), plan a corresponding test creation/modification task immediately after it. Then, plan a `Run command` task to execute the tests.

**Instructions:**
- Analyze the request, project goal, and project map. Plan only necessary steps for *this feature*.
- Break the feature down into the **smallest possible atomic tasks** (Create file, Modify file, Run command, Create directory, Prompt user input).
- **CRITICAL: Enforce Logical Order with Dependencies.** Your plan's success depends on defining the correct `depends_on:` relationships between tasks. A task should depend on any other task that creates or modifies a file it needs to read or a configuration it relies on.
- Follow the strict Markdown task format with all required metadata (`ID`, `Action`, `Target`, `Description`, `Requirements`, `Dependencies`, `Test step`, `Doc update`).
- Use hierarchical IDs (e.g., 1.1, 1.2, 2.1.1). **CRITICAL: Ensure IDs are unique within this feature\'s plan.**
- Define clear `Dependencies` between tasks using their IDs (e.g., `depends_on: 1.1, 1.3`). The key MUST be exactly `depends_on:` (lowercase \'o\'). Use `None` if no dependencies.
- Specify a single, precise `Test step` command for each task. Use simple, verifiable commands (like `python manage.py check <app>`, `python -m py_compile <file.py>`, `type <file.txt>`, `dir <folder>`). **AVOID interactive or complex test steps.** For template creation, `type <template_path.html>` is a good test.
- **Plan for Tests:** Your plan **MUST** include tasks to create or modify test files (e.g., `app_name/tests/test_views.py`). The `Requirements` for these test tasks should describe what needs to be asserted. Also, include `Run command` tasks to execute these tests (e.g., `python manage.py test app_name`).
- Handle external inputs using `Prompt user input` tasks and define placeholder `Target` names (e.g., `API_KEY`). Explain placeholder usage in `Requirements`.
- Ensure the plan is comprehensive and logically ordered for {framework_version}.
- Output **ONLY** the Markdown plan. No extra text, explanations, or introductions.
'''

# --- Type Hints for UI Callbacks ---
# These define the expected signatures for functions passed from the UI layer.
ProgressCallback = Callable[[Dict[str, Any]], None] # func(progress_data: Dict)
ShowInputPromptCallable = Callable[[str, bool, Optional[str]], Optional[str]] # func(title, is_password, prompt) -> user_input | None
ShowFilePickerCallable = Callable[[str], Optional[str]] # func(title) -> file_path | None
ShowConfirmationDialogCallable = Callable[[str], bool] # func(prompt) -> True | False
ShowUserActionPromptCallable = Callable[[str, str, str], bool] # func(title, instructions, command) -> True | False
RequestNetworkRetryCallable = Callable[[str, str], Awaitable[bool]] # agent_desc, error_message -> should_retry
RequestApiKeyUpdateCallable = Callable[[str, str, str], Awaitable[Tuple[Optional[str], bool]]] # agent_desc, error_type, current_key_name -> (new_key, retry_current)
RequestRemediationRetryCallable = Callable[[str, str], Awaitable[bool]] # task_id, failure_reason -> should_retry
# Callback for the WorkflowManager to request command execution via the UI
RequestCommandExecutionCallable = Callable[[str, str, str], Awaitable[Tuple[bool, str]]] # async func(task_id, command, description) -> (success, output/error)



class WorkflowManager:
    """
    Orchestrates the AI-driven development lifecycle using an adaptive TARS/CASE workflow.
    """
    def __init__(self,
                 agent_manager: AgentManager,
                 memory_manager: MemoryManager,
                 config_manager: ConfigManager,
                 file_system_manager: FileSystemManager,
                 command_executor: CommandExecutor,
                 # UI Callbacks
                 show_input_prompt_cb: ShowInputPromptCallable,
                 show_file_picker_cb: ShowFilePickerCallable,
                 progress_callback: ProgressCallback,
                 show_confirmation_dialog_cb: ShowConfirmationDialogCallable,
                 request_command_execution_cb: RequestCommandExecutionCallable,
                 show_user_action_prompt_cb: ShowUserActionPromptCallable,
                 request_network_retry_cb: Optional[RequestNetworkRetryCallable] = None,
                 request_remediation_retry_cb: Optional[RequestRemediationRetryCallable] = None,
                 request_api_key_update_cb: Optional[RequestApiKeyUpdateCallable] = None,
                 default_tars_temperature: float = 0.2,
                 default_case_temperature: float = 0.1,
                 remediation_config=None,
                 ui_communicator: Any = None
                 ):
        self.logger = logging.getLogger(__name__)
        self.prompts: Optional[FrameworkPrompts] = None
        self.agent_manager = agent_manager
        self.memory_manager = memory_manager
        self.config_manager = config_manager
        self.file_system_manager = file_system_manager
        self.command_executor = command_executor
        # Store UI callbacks
        self.show_input_prompt_cb = show_input_prompt_cb
        self.show_file_picker_cb = show_file_picker_cb
        self.progress_callback = progress_callback
        self.show_confirmation_dialog_cb = show_confirmation_dialog_cb
        self.request_command_execution_cb = request_command_execution_cb
        self.show_user_action_prompt_cb = show_user_action_prompt_cb
        self._request_network_retry_cb = request_network_retry_cb
        self._request_remediation_retry_cb = request_remediation_retry_cb
        self._request_api_key_update_cb = request_api_key_update_cb
        self.default_tars_temperature = default_tars_temperature
        self.default_case_temperature = default_case_temperature
        self.ui_communicator = ui_communicator
        self.code_intelligence_service = CodeIntelligenceService(self.file_system_manager.project_root)
        # --- NEW: Event for graceful shutdown ---
        self.stop_event_thread = threading.Event()
        self.stop_event = asyncio.Event()
        
        # Pass the stop event to the agent manager so it can interrupt long waits.
        self.agent_manager.stop_event = self.stop_event

        # --- FIX: Initialize state variables ---
        self.project_state: Optional[ProjectState] = None
        self.workflow_context: Dict[str, Any] = self.memory_manager.load_workflow_context()
        logger.info("WorkflowManager instance created.")

    def load_existing_project(self):
        """
        Loads the project state from memory and sets it as the active state for the manager.
        This is called by the UI after initialization to sync the backend state without
        starting a workflow, enabling the 'Continue' functionality.
        """
        try:
            if not self.memory_manager:
                raise RuntimeError("MemoryManager not available to load project state.")

            loaded_state = self.memory_manager.load_project_state()

            if loaded_state:
                # ✅ SAFETY CHECK: Validate loaded state against project reality
                is_empty_state = not loaded_state.features and not loaded_state.registered_apps
                if is_empty_state and self._project_has_code():
                    logger.error("CORRUPTION DETECTED: Project state is empty but project directory contains code. Attempting auto-restore.")
                    self.progress_callback({"warning": "Corruption detected! Attempting to restore from backup..."})
                    
                    restored_state = self.memory_manager.restore_from_latest_backup()
                    # ✅ FIX: Check if restored state has actual data
                    if restored_state and (restored_state.features or restored_state.registered_apps):
                        logger.info(f"SUCCESS: Auto-restore succeeded. Loaded {len(restored_state.features)} features from backup.")
                        self.project_state = restored_state
                        self.progress_callback({"system_message": f"Successfully restored {len(restored_state.features)} features from backup."})
                    else:
                        # SCENARIO 3: Existing project, no VebGen history, no valid backups.
                        self.logger.info("This appears to be an existing project without VebGen history.")
                        self.logger.info("Triggering initial project scan to build code intelligence...")
                        if restored_state:
                            logger.warning("Auto-restore loaded a state file, but it was also empty. All available backups may be empty.")
                        else:
                            logger.warning("Auto-restore failed. No valid, non-empty backups could be found.")
                        
                        self.project_state = loaded_state # Fallback to the corrupted (empty) state
                        self._perform_initial_project_scan()
                        self.progress_callback({"error": "Could not restore from backup. Project history may be lost."})
                else:
                    # State looks valid
                    self.project_state = loaded_state
                    logger.info(f"Loaded existing project with {len(loaded_state.features)} features.")
            else:
                # load_project_state returned None, indicating no file or a corrupted one that couldn't be restored.
                # We create a new, empty state for the current session but DO NOT save it.
                logger.warning("No valid project state found. Creating a new, temporary in-memory state.")
                self.project_state = self.memory_manager.create_new_project_state(
                    project_name_raw=self.file_system_manager.project_root.name,
                    framework=self.config_manager.get_available_frameworks()[0] if self.config_manager.get_available_frameworks() else "unknown",
                    project_root=str(self.file_system_manager.project_root)
                )
        except Exception as e:
            logger.exception(f"Critical error during project load: {e}. Creating a temporary empty state.")
            self.project_state = self.memory_manager.create_new_project_state(project_name_raw="error_state", framework="unknown", project_root=str(self.file_system_manager.project_root))

    def _perform_initial_project_scan(self):
        """
        Performs an initial scan of an existing project to populate code intelligence.
        This is ONLY called for Scenario 3 (external project with no VebGen history).
        """
        self.logger.info("="*60)
        self.logger.info("INITIAL PROJECT SCAN STARTED")
        self.logger.info("="*60)

        try:
            project_root = Path(self.project_state.root_path)
            file_summaries: Dict[str, str] = {}

            # Step 1: Scan Python files
            self.logger.info("Step 1/5: Scanning Python files...")
            python_files = [
                f for f in project_root.rglob("*.py")
                if not any(part in f.parts for part in ['venv', 'env', '.venv', '__pycache__', 'node_modules'])
            ]
            self.logger.info(f"Found {len(python_files)} Python files to analyze.")

            # === NEW: Step 1.5 - Scan Frontend Files ===
            self.logger.info("Step 1.5/5: Scanning frontend files (HTML/CSS/JS)...")
            
            # Find HTML, CSS, and JS files, excluding common ignored directories
            excluded_dirs_for_scan = ['node_modules', 'venv', 'env', '.venv', '__pycache__', '.git', 'dist', 'build']
            
            html_files = [f for f in project_root.rglob('*.html') if not any(part in f.parts for part in excluded_dirs_for_scan)]
            css_files = [f for f in project_root.rglob('*.css') if not any(part in f.parts for part in excluded_dirs_for_scan)]

            # --- FIX: Intelligent JS file filtering to avoid large/minified/vendor files ---
            js_files = []
            # Add Django admin static files to the exclusion list for JS
            js_excluded_dirs = excluded_dirs_for_scan + ['staticfiles/admin', 'vendor', 'libs', 'library']
            
            for js_file in project_root.rglob('**/*.js'):
                # Skip if in an excluded directory
                if any(excluded_dir in str(js_file) for excluded_dir in js_excluded_dirs):
                    continue
                
                # Skip minified files
                if '.min.js' in js_file.name:
                    logger.debug(f"Skipping minified JS file: {js_file.relative_to(project_root)}")
                    continue
                
                # Skip very large files (>100KB is a good heuristic for vendor code)
                if js_file.stat().st_size > 100_000:
                    logger.debug(f"Skipping large JS file ({js_file.stat().st_size / 1024:.1f} KB): {js_file.relative_to(project_root)}")
                    continue
                
                js_files.append(js_file)
            # --- END FIX ---
            
            all_files_to_scan = python_files + html_files + css_files + js_files
            logger.info(f"Found {len(html_files)} HTML, {len(css_files)} CSS, {len(js_files)} JS files. Total files to scan: {len(all_files_to_scan)}")

            # Step 2: Parse each file and store FULL AST DATA
            for idx, file_path in enumerate(all_files_to_scan, 1):
                try:
                    relative_path = str(file_path.relative_to(project_root))

                    # Use CodeIntelligenceService to parse the file
                    file_content = self.file_system_manager.read_file(relative_path)
                    if file_content is None:
                        self.logger.warning(f"Skipping empty or unreadable file: {relative_path}")
                        continue

                    # --- NEW: Add progress indicator logging ---
                    if idx % 10 == 0 or idx == len(all_files_to_scan):
                        progress_pct = (idx / len(all_files_to_scan)) * 100
                        logger.info(f"Scan Progress: {idx}/{len(all_files_to_scan)} files parsed ({progress_pct:.1f}%).")

                    file_info = self.code_intelligence_service.parse_file(relative_path, file_content)

                    if file_info:
                        # Update the project structure map with the detailed parsed info
                        self.code_intelligence_service._update_project_structure_map_with_file_info(
                            self.project_state, # type: ignore
                            relative_path,
                            file_info
                        )

                        # Generate a simple text summary for the code_summaries dictionary
                        summary = self._generate_file_summary(file_info, relative_path)
                        file_summaries[relative_path] = summary
                        # --- FIX for test_workflow_manager ---
                        # If a model file was parsed, update the defined_models state
                        if file_info.file_type == "django_model" and file_info.django_model_details:
                            app_name = Path(relative_path).parent.name
                            self.project_state.defined_models[app_name] = [m.name for m in file_info.django_model_details.models]
                        self.logger.debug(f"Parsed: {summary}")

                except Exception as e:
                    self.logger.warning(f"Failed to parse file {file_path}: {e}")
                    continue
            
            # === END NEW/MODIFIED SECTION ===

            # Step 3: Update project state with all summaries
            self.logger.info(f"Step 3/5: Updating project state with {len(file_summaries)} file summaries...")
            if self.project_state:
                self.project_state.code_summaries.update(file_summaries)

            # Step 4: Detect Django apps from INSTALLED_APPS
            self.logger.info("Step 4/5: Analyzing Django project structure...")

            if self.project_state and self.project_state.framework == "django":
                # Find settings.py
                settings_files = list(self.file_system_manager.project_root.rglob("settings.py"))

                if settings_files:
                    settings_file = settings_files[0]
                    relative_settings = str(settings_file.relative_to(self.file_system_manager.project_root))

                    # Parse settings.py using CodeIntelligenceService
                    settings_content = self.file_system_manager.read_file(relative_settings)
                    if settings_content:
                        settings_info = self.code_intelligence_service.parse_file(relative_settings, settings_content)

                        if settings_info and settings_info.django_settings_details:
                            # Extract installed apps from the parsed settings
                            installed_apps = settings_info.django_settings_details.key_settings.get("INSTALLED_APPS", [])

                            # Filter to get only user apps
                            user_apps = [
                                app.split('.')[0] for app in installed_apps
                                if not app.startswith('django.contrib') and not app.startswith('django.')
                            ]

                            self.project_state.registered_apps = set(user_apps)
                            self.logger.info(f"Detected {len(user_apps)} user apps from settings.py: {sorted(user_apps)}")

            # Step 5: Save the populated state
            self.logger.info("Step 5/5: Saving populated project state...")
            if self.project_state:
                self.memory_manager.save_project_state(self.project_state)

            self.logger.info("="*60)
            self.logger.info("✅ INITIAL PROJECT SCAN COMPLETE")
            self.logger.info(f"   - Scanned: {len(file_summaries)} files")
            if self.project_state:
                self.logger.info(f"   - Detected apps: {len(self.project_state.registered_apps)}")
                self.logger.info(f"   - Detected models: {sum(len(models) for models in self.project_state.defined_models.values())}")
            self.logger.info("="*60)

        except Exception as e:
            self.logger.error(f"Initial project scan failed: {e}", exc_info=True)

    @staticmethod
    def _generate_file_summary(file_info: FileStructureInfo, relative_path: str) -> str:
        """Generates a one-line summary string from a parsed FileStructureInfo object."""
        summary_parts = []
        if file_info.python_details:
            summary_parts.append(f"Imports: {len(file_info.python_details.imports)}")
            summary_parts.append(f"Funcs: {len(file_info.python_details.functions)}")
            summary_parts.append(f"Classes: {len(file_info.python_details.classes)}")
        if file_info.django_model_details and file_info.django_model_details.models:
            summary_parts.append(f"Models: {len(file_info.django_model_details.models)}")
        if file_info.django_view_details and file_info.django_view_details.views:
            summary_parts.append(f"Views: {len(file_info.django_view_details.views)}")
        if file_info.html_details:
            form_count = len(file_info.html_details.forms)
            if form_count > 0:
                summary_parts.append(f"Forms: {form_count}")
        if file_info.css_details:
            summary_parts.append(f"CSS Rules: {len(file_info.css_details.rules)}")
        if file_info.js_details:
            summary_parts.append(f"JS Funcs: {len(file_info.js_details.functions)}")

        summary_text = f"{relative_path}: " + ", ".join(summary_parts) if summary_parts else f"{relative_path}: Parsed"
        return summary_text

    def can_continue(self) -> Optional[ProjectFeature]:
        """
        Checks if there is a feature in a continuable state.
        This is the authoritative check for the UI.
        """
        if not self.project_state or not self.project_state.current_feature_id:
            # If no current_feature_id, check for ANY continuable feature as a fallback.
            if self.project_state and self.project_state.features:
                for feature in self.project_state.features:
                    if feature.status in self.get_continuable_statuses():
                        logger.info(f"Found a continuable feature ('{feature.name}') as a fallback for continuation.")
                        return feature
            return None # No current feature and no fallback found.

        feature = self.project_state.get_feature_by_id(self.project_state.current_feature_id)
        if feature and feature.status in self.get_continuable_statuses():
            return feature
        
        return None

    def get_continuable_statuses(self) -> set[FeatureStatusEnum]:
        """Returns a set of statuses that are considered continuable."""
        continuable_statuses = {
            FeatureStatusEnum.IDENTIFIED,
            FeatureStatusEnum.PLANNED,
            FeatureStatusEnum.IMPLEMENTING,
            FeatureStatusEnum.TASKS_IMPLEMENTED,
            FeatureStatusEnum.GENERATING_FEATURE_TESTS,
            FeatureStatusEnum.FEATURE_TESTING,
            FeatureStatusEnum.FEATURE_TESTING_FAILED,
            FeatureStatusEnum.REVIEWING
        }
        return continuable_statuses

    def _project_has_code(self) -> bool:
        """
        Checks if the project directory has signs of existing code, which helps in
        detecting a corrupted (empty) state file in a non-empty project.
        """
        if not self.file_system_manager or not self.file_system_manager.project_root.exists():
            return False
        
        # Check for common Django files/directories that indicate a non-empty project
        indicators = ["manage.py", "db.sqlite3", "requirements.txt"]
        for indicator in indicators:
            if (self.file_system_manager.project_root / indicator).exists():
                return True
        
        # As a fallback, check for any Python files other than in a venv
        for path in self.file_system_manager.project_root.rglob("*.py"):
            if 'venv' not in path.parts and '.venv' not in path.parts:
                return True # Found a Python file outside a virtual environment
                
        return False

    async def _call_llm_with_error_handling(
        self,
        agent_type_str: Literal["Tars", "Case"],
        messages: List[ChatMessage],
        feature_or_task_id: str,
        temperature: float
    ) -> ChatMessage:
        logger.debug(f"Calling LLM ({agent_type_str}) for '{feature_or_task_id}' with temperature: {temperature}")
        if not self.agent_manager:
            raise RuntimeError("AgentManager not available in WorkflowManager.")

        system_prompt = messages[0]
        user_messages = messages[1:]
        
        while True:
            # --- NEW: Check for stop signal before making an expensive LLM call ---
            if self.stop_event.is_set():
                logger.info("Stop requested. Halting LLM call.")
                raise InterruptedError("Workflow stopped by user during LLM call.")
            # --- END NEW ---

            try:
                response = await asyncio.to_thread(self.agent_manager.invoke_agent, system_prompt, user_messages, temperature)
                return response
            except (AuthenticationError, RateLimitError) as api_error:
                logger.warning(f"API error during LLM call for {feature_or_task_id}: {api_error}")
                error_type_str = "AuthenticationError" if isinstance(api_error, AuthenticationError) else "RateLimitError"
                if self._request_api_key_update_cb:
                    self.progress_callback({"message": f"{error_type_str}. Waiting for user action..."})
                    
                    # --- FIX: Gather all required arguments for the callback ---
                    provider_config = self.config_manager.providers_config.get(self.agent_manager.provider_id, {})
                    key_name_in_use = provider_config.get("api_key_name", "UNKNOWN_KEY")
                    provider_display_name = provider_config.get("display_name", self.agent_manager.provider_id)
                    agent_desc = f"{provider_display_name} ({self.agent_manager.model_id})"

                    new_key, should_retry = await self._request_api_key_update_cb(
                        agent_desc,
                        error_type_str,
                        key_name_in_use
                    )
                    # --- END FIX ---

                    if new_key:
                        self.progress_callback({"message": "New API key provided. Re-initializing agent and retrying..."})
                        # --- FIX: Explicitly re-initialize the agent with the new key ---
                        await asyncio.to_thread(
                            self.agent_manager.reinitialize_agent_with_new_key,
                            new_key
                        )
                        continue  # Retry the LLM call with the newly configured agent
                    elif should_retry:
                        self.progress_callback({"message": "Continuing with existing key. Retrying..."})
                        await asyncio.sleep(RETRY_DELAY_SECONDS) # Add a small delay before retrying
                        continue # Retry the LLM call
                    else:
                        # User cancelled
                        raise InterruptedError(f"User cancelled operation after {error_type_str}.")
                else: # Fallback if callback is not provided
                    logger.error("API error occurred but no API key update callback is configured.")
                    raise InterruptedError("API error occurred and no recovery mechanism is available.") from api_error # type: ignore
            except requests.exceptions.RequestException as net_error:
                logger.error(f"Network error during LLM call for {feature_or_task_id}: {net_error}")
                self.progress_callback({"error": f"Network Error: {net_error}"})
                if self._request_network_retry_cb:
                    self.progress_callback({"message": "Network error. Waiting for user to retry..."})
                    should_retry_network = await self._request_network_retry_cb(f"Agent ({self.agent_manager.model_id})", str(net_error))
                    if should_retry_network:
                        self.progress_callback({"message": "Retrying network call..."})
                        await asyncio.sleep(2)
                        continue
                    else:
                        logger.error(f"User chose not to retry network error during {feature_or_task_id}.")
                        raise InterruptedError("Network error and user chose not to retry.") from net_error
                else:
                    logger.error("No network retry callback available. Raising error.")
                    raise

        # Initialize state variables
        self.project_state: Optional[ProjectState] = None
        self.workflow_context: Dict[str, Any] = self.memory_manager.load_workflow_context()
        logger.info("WorkflowManager instance created for Adaptive Workflow.")

    def _report_error(self, message: str, is_fatal: bool = False):
        logger.error(message)
        self.progress_callback({"error": message})

    def _report_system_message(self, message: str):
        logger.info(message)
        self.progress_callback({"system_message": message})

    def request_stop(self):
        """
        Public method called by the UI to signal that the workflow should stop.
        Sets both the asyncio event for the main loop and the threading event for the command executor.
        """
        self.stop_event.set()
        self.stop_event_thread.set()
        logger.info("Stop requested. Signaling all components.")

    async def initialize_project(self, project_root: str, framework: str, initial_prompt: str, is_new_project: bool): # type: ignore
        logger.info(f"Initializing project. Root: '{project_root}', Framework: '{framework}'" )
        self.progress_callback({"increment": 5, "message": "Loading project state..."})

        loaded_state: Optional[ProjectState] = self.memory_manager.load_project_state()
        
        is_new_project_setup = is_new_project
        if loaded_state and loaded_state.framework != framework:
            logger.warning(f"Loaded project state framework ('{loaded_state.framework}') does not match selected framework ('{framework}'). Discarding old state.")
            self.memory_manager.clear_project_state()
            loaded_state = None
            is_new_project_setup = True

        if loaded_state:
            self.project_state = loaded_state # type: ignore
            self.project_state.root_path = project_root
            logger.info("Loaded existing project state successfully.")
            self.progress_callback({"increment": 10, "message": "Loaded existing project state."})
        else:
            is_new_project_setup = True

        if is_new_project_setup:
            logger.info("No valid existing project state found. Creating new state and performing initial setup.")
            safe_project_name = re.sub(r'\W|^(?=\d)', '_', self.file_system_manager.project_root.name).lower() or "my_project"
            
            self.project_state = ProjectState(
                project_name=safe_project_name,
                framework=framework,
                root_path=project_root,
                cumulative_docs=f"# {safe_project_name} - Technical Documentation\n\nFramework: {framework}\n",
            )
            self.progress_callback({"increment": 8, "message": "Created new project state."})

            try:
                logger.info("Performing initial framework setup for new project...")
                # We assume self._perform_initial_framework_setup exists and is correct
                await self._perform_initial_framework_setup(framework)
                logger.info("Initial framework setup completed successfully.")
                self.progress_callback({"increment": 15, "message": "Initial framework setup complete."})
            except Exception as setup_e:
                logger.exception("Fatal error during initial framework setup.")
                self._report_error(f"Initial framework setup failed: {setup_e}", is_fatal=True)
                if self.project_state: self.memory_manager.save_project_state(self.project_state) # type: ignore
                raise RuntimeError(f"Initial framework setup failed: {setup_e}") from setup_e
        
        # Save the initialized or loaded state.
        
        if initial_prompt:
            await self.run_adaptive_workflow(initial_prompt)
        elif self.project_state:
            # --- FIX: Ensure state is saved even if no prompt is run. ---
            # This is crucial for when an existing project is loaded. It ensures the
            # loaded state (including any `current_feature_id` found by `can_continue`)
            # is persisted, allowing the UI to correctly detect the "Continue" state.
            self.memory_manager.save_project_state(self.project_state) # type: ignore
            logger.info("Project initialized without an initial prompt. Ready for user input.")
            self.progress_callback({"increment": 100, "message": "Project loaded. Ready."})
        
        logger.info("Project initialization complete.")

    def _create_dummy_prompts(self) -> FrameworkPrompts:
        """Creates a dummy FrameworkPrompts object to satisfy legacy initialization paths."""
        dummy_chat_message: ChatMessage = {"role": "system", "content": "This is a dummy prompt for adaptive workflow."}
        return FrameworkPrompts(
            system_tars_markdown_planner=dummy_chat_message,
            system_case_executor=dummy_chat_message,
            system_tars_validator=dummy_chat_message,
            system_tars_error_analyzer=dummy_chat_message,
            system_tars_debugger=dummy_chat_message,
            system_tars_triage_engineer=dummy_chat_message,
            system_case_code_fixer=dummy_chat_message,
            system_tars_deep_analyzer=dummy_chat_message,
            system_case_remediation=dummy_chat_message
        )

    async def handle_new_prompt(self, prompt: str): # type: ignore
        if not self.project_state:
            self._report_error("Cannot process request: Project is not properly loaded.", is_fatal=True)
            raise RuntimeError("Project state not initialized. Call initialize_project first.")

        logger.info(f"Handling new prompt: '{prompt[:100]}...'")
        # If the prompt is empty, it's a signal to continue the last feature.
        if not prompt and self.project_state and self.project_state.current_feature_id:
            logger.info("Empty prompt received, treating as a 'continue' request.")
            await self.run_adaptive_workflow(user_request="") # Pass empty to signal continuation
        elif prompt:
            await self.run_adaptive_workflow(user_request=prompt)
        else:
            self._report_error("Cannot continue: No active feature found in project state.", is_fatal=False)

    async def run_adaptive_workflow(self, user_request: str):
        """
        Orchestrates the new TARS/CASE adaptive workflow.
        """
        # --- NEW: Reset stop events at the beginning of a run ---
        self.stop_event.clear()
        self.stop_event_thread.clear()
        # --- END NEW ---

        if not self.project_state:
            self._report_error("Cannot run adaptive workflow: Project state is not initialized.", is_fatal=True)
            return
        
        # --- SECURITY: Sanitize and validate the user's high-level request ---
        try:
            sanitized_request = sanitize_and_validate_input(user_request)
            if sanitized_request:
                logger.info(f"Starting adaptive workflow for sanitized request: '{sanitized_request[:100]}'...")
            else:
                logger.info("Starting adaptive workflow to continue previous feature.")
        except ValueError as e:
            self._report_error(f"Invalid user request: {e}", is_fatal=True)
            logger.error(f"Workflow stopped due to invalid user request: {e}")
            return
        # --- END SECURITY ---

        self.progress_callback({"message": "Starting adaptive workflow..."})

        # For the new adaptive workflow, we don't need framework-specific prompts.
        # We create a dummy object to satisfy components that still expect it.
        self.prompts = self._create_dummy_prompts()

        # --- NEW: Load framework-specific adaptive prompts ---
        framework_adaptive_rules = ""
        try:
            # Dynamically import the adaptive_prompts from the plugin directory
            module_name = f"src.plugins.{self.project_state.framework}.adaptive_prompts"
            adaptive_prompts_module = importlib.import_module(module_name)
            
            # Get the rules string (convention: DJANGO_ADAPTIVE_AGENT_RULES)
            rules_variable_name = f"{self.project_state.framework.upper()}_ADAPTIVE_AGENT_RULES"
            if hasattr(adaptive_prompts_module, rules_variable_name):
                framework_adaptive_rules = getattr(adaptive_prompts_module, rules_variable_name)
                logger.info(f"Successfully loaded adaptive agent rules for '{self.project_state.framework}'.")
            else:
                logger.warning(f"Could not find '{rules_variable_name}' in {module_name}. Using generic prompts.")
        except ImportError:
            logger.info(f"No adaptive_prompts.py found for framework '{self.project_state.framework}'. Using generic prompts.")
        except Exception as e:
            logger.error(f"Error loading adaptive prompts for framework '{self.project_state.framework}': {e}")
        # --- END NEW ---

        # --- MODIFIED: Only break down features if it's a new, non-empty request ---
        # If the sanitized_request is empty, it's a signal to continue the current feature.
        # The main `while (feature := self._select_next_feature()):` loop will correctly
        # pick up the `current_feature_id` from the project state.
        if not sanitized_request:
            logger.info("Empty request received. Proceeding to select and continue the current feature.")
            if not self.can_continue():
                self._report_error("Continue was requested, but no active feature was found to resume.", is_fatal=False)
                return
        elif sanitized_request: # This is a new request, so we break it down into features.
            # 1. TARS: Break down the user request into features
            self.progress_callback({"message": "TARS: Breaking down request into features..."})
            try:
                breakdown_prompt = TARS_FEATURE_BREAKDOWN_PROMPT.format( # type: ignore
                    user_request=sanitized_request, # Use the sanitized request
                    tech_stack=self.project_state.framework
                )
                messages = [
                    {"role": "system", "content": "You are an expert software architect."},
                    {"role": "user", "content": breakdown_prompt}
                ]
                response = await self._call_llm_with_error_handling("Tars", messages, "feature_breakdown", 0.3)
                
                raw_response = response['content'] # type: ignore
                # The new prompt asks for a numbered list under a "Features:" header.
                # We parse this by finding lines that start with a number and a dot,
                # then strip the numbering to get the feature description.
                feature_list = [
                    re.sub(r"^\d+\.\s*", "", line).strip()
                    for line in raw_response.split('\n')
                    if re.match(r"^\d+\.\s+", line.strip())
                ]

                if not feature_list:
                    self._report_system_message("TARS provided a direct instruction. Executing as a single feature.")
                    feature_list = [sanitized_request]

                self._report_system_message(f"TARS identified {len(feature_list)} features: {', '.join(feature_list)}")
                
                # Add these new features to the project state
                for i, desc in enumerate(feature_list):
                    new_feature = ProjectFeature(id=f"feat_{int(time.time())}_{i}", name=desc, description=desc) # type: ignore
                    self.project_state.features.append(new_feature) # type: ignore
                self.memory_manager.save_project_state(self.project_state) # type: ignore

            except (Exception, json.JSONDecodeError) as e:
                self._report_error(f"Failed to break down features: {e}", is_fatal=True)
                logger.exception("Error during TARS feature breakdown.")
                return

        # 2. TARS: Loop through features and delegate to CASE, using enumerate to get the index
        while (feature := self._select_next_feature()):
            if self.stop_event.is_set():
                logger.info("Stop requested. Halting workflow before starting next feature.")
                raise InterruptedError("Workflow stopped by user.")

            self.project_state.current_feature_id = feature.id
            feature.status = FeatureStatusEnum.IMPLEMENTING
            self.memory_manager.save_project_state(self.project_state)

            feature_desc = feature.description
            # Correctly get the total number of features for the progress message
            total_features = len(self.project_state.features) # type: ignore
            # --- FIX: Use enumerate on the features list to get a reliable index ---
            # This avoids an UnboundLocalError if the feature breakdown step is skipped.
            current_feature_index = next((idx for idx, f in enumerate(self.project_state.features) if f.id == feature.id), -1) # type: ignore
            self.progress_callback({"message": f"Feature {current_feature_index + 1}/{total_features}: '{feature_desc}'"})
            logger.info(f"Starting feature {current_feature_index + 1}: {feature_desc}")

            case_agent = AdaptiveAgent(
                agent_manager=self.agent_manager,
                tech_stack=self.project_state.framework,
                framework_rules=framework_adaptive_rules, # Pass the loaded rules
                project_state=self.project_state,
                file_system_manager=self.file_system_manager,
                command_executor=self.command_executor,
                memory_manager=self.memory_manager,
                code_intelligence_service=self.code_intelligence_service,
                show_input_prompt_cb=self.show_input_prompt_cb,
                progress_callback=self.progress_callback,
                show_file_picker_cb=self.show_file_picker_cb,
                stop_event=self.stop_event, # Pass the stop event
                request_command_execution_cb=self.request_command_execution_cb # Pass the UI command callback
            )

            current_feature_instruction = feature_desc
            # ✅ FIX: Track cumulative work across ALL remediation attempts
            cumulative_modified_files = set()  # Use set to avoid duplicates
            complete_work_log = []  # Track all work history across attempts
            
            # 3. TARS: Verification and Remediation Loop
            for attempt in range(MAX_REMEDIATION_ATTEMPTS):
                # --- NEW: Check for stop signal within the loop ---
                if self.stop_event.is_set():
                    logger.info("Stop requested. Halting workflow during feature implementation.")
                    raise InterruptedError("Workflow stopped by user.")
                # --- END NEW ---
                self.progress_callback({"message": f"CASE: Working on feature (Attempt {attempt+1})..."})
                try:
                    newly_modified_files, work_log = await case_agent.execute_feature(
                        current_feature_instruction
                    )
                    # If the feature execution completes without error, it means the stop event was not triggered during its run.
                    # We can proceed with verification.
                    if work_log:
                        self.progress_callback({"agent_name": "CASE", "agent_message": "Work History:\n" + "\n".join(f"- {log}" for log in work_log)})
                    # ✅ FIX: Accumulate files and work log across attempts
                    cumulative_modified_files.update(newly_modified_files)
                    complete_work_log.extend(work_log)
                    # Initialize variables for the success path
                    completion_percentage = -1 # Use a sentinel value
                    issues = []
                except Exception as e:
                    # --- FIX: Check for InterruptedError by name to handle multiple definitions ---
                    if e.__class__.__name__ == 'InterruptedError':
                        # If the user stops the agent, re-raise the error to be caught
                        # by the outer loop, which will gracefully terminate the workflow.
                        raise
                    # --- END FIX ---
    
                    self._report_error(f"CASE agent failed during execution: {e}")
                    logger.exception(f"Error in CASE agent for feature: {current_feature_instruction}")
                    
                    # ✅ FIX: Get work history safely
                    work_log = case_agent.work_history if hasattr(case_agent, 'work_history') else []
                    
                    # ✅ FIX: Check filesystem for actual completed files
                    verified_completed_files = []
                    logger.info(f"Verifying existence of {len(cumulative_modified_files)} file(s) from cumulative_modified_files...")
                    
                    for filepath in cumulative_modified_files:
                        if self.file_system_manager.file_exists(filepath):
                            verified_completed_files.append(filepath)
                            logger.info(f"✓ Verified file exists on disk: {filepath}")
                        else:
                            logger.warning(f"✗ File not found on disk: {filepath}")
                    
                    # ✅ FIX: Calculate real completion percentage based on verified files
                    if verified_completed_files:
                        # Progress WAS made despite the error!
                        num_verified = len(verified_completed_files)
                        num_expected = max(len(cumulative_modified_files), 3)  # Assume at least 3 files per feature
                        
                        completion_percentage = min(90, int((num_verified / num_expected) * 100))
                        
                        logger.warning(
                            f"Despite error, {num_verified} file(s) were successfully created and verified on disk: "
                            f"{verified_completed_files}"
                        )
                        
                        issues = [
                            f"Agent execution was interrupted by error: {str(e)[:150]}",
                            f"However, {num_verified} file(s) were successfully created before the error occurred.",
                            f"Completed files: {', '.join(verified_completed_files[:5])}"
                        ]
                    else:
                        # No verified files found - true failure
                        completion_percentage = 0
                        issues = [f"The agent's execution was interrupted by an error: {e}"]
                try:
                    # Only call TARS for verification if the agent execution didn't already fail
                    if completion_percentage == -1:
                        # ✅ FIX: Build complete code map from ALL accumulated files
                        # This now includes files from WRITE_FILE, PATCH_FILE, and GET_FULL_FILE_CONTENT
                        code_written_map = {}
                        for file_path in cumulative_modified_files:
                            # Read the current content of the file from disk. This ensures TARS sees
                            # the final state after all writes, patches, or the original state for inspections.
                            if self.file_system_manager.file_exists(file_path):
                                try:
                                    content = self.file_system_manager.read_file(file_path)
                                    code_written_map[file_path] = content
                                except Exception as e:
                                    logger.warning(f"Could not read modified file '{file_path}' for verification: {e}")
                            else:
                                logger.warning(f"File '{file_path}' was in the modified list but not found on disk for verification.")
                            # --- END BUG FIX ---
                        
                        code_written_str = "\n\n".join(
                            f"--- {path} ---\n{content}" 
                            for path, content in code_written_map.items()
                        )
                        
                        # FIX: Replace 'or' logic with an explicit check for an empty string.
                        # This prevents sending a contradictory message when command-based actions are used.
                        if not code_written_str:
                            code_written_str = (
                                "No explicit file writes were detected via WRITE_FILE/PATCH_FILE. "
                                "However, files may have been created by commands in the work log. "
                                "Verify completion based on successful command execution in the work log."
                            )

                        # --- NEW: Generate and include frontend validation summary ---
                        final_validator = FrontendValidator(self.project_state.project_structure_map)
                        final_report = final_validator.validate()
                        frontend_validation_summary = self._generate_frontend_validation_summary(final_report)
                        # --- END NEW ---

                        verification_prompt = TARS_VERIFICATION_PROMPT.format(
                            feature_description=feature_desc,
                            work_log="\n".join(complete_work_log),
                            code_written=code_written_str,
                            tech_stack=self.project_state.framework, # type: ignore
                            frontend_validation_summary=frontend_validation_summary
                        )
                        messages = [
                            {"role": "system", "content": "You are a quality assurance expert."},
                            {"role": "user", "content": verification_prompt}
                        ]
                        verify_response_msg = await self._call_llm_with_error_handling("Tars", messages, f"verify_feature_{current_feature_index + 1}", 0.2)
                        verification_result_raw = verify_response_msg['content'].strip()
                        
                        # --- NEW: Parse JSON verification result ---
                        try:
                            # Clean up potential markdown fences around the JSON
                            cleaned_json_str = re.sub(r"```(?:json)?\s*(.*)\s*```", r"\1", verification_result_raw, flags=re.DOTALL)
                            verification_data = json.loads(cleaned_json_str)
                            completion_percentage = verification_data.get("completion_percentage", 0)
                            issues = verification_data.get("issues", ["TARS provided an invalid verification response."]) # type: ignore
                        except json.JSONDecodeError:
                            logger.warning(
                                f"TARS verification response was not valid JSON. "
                                f"Falling back to filesystem verification. Raw response: {verification_result_raw[:200]}"
                            )
                            
                            # ✅ FIX: Instead of assuming 0%, check filesystem for actual completed files
                            verified_files = []
                            logger.info(
                                f"Verifying existence of {len(cumulative_modified_files)} file(s) "
                                f"from cumulative_modified_files..."
                            )
                            
                            for filepath in cumulative_modified_files:
                                if self.file_system_manager.file_exists(filepath):
                                    verified_files.append(filepath)
                                    logger.info(f"✓ Verified file exists on disk: {filepath}")
                                else:
                                    logger.warning(f"✗ File not found on disk: {filepath}")
                            
                            # Calculate real completion percentage based on verified files
                            if verified_files:
                                # Progress WAS made despite JSON parsing failure!
                                num_verified = len(verified_files)
                                num_expected = max(len(cumulative_modified_files), 3)
                                
                                completion_percentage = min(90, int((num_verified / num_expected) * 100))
                                
                                logger.warning(
                                    f"Despite JSON parsing error, {num_verified} file(s) were successfully "
                                    f"created and verified on disk: {verified_files}"
                                )
                                
                                issues = [
                                    f"TARS returned malformed response, but {num_verified} file(s) were verified on disk.",
                                    f"Completed files: {', '.join(verified_files[:5])}",
                                    f"The verification agent returned non-JSON prose instead of structured response."
                                ]
                            else:
                                # No verified files found - true failure
                                completion_percentage = 0
                                issues = [
                                    f"The verification agent returned a malformed (non-JSON) response AND "
                                    f"no files were found on disk: {verification_result_raw[:200]}"
                                ]
                        # --- END NEW ---
                    
                    # This block now correctly handles both successful verification and all failure cases (LLM error, JSON error, or <100% completion)
                    if completion_percentage < 100:
                        # This branch is taken if the feature is not 100% complete, including JSON decode errors where percentage is 0.
                        verification_failure_reason = "\n- ".join(issues)
                        self._report_system_message(f"TARS verification: {completion_percentage}% complete. Issues found:\n- {verification_failure_reason}")
                        logger.warning(f"Verification failed for feature '{feature_desc}'. Issues: {verification_failure_reason}")
                        
                        if attempt < MAX_REMEDIATION_ATTEMPTS - 1:
                            remediation_prompt = TARS_REMEDIATION_PROMPT.format(
                                feature_description=feature_desc,
                                issues=verification_failure_reason
                            )
                            messages = [ # type: ignore
                                {"role": "system", "content": "You are a lead software architect."},
                                {"role": "user", "content": remediation_prompt}
                            ]
                            remediation_response = await self._call_llm_with_error_handling("Tars", messages, f"remediate_feature_{current_feature_index + 1}", 0.3)
                            current_feature_instruction = remediation_response['content']
                            # --- BUG FIX #3: Don't retry startproject if project exists ---
                            if "startproject" in current_feature_instruction.lower():
                                if self._project_has_code():
                                    logger.warning("Remediation plan suggested 'startproject', but project already exists. Skipping remediation to avoid loop. Marking feature as failed.")
                                    self._report_error(f"Feature '{feature_desc}' failed. Remediation suggested re-creating an existing project.", is_fatal=False)
                                    break # Exit the remediation loop
                            # --- END BUG FIX #3 ---
                            self._report_system_message("TARS: Created remediation plan. Retrying implementation.")
                            logger.info(f"Generated new remediation instruction: {current_feature_instruction}")
                        else:
                            self._report_error(f"Feature '{feature_desc}' failed verification after {MAX_REMEDIATION_ATTEMPTS} attempts.", is_fatal=False)
                            logger.error(f"Failed to remediate feature '{feature_desc}' after max attempts.")
                            break # Exit the remediation loop after max attempts
                    else: # completion_percentage is 100
                        self._report_system_message(f"TARS verified feature '{feature_desc}' successfully.")
                        logger.info(f"Feature '{feature_desc}' verified successfully on attempt {attempt+1}.")
                        feature.status = FeatureStatusEnum.MERGED
                        break # Exit the remediation loop on success                    

                except Exception as e:
                    # ✅ FIX: Log error in complete work log
                    complete_work_log.append(f"ERROR during attempt {attempt + 1}: {str(e)}")
                    self._report_error(f"An error occurred during verification/remediation: {e}")
                    logger.exception(f"Error in TARS verification/remediation loop for feature: {feature_desc}")
                    break
            else:
                # This block runs if the remediation loop finishes without a `break` (i.e., max attempts reached)
                feature.status = FeatureStatusEnum.IMPLEMENTATION_FAILED
                self._report_error(f"Feature '{feature.description}' could not be successfully verified after {MAX_REMEDIATION_ATTEMPTS} attempts.", is_fatal=False)
                logger.error(f"Failed to implement feature '{feature.description}' after max attempts.")

        # --- Final state saving and cleanup ---
        try:
            if self.project_state:
                self.project_state.current_feature_id = None
                self.memory_manager.save_project_state(self.project_state)
        except InterruptedError as e:
            logger.warning(f"Workflow gracefully stopped by user: {e}")
            raise  # Re-raise the exception to be caught by the final handler in the UI thread.
        except Exception as final_e:
            logger.error(f"Error during final feature state update: {final_e}")

        self.progress_callback({"increment": 100, "message": "Adaptive workflow complete."})
        logger.info("Adaptive workflow finished.")
        
        # --- NEW: Log performance report at the end of the workflow ---
        performance_monitor.log_report()
        performance_monitor.reset() # Reset for the next run

        # Other helper methods like get_current_state_for_ui, save_project_state, etc. can remain.
    def get_project_state(self):
        return self.project_state

    def _generate_frontend_validation_summary(self, report: FrontendValidationReport) -> str:
        """Formats the frontend validation report into a string for the TARS prompt."""
        if not report.issues:
            return "No frontend validation issues found. Looks good."

        from collections import defaultdict
        severity_counts = defaultdict(int)
        category_counts = defaultdict(int)
        for issue in report.issues:
            severity_counts[issue.severity] += 1
            category_counts[issue.category] += 1

        summary_lines = [f"Total Issues: {report.total_issues}"]
        summary_lines.append("By Severity: " + ", ".join(f"{count} {sev}" for sev, count in severity_counts.items()))
        summary_lines.append("By Category: " + ", ".join(f"{count} {cat}" for cat, count in category_counts.items()))

        return "\n".join(summary_lines)


    def save_current_project_state(self):
        if self.project_state:
            self.memory_manager.save_project_state(self.project_state)


    async def _perform_initial_framework_setup(self, framework: str) -> None:
        """
        Performs the initial setup for a new project based on the framework.
        This typically involves creating a virtual environment, installing base
        requirements, and running initial framework commands (e.g., startproject).

        Uses self.command_executor for all operations.

        Args:
            framework: The name of the framework being set up.

        Raises:
            RuntimeError: If any setup command fails.
            FileNotFoundError: If required files (like requirements.txt) are missing.
        """
        if not self.project_state:
            raise RuntimeError("Project state not initialized for setup.")
        project_root = Path(self.project_state.root_path) # Use attribute access
        venv_path = project_root / "venv"
        requirements_file = project_root / "requirements.txt"

        logger.info(f"Starting initial setup for {framework} in {project_root}")
        self.progress_callback({"message": f"Setting up {framework} environment..."})

        try:
            # --- 1. Create Virtual Environment ---
            if not venv_path.exists():
                logger.info("Creating virtual environment (venv)...")
                self.progress_callback({"message": "Creating virtual environment..."})
                # Use command_executor to run 'python -m venv venv'
                # Determine the python executable to use (system python)
                python_executable = sys.executable or "python" # Default to 'python' if sys.executable is None
                # Construct the command string WITHOUT extra quotes around the executable
                venv_command = f'{python_executable} -m venv venv'
                # The complex remediation loop is overkill for these initial, reliable commands. We can execute them more directly.
                setup_task_id = f"setup_{int(time.time())}"
                logger.info(f"Requesting UI execution for command: `{venv_command}` (Task: {setup_task_id})")
                self.progress_callback({"action_details": f"Waiting for user to run: {venv_command}"})
 
                # Directly call the command execution callback, which is simpler than the full remediation loop.
                # This assumes the UI will handle the execution and return the result.
                # The `request_command_execution_cb` is expected to be an async function.
                setup_success, setup_output_json = await self.request_command_execution_cb( # type: ignore
                     setup_task_id,
                     venv_command,
                     "Create Python virtual environment"
                 )
 
                if not setup_success:
                    try:
                        # Attempt to parse a structured error from the JSON output.
                        error_details = json.loads(setup_output_json).get("stderr", setup_output_json)
                    except json.JSONDecodeError:
                        # Fallback to using the raw output if it's not valid JSON.
                        error_details = setup_output_json
                    logger.error(f"Initial setup command '{venv_command}' failed: {error_details}")
                    raise RuntimeError(f"Initial setup command '{venv_command}' failed: {error_details}")
                
                logger.info(f"Command '{venv_command}' executed successfully via UI on the first try.")
                logger.info("Virtual environment created successfully.")
                self.progress_callback({"increment": 5, "message": "Virtual environment created."})
            else:
                logger.info("Virtual environment already exists. Skipping creation.")
                self.progress_callback({"increment": 5, "message": "Virtual environment found."})
            
            # --- BUG FIX #13: Set venv_path in project state ---
            self.project_state.venv_path = str(venv_path.relative_to(project_root))
            logger.info(f"Set project_state.venv_path to: {self.project_state.venv_path}")

            # --- 2. Create/Update requirements.txt ---
            # Define base requirements based on framework
            base_requirements: List[str] = [] # Initialize for all Python-based frameworks
            if framework == "django":
                base_requirements = ["django~=4.2", "python-dotenv~=1.0"] # Example versions
            elif framework == "flask":
                base_requirements = ["flask~=2.3", "python-dotenv~=1.0"]
            elif framework == "nodejs":
                # Node.js uses package.json, handled later
                pass
            elif framework == "react":
                # React setup is different, handled below. No requirements.txt initially.
                pass
            else:
                logger.warning(f"No base requirements defined for framework: {framework}")

            if base_requirements:
                logger.info(f"Ensuring base requirements in {requirements_file.name}...")
                existing_reqs = set()
                if requirements_file.exists():
                    try:
                        with open(requirements_file, 'r', encoding='utf-8') as f:
                            # Read existing, filter comments/empty lines, normalize case
                            existing_reqs = {line.strip().lower() for line in f if line.strip() and not line.strip().startswith('#')}
                    except Exception as read_e:
                        logger.warning(f"Could not read existing requirements file: {read_e}. Overwriting.")
                        existing_reqs = set()

                # Add missing base requirements
                needs_update = False
                updated_reqs_content = ""
                if requirements_file.exists():
                     with open(requirements_file, 'r', encoding='utf-8') as f:
                         updated_reqs_content = f.read()

                for req in base_requirements:
                    req_base = req.split('~=')[0].split('==')[0].split('<')[0].split('>')[0].lower() # Normalize name
                    # Check if a version of the package is already listed
                    if not any(existing_req.startswith(req_base) for existing_req in existing_reqs):
                        logger.info(f"Adding '{req}' to requirements.")
                        updated_reqs_content += f"\n{req}"
                        needs_update = True

                if needs_update or not requirements_file.exists():
                    try:
                        with open(requirements_file, 'w', encoding='utf-8') as f:
                            f.write(updated_reqs_content.strip() + "\n")
                        logger.info(f"{requirements_file.name} created/updated.")
                    except Exception as write_e:
                        logger.error(f"Failed to write requirements file: {write_e}")
                        raise RuntimeError(f"Failed to write {requirements_file.name}: {write_e}") from write_e
                else:
                    logger.info(f"{requirements_file.name} already contains base requirements.")

            # --- 3. Install Requirements (Python frameworks) ---
            if framework in ["django", "flask"] and base_requirements and requirements_file.exists():
                logger.info(f"Installing requirements from {requirements_file.name} using venv pip...")
                self.progress_callback({"message": "Installing requirements..."})
                # CommandExecutor handles finding venv pip
                install_command = f"pip install -r {requirements_file.name}"
                # Use a simpler execution for initial setup, similar to venv creation.
                setup_task_id = f"setup_{int(time.time())}"
                logger.info(f"Requesting UI execution for command: `{install_command}` (Task: {setup_task_id})")
                self.progress_callback({"action_details": f"Waiting for user to run: {install_command}"})
 
                setup_success, setup_output_json = await self.request_command_execution_cb( # type: ignore
                     setup_task_id,
                     install_command,
                     "Install Python dependencies"
                 )
 
                if not setup_success:
                    try:
                        # Attempt to parse a structured error from the JSON output.
                        error_details = json.loads(setup_output_json).get("stderr", setup_output_json)
                    except json.JSONDecodeError:
                        # Fallback to using the raw output if it's not valid JSON.
                        error_details = setup_output_json
                    logger.error(f"Initial setup command '{install_command}' failed: {error_details}")
                    raise RuntimeError(f"Initial setup command '{install_command}' failed: {error_details}")
                
                logger.info(f"Command '{install_command}' executed successfully via UI on the first try.")
                logger.info("Requirements installed successfully.")
                await self._update_dependency_info() # BUG FIX #15
                self.progress_callback({"increment": 5, "message": "Requirements installed."})
            elif framework in ["django", "flask"] and base_requirements and not requirements_file.exists():
                 logger.warning(f"Cannot install requirements: {requirements_file.name} not found.")
                 # Decide if this is fatal. For now, log and continue.

            # --- 4. Framework Specific Init (startproject / npm init) ---
            if framework == "django":
                # Check if manage.py already exists (might happen if user ran setup manually)
                manage_py_path = project_root / "manage.py"
                project_dir_path = project_root / self.project_state.project_name # Use attribute access

                if not manage_py_path.exists() and not project_dir_path.exists():
                    logger.info(f"Running django-admin startproject {self.project_state.project_name}...") # Use attribute access
                    self.progress_callback({"message": "Running django-admin startproject..."})
                    # CommandExecutor handles finding venv django-admin
                    startproject_command = f"django-admin startproject {self.project_state.project_name} ." # Use attribute access, note the '.' for current dir
                    # Use a simpler execution for initial setup.
                    setup_task_id = f"setup_{int(time.time())}"
                    logger.info(f"Requesting UI execution for command: `{startproject_command}` (Task: {setup_task_id})")
                    self.progress_callback({"action_details": f"Waiting for user to run: {startproject_command}"})
 
                    setup_success, setup_output_json = await self.request_command_execution_cb( # type: ignore
                         setup_task_id,
                         startproject_command,
                         "Create Django project structure"
                     )
 
                    if not setup_success:
                        try:
                            # Attempt to parse a structured error from the JSON output.
                            error_details = json.loads(setup_output_json).get("stderr", setup_output_json)
                        except json.JSONDecodeError:
                            # Fallback to using the raw output if it's not valid JSON.
                            error_details = setup_output_json
                        logger.error(f"Initial setup command '{startproject_command}' failed: {error_details}")
                        raise RuntimeError(f"Initial setup command '{startproject_command}' failed: {error_details}")
                    
                    logger.info(f"Command '{startproject_command}' executed successfully via UI on the first try.")
                    logger.info("django-admin startproject completed.")
                    self.progress_callback({"increment": 5, "message": "Django project created."})
                else:
                    logger.info("manage.py or project directory already exists. Skipping django-admin startproject.")
                    self.progress_callback({"increment": 5, "message": "Django project found."})

            elif framework == "node": # Ensure this matches the framework key used elsewhere (e.g., 'node' vs 'nodejs')
                package_json_path = project_root / "package.json"
                if not package_json_path.exists():
                    logger.info("Running npm init -y...")
                    self.progress_callback({"message": "Running npm init..."})
                    # CommandExecutor handles finding npm
                    npm_init_command = "npm init -y"
                    await self._execute_command_with_remediation(npm_init_command)
                    logger.info("npm init completed.")
                    self.progress_callback({"increment": 5, "message": "package.json created."})
                else:
                    logger.info("package.json already exists. Skipping npm init.")
                    self.progress_callback({"increment": 5, "message": "package.json found."})

                # Install base Node.js dependencies if needed (e.g., express)
                # This requires parsing package.json or defining base deps
                # Example: await asyncio.to_thread(self.command_executor.run_command, "npm install express")
                logger.info("Skipping base npm package installation for now.") # Placeholder

            elif framework == "flask":
                 logger.info("Flask setup complete (venv and requirements). No specific init command needed.")
                 self.progress_callback({"increment": 5, "message": "Flask environment ready."})
            
            elif framework == "react":
                logger.info(f"Starting React frontend setup in {project_root / 'frontend'}")
                self.progress_callback({"message": "Setting up React frontend..."})
                frontend_dir = project_root / "frontend"
                frontend_dir.mkdir(exist_ok=True) # Ensure frontend directory exists

                original_cmd_executor_root = self.command_executor.project_root
                self.command_executor.project_root = frontend_dir # Set CWD for CommandExecutor
                logger.info(f"Switched CommandExecutor CWD to: {self.command_executor.project_root} for React setup.")

                try:
                    logger.info("Running npx create-react-app .")
                    await self._execute_command_with_remediation("npx create-react-app .")
                    logger.info("create-react-app completed.")
                    self.progress_callback({"increment": 10, "message": "React app scaffolded."})
                    
                    logger.info("Installing axios and react-router-dom...")
                    await self._execute_command_with_remediation("npm install axios react-router-dom")
                    logger.info("axios and react-router-dom installed.")
                    self.progress_callback({"increment": 5, "message": "Core React dependencies installed."})
                finally:
                    self.command_executor.project_root = original_cmd_executor_root # Restore CWD
                    logger.info(f"Restored CommandExecutor CWD to: {self.command_executor.project_root} after React setup.")


            logger.info(f"Initial setup for {framework} completed.")

            # --- MOVED: Attempt Git Init and Initial Commit on New Project Setup ---
            # This should run AFTER successful framework setup.
            git_dir = project_root / ".git"
            if not git_dir.exists():
                logger.info("Attempting Git initialization...")
                self.progress_callback({"message": "Initializing Git repository..."})
                try:
                    await asyncio.to_thread(self.command_executor.run_command, "git init")
                    logger.info("Git repository initialized.")

                    # Add all files and make initial commit
                    await asyncio.to_thread(self.command_executor.run_command, "git add .")
                    initial_commit_msg = f"Initial project setup for {self.project_state.project_name}"
                    await asyncio.to_thread(self.command_executor.run_command, f'git commit -m "{initial_commit_msg}"')
                    logger.info("Initial Git commit created.")
                    # --- BUG FIX #14: Set active git branch ---
                    self.project_state.active_git_branch = "main" # Default for new repos
                    self.progress_callback({"increment": 18, "message": "Git repository initialized."})

                    # --- NEW: Add Performance Monitoring Middleware ---
                    logger.info("Adding performance monitoring middleware to the new Django project...")
                    self.progress_callback({"message": "Adding performance monitoring..."})
                    try:
                        # 1. Define middleware content and path
                        middleware_snippet_path = Path(__file__).parent.parent / "plugins" / "django" / "snippets" / "performance_monitoring_middleware.py"
                        if middleware_snippet_path.exists():
                            middleware_content = middleware_snippet_path.read_text()
                            
                            # Create the middleware directory and file within the app
                            app_name = self.project_state.project_name # Assuming app name is same as project for startproject
                            middleware_dir = project_root / app_name / "middleware"
                            middleware_file_path = middleware_dir / "performance.py"
                            
                            await asyncio.to_thread(self.file_system_manager.create_directory, middleware_dir.relative_to(project_root))
                            await asyncio.to_thread(self.file_system_manager.write_file, middleware_file_path.relative_to(project_root), middleware_content)
                            logger.info(f"Performance middleware written to {middleware_file_path}")

                            # 2. Modify settings.py to add middleware and logging
                            settings_path_str = f"{app_name}/settings.py"
                            settings_content = await asyncio.to_thread(self.file_system_manager.read_file, settings_path_str)

                            # Add middleware to the MIDDLEWARE list
                            middleware_str = f"    '{app_name}.middleware.performance.PerformanceMonitoringMiddleware',"
                            settings_content = re.sub(r"(\s*'django.contrib.sessions.middleware.SessionMiddleware',\n)", f"\\1{middleware_str}\n", settings_content, 1)

                            # Add logging configuration at the end of the file
                            logging_config_str = """

# --- Performance Logging Configuration ---
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'performance_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs/performance.log',
        },
    },
    'loggers': {
        'performance': {
            'handlers': ['performance_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
"""
                            settings_content += logging_config_str
                            await asyncio.to_thread(self.file_system_manager.write_file, settings_path_str, settings_content)
                            logger.info(f"Updated {settings_path_str} with performance middleware and logging config.")
                            self.progress_callback({"increment": 2, "message": "Performance monitoring configured."})
                        else:
                            logger.warning(f"Middleware snippet not found at {middleware_snippet_path}. Skipping performance monitoring setup.")
                    except Exception as perf_e:
                        logger.error(f"Failed to set up performance monitoring: {perf_e}")
                        # Don't make this a fatal error, just log it and continue.
                        self.progress_callback({"warning": "Could not set up performance monitoring."})
                    # --- END NEW ---
                except Exception as git_e: # Catch any other unexpected error in this block
                    logger.warning(f"Failed during Git initialization or initial commit after successful framework setup: {git_e}")
            else:
                logger.info("Git repository already exists. Skipping initialization.")
        except (RuntimeError, ValueError, FileNotFoundError, InterruptedError) as setup_e:
            # Catch errors specifically raised by command_executor or file ops
            logger.error(f"Initial setup failed: {setup_e}")
            raise # Re-raise the exception to be handled by the caller
        except Exception as e:
            # Catch any other unexpected errors
            logger.exception(f"Unexpected error during initial setup for {framework}")
            raise RuntimeError(f"Unexpected error during initial setup: {e}") from e
        finally:
            # --- DEFINITIVE FIX: Save state AFTER all setup is complete ---
            # This ensures the project state file is only created once the project is truly initialized.
            if self.project_state:
                self.memory_manager.save_project_state(self.project_state)
                logger.info("Project state saved after successful initial framework setup.")

    async def _update_dependency_info(self):
        """
        (BUG FIX #15) Parses requirements.txt and updates detailed_dependency_info.
        """
        if not self.project_state: return
        req_file = self.file_system_manager.project_root / "requirements.txt"
        if not req_file.exists(): return

        logger.info("Updating detailed dependency info from requirements.txt...")
        try:
            content = await asyncio.to_thread(self.file_system_manager.read_file, "requirements.txt")
            deps = {}
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    match = re.match(r"([a-zA-Z0-9\-_]+)[\s~=<>!]*([\d\.]*)?", line)
                    if match:
                        name, version = match.groups()
                        deps[name] = version or "any"
            self.project_state.detailed_dependency_info["pip"] = deps
            logger.info(f"Updated pip dependencies: {deps}")
        except Exception as e:
            logger.error(f"Failed to parse requirements.txt for dependency info: {e}")


    def _select_next_feature(self) -> Optional[ProjectFeature]:
        """
        Selects the next feature to work on based on status and dependencies.
        Halts if a critical feature has failed planning or execution.
        Prioritizes continuing the current feature if it's active.
        """
        if not self.project_state or not self.project_state.features:
            logger.debug("No features in project state to select from.")
            return None

        # Check if any feature is in a critical failed state that should halt progression
        for f_check in self.project_state.features:
            if f_check.status in ["planning_failed", "implementation_failed", "cancelled"]:
                if self.project_state.current_feature_id == f_check.id or \
                   not self.project_state.current_feature_id:
                    logger.warning(f"Workflow is halted because feature '{f_check.name}' ({f_check.id}) is in a failed state: {f_check.status}.")
                    return None

        # Prioritize continuing the current feature
        if self.project_state.current_feature_id:
            current_feature = self.project_state.get_feature_by_id(self.project_state.current_feature_id)
            if current_feature and current_feature.status not in ["merged", "planning_failed", "implementation_failed", "cancelled"]:
                logger.info(f"Continuing with current feature: '{current_feature.name}' ({current_feature.id}), Status: {current_feature.status}")
                return current_feature
            else:
                logger.info(f"Current feature '{current_feature.name if current_feature else self.project_state.current_feature_id}' is done or failed. Clearing current_feature_id.")
                self.project_state.current_feature_id = None
                # Save state immediately after clearing current_feature_id
                try:
                    if self.project_state: self.memory_manager.save_project_state(self.project_state)
                except Exception as e:
                    logger.error(f"Failed to save state after clearing current_feature_id: {e}")
        
        # If no current feature, or current feature is done/failed, find the next eligible one.
        logger.info("Looking for the next eligible feature to process...")
        # Define all non-terminal statuses that represent workable features.
        eligible_statuses = {
            FeatureStatusEnum.IDENTIFIED,
            FeatureStatusEnum.PLANNED,
            FeatureStatusEnum.IMPLEMENTING,
            FeatureStatusEnum.TASKS_IMPLEMENTED,
            FeatureStatusEnum.GENERATING_FEATURE_TESTS,
            FeatureStatusEnum.FEATURE_TESTING,
            FeatureStatusEnum.FEATURE_TESTING_FAILED, # Allow retrying a failed test
            FeatureStatusEnum.REVIEWING
        }
        for feature_to_check in self.project_state.features:
            if feature_to_check.status in eligible_statuses:
                if self._are_feature_dependencies_met(feature_to_check): # Check dependencies
                    logger.info(f"Selected next feature: '{feature_to_check.name}' ({feature_to_check.id}), Status: {feature_to_check.status}")
                    return feature_to_check
                else:
                    logger.info(f"Feature '{feature_to_check.name}' is eligible but dependencies not met. Skipping for now.")
        
        logger.info("No suitable eligible features found whose dependencies are met.")
        return None
    # --- Planning Phase Method ---


    def _validate_plan(self, feature: ProjectFeature) -> bool:
        """
        Performs rule-based validation on the parsed tasks of a feature's plan. # Added feature.name
        Checks for valid actions, target formats, dependency existence, and basic loops.
        Includes enhanced logging for dependency failures, including problematic task details.

        Args:
            feature: The ProjectFeature whose tasks need validation.

        Returns:
            True if the plan seems valid, False otherwise. Updates feature status on failure.
        """
        if not feature.tasks:
            # --- MODIFIED: An empty task list is an invalid plan --- # Added feature.name
            logger.error(f"Plan Validation Failed for '{feature.name}': Plan resulted in an empty task list. This is invalid.")
            feature.status = FeatureStatusEnum.PLANNING_FAILED # Mark as planning_failed
            error_note = "\n\n[PLAN VALIDATION FAILED: Empty task list generated by planner. The feature cannot be implemented without tasks.]"
            feature.plan_markdown = (feature.plan_markdown or "") + error_note
            self.memory_manager.save_project_state(self.project_state) # Save state after update
            return False

        logger.info(f"Validating plan for feature '{feature.name}' ({len(feature.tasks)} tasks)...") # Added feature.name
        task_ids = {task.task_id_str for task in feature.tasks}
        valid_actions = {
            "Create file", 
            "Modify file", 
            "Run command", 
            "Create directory", 
            "Prompt user input", 
            "delete_all_default_tests_py", # Added
            "delete_app_tests_py",         # Added
            "Delete file"                  # Keep from previous fix
        }

        for task_idx, current_task in enumerate(feature.tasks):
            if current_task.action not in valid_actions:
                logger.error(f"Plan Validation Failed (Task {current_task.task_id_str}): Invalid action '{current_task.action}'. Valid actions are: {valid_actions}.")
                logger.debug(f"Problematic task details for invalid action: {current_task.model_dump_json(indent=2)}")
                feature.status = FeatureStatusEnum.PLANNING_FAILED; feature.plan_markdown += "\n\n[PLAN VALIDATION FAILED: Invalid action]"
                return False

            if not current_task.target or not isinstance(current_task.target, str):
                logger.error(f"Plan Validation Failed (Task {current_task.task_id_str}): Missing or invalid target string.")
                logger.debug(f"Problematic task details for invalid target: {current_task.model_dump_json(indent=2)}")
                feature.status = FeatureStatusEnum.PLANNING_FAILED; feature.plan_markdown += "\n\n[PLAN VALIDATION FAILED: Invalid target]"
                return False

            if current_task.dependencies:
                for dep_id in current_task.dependencies:
                    if not isinstance(dep_id, str) or not dep_id.strip(): # Check if dep_id is a non-empty string
                        logger.error(f"Plan Validation Failed (Task {current_task.task_id_str}): Invalid dependency format '{dep_id}'. Expected non-empty string.")
                        logger.debug(f"Problematic task details for invalid dependency format: {current_task.model_dump_json(indent=2)}")
                        feature.status = FeatureStatusEnum.PLANNING_FAILED; feature.plan_markdown += f"\n\n[PLAN VALIDATION FAILED: Invalid dependency format for '{dep_id}']"
                        return False
                    if dep_id == current_task.task_id_str:
                        logger.error(f"Plan Validation Failed (Task {current_task.task_id_str}): Task cannot depend on itself.")
                        logger.debug(f"Problematic task details for self-dependency: {current_task.model_dump_json(indent=2)}")
                        feature.status = FeatureStatusEnum.PLANNING_FAILED; feature.plan_markdown += "\n\n[PLAN VALIDATION FAILED: Self-dependency]"
                        return False
                    # Moved this check inside the loop where dep_id is defined
                    if dep_id not in task_ids:
                        # Enhanced logging for dependency failure
                        # The task.dependencies attribute should already be a list of strings from Pydantic validation
                        parsed_deps_for_task_str = ", ".join(current_task.dependencies) if current_task.dependencies else "None"

                        logger.error(
                            f"Plan Validation Failed (Task {current_task.task_id_str}): "
                            f"Parsed Dependency ID '{dep_id}' (from task's parsed dependencies: [{parsed_deps_for_task_str}]) "
                            f"not found in the set of plan's task IDs: {task_ids}."
                        )
                        # Log the full problematic task details for better debugging
                        logger.debug(f"Problematic task details for missing dependency: {current_task.model_dump_json(indent=2)}")
                        feature.status = FeatureStatusEnum.PLANNING_FAILED; feature.plan_markdown += f"\n\n[PLAN VALIDATION FAILED: Missing dependency '{dep_id}']"
                        return False

            #            # --- ADDED: Django-specific check for redundant mkdir before startapp ---
            if self.project_state and self.project_state.framework == 'django' and \
               current_task.action == "Run command" and "manage.py startapp" in current_task.target:
                startapp_match = re.search(r"manage.py startapp\s+([a-zA-Z_][a-zA-Z0-9_]*)", current_task.target)
                if startapp_match:
                    app_name_from_startapp = startapp_match.group(1)
                    # Iterate through all tasks *before* the current startapp task
                    for prev_task_idx in range(task_idx):
                        prev_task = feature.tasks[prev_task_idx]
                        if prev_task.action == "Create directory" and prev_task.target == app_name_from_startapp:
                            logger.error(f"Plan Validation Failed (Task {current_task.task_id_str}): "
                                         f"Redundant 'Create directory {app_name_from_startapp}' (Task {prev_task.task_id_str}) "
                                         f"found before 'python manage.py startapp {app_name_from_startapp}'. "
                                             f"'startapp' creates its own directory.") # type: ignore
                            feature.status = FeatureStatusEnum.PLANNING_FAILED
                            error_note = f"\n\n[PLAN VALIDATION FAILED: Redundant 'Create directory {app_name_from_startapp}' before 'startapp {app_name_from_startapp}'. 'startapp' handles directory creation.]"
                            # This line must be at the same indentation level as feature.status and error_note
                            feature.plan_markdown = (feature.plan_markdown or "") + error_note
                            if self.project_state: # Ensure project_state is not None
                                self.memory_manager.save_project_state(self.project_state) # Save state after update
                                return False
            # --- END DJANGO CHECK ---

            # --- "Base Template First" Rule Validation ---
            if self.project_state and self.project_state.framework == 'django':
                base_html_creation_task_id = None
                settings_template_dir_task_id = None
                for task_item_base_tpl in feature.tasks:
                    if task_item_base_tpl.action == "Create file" and task_item_base_tpl.target == "templates/base.html":
                        base_html_creation_task_id = task_item_base_tpl.task_id_str
                    if task_item_base_tpl.action == "Modify file" and task_item_base_tpl.target.endswith("settings.py") and \
                       task_item_base_tpl.requirements and "BASE_DIR / 'templates'" in task_item_base_tpl.requirements and "TEMPLATES[0]['DIRS']" in task_item_base_tpl.requirements:
                        settings_template_dir_task_id = task_item_base_tpl.task_id_str

                for task_item_base_tpl_check in feature.tasks:
                    if task_item_base_tpl_check.action == "Create file" and isinstance(task_item_base_tpl_check.target, str) and task_item_base_tpl_check.target.endswith(".html") and task_item_base_tpl_check.target != "templates/base.html":
                        # This is a heuristic. A better way is to parse template content for {% extends 'base.html' %}
                        # For now, we assume if base.html is planned, other templates might extend it.
                        if base_html_creation_task_id and base_html_creation_task_id not in (task_item_base_tpl_check.dependencies or []):
                            logger.error(f"Plan Validation Failed (Task {task_item_base_tpl_check.task_id_str}): Template might extend 'base.html' but does not depend on its creation task '{base_html_creation_task_id}'.")
                            error_note = f"\n\n[PLAN VALIDATION FAILED: Task {task_item_base_tpl_check.task_id_str} (template creation) might extend 'base.html' but does not depend on its creation task '{base_html_creation_task_id}']" # Define error_note
                            feature.plan_markdown = (feature.plan_markdown or "") + error_note
                            if self.project_state: # Ensure project_state is not None
                                self.memory_manager.save_project_state(self.project_state) # Save state after update
                            feature.status = FeatureStatusEnum.PLANNING_FAILED # Ensure status is set
                            return False
            # --- END DJANGO CHECK ---

                        if settings_template_dir_task_id and settings_template_dir_task_id not in (task_item_base_tpl_check.dependencies or []):
                            logger.error(f"Plan Validation Failed (Task {task_item_base_tpl_check.task_id_str}): Template might extend 'base.html' but does not depend on settings.py TEMPLATES['DIRS'] update task '{settings_template_dir_task_id}'.")
                            feature.status = FeatureStatusEnum.PLANNING_FAILED
                            feature.plan_markdown = (feature.plan_markdown or "") + "\n\n[PLAN VALIDATION FAILED: Template dependency on settings.py (TEMPLATES DIRS) missing]"
                            if self.project_state: self.memory_manager.save_project_state(self.project_state)
                            return False

        logger.info(f"Plan validation passed for feature '{feature.name}'.")
        return True

    async def _update_project_structure_map(self, file_path_str: str):
        """
        Updates the project_structure_map in ProjectState after a file is modified.
        """
        if not self.project_state or not self.code_intelligence_service:
            return

        absolute_file_path: Path
        try:
            absolute_file_path = (self.file_system_manager.project_root / file_path_str).resolve(strict=True)
            if not absolute_file_path.is_file():
                logger.warning(f"Cannot update structure map: Path is not a file {absolute_file_path}")
                return

            content = await asyncio.to_thread(self.file_system_manager.read_file, file_path_str)
        except (FileNotFoundError, Exception) as e:
            logger.error(f"Cannot update structure map: Error reading file {file_path_str}: {e}")
            return

        try:
            parsed_file_info = self.code_intelligence_service.parse_file(file_path_str, content)

            if parsed_file_info:
                # Determine app_name based on the file's path relative to project_root
                # This is a simplified heuristic. A more robust app detection might be needed.
                relative_path_parts = Path(file_path_str).parts
                file_name = Path(file_path_str).name


                if len(relative_path_parts) == 1:
                    # Project-root file (utils.py, manage.py, etc.)
                    self.project_state.project_structure_map.global_files[file_name] = parsed_file_info
                    logger.info(f"Updated structure map for global file '{file_name}'.")
                else:
                    # App-level file (e.g., my_app/views.py)
                    app_name = relative_path_parts[0]
                    # Ensure app and file entries exist in the project_structure_map
                    if app_name not in self.project_state.project_structure_map.apps:
                        from .project_models import AppStructureInfo # Local import
                        self.project_state.project_structure_map.apps[app_name] = AppStructureInfo()
                    self.project_state.project_structure_map.apps[app_name].files[file_name] = parsed_file_info
                    logger.info(f"Updated project structure map for app '{app_name}', file '{file_name}'.")
                # Consider saving project state here or let the caller handle it.
        except Exception as e:
            logger.error(f"Error updating project structure map for {file_path_str}: {e}")


    def _clean_llm_markdown_output(self, raw_output: str) -> str:
        """Removes common LLM preamble/postamble and code fences from Markdown output."""
        if not raw_output:
            return ""
        cleaned = raw_output

        # 1. Remove markdown code fences (more robustly)
        cleaned = re.sub(r"^\s*```(?:json|xml|markdown|[\w\-\.]+)?\s*\n?", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
        cleaned = re.sub(r"\n?\s*```\s*$", "", cleaned, flags=re.MULTILINE)
        cleaned = cleaned.strip()

        # 2. Remove "file.ext: X lines selected" type lines (more robustly, anywhere in the output)
        # This pattern looks for lines that start with optional whitespace, then a filepath-like string,
        # followed by a colon, a number, and "lines selected" or "line selected".
        extraneous_line_pattern = r"^\s*[\w\/\.\-\\]+?\.(?:py|js|jsx|ts|tsx|html|css|json|txt|md|yaml|yml|sh|bat|xml|log|csv|config|ini|toml|lock|cfg|env|git\w*):\s*\d+\s*(?:lines? selected|line|lines?)\s*$"
        cleaned = re.sub(extraneous_line_pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
        cleaned = cleaned.strip() # Strip again after removal

        # 3. Remove common textual preambles (case-insensitive)
        preambles = [
            "here is the markdown plan:", "here's the plan:", "okay, here's the plan:",
            "sure, here is the plan:", "certainly, here is the plan:", "answer:",
            "okay, i've generated the plan:", "the plan is as follows:",
            "based on the project context and the current feature request" # From user log
            # Add any other observed preambles
        ]
        made_change_in_preamble_loop = True
        while made_change_in_preamble_loop:
            made_change_in_preamble_loop = False
            for pre in preambles:
                if cleaned.lower().startswith(pre.lower()):
                    cleaned = cleaned[len(pre):].strip()
                    made_change_in_preamble_loop = True
                    break
            if made_change_in_preamble_loop:
                continue

        # 4. Ensure plan starts with a task header or metadata list
        first_task_header_match = re.search(r"^\s*###\s+Task\s+[0-9.]+", cleaned, re.MULTILINE)
        if first_task_header_match:
            cleaned = cleaned[first_task_header_match.start():]
        else:
            first_metadata_match = re.search(r"^\s*[-*]\s*`?[A-Za-z\s_]+?`?:", cleaned, re.MULTILINE)
            if first_metadata_match:
                cleaned = cleaned[first_metadata_match.start():]
            elif cleaned.strip(): # Content exists but no standard start
                logger.warning(
                    "Cleaned plan content does not start with '### Task' or a metadata list item. "
                    f"The plan might be malformed or entirely conversational. Original raw output started with: '{raw_output[:150]}...'")

        logger.debug(f"Cleaned Markdown Output (final for parsing):\n---\n{cleaned[:500]}...\n---")
        return cleaned.strip()


    async def _execute_directory_task_fs(self, task: FeatureTask):
        """Handles 'Create directory' tasks using FileSystemManager."""
        dir_path = task.target # Use attribute access
        task_id_str = task.task_id_str # Use attribute access

        # Validate the target path
        if not dir_path or not isinstance(dir_path, str) or '..' in dir_path or Path(dir_path).is_absolute():
            logger.error(f"Directory task {task_id_str} has invalid or unsafe path target: '{dir_path}'")
            raise ValueError(f"Invalid or unsafe directory path: '{dir_path}'")

        logger.info(f"Task {task_id_str}: Creating directory: `{dir_path}`")
        self.progress_callback({"action_details": f"Creating directory: {dir_path}"})
        try:
            # Use asyncio.to_thread as mkdir can be a blocking I/O operation
            await asyncio.to_thread(self.file_system_manager.create_directory, dir_path)
            logger.info(f"Task {task_id_str}: Directory '{dir_path}' created successfully (or already existed).")
            task.result = "Directory created successfully." # Update task result # Use attribute access
        except Exception as e:
            logger.exception(f"Failed to create directory '{dir_path}' for task {task_id_str}.")
            task.result = f"Directory creation failed: {e}" # Store error in result # Use attribute access
            raise RuntimeError(f"Directory creation failed: {e}") from e


    async def _execute_prompt_user_task(self, task: FeatureTask):
        """
        Handles 'Prompt user input' tasks by checking for existing stored values
        (in secure storage for secrets, or project state for normal values) and
        only prompting the user via a UI callback if the value is not found.
        The retrieved value is then stored for future use.
        """
        if not self.project_state: raise RuntimeError("Project state not loaded.")

        placeholder_name = task.target # The key to store/retrieve the value # Use attribute access
        description = task.description or f"Input needed for {placeholder_name}" # Use attribute access
        task_id_str = task.task_id_str # Use attribute access

        logger.info(f"Task {task_id_str}: Handling user input prompt for: `{placeholder_name}`")
        self._report_system_message(f"Waiting for user input: {description}", task_id=task_id_str)

        # Determine if the placeholder represents sensitive data
        is_password = "PASSWORD" in placeholder_name.upper() or \
                      "SECRET" in placeholder_name.upper() or \
                      "KEY" in placeholder_name.upper() or \
                      "TOKEN" in placeholder_name.upper()

        # Determine if it's likely a request for a file path
        req_lower = (task.requirements or "").lower() # Use attribute access
        desc_lower = description.lower()
        needs_file_path = "path to" in req_lower or "select the file" in req_lower or \
                          "path to" in desc_lower or "select the file" in desc_lower or \
                          "UPLOAD" in placeholder_name.upper()

        stored_value: Optional[str] = None

        # 1. Check secure storage for sensitive data
        if is_password:
            stored_value = retrieve_credential(placeholder_name)
            if stored_value: logger.debug(f"Retrieved sensitive value for '{placeholder_name}' from secure storage.")
        # 2. Check project state placeholders for non-sensitive data
        elif placeholder_name in self.project_state.placeholders: # Use attribute access
             stored_value = self.project_state.placeholders[placeholder_name] # Use attribute access
             if stored_value is not None: logger.debug(f"Retrieved value for '{placeholder_name}' from project state.")

        # 3. If not found, prompt the user
        if stored_value is None:
            logger.info(f"Task {task_id_str}: No stored value found for '{placeholder_name}'. Prompting user.")
            user_input: Optional[str] = None
            try:
                # Choose the correct UI callback
                if needs_file_path:
                    logger.debug(f"Requesting file picker for '{placeholder_name}'")
                    user_input = await asyncio.to_thread(self.show_file_picker_cb, description)
                else:
                    logger.debug(f"Requesting input prompt for '{placeholder_name}' (Password: {is_password})")
                    user_input = await asyncio.to_thread(self.show_input_prompt_cb, description, is_password, f"Enter value for {placeholder_name}")

                # --- SECURITY: Sanitize and validate the user's input ---
                if user_input is not None:
                    user_input = sanitize_and_validate_input(user_input)
                # --- END SECURITY ---

                if user_input is None:
                    logger.warning(f"User cancelled input for placeholder '{placeholder_name}'.")
                    raise InterruptedError(f"User cancelled input for {placeholder_name}")

                user_input_stripped = user_input.strip()

                # Handle empty input
                if not user_input_stripped:
                     if is_password:
                         logger.error(f"User provided empty password for '{placeholder_name}'.")
                         raise InterruptedError(f"Password cannot be empty for {placeholder_name}")
                     else:
                         logger.warning(f"User provided empty input for non-password placeholder '{placeholder_name}'. Storing empty string.")
                         user_input_stripped = "" # Store empty string if allowed

                # Store the retrieved value
                if is_password:
                    store_credential(placeholder_name, user_input_stripped)
                    logger.info(f"Stored sensitive input for '{placeholder_name}' securely.")
                else:
                    # Pydantic ensures self.project_state.placeholders exists
                    self.project_state.placeholders[placeholder_name] = user_input_stripped # Use attribute access
                    # Save state immediately after getting non-sensitive input
                    self.memory_manager.save_project_state(self.project_state)
                    logger.info(f"Stored non-sensitive input for '{placeholder_name}' in project state.")

                stored_value = user_input_stripped # Use the newly acquired value
                self._report_system_message(f"User provided input for {placeholder_name}.", task_id=task_id_str)
                task.result = "User input provided." # Use attribute access

            except InterruptedError:
                 task.result = "User cancelled input." # Use attribute access
                 raise # Re-raise cancellation to stop the workflow if needed
            except Exception as e:
                 logger.exception(f"Error during user prompt for {placeholder_name}: {e}")
                 task.result = f"Error getting user input: {e}" # Use attribute access
                 raise RuntimeError(f"Failed to get user input for {placeholder_name}: {e}") from e
        else:
            # Value was already stored
            masked_value = "******" if is_password else str(stored_value)[:30] + "..."
            logger.info(f"Task {task_id_str}: Using already stored value for '{placeholder_name}' ({masked_value}).")
            self._report_system_message(f"Using stored value for {placeholder_name}.", task_id=task_id_str)
            task.result = "Used stored value." # Use attribute access

    async def _identify_relevant_files(self, task: FeatureTask, error_output: str) -> List[str]:
        """
        Identifies a list of relevant file paths for debugging a failed task.

        It uses heuristics based on the task itself, the error output (especially
        Python tracebacks), and the project's recent history to gather a set of
        files that are likely related to the error, providing context for remediation.
        """
        if not self.project_state or not self.file_system_manager:
            logger.error("Cannot identify relevant files: Project state or FileSystemManager not available.")
            return []

        relevant_paths: set[str] = set()
        project_root_path = self.file_system_manager.project_root

        # 1. Always include the task's target file if it's a file operation
        if task.action in ["Create file", "Modify file", "Delete file"] and task.target and isinstance(task.target, str):
            if '.' in Path(task.target).name: # Simple check for an extension
                try:
                    safe_target_path = self.file_system_manager._resolve_safe_path(task.target)
                    relevant_paths.add(str(safe_target_path.relative_to(project_root_path)))
                except ValueError:
                    logger.warning(f"Task target '{task.target}' is invalid or outside project root. Not adding to relevant files.")

        # 2. Extract file paths from traceback, prioritizing project files over venv files
        error_lower = error_output.lower()
        traceback_files_matches = re.findall(r'File "([^"]+\.py)"', error_output, re.IGNORECASE)
        
        project_files_from_traceback: List[Path] = []
        for tb_file_str in traceback_files_matches:
            try:
                resolved_tb_path = Path(tb_file_str)
                if not resolved_tb_path.is_absolute():
                    resolved_tb_path = (project_root_path / resolved_tb_path).resolve()
                
                # Prioritize files within the project root, excluding venv
                if resolved_tb_path.is_relative_to(project_root_path) and 'venv' not in resolved_tb_path.parts:
                    project_files_from_traceback.append(resolved_tb_path)
            except (ValueError, Exception):
                # Ignore paths that can't be resolved or are outside the project root
                pass

        # Add project files from traceback to the context
        test_file_path_from_traceback: Optional[Path] = None
        for p_path in project_files_from_traceback:
            relative_path_to_add = str(p_path.relative_to(project_root_path))
            relevant_paths.add(relative_path_to_add)
            logger.debug(f"Added traceback file to relevant_paths: {relative_path_to_add}")
            # Identify the first test file found in the project traceback
            if test_file_path_from_traceback is None and "test" in relative_path_to_add.lower():
                test_file_path_from_traceback = p_path

        # 3. Handle AssertionError in test files
        if "assertionerror" in error_lower and test_file_path_from_traceback:
            logger.info(f"AssertionError detected in test file: {test_file_path_from_traceback}. Identifying related app files.")
            

            # Determine the app directory from the test file path
            # Assuming structure like: project_root/app_name/test/test_*.py
            try:
                app_dir = test_file_path_from_traceback.parent.parent # Up two levels from test_*.py to app_name/
                if app_dir.is_dir() and app_dir.is_relative_to(project_root_path):
                    app_name = app_dir.name
                    logger.debug(f"Inferred app name '{app_name}' from test file path.")

                    models_file = app_dir / "models.py"
                    views_file = app_dir / "views.py"

                    if models_file.exists() and models_file.is_file():
                        relevant_paths.add(str(models_file.relative_to(project_root_path)))
                        logger.debug(f"Added related models.py: {models_file.relative_to(project_root_path)}")
                    if views_file.exists() and views_file.is_file():
                        relevant_paths.add(str(views_file.relative_to(project_root_path)))
                        logger.debug(f"Added related views.py: {views_file.relative_to(project_root_path)}")
                # --- NEW: Also find and add all relevant .html template files from the app ---
                templates_dir = app_dir / "templates"
                if templates_dir.is_dir():
                    # Look for templates in both app_name/templates/ and app_name/templates/app_name/
                    for html_file in templates_dir.rglob("*.html"):
                        if html_file.is_file():
                            relevant_paths.add(str(html_file.relative_to(project_root_path)))
                            logger.debug(f"Added related template file: {html_file.relative_to(project_root_path)}")
                else:
                    logger.warning(f"Could not determine app directory from test file path: {test_file_path_from_traceback}")
            except Exception as e_app_path:
                logger.warning(f"Error inferring app path for AssertionError: {e_app_path}")

        # 4. Specific handling for NoReverseMatch (can be combined with other error checks)
        if "noreversematch" in error_lower:
            logger.info(f"NoReverseMatch detected in error output for task {task.task_id_str}. Adding relevant URL and test files.")
            project_config_dir_name = self.project_state.project_name # Assuming project_name is the config dir
            project_urls_path_str = f"{project_config_dir_name}/urls.py"
            if (project_root_path / project_urls_path_str).exists():
                relevant_paths.add(project_urls_path_str)

            app_name_match = re.search(r"Reverse for '([^:]+):[^']+' not found", error_output, re.IGNORECASE)
            if app_name_match:
                app_name_from_error = app_name_match.group(1)
                app_urls_path_str = f"{app_name_from_error}/urls.py"
                if (project_root_path / app_urls_path_str).exists():
                    relevant_paths.add(app_urls_path_str)
            # Test file is already added by traceback parsing if it was the source of NoReverseMatch

        # 5. Include files from 2-3 recently successful tasks in the current feature
        if self.project_state and self.project_state.current_feature_id:
            current_feature = self.project_state.get_feature_by_id(self.project_state.current_feature_id)
            if current_feature:
                completed_file_op_tasks = [
                    t for t in reversed(current_feature.tasks) # Iterate recent first
                    if t.status == "completed" and t.action in ["Create file", "Modify file"] and t.target and isinstance(t.target, str)
                ]
                for i, completed_task in enumerate(completed_file_op_tasks):
                    if i >= 3: break # Limit to last 3
                    if '.' in Path(completed_task.target).name: # Basic check for file extension
                        try:
                            # Ensure path is resolved relative to the project root
                            relevant_paths.add(str(Path(completed_task.target)))
                        except ValueError:
                            logger.warning(f"Recent task target '{completed_task.target}' is invalid. Not adding.")

        logger.info(f"Identified relevant files for debugging task {task.task_id_str}: {list(relevant_paths)}")
        return list(relevant_paths)

    def _build_error_report(self, task: FeatureTask, error_output: str, previous_diff: Optional[str]) -> Dict[str, Any]:
        """Builds the structured error report for Tars."""
        # This is a simplified report. A real one would be more detailed.
        report = {
            "error_type": "CommandExecutionError", # Can be refined
            "error_message": error_output,
            "triggering_task": task.model_dump(),
            "context_files": {}, # This will be populated below
        }
        if previous_diff:
            report["previous_failed_diff"] = previous_diff
        return report

    
    async def _handle_placeholders_in_code(self, code: str) -> str:
        """
        Finds and replaces placeholders like `{{ API_KEY }}` in code or command strings.

        It retrieves the value for the placeholder from secure storage or the project
        state. If the value isn't found, it triggers the `_execute_prompt_user_task`
        method to ask the user for the value.
        """
        if not self.project_state:
            logger.warning("Cannot handle placeholders: Project state not loaded.")
            return code # Return original code if state is missing

        # Regex to find placeholders like {{ PLACEHOLDER }} or {{PLACEHOLDER}}
        placeholder_regex = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")
        processed_code = code
        placeholders_found = list(placeholder_regex.finditer(code))

        if not placeholders_found:
            return code # No placeholders found, return original

        logger.debug(f"Found {len(placeholders_found)} placeholder(s) in code/command.")

        # Use a dictionary to avoid prompting for the same placeholder multiple times in one call
        resolved_values: Dict[str, str] = {}

        for match in placeholders_found:
            full_match = match.group(0)
            placeholder_name = match.group(1)

            if placeholder_name in resolved_values:
                continue # Already resolved this placeholder in this call

            logger.debug(f"Processing placeholder: {full_match}")
            stored_value: Optional[str] = None
            is_password = "PASSWORD" in placeholder_name or "SECRET" in placeholder_name or "KEY" in placeholder_name or "TOKEN" in placeholder_name

            # 1. Check cache first
            # (resolved_values cache is handled by the loop logic)

            # 2. Check secure storage / project state
            if is_password:
                stored_value = retrieve_credential(placeholder_name)
            elif placeholder_name in self.project_state.placeholders: # Use attribute access
                stored_value = self.project_state.placeholders[placeholder_name] # Use attribute access

            # 3. Prompt if not found
            if stored_value is None:
                logger.warning(f"Placeholder {full_match} value not found. Prompting user.")
                try:
                    # Create a temporary task structure to reuse the prompt execution logic
                    # Use Pydantic model for the temporary task
                    prompt_task = FeatureTask(
                        task_id_str=f"placeholder_{placeholder_name}", # Temporary ID
                        action="Prompt user input",
                        target=placeholder_name,
                        description=f"Value needed for placeholder: {placeholder_name}",
                        requirements="This value is required to process the current code or command.",
                        # dependencies, test_step, status, result, remediation_attempts use defaults
                    )
                    # Execute the prompt task (this will store the value if successful)
                    await self._execute_prompt_user_task(prompt_task)

                    # Re-check storage after prompting
                    if is_password: stored_value = retrieve_credential(placeholder_name)
                    else: stored_value = self.project_state.placeholders.get(placeholder_name) # Use attribute access

                    # Handle case where prompt was cancelled or failed
                    if stored_value is None:
                        # Allow empty string for non-passwords if user provided it
                        if not is_password and placeholder_name in self.project_state.placeholders: # Use attribute access
                             logger.warning(f"Placeholder {full_match} resolved to empty string after prompt.")
                             stored_value = ""
                        else:
                             logger.error(f"Required placeholder {full_match} has no stored value even after prompting.")
                             raise ValueError(f"Required placeholder {full_match} was not provided by user.")

                except InterruptedError as e:
                     logger.error(f"User cancelled input for required placeholder {full_match}.")
                     raise ValueError(f"Required placeholder {full_match} was not provided by user.") from e
                except Exception as e:
                     logger.error(f"Error prompting for missing placeholder {full_match}: {e}")
                     raise ValueError(f"Failed to get value for required placeholder {full_match}.") from e
            else:
                 logger.debug(f"Using stored value for placeholder {full_match}.")

            resolved_values[placeholder_name] = stored_value # Cache resolved value

        # Perform all replacements after resolving all unique placeholders
        if resolved_values:
             # Create a new regex pattern incorporating all found keys for efficient replacement
             combined_pattern = r"\{\{\s*(" + "|".join(re.escape(k) for k in resolved_values.keys()) + r")\s*\}\} "
             def replace_match(m):
                 key = m.group(1)
                 return resolved_values.get(key, m.group(0)) # Return original match if key somehow missing

             processed_code = re.sub(combined_pattern, replace_match, code)
             logger.info(f"Placeholders replaced in code/command string.")

        return processed_code


    def _are_feature_dependencies_met(self, feature: ProjectFeature) -> bool:
        """
        Checks if all dependencies for a given feature have been met. A dependency
        is considered met if the feature it depends on has the status 'merged'.
        """
        if not self.project_state:
            return False # Cannot check if project state is not loaded
        if not feature.dependencies:
            return True # No dependencies, so they are met

        for dep_id in feature.dependencies:
            dep_feature = self.project_state.get_feature_by_id(dep_id) # Assuming this method exists
            if not dep_feature or dep_feature.status != "merged":
                logger.debug(f"Dependency '{dep_id}' for feature '{feature.name}' not met (Status: {dep_feature.status if dep_feature else 'Not Found'}).")
                return False
        return True

    async def _generate_and_run_feature_tests(self, feature: ProjectFeature) -> bool:
        """
        Generates and runs a dedicated test file for a completed feature.

        This method calls an LLM to write a feature-level test file, executes the
        tests, and triggers a remediation loop if the tests fail.
        """
        if not self.prompts or not self.project_state or not self.agent_manager:
            logger.error("Cannot generate/run feature tests: Core components missing.")
            feature.status = "implementation_failed" # Treat as failure if we can't test
            return False

        feature_name_snake_case = re.sub(r'\W+', '_', feature.name.lower()).strip('_')
        feature_name_pascal_case = "".join(word.capitalize() for word in feature_name_snake_case.split('_'))

        # Determine primary app for the feature (heuristic, might need refinement)
        app_name = self.project_state.project_name # Default to project name if no clear app
        if feature.tasks:
            first_file_task_target = next((t.target for t in feature.tasks if t.action in ["Create file", "Modify file"] and isinstance(t.target, str)), None)
            if first_file_task_target:
                parts = Path(first_file_task_target).parts
                if len(parts) > 1 and parts[0] != self.project_state.project_name:
                    app_name = parts[0]

        test_file_relative_path = f"{app_name}/test/test_{feature_name_snake_case}.py" # Use singular 'test'
        logger.info(f"Starting feature-level testing for '{feature.name}'. Test file: '{test_file_relative_path}'")

        test_agent_prompt_template = getattr(self.prompts, "system_test_agent_feature_tester", None)
        if not test_agent_prompt_template or not isinstance(test_agent_prompt_template, dict) or not test_agent_prompt_template.get("content"):
            logger.error("Test Agent prompt not found or invalid. Cannot generate feature tests.")
            feature.status = "implementation_failed"
            return False
        # Determine if test file needs to be generated initially
        initial_generation_needed = True
        if await asyncio.to_thread(self.file_system_manager.file_exists, test_file_relative_path):
            logger.info(f"Feature test file '{test_file_relative_path}' already exists. Skipping initial generation in this cycle.")
            initial_generation_needed = False

        for attempt in range(1, MAX_FEATURE_TEST_ATTEMPTS + 1):
            if initial_generation_needed and attempt == 1: # Only generate if it didn't exist and it's the first attempt
                feature.status = "generating_feature_tests"
                self.memory_manager.save_project_state(self.project_state)
                self.progress_callback({"message": f"Generating tests for {feature.name} (Attempt {attempt})..."})

                # Gather context: feature files and their content
                feature_files_context_str = "\n**Feature Files Context:**\n"
                files_for_feature = set()
                for task_item in feature.tasks:
                    if task_item.action in ["Create file", "Modify file"] and isinstance(task_item.target, str):
                        files_for_feature.add(task_item.target)
                
                for file_path_str_ctx in sorted(list(files_for_feature)): # Renamed file_path_str to avoid conflict
                    try:
                        content_ctx = await asyncio.to_thread(self.file_system_manager.read_file, file_path_str_ctx)
                        feature_files_context_str += f"--- File: `{file_path_str_ctx}` ---\n```python\n{content_ctx}\n```\n"
                    except Exception as e_ctx_read: # Renamed e to avoid conflict
                        feature_files_context_str += f"--- File: `{file_path_str_ctx}` ---\n[Error reading file: {e_ctx_read}]\n"
                if not files_for_feature:
                    feature_files_context_str += "No primary feature files found to provide context for testing.\n"

                # Construct the user message content for the TestAgent
                # The system_test_agent_feature_tester prompt is the system message.
                # The content of that prompt often has placeholders for the user message part.
                # We use the `system_test_agent_content` as the base system message.
                # The user message provides the specifics.
                user_content_for_test_agent_generation = test_agent_prompt_template["content"].replace( # type: ignore
                    "{{ FEATURE_NAME }}", feature.name
                ).replace("{{ FEATURE_DESCRIPTION }}", feature.description
                ).replace("{{ APP_NAME }}", app_name
                ).replace("{{ FEATURE_NAME_SNAKE_CASE }}", feature_name_snake_case # type: ignore
                ).replace("{{ FEATURE_NAME_PASCAL_CASE }}", feature_name_pascal_case
                ).replace("{{ FRAMEWORK_VERSION }}", self.project_state.framework) # type: ignore

                linking_introduction = (
                    f"You are writing tests for the '{feature.name}' feature, primarily implemented in the app '{app_name}'. "
                    f"The main files involved are listed below. Pay close attention to how they interact. Your tests in '{test_file_relative_path}' should verify these interactions.\n"
                )
                user_content_for_test_agent_generation = user_content_for_test_agent_generation.replace("{{ FEATURE_FILES_CONTEXT }}", linking_introduction + feature_files_context_str)

                test_gen_messages: List[ChatMessage] = [
                    # Pillar 2: Resolve placeholders in test agent prompt
                    await self._resolve_placeholders_in_prompt_text(test_agent_prompt_template), # type: ignore
                    {"role": "user", "content": user_content_for_test_agent_generation }
                ]

                try:
                    test_file_content_response = await self._call_llm_with_error_handling(
                        "Tars", test_gen_messages, feature_or_task_id=f"{feature.id}_test_gen_fallback", temperature=0.2 # Using Tars for now
                    )
                    raw_test_file_output = test_file_content_response['content']

                    # --- FIX: Parse the XML output to get clean code ---
                    parsed_path, parsed_content = self._parse_mcp_file_content(raw_test_file_output)
                    if not parsed_content:
                        raise ValueError("TestAgent returned invalid or empty <file_content> XML.")
                    # --- END FIX ---

                    logger.info(f"Writing generated test file to '{test_file_relative_path}'")
                    generated_summary = self._extract_summary_from_code(parsed_content)
                    clean_test_code = self._remove_summary_comment_from_code(parsed_content)
                    await asyncio.to_thread(self.file_system_manager.write_file, test_file_relative_path, clean_test_code) # Write the clean code
                    await self._update_project_structure_map(test_file_relative_path)
                    if generated_summary and self.project_state:
                        self.project_state.code_summaries[test_file_relative_path] = generated_summary
                except Exception as e_gen_fallback:
                    logger.error(f"Failed to generate or write test file (fallback) for '{feature.name}': {e_gen_fallback}")
                    if attempt < MAX_FEATURE_TEST_ATTEMPTS:
                        await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)
                        continue 
                    else:
                        feature.status = "implementation_failed"
                        self.memory_manager.save_project_state(self.project_state)
                        return False
            elif attempt > 1: # This is a retry after a failure
                logger.info(f"Retrying tests for '{feature.name}' (Attempt {attempt}). Test file was previously generated or existed.")

            # Run the generated tests
            feature.status = "feature_testing"
            self.memory_manager.save_project_state(self.project_state)
            self.progress_callback({"message": f"Running tests for {feature.name}..."})

            # Construct test command (Django specific example)
            # e.g., app_name.tests.test_feature_name_snake_case
            test_module_path = f"{app_name}.test.{Path(test_file_relative_path).stem}" # Use singular 'test'
            if self.project_state.framework == "django":
                # Corrected command for Django: run all tests in the app
                test_command = f"python manage.py test {app_name}"
            else:
                test_command = f"python manage.py test {test_module_path}" # Fallback or other frameworks

            logger.info(f"Executing feature tests for '{feature.name}': {test_command}")
            # Initialize variables to satisfy linters and ensure definition
            test_success: bool = False
            test_run_output_json_str: str = ""
            test_success, test_run_output_json_str = await self.request_command_execution_cb( # type: ignore
                f"{feature.id}_feature_test_run_{attempt}",
                test_command,
                f"Run feature tests for {feature.name}"
            )
            # Parse the JSON output to get detailed stderr for remediation
            stderr_details_for_remediation = test_run_output_json_str # Default to full string if not JSON
            try:
                cmd_output_details = json.loads(test_run_output_json_str)
                if isinstance(cmd_output_details, dict) and "stderr" in cmd_output_details:
                    stderr_details_for_remediation = cmd_output_details["stderr"]
                    logger.debug(f"Extracted stderr for remediation: {stderr_details_for_remediation[:300]}...")
            except json.JSONDecodeError:
                logger.warning(f"Could not parse command output as JSON for feature test of '{feature.name}'. Raw output: {test_run_output_json_str[:300]}")

            if test_success:
                logger.info(f"Feature-level tests PASSED for '{feature.name}'.")
                feature.status = "feature_testing_passed"
                self.memory_manager.save_project_state(self.project_state)
                return True # Tests passed, feature implementation successful for this stage

            # Tests failed
            logger.error(f"Feature-level tests FAILED for '{feature.name}' (Attempt {attempt}/{MAX_FEATURE_TEST_ATTEMPTS}). Output:\n{test_run_output_json_str}")
            self.progress_callback({"error": f"Tests failed for {feature.name}. Output: {stderr_details_for_remediation[:200]}..."})
            feature.status = "feature_testing_failed"
            self.memory_manager.save_project_state(self.project_state)

            if attempt >= MAX_FEATURE_TEST_ATTEMPTS:
                logger.error(f"Max feature test attempts reached for '{feature.name}'. Marking as implementation_failed.")
                feature.status = "implementation_failed"
                self.memory_manager.save_project_state(self.project_state)
                return False

            # Attempt remediation for the feature based on test failure
            self.progress_callback({"message": f"Attempting to fix code for {feature.name} based on test failures..."})
            remediation_applied = await self._remediate_feature_after_test_failure(feature, stderr_details_for_remediation)

            if not remediation_applied:
                logger.error(f"Remediation for feature test failure of '{feature.name}' was not applied or failed. Marking as implementation_failed.")
                feature.status = "implementation_failed"
                self.memory_manager.save_project_state(self.project_state)
                return False
            
            logger.info(f"Remediation applied for feature '{feature.name}'. Retrying feature tests.")
            # Loop continues to re-run tests. Consider if test file needs regeneration.

        logger.error(f"Feature '{feature.name}' failed all feature test attempts and remediations.")
        feature.status = "implementation_failed" # Should be set by the loop, but as a safeguard
        self.memory_manager.save_project_state(self.project_state)
        return False

    async def _get_project_context_for_planning(self) -> str:
        """
        Assembles a comprehensive string of project context for the Tars planning agent.

        This is one of the most critical context-providing methods. It includes the
        project's file structure, feature status, code summaries, historical decisions,
        and feedback from the security system to give the planner a rich understanding
        of the current state of the project.
        """
        if not self.project_state: return "Error: Project state not available."

        context_parts = []
        # --- BUG FIX #14: Update Git status before planning ---
        try:
            git_dir = self.file_system_manager.project_root / ".git"
            if git_dir.is_dir():
                # Update branch name
                branch_result = await asyncio.to_thread(self.command_executor.run_command, "git branch --show-current")
                if branch_result.exit_code == 0 and branch_result.stdout:
                    self.project_state.active_git_branch = branch_result.stdout.strip()
                # Update status summary
                status_result = await asyncio.to_thread(self.command_executor.run_command, "git status --short")
                if status_result.exit_code == 0:
                    self.project_state.git_status_summary = status_result.stdout.strip()
        except Exception as e:
            logger.warning(f"Could not update Git status for context: {e}")
        # --- END BUG FIX #14 ---

        project_name = getattr(self.project_state, 'project_name', 'Unknown Project')
        framework = getattr(self.project_state, 'framework', 'Unknown Framework')
        current_feature_id = getattr(self.project_state, 'current_feature_id', None)

        # Ensure project_name is a string for path operations
        if not isinstance(project_name, str):
            project_name = 'Unknown Project'
        if not isinstance(framework, str):
            framework = 'Unknown Framework'
        
        context_parts.append(f"Project Name: {project_name}")
        context_parts.append(f"Framework: {framework}")
        if self.project_state.venv_path: context_parts.append(f"Virtual Env Path: `{self.project_state.venv_path}`")
        if self.project_state.active_git_branch: context_parts.append(f"Active Git Branch: `{self.project_state.active_git_branch}`")

        venv_dir = self.file_system_manager.project_root / "venv"
        manage_py_file = self.file_system_manager.project_root / "manage.py"
        # Ensure project_name is valid for path construction
        safe_project_name_for_path = re.sub(r'[<>:"/\\|?*]', '_', project_name)
        project_config_dir = self.file_system_manager.project_root / safe_project_name_for_path
        settings_py_file = project_config_dir / "settings.py"
        requirements_txt_file = self.file_system_manager.project_root / "requirements.txt"

        context_parts.append(f"venv_created: {venv_dir.is_dir()}")
        context_parts.append(f"requirements_installed: {requirements_txt_file.is_file() and venv_dir.is_dir()}")
        context_parts.append(f"django_project_initialized: {manage_py_file.is_file() and settings_py_file.is_file()}")
        if manage_py_file.is_file() and settings_py_file.is_file():
            context_parts.append(f"PROJECT_CONFIG_DIR_NAME: {safe_project_name_for_path}")

        context_parts.append("\n--- Project Map ---")
        context_parts.append("\n**Features:**")
        all_features = getattr(self.project_state, 'features', [])
        if all_features:
            for f_item in all_features: # Renamed f to f_item to avoid conflict
                current_marker = " (<<< CURRENTLY PLANNING)" if f_item.id == current_feature_id else ""
                context_parts.append(f"- {f_item.name or 'Unnamed Feature'} ({f_item.id or 'N/A'}): {f_item.status or 'unknown'}{current_marker}")
        else:
            context_parts.append("- None defined yet.")

        completed_task_ids_in_context = {step['id'] for step in self.workflow_context.get('steps', []) if step.get('status') == 'completed'}
        failed_task_ids_in_context = {step['id'] for step in self.workflow_context.get('steps', []) if step.get('status') == 'failed'}
        if completed_task_ids_in_context: context_parts.append(f"\n**Recently Completed Task IDs:** {sorted(list(completed_task_ids_in_context))[-10:]}")
        if failed_task_ids_in_context: context_parts.append(f"\n**Recently Failed Task IDs:** {sorted(list(failed_task_ids_in_context))[-10:]}")
        
        if getattr(self.project_state, 'detailed_dependency_info', None):
            context_parts.append("\n**Key Dependencies:**")
            for lang, deps in self.project_state.detailed_dependency_info.items():
                dep_str = ", ".join([f"{name} ({version})" for name, version in deps.items()])
                context_parts.append(f"- {lang.capitalize()}: {dep_str}")

        context_parts.append("\n**Placeholders (User Inputs Provided):**")
        placeholders = getattr(self.project_state, 'placeholders', {})
        if placeholders:
            for key, value in placeholders.items():
                is_sensitive = "KEY" in key or "SECRET" in key or "TOKEN" in key or "PASSWORD" in key
                display_value = "******" if is_sensitive else str(value)[:30] + ("..." if len(str(value)) > 30 else "")
                context_parts.append(f"- `{{{{{key}}}}}`: (Set - Value: '{display_value}')")
        else:
            context_parts.append("- None defined yet.")
        
        if getattr(self.project_state, 'open_files_context', None):
            context_parts.append("\n**Open Files Context (Summaries):**")
            for path, summary in self.project_state.open_files_context.items():
                context_parts.append(f"- `{path}`: {summary[:100]}{'...' if len(summary) > 100 else ''}")
        else:
            context_parts.append("Open Files Context: None currently tracked.")

        # --- Include Code Summaries ---
        if getattr(self.project_state, 'code_summaries', None):
            context_parts.append("\n**Code Summaries (Recently Modified/Created Files):**")
            recent_summaries_count = 0
            max_summaries_in_context = 5
            for path, summary in sorted(self.project_state.code_summaries.items())[-max_summaries_in_context:]:
                context_parts.append(f"- `{path}`: {summary[:200]}{'...' if len(summary) > 200 else ''}")
                recent_summaries_count +=1
            if not recent_summaries_count:
                 context_parts.append("  - None available yet.")
        else:
            context_parts.append("\n**Code Summaries:** None available yet.")

        # --- Include Historical Notes ---
        if getattr(self.project_state, 'historical_notes', None):
            context_parts.append("\n**Historical Notes/Decisions:**")
            for note in self.project_state.historical_notes[-5:]:
                context_parts.append(f"- {note[:300]}{'...' if len(note) > 300 else ''}")
        else:
            context_parts.append("\n**Historical Notes/Decisions:** None recorded yet.")

        # --- Include Security Feedback History ---
        if getattr(self.project_state, 'security_feedback_history', None):
            context_parts.append("\n\n--- Security & Safety Feedback (Recent Blocked Commands) ---")
            context_parts.append("The following command patterns were previously blocked by the security filter. "
                                 "Do NOT use these patterns again. Adapt your plans to use the provided "
                                 "alternatives or other safe methods for testing.")
            for feedback in self.project_state.security_feedback_history[-5:]: # Show last 5 feedbacks
                context_parts.append(f"- Task '{feedback.get('task_id_str', 'N/A')}': Blocked=`{feedback.get('blocked_command', 'N/A')}`. Reason: {feedback.get('reason', 'N/A')}. Alternative Used: `{feedback.get('executed_alternative', 'N/A')}` (Outcome: {feedback.get('outcome', 'N/A')})")
        # --- End Security Feedback ---

        context_parts.append("\n**Key Files/Structure (Detected):**")
        key_files_found = []
        apps_or_modules_found = []
        try:
            patterns_to_check: List[str] = []
            if framework == 'django':
                patterns_to_check = [
                    "manage.py", f"{safe_project_name_for_path}/settings.py", f"{safe_project_name_for_path}/urls.py",
                    "requirements.txt", "*/models.py", "*/views.py", "*/urls.py",
                    "*/admin.py", "*/forms.py", "*/apps.py", "*/templates/**/*.html", "*/static/**/*",
                    f"{safe_project_name_for_path}/__init__.py", "*/__init__.py"
                ]

            checked_dirs = set()
            for pattern in patterns_to_check:
                try:
                    glob_method = self.file_system_manager.project_root.rglob if '**' in pattern else self.file_system_manager.project_root.glob
                    for item_path in glob_method(pattern):
                        if 'venv' in item_path.parts or 'node_modules' in item_path.parts:
                            continue
                        relative_path_str = item_path.relative_to(self.file_system_manager.project_root).as_posix()
                        if item_path.is_file():
                            role_hint = ""
                            if framework == 'django':
                                if relative_path_str == f"{safe_project_name_for_path}/settings.py": role_hint = " (PROJECT SETTINGS)"
                                elif relative_path_str == f"{safe_project_name_for_path}/urls.py": role_hint = " (PROJECT URLS)"
                                elif item_path.name == "urls.py" and item_path.parent.name != safe_project_name_for_path: role_hint = f" (APP URLS for {item_path.parent.name})"
                                elif item_path.name == "apps.py": role_hint = f" (APP CONFIG for {item_path.parent.name})"
                            key_files_found.append(f"`{relative_path_str}`{role_hint}")
                        elif item_path.is_dir() and item_path not in checked_dirs:
                             dir_name = item_path.name
                             parent_dir = item_path.parent
                             is_module_like = (parent_dir == self.file_system_manager.project_root and
                                                (framework != 'node' and IDENTIFIER_REGEX.match(dir_name)) or
                                                (framework == 'node' and dir_name in ['routes', 'models', 'controllers', 'views', 'public', 'config', 'middleware', 'src']))
                             if is_module_like:
                                 apps_or_modules_found.append(f"`{relative_path_str}` (Dir)")
                                 checked_dirs.add(item_path)
                except Exception as glob_e:
                    logger.warning(f"Error during glob pattern '{pattern}' for project map: {glob_e}")
        except Exception as map_e:
             logger.warning(f"Error gathering project file structure for map: {map_e}")

        if key_files_found:
            unique_files = sorted(list(set(key_files_found)))
            max_files_in_context = 20
            context_parts.append("Files: " + ", ".join(unique_files[:max_files_in_context]))
            if len(unique_files) > max_files_in_context: context_parts[-1] += ", ..."
        else:
            context_parts.append("Files: No standard project files detected.")
        if apps_or_modules_found:
             context_parts.append("Modules/Dirs: " + ", ".join(sorted(list(set(apps_or_modules_found)))))
        context_parts.append("--- End Project Map ---")

        if getattr(self.project_state, 'cumulative_docs', None):
            context_parts.append("\n**Cumulative Documentation (Summary):**")
            doc_summary = self.project_state.cumulative_docs
            max_doc_len = 1000
            if len(doc_summary) > max_doc_len:
                doc_summary = doc_summary[:max_doc_len] + "\n... [Documentation Truncated]"
            context_parts.append(doc_summary)
        
        if getattr(self.project_state, 'last_error_context', None):
            context_parts.append("\n**Last Major Error Context:**")
            error_summary = str(self.project_state.last_error_context)[:300]
            context_parts.append(error_summary + ("..." if len(str(self.project_state.last_error_context)) > 300 else ""))

        
        return "\n".join(context_parts)
