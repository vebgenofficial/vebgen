# src/core/workflow_manager.py
import logging
import asyncio
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
from pathlib import Path
import bs4
from markdown_it import MarkdownIt
from bs4 import BeautifulSoup, FeatureNotFound # Already imported, good for XML parsing
import huggingface_hub # Added for potential Hugging Face token management
from .project_models import FeatureTask
from pydantic import ValidationError

# Import core components
from .agent_manager import AgentManager
from .memory_manager import MemoryManager # Keep MemoryManager
from .config_manager import ConfigManager, FrameworkPrompts # Keep FrameworkPrompts
from .file_system_manager import FileSystemManager
from .command_executor import CommandExecutor, ConfirmationCallback, IDENTIFIER_REGEX
# Import project data models, including the new FeatureStatusEnum
from .project_models import (
    ProjectState, ProjectFeature, FeatureTask, FeatureStatusEnum, TaskStatus,
    AppStructureInfo, ProjectStructureMap, CommandOutput, FixLogicTask, AnyRemediationTask, FixBundleTask, CreateFileTask, FixSyntaxTask, FixCommandTask
)
# Import LLM client specifics
from .remediation_manager import RemediationManager
from .remediation_planner import RemediationPlanner
from .project_models import RemediationPlan
from .llm_client import RateLimitError, ChatMessage, AuthenticationError
# Import secure storage for placeholder handling and APIContract
from .exceptions import BlockedCommandException # Import the new exception
from .secure_storage import store_credential, retrieve_credential, delete_credential
# Import CodeIntelligenceService
from .code_intelligence_service import CodeIntelligenceService # Keep CodeIntelligenceService
from .exceptions import RemediationError, PatchApplyError, CommandExecutionError # Import CommandExecutionError

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

**Chain of Thought Instructions:**
- For each feature, always create the app directory (if it doesn't exist) BEFORE running the startapp command. Never reverse the order. Always prefer that directory should be created first then the app create command run.

**Instructions:**
- Analyze the request, project goal, and project map. Plan only necessary steps for *this feature*.
- Break the feature down into the **smallest possible atomic tasks** (Create file, Modify file, Run command, Create directory, Prompt user input).
- Follow the strict Markdown task format with all required metadata (`ID`, `Action`, `Target`, `Description`, `Requirements`, `Dependencies`, `Test step`, `Doc update`).
- Use hierarchical IDs (e.g., 1.1, 1.2, 2.1.1). **CRITICAL: Ensure IDs are unique within this feature's plan.**
- Define clear `Dependencies` between tasks using their IDs (e.g., `depends_on: 1.1, 1.3`). The key MUST be exactly `depends_on:` (lowercase 'o'). Use `None` if no dependencies.
- Specify a single, precise `Test step` command for each task. Use simple, verifiable commands (like `python manage.py check <app>`, `python -m py_compile <file.py>`, `type <file.txt>`, `dir <folder>`). **AVOID interactive or complex test steps.** For template creation, `type <template_path.html>` is a good test.
- **Testing Tasks:** Plan for unit tests (backend functions/views, frontend components/logic) and integration tests (verifying API contract adherence between frontend and backend).
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
RequestRemediationRetryCallable = Callable[[str, str], Awaitable[bool]] # task_id, failure_reason -> should_retry
# Callback for the WorkflowManager to request command execution via the UI
RequestCommandExecutionCallable = Callable[[str, str, str], Awaitable[Tuple[bool, str]]] # async func(task_id, command, description) -> (success, output/error)

# --- Constants ---
RETRY_DELAY_SECONDS = 2.0       # Default delay for retries (seconds)
MAX_PLANNING_ATTEMPTS = 3       # Max attempts for Tars to generate a valid plan (including initial)
MAX_IMPLEMENTATION_ATTEMPTS = 2 # Max attempts for Case to generate code for a single task
MAX_REMEDIATION_ATTEMPTS_FOR_TASK = 2    # Max attempts for a task to be remediated (blueprint: "Max 2 attempts")
MAX_VALIDATION_ATTEMPTS = 1     # Max attempts to validate a task (usually test step) before failing
LOG_PROMPT_SUMMARY_LENGTH = 200 # Max length for logging prompt summaries
MAX_FEATURE_TEST_ATTEMPTS = 3   # Max attempts to generate and pass feature-level tests

# --- Custom Exception for User Cancellation ---
class InterruptedError(Exception):
    """Custom exception for user cancellation."""
    pass

class WorkflowManager:
    """
    Orchestrates the entire AI-driven development lifecycle from prompt to completion.

    This is the central nervous system of the application. It manages the state of the
    project, directs the flow of work between different AI agents (Tars for planning,
    Case for coding), and handles the execution and validation of each step. It is
    responsible for the main feature cycle, including planning, implementation, and remediation.
    Orchestrates the AI-driven development workflow based on features, plans, and tasks.

    Handles:
    - Project initialization and setup.
    - Feature identification and planning using Tars.
    - Task execution using Case (code generation) and CommandExecutor (commands).
    - Dependency management between tasks.
    - Validation of tasks using test steps.
    - Self-correction/remediation of failed tasks using Tars Analyzer.
    - Interaction with the UI via callbacks for input, confirmation, and command execution.
    - **Note:** While Hugging Face models can be added to the UI, the underlying
      `AgentManager` and `LlmClient` currently only support the OpenRouter API structure
      and authentication. Significant changes in `AgentManager` are required to fully
      integrate direct calls to Hugging Face APIs (Inference API or local models).
    - Saving and loading project state.
    """
    def __init__(self,
                 agent_manager: AgentManager,
                 memory_manager: MemoryManager,
                 config_manager: ConfigManager,
                 file_system_manager: FileSystemManager,
                 command_executor: CommandExecutor,
                 # UI Callbacks (expected to be thread-safe wrappers)
                 show_input_prompt_cb: ShowInputPromptCallable,
                 show_file_picker_cb: ShowFilePickerCallable,
                 progress_callback: ProgressCallback,
                 show_confirmation_dialog_cb: ShowConfirmationDialogCallable,
                 request_command_execution_cb: RequestCommandExecutionCallable, # UI handles command execution
                 show_user_action_prompt_cb: ShowUserActionPromptCallable,
                 request_network_retry_cb: Optional[RequestNetworkRetryCallable] = None, # New callback
                 request_remediation_retry_cb: Optional[RequestRemediationRetryCallable] = None, # New callback
                 default_tars_temperature: float = 0.2, # Default from user request for Tars planning
                 default_case_temperature: float = 0.1,  # Default from user request for Case coding
                 remediation_config=None,
                 ui_communicator: Any = None # Add this parameter
                 ):
        # Initialize state variables that are needed by other components during init
        self.prompts: Optional[FrameworkPrompts] = None

        """
        Initializes the WorkflowManager with all necessary core components and UI callbacks.

        Args:
            # ... (other args) ...
            agent_manager: Instance of AgentManager for LLM client access.
            memory_manager: Instance of MemoryManager for state/history persistence.
            config_manager: Instance of ConfigManager for loading framework prompts.
            file_system_manager: Instance of FileSystemManager for safe file operations.
            command_executor: Instance of CommandExecutor for safe command execution.
            show_input_prompt_cb: Callback to request text input from the user.
            show_file_picker_cb: Callback to request a file path selection from the user.
            progress_callback: Callback to send progress updates (status, percentage) to the UI.
            show_confirmation_dialog_cb: Callback to ask the user for yes/no confirmation.
            request_command_execution_cb: Callback to ask the UI to execute a command and return results.
            show_user_action_prompt_cb: Callback to prompt the user to perform a manual action.
            request_network_retry_cb: Callback to ask user if they want to retry after a network error.
            request_remediation_retry_cb: Callback to ask user if they want to retry a failed remediation cycle.
            default_tars_temperature: Default temperature for Tars agent.
            default_case_temperature: Default temperature for Case agent.
        """
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
        self._request_network_retry_cb = request_network_retry_cb # Store new callback
        self._request_remediation_retry_cb = request_remediation_retry_cb # Store new callback
        self.default_tars_temperature = default_tars_temperature
        self.default_case_temperature = default_case_temperature
        self.ui_communicator = ui_communicator

        # Establish a default, fully-enabled remediation config.
        default_remediation_config = {
            'allow_createfile': True,
            'allow_fixsyntax': True,
            'allow_fixcommand': True,
            'allow_fixlogic': True,
            'allow_fixbundle': True,
        }
        
        # If a specific config is provided, update the defaults with it.
        # This preserves any user-defined overrides while ensuring all keys are present.
        if remediation_config:
            default_remediation_config.update(remediation_config)
        
        self.remediation_config = default_remediation_config
        print("WorkflowManager initialized with remediation safety config:", self.remediation_config)

        # --- Initialize CodeIntelligenceService ---
        if self.file_system_manager and self.file_system_manager.project_root:
            self.code_intelligence_service = CodeIntelligenceService(self.file_system_manager.project_root)
        else:
            logger.error("Cannot initialize CodeIntelligenceService: FileSystemManager or project_root not available.")
            self.code_intelligence_service = None # Or raise an error if it's critical

        # Initialize state variables
        self.project_state: Optional[ProjectState] = None # Holds the entire project state (loaded/created)
        self.workflow_context: Dict[str, Any] = {}        # Holds non-sensitive workflow context (steps, user reqs)
        self.md_parser = MarkdownIt() # Initialize Markdown parser

        self.is_recovering: bool = False # Add this new attribute

        self.workflow_context = self.memory_manager.load_workflow_context() # Load context on init
        logger.info("WorkflowManager instance created.")

        # --- Initialize RemediationManager ---
        # It's better to initialize it once here and pass it around,
        # rather than creating it on-the-fly in the remediation loop.
        # We can re-initialize it if prompts change.
        self.remediation_manager = RemediationManager(
            agent_manager=self.agent_manager,
            file_system_manager=self.file_system_manager,
            command_executor=self.command_executor,
            prompts=self.prompts or FrameworkPrompts(system_tars_markdown_planner=ChatMessage(role="system", content=""), system_case_executor=ChatMessage(role="system", content=""), system_tars_validator=ChatMessage(role="system", content=""), system_tars_error_analyzer=None, system_case_remediation=None), # Pass dummy if not loaded
            remediation_config=self.remediation_config,
            progress_callback=self.progress_callback,
            request_network_retry_cb=self._request_network_retry_cb
        )
        self.remediation_planner = RemediationPlanner()
    async def _gather_holistic_context(self, task: FeatureTask) -> str:
        """
        Gathers the content of the target file and any directly related files to
        provide a holistic context for the AI agents. This is a key part of providing
        the necessary information for the AI to make intelligent decisions, especially
        during code generation or remediation.
        """
        logger.info(f"Gathering holistic context for task target: {task.target}")
        related_files = set() # Use a set to avoid duplicates
        if task.target and isinstance(task.target, str): # Ensure target is a non-empty string
            related_files.add(task.target)

        # --- Add rules to find related files ---
        # Heuristics to find related files based on conventions (e.g., Django MVC).
        # Ensure task.target is a string before path operations
        if task.target and isinstance(task.target, str):
            # Example rule for views: if modifying a view, also get its model and urls
            if 'views.py' in task.target:
                # task.target is relative to project_root. os.path.dirname will work on it.
                app_path = os.path.dirname(task.target) # This will be a relative path string
                models_path = os.path.join(app_path, 'models.py')
                urls_path = os.path.join(app_path, 'urls.py')
                # file_system_manager methods expect paths relative to project_root
                if await asyncio.to_thread(self.file_system_manager.file_exists, models_path):
                    related_files.add(models_path)
                if await asyncio.to_thread(self.file_system_manager.file_exists, urls_path):
                    related_files.add(urls_path)

            # Example rule for tests: if writing a test, get the app code it's testing
            # Assuming test files are like 'app_name/test/test_feature.py' or 'app_name/tests.py'
            if 'test' in task.target.lower() and (task.target.endswith('.py') or task.target.endswith('.jsx')):
                # Try to determine app_path. This is a heuristic.
                potential_app_path_from_test = Path(task.target).parent
                if potential_app_path_from_test.name.lower() == 'test': # e.g. app/test/
                    potential_app_path_from_test = potential_app_path_from_test.parent # e.g. app/
                
                app_path_str = str(potential_app_path_from_test)

                views_path = os.path.join(app_path_str, 'views.py')
                models_path = os.path.join(app_path_str, 'models.py')
                app_urls_path = os.path.join(app_path_str, 'urls.py')
                app_forms_path = os.path.join(app_path_str, 'forms.py')

                if await asyncio.to_thread(self.file_system_manager.file_exists, views_path):
                    related_files.add(views_path)
                if await asyncio.to_thread(self.file_system_manager.file_exists, models_path):
                    related_files.add(models_path)
                if await asyncio.to_thread(self.file_system_manager.file_exists, app_urls_path):
                    related_files.add(app_urls_path)
                if await asyncio.to_thread(self.file_system_manager.file_exists, app_forms_path):
                    related_files.add(app_forms_path)
                
        # Assemble the context string from the contents of the identified files.
        context_str = ""
        for file_path_rel_str in sorted(list(related_files)):
            if await asyncio.to_thread(self.file_system_manager.file_exists, file_path_rel_str):
                try:
                    content = await asyncio.to_thread(self.file_system_manager.read_file, file_path_rel_str)
                    context_str += f"--- START OF {file_path_rel_str} ---\n\n{content}\n\n--- END OF {file_path_rel_str} ---\n\n"
                except Exception as e:
                    logger.warning(f"Could not read file {file_path_rel_str} for holistic context: {e}")
                    context_str += f"--- START OF {file_path_rel_str} ---\n\n[Error reading file: {e}]\n\n--- END OF {file_path_rel_str} ---\n\n"
            else:
                logger.debug(f"File {file_path_rel_str} not found for holistic context (might be a 'Create file' task).")
                context_str += f"--- START OF {file_path_rel_str} ---\n\n[File does not exist or not yet created]\n\n--- END OF {file_path_rel_str} ---\n\n"
                
        return context_str if context_str else "# No holistic context gathered.\n"



    def _clean_llm_code_output(self, raw_code: str) -> str:
        """
        A guardrail function that automatically strips common LLM artifacts, like
        Markdown code fences (e.g., ```python), from the generated code. This ensures
        that only the raw code is written to the file.
        """
        # Remove leading/trailing markdown fences (e.g., ```python ... ```)
        # Make stripping more aggressive: strip leading/trailing whitespace first, then regex
        cleaned_code = raw_code.strip()
        # This regex removes the opening and closing fences, including an optional
        # language specifier like 'python'.
        # Regex to remove leading and trailing fences, including optional language specifier
        cleaned_code = re.sub(r"^\s*```(?:python|html|css|javascript|text|xml)?\s*\n?", "", cleaned_code, flags=re.IGNORECASE | re.MULTILINE)
        cleaned_code = re.sub(r"\n?\s*```\s*$", "", cleaned_code, flags=re.MULTILINE).strip() # Strip again after regex
        return cleaned_code

    # ADD THIS SECOND NEW HELPER METHOD
    def _validate_python_syntax(self, code: str, file_path: str) -> None:
        """
        Validates Python code syntax using the built-in `ast` module before writing
        it to a file. This is a fast, local check that prevents the system from
        writing syntactically invalid code, which would cause later steps to fail.
        """
        if not file_path.lower().endswith(".py"):
            return # Only validate Python files
        try:
            ast.parse(code)
        except SyntaxError as e:
            # Raise a specific error that can be caught and handled
            raise ValueError(f"Generated code for {file_path} has a SyntaxError on line {e.lineno}: {e.msg}") from e

    async def _call_llm_with_error_handling(
        self,
        agent_type_str: Literal["Tars", "Case"],
        messages: List[ChatMessage],
        feature_or_task_id: str, # For logging/reporting context
        temperature: float # Add temperature parameter
    ) -> ChatMessage:
        """
        A centralized helper method to call an LLM agent with robust, built-in
        error handling. It automatically handles API authentication errors by
        prompting the user to update their key and handles transient network
        errors by asking the user if they want to retry.
        """
        logger.debug(f"Calling LLM ({agent_type_str}) for '{feature_or_task_id}' with temperature: {temperature}")
        if not self.agent_manager:
            raise RuntimeError("AgentManager not available in WorkflowManager.")

        system_prompt = messages[0]
        user_messages = messages[1:]
        # The AgentManager's invoke_agent method now handles client selection and temperature.
        # We will call agent_manager.invoke_agent instead of client_method directly.
        # This loop allows for retries without the calling function needing to manage it.

        while True:
            try:
                # Use agent_manager.invoke_agent which now accepts temperature
                # Note: The system_prompt for invoke_agent is not directly available here.
                # This indicates a potential refactoring need if _call_llm_with_error_handling
                # is meant to be a generic LLM call wrapper.
                # For now, assuming the `messages` list already includes the system prompt
                # as the first message, or that the client's .chat() method is still appropriate.
                # Given the previous diffs, client.chat() was updated to take temperature.
                response = await asyncio.to_thread(self.agent_manager.invoke_agent, system_prompt, user_messages, temperature)
                # If the call is successful, return the response.
                return response
            except (AuthenticationError, RateLimitError) as api_error:
                logger.warning(f"API error during LLM call for {feature_or_task_id}: {api_error}")
                self.progress_callback({"message": f"API Error. Waiting for API key update..."})

                error_type_str = "AuthenticationError" if isinstance(api_error, AuthenticationError) else "RateLimitError"
                
                resolved = await self.agent_manager.handle_api_error_and_reinitialize(error_type_str, str(api_error))

                # If the user provided a new key or chose to retry, the loop continues.
                if resolved:
                    self.progress_callback({"message": f"API key updated/confirmed. Retrying..."})
                    continue # Retry the chat call
                else:
                    logger.error(f"User cancelled API key update during {feature_or_task_id}.")
                    raise InterruptedError(f"User cancelled API key update.") from api_error
            except requests.exceptions.RequestException as net_error:
                logger.error(f"Network error during LLM call for {feature_or_task_id}: {net_error}")
                if self._request_network_retry_cb:
                    self.progress_callback({"message": f"Network error. Waiting for user to retry..."})
                    should_retry_network = await self._request_network_retry_cb(f"Agent ({self.agent_manager.model_id})", str(net_error))
                    if should_retry_network:
                        self.progress_callback({"message": f"Retrying network call..."})
                        await asyncio.sleep(2) # Brief pause before retry
                        continue
                    else:
                        logger.error(f"User chose not to retry network error during {feature_or_task_id}.")
                        raise InterruptedError(f"Network error and user chose not to retry.") from net_error
                else:
                    logger.error(f"No network retry callback available. Raising error.")
                    raise # Re-raise if no way to handle network retry prompt



    # --- User-Friendly Error Reporting ---
    def _report_error(self, message: str, task_id: Optional[str] = None, is_fatal: bool = False):
        """
        A standardized helper function to report errors to the user via the
        thread-safe progress callback.
        """
        log_prefix = f"Task {task_id}: " if task_id else ""
        logger.error(f"{log_prefix}{message}")
        # Use a more generic error message for the user unless it's fatal
        user_message = f"An issue occurred"
        if task_id: user_message += f" while working on task {task_id}"
        user_message += f". {message}" # Append the specific message for now, can refine later
        if is_fatal: user_message += " Cannot continue."

        # Send error message via progress callback
        # IMPORTANT: Avoid sending raw technical tracebacks here.
        # The 'error' key might trigger specific UI handling.
        self.progress_callback({"error": user_message})
    def _report_system_message(self, message: str, task_id: Optional[str] = None):
        """ Helper function to report system status messages. """
        log_prefix = f"Task {task_id}: " if task_id else ""
        logger.info(f"{log_prefix}{message}")
        self.progress_callback({"system_message": message})

    async def _resolve_placeholders_in_prompt_text(self, prompt_text: str) -> str:
        """
        Resolves {{placeholder_id}} and {{placeholder_id.attribute}} in prompt text
        using self.project_state.artifact_registry.
        Pillar 2.
        """
        if not self.project_state or not self.project_state.artifact_registry:
            return prompt_text

        # Regex to find {{ placeholder_id }} or {{ placeholder_id.attribute_name }}
        # It captures the main placeholder_id and an optional attribute_name
        placeholder_regex = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)(?:\.([a-zA-Z_][a-zA-Z0-9_]*))?\s*\}\}")

        def replace_match(match):
            placeholder_id = match.group(1)
            attribute_name = match.group(2)

            if self.project_state and placeholder_id in self.project_state.artifact_registry:
                artifact = self.project_state.artifact_registry[placeholder_id]
                if attribute_name:
                    # If an attribute is specified, try to get it from the artifact (assuming artifact is a dict)
                    if isinstance(artifact, dict) and attribute_name in artifact:
                        return str(artifact[attribute_name])
                    else:
                        logger.warning(f"Artifact '{placeholder_id}' found, but attribute '{attribute_name}' is missing or artifact is not a dict. Artifact: {artifact}")
                        return match.group(0) # Return original placeholder if attribute not found
                else:
                    # No attribute specified, return a default representation of the artifact
                    # This could be 'name', 'file_path', or just the string representation
                    if isinstance(artifact, dict):
                        # Prioritize 'name', then 'file_path', then the whole dict as string
                        return str(artifact.get("name", artifact.get("file_path", match.group(0))))
                    else: # If artifact is not a dict (e.g., just a string value)
                        return str(artifact)
            else:
                logger.warning(f"Placeholder '{{{{{placeholder_id}}}}}' not found in artifact registry.")
                return match.group(0) # Return original placeholder if not found

        return placeholder_regex.sub(replace_match, prompt_text)

    async def _update_artifact_registry(self, task: FeatureTask, result: Any):
        """
        Updates the project_state.artifact_registry based on a completed task.
        Pillar 2.
        """
        if not self.project_state or not task.resources_defined:
            return

        placeholder_id = task.resources_defined
        # Basic artifact details
        artifact_details: Dict[str, Any] = {"id": placeholder_id, "defined_by_task": task.task_id_str}

        if task.action == "Create file" or task.action == "Modify file":
            file_path = task.target
            if not file_path:
                logger.warning(f"Cannot update artifact registry for task {task.task_id_str}: task target is empty.")
                return
            artifact_details["file_path"] = file_path
            artifact_details["type"] = "file"

            # Basic parsing for Python files (can be enhanced with AST or CodeIntelligenceService)
            if file_path.endswith(".py"):
                try:
                    content = await asyncio.to_thread(self.file_system_manager.read_file, file_path)
                    # Simple regex for class and function names (can be improved)
                    class_match = re.search(r"class\s+([A-Za-z_][A-Za-z0-9_]*)", content)
                    func_match = re.search(r"def\s+([A-Za-z_][A-Za-z0-9_]*)", content) # Simplified
                    if class_match:
                        artifact_details["name"] = class_match.group(1)
                        artifact_details["resource_kind"] = "class" # Example kind
                    elif func_match: # Prioritize class if both found, or make more specific
                        artifact_details["name"] = func_match.group(1)
                        artifact_details["resource_kind"] = "function"
                except Exception as e:
                    logger.warning(f"Could not parse file {file_path} for artifact registry: {e}")
        elif task.action == "Create directory":
            if not task.target: return
            artifact_details["file_path"] = task.target # Path to the directory
            artifact_details["type"] = "directory"
            artifact_details["name"] = Path(task.target).name # Name of the directory
        # Add more conditions for other actions or resource types if needed

        if self.project_state: # Ensure project_state is still valid
            self.project_state.artifact_registry[placeholder_id] = artifact_details
            logger.info(f"Updated artifact registry: '{placeholder_id}' -> {artifact_details}")
            self.memory_manager.save_project_state(self.project_state) # Save state after update



    async def initialize_project(self, project_root: str, framework: str, initial_prompt: str, is_new_project: bool):
        """
        Initializes the project state for the WorkflowManager.

        This involves:
        1. Loading framework-specific prompts.
        2. Loading existing project state from disk, if available and matching the framework.
        3. If no state exists or framework mismatches:
           - Creating a new project state structure.
           - Performing initial framework setup (venv, requirements, startproject/npm init).
           - Identifying initial features based on the user's first prompt.
           - **Triggering the main feature cycle to start processing.**
        4. Saving the initialized or loaded state.

        Args:
            project_root: The absolute path to the project's root directory.
            framework: The name of the selected framework (e.g., "django").
            initial_prompt: The user's first prompt describing the project goal.
            is_new_project: Flag from the UI indicating if initial framework setup should run.

        Raises:
            RuntimeError: If prompt loading or initial setup fails critically.
            ValueError: If required prompts are missing for the framework.
        """
        logger.info(f"Initializing project. Root: '{project_root}', Framework: '{framework}'")
        self.progress_callback({"increment": 5, "message": "Loading project state & prompts..."})

        # --- 0. Load Workflow Context ---
        self.workflow_context = self.memory_manager.load_workflow_context()

        # --- 1. Load Framework Prompts ---
        try:
            self.prompts = self.config_manager.load_prompts(framework)
            # --- FIX: Update the RemediationManager with the loaded prompts ---
            if self.remediation_manager:
                self.remediation_manager.prompts = self.prompts
                logger.info("RemediationManager prompts updated with loaded framework prompts.")
            # --- END FIX ---
            required_prompt_keys = list(FrameworkPrompts.__annotations__.keys())
            if not all(hasattr(self.prompts, key.lower()) for key in required_prompt_keys): # Check attributes on the dataclass instance
                missing_keys = [key for key in required_prompt_keys if not hasattr(self.prompts, key.lower())]
                logger.error(f"Framework '{framework}' prompts file is missing required keys: {missing_keys}. Workflow cannot proceed.")
                raise ValueError(f"Required prompt keys missing for framework '{framework}': {missing_keys}")
            logger.info(f"Loaded prompts successfully for framework: {framework}")
        except (ValueError, RuntimeError, FileNotFoundError) as e:
             logger.exception(f"Fatal error: Failed to load prompts for framework '{framework}'.")
             self._report_error(f"Failed to load essential configuration for {framework}. Cannot proceed.", is_fatal=True)
             raise RuntimeError(f"Failed to load prompts: {e}") from e # Stop initialization

        # --- 2. Load Existing Project State ---
        # MemoryManager.load_project_state now returns a ProjectState instance or None
        loaded_state: Optional[ProjectState] = self.memory_manager.load_project_state()

        # --- Intercept for Remediation Testing ---
        # If a special developer test prompt is used, we must clear any existing features
        # from the loaded state. This ensures the special test plan is generated and run,
        # overriding any previously failed states that would otherwise halt the workflow.
        prompt_upper = initial_prompt.strip().upper()
        if prompt_upper in ["TEST_REMEDIATION", "TEST_EMPTY_FILE_FAILURE", "TEST_REMEDIATION_RETRY", "TEST_COMMAND_REMEDIATION"] and loaded_state:
            logger.info(f"{prompt_upper} prompt detected. Clearing existing features from loaded state to force test plan generation.")
            loaded_state.features.clear()

        # Determine if setup is needed. It's needed if the user checked "New Project"
        # AND there's no valid existing state. If user unchecks it, we skip setup
        # even if no state file is found.
        is_new_project_setup = is_new_project

        if loaded_state:
            # Check if loaded state matches the selected framework
            if loaded_state.framework != framework:
                logger.warning(f"Loaded project state framework ('{loaded_state.framework}') does not match selected framework ('{framework}'). Discarding old state.")
                self.memory_manager.clear_project_state() # Discard inconsistent state
                loaded_state = None # Treat as a new project scenario
                # If state is discarded, we must treat it as a new project setup regardless of the checkbox
                is_new_project_setup = True
            else:
                # State loaded and framework matches. Use the loaded state.
                self.project_state = loaded_state
                # Update root path
                self.project_state.root_path = project_root
                # Pydantic handles defaults, but ensure consistency if loaded from older format
                if not hasattr(self.project_state, 'placeholders') or self.project_state.placeholders is None:
                    self.project_state.placeholders = {}
                # Ensure project_structure_map exists
                if not hasattr(self.project_state, 'project_structure_map') or self.project_state.project_structure_map is None:
                    from .project_models import ProjectStructureMap # Local import for safety
                    self.project_state.project_structure_map = ProjectStructureMap()
                if not hasattr(self.project_state, 'features') or self.project_state.features is None:
                     self.project_state.features = []
                if not hasattr(self.project_state, 'cumulative_docs') or self.project_state.cumulative_docs is None:
                     self.project_state.cumulative_docs = f"# {self.project_state.project_name or 'Project'} - Technical Documentation\n\nFramework: {framework}\n"
                if not hasattr(self.project_state, 'current_feature_id'):
                     self.project_state.current_feature_id = None
                # Ensure new fields from ProjectState are present
                if not hasattr(self.project_state, 'code_summaries') or self.project_state.code_summaries is None:
                    self.project_state.code_summaries = {}
                if not hasattr(self.project_state, 'historical_notes') or self.project_state.historical_notes is None:
                    self.project_state.historical_notes = []
                # --- ADDED: Ensure security_feedback_history exists ---
                if not hasattr(self.project_state, 'security_feedback_history') or self.project_state.security_feedback_history is None:
                    self.project_state.security_feedback_history = []
                # --- END ADDED ---
                if not hasattr(self.project_state, 'historical_notes') or self.project_state.historical_notes is None:

                    self.project_state.historical_notes = []


                # Initialize remediation_attempts if missing from loaded tasks (using attribute access)
                for feature in self.project_state.features:
                    if not hasattr(feature, 'status'): feature.status = "identified" # Default if missing
                    if not hasattr(feature, 'tasks'): feature.tasks = []
                    for task in feature.tasks:
                        if not hasattr(task, 'remediation_attempts') or task.remediation_attempts is None:
                            task.remediation_attempts = 0
                        if not hasattr(task, 'status'): task.status = "pending" # Default if missing

                logger.info("Loaded existing project state successfully.")
                self.progress_callback({"increment": 10, "message": "Loaded existing project state."})

                # Check if the loaded state has features, or if we should re-identify based on the prompt
                if not self.project_state.features:
                    logger.warning("Loaded project state has no features. Attempting feature identification from the current initial prompt.")
                    self._report_system_message("Existing state has no features. Identifying from prompt...")
                    try:
                        identified_features = await self._identify_features_from_prompt(initial_prompt, is_initial=True) # Use await here
                        if identified_features:
                            self.project_state.features.extend(identified_features)
                            feature_names = [f.name for f in identified_features] # Use attribute access
                            logger.info(f"Identified and added {len(identified_features)} initial features to existing state: {feature_names}")
                            self._report_system_message(f"Added initial features to existing state: {feature_names}")
                        else:
                            logger.warning("Initial feature identification returned no features for existing state.")
                            self._report_system_message("Could not identify specific features from prompt for existing state.")
                    except Exception as e:
                        logger.exception("Failed during feature identification for existing state.")
                        self._report_error(f"Failed feature identification for existing state: {e}")
                        # Decide if this should be fatal or just logged. Logging for now.
                else:
                    logger.info("Existing project state already contains features. Skipping initial feature identification.")

                # Since we loaded state, we consider setup "done" for this phase.
                # The main loop will decide whether to run the feature cycle.
                is_new_project_setup = False

        else:
             # No state file found or framework mismatch - this is a new project setup scenario
             is_new_project_setup = True

        # --- 3. Handle New Project Scenario ---
        if is_new_project_setup:
            logger.info("No valid existing project state found. Creating new state and performing initial setup.")
            project_name_raw = Path(project_root).name
            # Create a safe project name (valid Python identifier, needed for Django/Flask module names)
            safe_project_name = re.sub(r'\W|^(?=\d)', '_', project_name_raw).lower()
            if not safe_project_name or safe_project_name in ['django', 'flask', 'test', 'src', 'core', 'venv']: # Avoid reserved/common names
                safe_project_name = f"proj_{safe_project_name}" if safe_project_name else "my_project"
            logger.info(f"Using safe project name: '{safe_project_name}' (derived from '{project_name_raw}')")

            # Create the initial project state structure using the Pydantic model
            try:
                self.project_state = ProjectState(
                    project_name=safe_project_name,
                    framework=framework,
                    root_path=project_root,
                    # features, current_feature_id, cumulative_docs, placeholders, code_summaries, historical_notes use defaults
                    cumulative_docs=f"# {safe_project_name} - Technical Documentation\n\nFramework: {framework}\n",
                )

            except ValidationError as val_e:
                 logger.error(f"Failed to create initial ProjectState model: {val_e}")
                 raise RuntimeError(f"Failed to create initial project state: {val_e}") from val_e

            self.progress_callback({"increment": 8, "message": "Created new project state."})

            # --- 3a. Perform Initial Framework Setup ---
            # This creates venv, installs base requirements, runs startproject/npm init etc.
            if is_new_project_setup:
                try:
                    logger.info("Performing initial framework setup for new project...")
                    await self._perform_initial_framework_setup(framework)
                    logger.info("Initial framework setup completed successfully.")
                    self.progress_callback({"increment": 15, "message": "Initial framework setup complete."})
                except Exception as setup_e: # This 'except' is correctly aligned with the 'try'
                    # --- ADDED: Attempt Git Init and Initial Commit on New Project Setup ---
                    # Even if framework setup fails, try to init Git for basic versioning
                    try:
                        git_dir = Path(project_root) / ".git" # Corrected: project_root should be Path object
                        if not git_dir.exists():
                            logger.info("Attempting Git initialization...")
                            self.progress_callback({"message": "Initializing Git repository..."})
                            await asyncio.to_thread(self.command_executor.run_command, "git init")
                            logger.info("Git repository initialized.")
                            
                            # Add all files and make initial commit
                            await asyncio.to_thread(self.command_executor.run_command, "git add .")
                            initial_commit_msg = f"Initial project setup for {self.project_state.project_name}"
                            await asyncio.to_thread(self.command_executor.run_command, f'git commit -m "{initial_commit_msg}"')
                            logger.info("Initial Git commit created.")
                            self.project_state.active_git_branch = "main" # Assume 'main' is default after init
                            self.progress_callback({"increment": 18, "message": "Git repository initialized."})
                        else:
                            logger.info("Git repository already exists. Skipping initialization.")
                            self.progress_callback({"increment": 18, "message": "Git repository found."})
                    except Exception as git_e:
                        logger.warning(f"Failed during Git initialization or initial commit: {git_e}")
                    # --- END ADDED Git Init ---
                    logger.exception("Fatal error during initial framework setup.") # Corrected indentation
                    self._report_error(f"Initial framework setup failed: {setup_e}", is_fatal=True) # Corrected indentation
                    # Save the partially created state even on setup failure for inspection # Corrected indentation
                    if self.project_state: self.memory_manager.save_project_state(self.project_state) # Corrected indentation
                    raise RuntimeError(f"Initial framework setup failed: {setup_e}") from setup_e # Stop initialization # Corrected indentation
            else:
                logger.info("Skipping initial framework setup as 'New Project' was not checked or state was loaded.")
                self.progress_callback({"message": "Skipping initial setup for existing project."})

            # --- 3b. Identify Initial Features from Prompt ---
            # Only do this for a truly new project setup.
            logger.info("Attempting initial feature identification for new project...")
            try:
                # This method should analyze the prompt and create initial ProjectFeature entries
                identified_features = await self._identify_features_from_prompt(initial_prompt, is_initial=True) # Use await
                if identified_features:
                    # Ensure new features have remediation_attempts initialized (done within _identify_features)
                    self.project_state.features.extend(identified_features) # Use attribute access
                    feature_names = [f.name for f in identified_features] # Use attribute access
                    logger.info(f"Identified {len(identified_features)} initial features: {feature_names}")
                    self._report_system_message(f"Identified initial features: {feature_names}")
                else:
                    logger.warning("Initial feature identification returned no features.")
                    self._report_system_message("No specific features identified yet. Ready for planning.")

                # Save the newly created state with identified features
                self.memory_manager.save_project_state(self.project_state)
                self.progress_callback({"increment": 20, "message": "Initial project state ready."})

            except Exception as e:
                logger.exception("Failed during initial feature identification or subsequent cycle trigger.")
                self._report_error(f"Failed initial feature identification/cycle start: {e}")
                # Save state even if feature ID fails
                if self.project_state: self.memory_manager.save_project_state(self.project_state)
                self.progress_callback({"increment": 20, "message": "Project state created (feature ID/cycle failed)."})
                # Don't necessarily stop initialization here, user might want to proceed manually
                # --- FIX: Re-raise the exception to signal failure ---
                raise RuntimeError(f"Failed during initial feature identification or cycle start: {e}") from e

        # --- Trigger feature cycle if there are features to process ---
        if self.project_state and self.project_state.features:
            if any(f.status != "merged" for f in self.project_state.features):
                logger.info("Project has unprocessed features. Triggering feature cycle...")
                await self.run_feature_cycle()
            else:
                logger.info("Project loaded, and all features are merged. Ready for new prompt.")
                self.progress_callback({"increment": 100, "message": "Project loaded. Ready."})

        # --- 4. Final Save (if not already saved during new project setup) ---
        # This handles the case where an existing state was loaded but maybe modified (e.g., root_path)
        if not is_new_project_setup and self.project_state:
            try:
                self.memory_manager.save_project_state(self.project_state)
            except Exception as e:
                logger.error(f"Failed to save loaded project state after initialization: {e}")
                # Non-fatal, but log the error.

        # --- 5. Save Workflow Context ---
        try:
            # Save any potential updates made during initialization (though none currently)
            self.memory_manager.save_workflow_context(self.workflow_context)
        except Exception as e:
            logger.error(f"Failed to save workflow context after initialization: {e}")

        logger.info("Project initialization complete.")

    async def _define_or_refine_api_contracts(self, feature: ProjectFeature) -> None:
        """
        Uses Tars to define or refine API contracts for a given feature.
        Stores the contracts in project_state.api_contracts and links them to the feature.
        (Simplified initial implementation - a full LLM-driven contract generation is complex)
        """
        if not self.project_state or not self.prompts:
            logger.error("Cannot define API contracts: Project state or prompts not loaded.")
            return

        # For now, this is a placeholder. A real implementation would:
        # 1. Craft a prompt for Tars asking it to define API endpoints (path, method, request/response schema)
        #    based on feature.description and existing project context/contracts.
        # 2. Call the LLM.
        # 3. Parse the LLM's response (e.g., structured JSON or Markdown describing the API).
        # 4. Convert the parsed information into APIContract Pydantic models.
        # 5. Add/update these contracts in self.project_state.api_contracts.
        # 6. Populate feature.related_api_contract_ids with the IDs of the generated/updated contracts.

        logger.info(f"Placeholder: Defining/refining API contracts for feature '{feature.name}'.")
        self.progress_callback({"message": f"Defining API contracts for {feature.name}..."})

        # Example: Create a dummy contract if the feature description mentions "API"
        if "api" in feature.description.lower() and not feature.related_api_contract_ids:
            from .project_models import APIContract, APIContractEndpoint # Local import
            dummy_contract_id = f"contract_{feature.id.replace('-', '_')}_{int(time.time())}"
            dummy_endpoint = APIContractEndpoint(
                path=f"/api/{feature.id.replace(' ', '-').lower()}",
                method="GET",
                summary=f"Endpoint for {feature.name}",
                responses={"200": {"description": "Successful response"}}
            )
            dummy_contract = APIContract(
                contract_id=dummy_contract_id,
                feature_id=feature.id,
                title=f"API for {feature.name}",
                endpoints=[dummy_endpoint]
            )
            if self.project_state: # Ensure project_state is not None
                if not hasattr(self.project_state, 'api_contracts') or self.project_state.api_contracts is None:
                    self.project_state.api_contracts = [] # Initialize if missing
                self.project_state.api_contracts.append(dummy_contract)
                feature.related_api_contract_ids.append(dummy_contract_id)
                logger.info(f"Created dummy API contract '{dummy_contract_id}' for feature '{feature.name}'.")
                self.memory_manager.save_project_state(self.project_state)


    async def handle_new_prompt(self, prompt: str):
        """
        Handles a new user prompt received after the project has been initialized.

        This typically involves:
        1. Identifying new features based on the prompt.
        2. Adding these features to the project state.
        3. Triggering the main feature development cycle (`run_feature_cycle`).

        Args:
            prompt: The new user prompt describing desired changes or features.

        Raises:
            RuntimeError: If the project state is not initialized.
        """
        if not self.project_state:
            logger.error("Cannot handle new prompt: Project state is not initialized.")
            self._report_error("Cannot process request: Project is not properly loaded.", is_fatal=True)
            raise RuntimeError("Project state not initialized. Call initialize_project first.")

        logger.info(f"Handling new prompt: '{prompt[:100]}...'")
        self.progress_callback({"increment": 5, "message": "Identifying features from new prompt..."})

        try:
            # Identify features based on the new prompt (not the initial one)
            new_features = await self._identify_features_from_prompt(prompt, is_initial=False) # Use await

            if not new_features:
                logger.warning("No new features identified from the prompt.")
                self.progress_callback({"increment": 100, "message": "No new features identified. Ready for next prompt."})
                self._report_system_message("Could not identify specific new features from the prompt.")
                return # Nothing to do if no features are identified

            logger.info(f"Identified {len(new_features)} new features from prompt.")
            feature_names = [f.name for f in new_features] # Use attribute access
            self._report_system_message(f"Identified new features: {feature_names}")

            # Add the newly identified features to the project state
            if self.project_state: # Ensure project_state is not None
                if not hasattr(self.project_state, 'features') or self.project_state.features is None:
                    self.project_state.features = [] # Initialize if missing
                self.project_state.features.extend(new_features) # Use attribute access
                self.memory_manager.save_project_state(self.project_state) # Save state after adding features
                logger.info("Added new features to project state.")
                self.progress_callback({"increment": 10, "message": "New features added. Starting development cycle..."})

                # Start the main development cycle to plan and implement the new features
                await self.run_feature_cycle()
            else:
                logger.error("Cannot add new features: Project state is None.")
                self._report_error("Critical error: Project state became unavailable.", is_fatal=True)

        except Exception as e:
            logger.exception(f"Error handling new prompt: {e}")
            self._report_error(f"Failed to process the new request: {e}")
            # Attempt to save state even after an error
            if self.project_state:
                try: self.memory_manager.save_project_state(self.project_state)
                except Exception as save_e: logger.error(f"Failed to save state after prompt handling error: {save_e}")


    async def _identify_features_from_prompt(self, prompt: str, is_initial: bool) -> List[ProjectFeature]:
        """
        Identifies potential features from a user prompt using Tars (Feature Identifier).

        Args:
            prompt: The user's prompt string.
            is_initial: Boolean indicating if this is the very first prompt for a new project.

        Returns:
            A list containing ProjectFeature Pydantic models (or empty list if prompt is empty or identification fails).
        """
        if not prompt or not self.prompts or not self.project_state:
            logger.warning("Cannot identify features: Missing prompt, prompts config, or project state.")
            return []

        # --- Special Handling for Remediation System Testing ---
        # This allows developers to bypass the full planning cycle to test the self-healing capabilities directly.
        if prompt.strip().upper() == "TEST_REMEDIATION":
            logger.info("TEST_REMEDIATION mode activated. Bypassing LLM for feature identification and planning.")
            self._report_system_message("TEST_REMEDIATION mode activated. Creating a direct test plan.")

            # Create a hardcoded feature and a single task to run the tests.
            test_task = FeatureTask(
                task_id_str="1.1",
                action="Run command",
                target="python manage.py test",
                description="Run all project tests to trigger and validate the remediation system.",
                requirements="This is a test to validate the self-healing capabilities of the system against a pre-configured buggy project.",
                test_step="echo 'Manual: Review test output and remediation process.'"
            )
            test_feature = ProjectFeature(
                id="remediation_test_feature_001",
                name="Remediation System Test",
                description="A special feature to directly test the remediation system by running tests.",
                status=FeatureStatusEnum.PLANNED, # Mark as 'planned' to skip the _plan_feature step.
                tasks=[test_task]
            )
            return [test_feature]
        
        # --- NEW: Special Handling for Empty File Creation Test ---
        if prompt.strip().upper() == "TEST_EMPTY_FILE_FAILURE":
            logger.info("TEST_EMPTY_FILE_FAILURE mode activated. Bypassing LLM for feature identification.")
            self._report_system_message("TEST_EMPTY_FILE_FAILURE mode activated. Creating a direct test plan.")

            # This task is designed to fail if the logic for empty files is incorrect.
            # The requirement "Create an empty placeholder file" is likely to make the LLM return empty content.
            empty_file_task = FeatureTask(
                task_id_str="1.1",
                action="Create file",
                target="test_empty_file.js",
                description="Create an empty placeholder file to test the agent's handling of empty content from Case.",
                requirements="Create an empty placeholder file. The file should contain no content.",
                test_step="type test_empty_file.js" # Windows command to verify existence
            )
            test_feature = ProjectFeature(
                id="empty_file_test_feature_001", name="Empty File Creation Test", description="A special feature to test empty file creation.", status=FeatureStatusEnum.PLANNED, tasks=[empty_file_task]
            )
            return [test_feature]
        
        # --- NEW: Special Handling for Remediation Retry Test ---
        if prompt.strip().upper() == "TEST_REMEDIATION_RETRY":
            logger.info("TEST_REMEDIATION_RETRY mode activated. Bypassing LLM for feature identification.")
            self._report_system_message("TEST_REMEDIATION_RETRY mode activated. Creating a direct test plan.")

            # This task is designed to fail, triggering the remediation manager,
            # which is also expected to fail, which will then trigger the user retry prompt.
            failing_task = FeatureTask(
                task_id_str="1.1",
                action="Run command",
                target='python -c "import sys; print(\'Simulating a persistent error\', file=sys.stderr); sys.exit(1)"',
                description="Run a command that is guaranteed to fail to test the remediation retry dialog.",
                requirements="This command must fail to trigger the remediation cycle.",
                test_step="echo 'This test step will not be reached on the first pass.'"
            )
            test_feature = ProjectFeature(
                id="remediation_retry_test_feature_001",
                name="Remediation Retry System Test",
                description="A special feature to test the user-facing retry mechanism for a failed remediation cycle.",
                status=FeatureStatusEnum.PLANNED,
                tasks=[failing_task]
            )
            return [test_feature]

        if prompt.strip().upper() == "TEST_COMMAND_REMEDIATION":
            logger.info("TEST_COMMAND_REMEDIATION mode activated. Bypassing LLM for feature identification.")
            self._report_system_message("TEST_COMMAND_REMEDIATION mode activated. Creating a direct test plan.")

            # This task is designed to fail with a command error that the LLM can fix by changing the command.
            failing_command_task = FeatureTask(
                task_id_str="1.1",
                action="Run command",
                target='python manage.py startapp calculator', # This will fail due to name conflict
                description="Run a command that is guaranteed to fail with a name conflict to test command remediation.",
                requirements="This command must fail to trigger the remediation cycle for command correction.",
                test_step="dir calculator" # This test step will fail if the command fails, which is intended.
            )
            test_feature = ProjectFeature(
                id="command_remediation_test_feature_001",
                name="Command Remediation System Test",
                description="A special feature to test the remediation system's ability to correct a failing command string.",
                status=FeatureStatusEnum.PLANNED,
                tasks=[failing_command_task]
            )
            return [test_feature]
        # Ensure the specific feature identifier prompt key exists
        feature_id_prompt_key = "system_Tars_Feature_Identifier" # Assuming this key exists in FrameworkPrompts
        # Use getattr safely to access the prompt message
        identifier_system_prompt = getattr(self.prompts, feature_id_prompt_key.lower(), None)
        if not identifier_system_prompt:
             logger.error(f"Feature identifier prompt key '{feature_id_prompt_key}' not found. Using placeholder identification.")
             # Fallback to placeholder logic if prompt is missing
             return self._identify_features_placeholder(prompt, is_initial)

        logger.info(f"Identifying features from prompt using Tars (Feature Identifier)... (Initial: {is_initial})")
        self.progress_callback({"system_message": "Analyzing request to identify features..."})

        # --- Prepare context for Tars Feature Identifier ---
        # Less context needed than planner, focus on project goal and existing features
        project_context_summary = f"Project Name: {self.project_state.project_name or 'N/A'}\n" \
                                 f"Framework: {self.project_state.framework or 'N/A'}\n" \
                                 f"Initial Goal (if available): {self.project_state.features[0].description if self.project_state.features else 'N/A'}\n" \
                                 f"Existing Features: {', '.join([f.name for f in self.project_state.features]) if self.project_state.features else 'None'}"

        identifier_prompt_content = f"""
Analyze the following user request and identify distinct, actionable software features.
Consider the project context and any existing features.

**Project Context:**
{project_context_summary}

**User Request:**
"{prompt}"

**Instructions:**
- Break the request down into logical, high-level features.
- For each feature, provide a concise `name` and a brief `description`.
- Output the features as a JSON list of objects, each with "name" and "description" keys.
- If the request is too vague or doesn't seem to describe new features, return an empty list `[]`.
- Output ONLY the JSON list. No explanations.

Example Output:
[
  {{"name": "User Authentication", "description": "Allow users to sign up, log in, and log out."}},
  {{"name": "Product Catalog Display", "description": "Show a list of available products with images and prices."}}
]
"""
        identifier_request_messages: List[ChatMessage] = [
            identifier_system_prompt, # Use the loaded system prompt
            {"role": "user", "content": identifier_prompt_content}
        ]

        try:
            logger.debug("Sending feature identification request to Tars.")
            # --- CONCEPTUAL CHANGE NEEDED ---
            response_chat_message = await self._call_llm_with_error_handling("Tars", identifier_request_messages, feature_or_task_id="feature_identification", temperature=0.4)
            raw_output = response_chat_message['content']
            logger.debug(f"Raw feature identification response: {raw_output}")



            # --- MODIFIED: More robust JSON extraction ---
            json_str_candidate = None
            # Try to find JSON array within ```json ... ``` or ``` ... ```
            match_fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_output, re.DOTALL | re.IGNORECASE)
            if match_fenced:
                json_str_candidate = match_fenced.group(1)
            else:
                # Try to find the outermost JSON array if no fences
                # This regex looks for a string starting with '[' and ending with ']', containing anything in between.
                match_bare = re.search(r"(\[[\s\S]*\])", raw_output, re.DOTALL)
                if match_bare:
                    json_str_candidate = match_bare.group(0)

            if json_str_candidate:
                try:
                    identified_features_raw = json.loads(json_str_candidate)
                    logger.info("Successfully extracted and parsed JSON feature list from LLM response.")
                except json.JSONDecodeError as e:
                    logger.error(f"Extracted JSON candidate but failed to parse: {e}. Candidate: {json_str_candidate[:500]}")
                    return self._identify_features_placeholder(prompt, is_initial) # Fallback if extracted JSON is bad
            elif "no new features" in raw_output.lower() or raw_output.strip() == "[]" or raw_output.strip() == "null":
                     logger.info("Tars indicated no new features identified.")
                     return []
            else:
                logger.warning(f"Could not extract a valid JSON list from Tars feature identification response. Raw: {raw_output[:500]}...")
                return self._identify_features_placeholder(prompt, is_initial) # Fallback if no JSON list found
            # --- END MODIFICATION ---


            # --- Convert raw features to ProjectFeature structure and filter generic setup features ---
            project_features: List[ProjectFeature] = []
            existing_feature_ids = {f.id for f in self.project_state.features} # Use attribute access
            
            raw_features_from_llm: List[Dict[str, str]] = []
            if isinstance(identified_features_raw, list):
                raw_features_from_llm = [
                    item for item in identified_features_raw 
                    if isinstance(item, dict) and "name" in item and "description" in item
                ]

            original_llm_feature_names_before_filtering = [
                str(rf.get("name", "")).lower().strip() for rf in raw_features_from_llm
            ]

            for raw_feature_dict in raw_features_from_llm:
                feature_name = str(raw_feature_dict["name"]).strip()
                feature_description = str(raw_feature_dict["description"]).strip()

                # Generate a unique ID
                timestamp = int(time.time() * 1000)
                base_id = re.sub(r'\W+', '_', feature_name.lower()[:30]).strip('_') or "feature"
                feature_id = f"{base_id}_{timestamp}"
                while feature_id in existing_feature_ids: # Ensure uniqueness
                    feature_id = f"{base_id}_{int(time.time() * 1000)}_{hash(feature_name)}"

                try:
                    feature = ProjectFeature(
                        id=feature_id,
                        name=feature_name,
                        description=feature_description,
                        status="identified",
                    )
                    project_features.append(feature)
                    existing_feature_ids.add(feature_id)
                except ValidationError as val_e:
                    logger.error(f"Failed to validate created ProjectFeature: {val_e}. Skipping feature: {raw_feature_dict}")
                    continue
            
            # --- Filter out generic setup features and handle insufficient breakdown ---
            if project_features:
                filtered_features = []
                # Keywords to filter for generic setup tasks
                generic_setup_keywords = [
                    "initial project setup", 
                    "project setup", 
                    "base structure", 
                    "project initialization",
                    "environment setup",
                    "project scaffolding",
                    "application setup",
                    "initial setup", # Added this
                    "basic setup"    # Added this
                ]
                
                for pf_filter in project_features:
                    feature_name_lower = pf_filter.name.lower().strip() # Normalize: lowercase and strip whitespace
                    
                    is_generic_setup = False
                    for keyword in generic_setup_keywords:
                        if keyword == feature_name_lower: # Exact match for generic setup keywords
                            is_generic_setup = True
                            break 
                    
                    if not is_generic_setup:
                        filtered_features.append(pf_filter)
                    else:
                        logger.warning(f"Filtered out generic setup feature: '{pf_filter.name}' during feature identification.")

                # Check if the LLM only returned generic features for an initial complex prompt
                if is_initial:
                    # If the original LLM response (before Pydantic validation) was not empty,
                    # but after filtering, the list of functional features is empty,
                    # and the original LLM response *only* contained generic setup keywords.
                    if original_llm_feature_names_before_filtering and not filtered_features and \
                       all(any(keyword == orig_name for keyword in generic_setup_keywords) for orig_name in original_llm_feature_names_before_filtering):
                        
                        logger.error(
                            f"LLM failed to provide functional features for the initial prompt '{prompt}'. "
                            f"It only returned generic setup feature(s): {original_llm_feature_names_before_filtering}. "
                            "This indicates a failure to break down the user's actual requirements."
                        )
                        self._report_error(
                            "The AI failed to identify specific functional features for your request. "
                            "It only suggested basic project setup. Please try rephrasing your request with more detail, "
                            "or the system will proceed with a placeholder if this is the initial setup.",
                            is_fatal=False 
                        )
                        return [] # Return empty list to signify failure to get functional features
                project_features = filtered_features # Use the filtered list

                if not project_features and is_initial: # Check again after filtering
                    logger.warning("Feature identification resulted in no specific features after filtering generic setup. User prompt might have been too vague for initial feature breakdown or LLM failed to identify functional features.")

            logger.info(f"Tars identified {len(project_features)} specific features after filtering.")
            return project_features

        except json.JSONDecodeError as json_e:
            logger.error(f"Failed to parse JSON response from Tars Feature Identifier: {json_e}")
            logger.debug(f"Invalid JSON content (candidate that failed): {json_str_candidate if 'json_str_candidate' in locals() else 'N/A'}")
            # Fallback to placeholder on JSON error
            return self._identify_features_placeholder(prompt, is_initial)
        except (RateLimitError, AuthenticationError) as api_err:
             logger.error(f"Tars (Feature ID) failed due to API error: {api_err}")
             self._report_error(f"Could not analyze request due to an API issue ({type(api_err).__name__}).")
             # Fallback or return empty? Returning empty.
             return []
        except Exception as e:
            logger.exception("Error during Tars feature identification.")
            self._report_error(f"An unexpected error occurred while analyzing the request: {e}")
            # Fallback to placeholder on general error
            return self._identify_features_placeholder(prompt, is_initial)

    def _identify_features_placeholder(self, prompt: str, is_initial: bool) -> List[ProjectFeature]:
        """ Placeholder feature identification if LLM fails or is disabled. """
        logger.warning("Using placeholder feature identification.")
        if not prompt: return []

        if is_initial:
            feature_id = "initial_request"
            feature_name = "Initial Project Setup"
        else:
            timestamp = int(time.time() * 1000)
            prompt_keywords = re.findall(r'\b\w{4,15}\b', prompt.lower())
            id_suffix = "_".join(prompt_keywords[:3]) if prompt_keywords else "feature"
            id_suffix_safe = re.sub(r'\W+', '_', id_suffix)
            feature_id = f"{id_suffix_safe}_{timestamp}"
            feature_name = f"Request: {prompt[:40]}..."
        try:
            feature = ProjectFeature(
                id=feature_id,
                name=feature_name,
                description=prompt,
                status="identified",
            )
            return [feature]
        except ValidationError as val_e:
             logger.error(f"Failed to validate placeholder ProjectFeature: {val_e}")
             return []

    def _get_task_phase_priority(self, task: FeatureTask) -> int:
        """
        Assigns a numerical priority to a task based on its type and target for sorting.
        Lower numbers execute first. This is critical for logical framework workflows.
        """
        action = task.action
        target = task.target.lower() if isinstance(task.target, str) else "" # type: ignore
        # Safely get project name for constructing paths
        project_config_dir_name = self.project_state.project_name.lower() if self.project_state and self.project_state.project_name else "project_config" # type: ignore

        # Phase 1: Foundational App & Project Configuration
        if action == "Run command" and "manage.py startapp" in target: return 10
        if action == "Modify file" and target.endswith("/apps.py"): return 20
        if action == "Modify file" and f"{project_config_dir_name}/settings.py" in target:
            # Modifying INSTALLED_APPS is the highest priority settings change.
            if task.requirements and "installed_apps" in task.requirements.lower(): return 30 # type: ignore
            return 55 # General settings.py changes are lower priority but still foundational

        # Phase 2: Data Layer
        if (action == "Create file" or action == "Modify file") and target.endswith("/models.py"): return 100
        if action == "Run command" and "manage.py makemigrations" in target: return 110
        if action == "Run command" and "manage.py migrate" in target: return 120

        # Phase 3: Admin Interface & Forms
        if (action == "Create file" or action == "Modify file") and target.endswith("/admin.py"): return 200
        if (action == "Create file" or action == "Modify file") and target.endswith("/forms.py"): return 210

        # Phase 4: Business Logic & App-Level Routing
        if (action == "Create file" or action == "Modify file") and target.endswith("/views.py"): return 220
        # App-level urls.py must exist before the project-level urls.py can include it
        if (action == "Create file" or action == "Modify file") and target.endswith("/urls.py") and project_config_dir_name not in target: return 230

        # Phase 5: Project-Level URL Integration
        if action == "Modify file" and f"{project_config_dir_name}/urls.py" in target: return 300

        # Phase 6: Presentation & Static Files
        if (action == "Create file" or action == "Modify file") and "/templates/" in target and target.endswith(".html"): return 400
        if action == "Create directory" and "/static/" in target: return 410
        if (action == "Create file" or action == "Modify file") and "/static/" in target: return 420

        # Phase 6: Testing
        if action == "Run command" and "manage.py test" in target: return 600

        # General tasks with default priorities # type: ignore
        if action == "Prompt user input": return 50
        if action == "Create directory": return 800
        if action == "Create file": return 810
        if action == "Modify file": return 820
        if action == "Run command": return 830

        return 999 # Default for any unknown tasks

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
        requirements_file = project_root / "requirements.txt" # Standard name

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
                await self._execute_command_with_remediation(venv_command)
                logger.info("Virtual environment created successfully.")
                self.progress_callback({"increment": 5, "message": "Virtual environment created."})
            else:
                logger.info("Virtual environment already exists. Skipping creation.")
                self.progress_callback({"increment": 5, "message": "Virtual environment found."})

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
                await self._execute_command_with_remediation(install_command)
                logger.info("Requirements installed successfully.")
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
                    await self._execute_command_with_remediation(startproject_command)
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
            try:
                 git_dir = project_root / ".git"
                 if not git_dir.exists():
                     logger.info("Attempting Git initialization...")
                     self.progress_callback({"message": "Initializing Git repository..."})
                     # Use command_executor directly and catch FileNotFoundError
                     try:
                         await asyncio.to_thread(self.command_executor.run_command, "git init")
                         logger.info("Git repository initialized.")
 
                         # Add all files and make initial commit
                         await asyncio.to_thread(self.command_executor.run_command, "git add .")
                         initial_commit_msg = f"Initial project setup for {self.project_state.project_name}"
                         await asyncio.to_thread(self.command_executor.run_command, f'git commit -m "{initial_commit_msg}"')
                         logger.info("Initial Git commit created.")
                         self.project_state.active_git_branch = "main"
                         self.progress_callback({"increment": 18, "message": "Git repository initialized."})
                     except FileNotFoundError:
                         logger.warning("`git` command not found. Skipping Git initialization. The project will not be version-controlled.")
                         self.progress_callback({"warning": "Git not found. Skipping repository initialization."})
                     except Exception as git_e:
                         logger.warning(f"An error occurred during Git initialization: {git_e}. The project will not be version-controlled.")
                         self.progress_callback({"warning": f"Git initialization failed: {git_e}"})
                 else:
                     logger.info("Git repository already exists. Skipping initialization.")
            except Exception as git_e: # Catch any other unexpected error in this block
                 logger.warning(f"Failed during Git initialization or initial commit after successful framework setup: {git_e}")
        except (RuntimeError, ValueError, FileNotFoundError, InterruptedError) as setup_e:
            # Catch errors specifically raised by command_executor or file ops
            logger.error(f"Initial setup failed: {setup_e}")
            raise # Re-raise the exception to be handled by the caller
        except Exception as e:
            # Catch any other unexpected errors
            logger.exception(f"Unexpected error during initial setup for {framework}")
            raise RuntimeError(f"Unexpected error during initial setup: {e}") from e


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
                    logger.debug(f"Feature '{feature_to_check.name}' is eligible but dependencies not met. Skipping for now.")
        
        logger.info("No suitable eligible features found whose dependencies are met.")
        return None
    # --- Planning Phase Method ---

    async def _plan_feature(self, feature: ProjectFeature) -> bool:
        """
        Generates the detailed Markdown plan for a given feature using Tars (Planner).
        Includes validation of the generated plan.

        Args:
            feature: The ProjectFeature Pydantic model instance to plan.

        Returns:
            True if planning and validation succeed, False otherwise.
        """
        if not self.prompts or not self.project_state:
            logger.error("Cannot plan feature: Prompts or project state not loaded.")
            feature.status = FeatureStatusEnum.PLANNING_FAILED # Mark as failed if prerequisites are missing
            return False

        markdown_planner_prompt_key = "system_Tars_Markdown_Planner"
        # Ensure attribute access is lowercase for dataclass fields
        planner_system_prompt_template_dict = getattr(self.prompts, markdown_planner_prompt_key.lower().replace('-', '_'), None)

        if not planner_system_prompt_template_dict or \
           not isinstance(planner_system_prompt_template_dict, dict) or \
           not planner_system_prompt_template_dict.get("content"):
            logger.error(f"Markdown planner prompt key '{markdown_planner_prompt_key}' not found or invalid. Cannot plan feature '{feature.name}'.")
            self._report_error(f"Planning failed: Missing essential configuration for planner.", task_id=feature.id)
            feature.status = FeatureStatusEnum.PLANNING_FAILED
            self.memory_manager.save_project_state(self.project_state)
            return False

        framework_version_str = getattr(self.project_state, 'framework_version', 'latest')
        
        # Derive project_name_snake_case for the prompt
        project_name_snake_case = "myproject" # Default
        if self.project_state and self.project_state.project_name:
            project_name_snake_case = re.sub(r'\W|^(?=\d)', '_', self.project_state.project_name).lower()
            if not project_name_snake_case or project_name_snake_case in ['django', 'flask', 'test', 'src', 'core', 'venv']:
                project_name_snake_case = f"proj_{project_name_snake_case}" if project_name_snake_case else "my_project"

        planner_system_prompt_content_intermediate = planner_system_prompt_template_dict["content"].replace(
            "{{ FRAMEWORK_VERSION }}", framework_version_str
        )
        planner_system_prompt_content_final = planner_system_prompt_content_intermediate.replace(
            "{{PROJECT_NAME_SNAKE_CASE}}", project_name_snake_case
        )
        # --- FIX: Add substitution for PROJECT_CONFIG_DIR_NAME ---
        planner_system_prompt_content_final = planner_system_prompt_content_final.replace(
            "{{PROJECT_CONFIG_DIR_NAME}}", project_name_snake_case
        )
        # Pillar 2: Resolve placeholders in the system prompt content itself
        planner_system_prompt_content_final = await self._resolve_placeholders_in_prompt_text(planner_system_prompt_content_final) # Pillar 2

        planner_system_prompt: ChatMessage = { # type: ignore
            "role": "system",
            "name": "Tars",
            "content": planner_system_prompt_content_final
        }

        feature_name = feature.name
        feature_id = feature.id
        self.progress_callback({"increment": 15, "message": f"Planning feature: {feature_name}..."})
        logger.info(f"Requesting detailed plan for feature '{feature_name}' ({feature_id}) from Tars (Planner).")

        project_context = self._get_project_context_for_planning()
        # --- Define/Refine API Contracts before planning ---
        await self._define_or_refine_api_contracts(feature)
        # --- End API Contract Definition ---

        
        # Determine if frontend tasks are needed (simplified from your original)
        initial_prompt_lower = self.project_state.features[0].description.lower() if self.project_state and self.project_state.features else ''
        needs_frontend = "frontend" in initial_prompt_lower or "ui" in initial_prompt_lower or "template" in initial_prompt_lower

        project_goal_desc = self.project_state.features[0].description if self.project_state and self.project_state.features else 'N/A'

        # --- Get summary of related API contracts for the planner prompt ---

        
        # Determine if frontend tasks are needed (simplified from your original)
        initial_prompt_lower = self.project_state.features[0].description.lower() if self.project_state.features else ''
        needs_frontend = "frontend" in initial_prompt_lower or "ui" in initial_prompt_lower or "template" in initial_prompt_lower

        project_goal_desc = self.project_state.features[0].description if self.project_state.features else 'N/A'

        related_contracts_summary = ""
        if feature.related_api_contract_ids and self.project_state:
            for contract_id in feature.related_api_contract_ids:
                contract = self.project_state.get_api_contract_by_id(contract_id)
                if contract:
                    related_contracts_summary += f"- Contract ID: {contract.contract_id}, Title: {contract.title}\n"
                    for endpoint in contract.endpoints[:2]: # Show first 2 endpoints
                        related_contracts_summary += f"  - {endpoint.method} {endpoint.path} ({endpoint.summary or 'No summary'})\n" # type: ignore
                    if len(contract.endpoints) > 2: # Corrected: use > instead of &gt;
                        related_contracts_summary += "  - ... and more endpoints.\n"
        # Use the helper method to build the prompt
        # Assuming _build_planner_prompt_content_for_feature is defined globally or as self._build_planner_prompt_content_for_feature
        planner_prompt_content = _build_planner_prompt_content_for_feature(
            feature_name=feature_name,
            feature_id=feature_id,
            feature_description=feature.description,
            project_goal=project_goal_desc,
            project_context=project_context,
            framework_version=framework_version_str,
            needs_frontend=needs_frontend, # type: ignore
            related_api_contracts_summary=related_contracts_summary if related_contracts_summary else None
        )
        # Pillar 2: Resolve placeholders in the user-facing part of the planner prompt
        planner_prompt_content = await self._resolve_placeholders_in_prompt_text(planner_prompt_content) # Pillar 2

        plan_request_messages: List[ChatMessage] = [
            planner_system_prompt, # type: ignore
            {"role": "user", "content": planner_prompt_content}
        ]

        markdown_plan_raw = None
        parsed_tasks: List[FeatureTask] = []
        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_PLANNING_ATTEMPTS + 1):
            logger.info(f"Planning attempt {attempt}/{MAX_PLANNING_ATTEMPTS} for feature '{feature_name}'...")
            self.progress_callback({"message": f"Planning {feature_name} (Attempt {attempt})..."})
            try:
                logger.debug(f"Sending planning request to agent for feature '{feature_name}'.")
                plan_response_chat_message = await self._call_llm_with_error_handling("Tars", plan_request_messages, feature_or_task_id=feature.id, temperature=0.2)
                markdown_plan_raw = plan_response_chat_message['content']
                logger.info(f"Received Markdown plan from Tars for '{feature_name}' (Attempt {attempt}).")
                logger.debug(f"RAW MARKDOWN PLAN RECEIVED:\n---\n{markdown_plan_raw}\n---")

                markdown_plan_cleaned = self._clean_llm_markdown_output(markdown_plan_raw)
                logger.debug(f"--- Plan for Feature '{feature.name}' (After Cleaning by _clean_llm_markdown_output) ---")
                logger.debug(markdown_plan_cleaned)
                logger.debug(f"CLEANED MARKDOWN PLAN for parsing:\n---\n{markdown_plan_cleaned}\n---")

                parsed_tasks = self._parse_detailed_markdown_plan(markdown_plan_cleaned)

                # --- Apply "Admin Always" Rule first ---
                # This rule adds admin registration tasks if models are created/modified.
                # It should run before Django-specific sorting so admin tasks are also sorted.
                if parsed_tasks: # Only run if there are tasks to process
                    logger.info(f"Applying 'Admin Always' rule for feature '{feature.name}'...")
                    new_tasks_with_admin_rule: List[FeatureTask] = []
                    for task_item_admin_rule in parsed_tasks:
                        new_tasks_with_admin_rule.append(task_item_admin_rule)
                        if task_item_admin_rule.action in ["Create file", "Modify file"] and \
                           isinstance(task_item_admin_rule.target, str) and \
                           task_item_admin_rule.target.endswith("models.py"):
                            
                            app_name_match_admin_rule = re.match(r"([^/\\]+)[/\\]models\.py", task_item_admin_rule.target) # Use [/\\] for platform-agnostic path
                            if app_name_match_admin_rule and self.project_state:
                                app_name_for_admin_rule = app_name_match_admin_rule.group(1)
                                if not re.match(IDENTIFIER_REGEX, app_name_for_admin_rule):
                                    logger.warning(f"Skipping admin task for invalid app name '{app_name_for_admin_rule}' from target '{task_item_admin_rule.target}'")
                                    continue

                                admin_task_id_rule = f"{task_item_admin_rule.task_id_str}_admin_rule"
                                admin_target_path_rule = f"{app_name_for_admin_rule}{os.sep}admin.py" # Use os.sep for target path
                                admin_task_obj = FeatureTask( # Renamed variable to avoid conflict
                                    task_id_str=admin_task_id_rule,
                                    action="Modify file",
                                    target=admin_target_path_rule,
                                    description=f"Register models from {app_name_for_admin_rule}/models.py in admin (Admin Always Rule).",
                                    requirements=(
                                        f"Import all models from `.{app_name_for_admin_rule}.models` (or simply `.models`). "
                                        f"Register all imported models with `admin.site.register(ModelName)`. "
                                        f"Ensure `from django.contrib import admin` is present."
                                    ),
                                    dependencies=[task_item_admin_rule.task_id_str],
                                    test_step=f"python -m py_compile {admin_target_path_rule.replace('/', '\\\\')}",
                                    doc_update=f"Registers models for {app_name_for_admin_rule} in admin (Admin Always Rule)."
                                )
                                new_tasks_with_admin_rule.append(admin_task_obj)
                                logger.info(f"Added admin registration task '{admin_task_id_rule}' for app '{app_name_for_admin_rule}' (Admin Always Rule).")
                    parsed_tasks = new_tasks_with_admin_rule # Update parsed_tasks with admin tasks included
                    logger.info(f"'Admin Always' rule applied. Task count now: {len(parsed_tasks)}") # Added feature.name

                # --- Programmatic Correction for py_compiler typo ---
                if parsed_tasks:
                    corrected_tasks_list = []
                    for task_item in parsed_tasks: 
                        if task_item.test_step and "python -m py_compiler " in task_item.test_step:
                            original_test_step = task_item.test_step
                            task_item.test_step = original_test_step.replace("python -m py_compiler ", "python -m py_compile ")
                            logger.warning(
                                f"WorkflowManager: Auto-corrected invalid test step for task {task_item.task_id_str}. "
                                f"Changed '{original_test_step}' to '{task_item.test_step}'."
                            )
                            if self.project_state:
                                self.project_state.historical_notes.append(
                                    f"Auto-corrected test step for task {task_item.task_id_str} from '{original_test_step}' to '{task_item.test_step}'."
                                )
                        corrected_tasks_list.append(task_item)
                    parsed_tasks = corrected_tasks_list # Use the corrected list
                # --- End Programmatic Correction ---

                logger.info(f"Parsed {len(parsed_tasks)} tasks from the plan for feature '{feature.name}'.") # Added feature.name
                if not parsed_tasks and markdown_plan_cleaned.strip():
                    logger.error(f"CRITICAL PARSING ISSUE: Markdown plan parsing for feature '{feature.name}' resulted in ZERO tasks despite non-empty cleaned plan. This is a bug or malformed LLM output.")
                    logger.error(f"CRITICAL DEBUG: ZERO tasks parsed from a non-empty cleaned plan for feature '{feature.name}'. Plan content was:\n{markdown_plan_cleaned}")

                if not parsed_tasks and markdown_plan_cleaned.strip():
                    logger.warning(f"Planning Attempt {attempt}: Markdown plan parsing resulted in zero tasks despite non-empty cleaned plan. Format might be incorrect.")
                    last_error = ValueError("Failed to parse any tasks from the generated plan (non-empty response).")
                    plan_request_messages.append({"role": "assistant", "content": markdown_plan_raw}) 
                    plan_request_messages.append({"role": "user", "content": "The previous plan was not parseable or contained no valid tasks. Please strictly adhere to the required Markdown task format with all metadata fields (ID, Action, Target, Description, Requirements, Dependencies, Test step) for every task."})
                    if attempt < MAX_PLANNING_ATTEMPTS: # Corrected: use < instead of &lt;
                        await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)
                        continue
                    else: 
                        break 

                feature.plan_markdown = markdown_plan_raw # Store raw plan
                feature.tasks = parsed_tasks # Assign parsed tasks, sorting will happen in _implement_feature_tasks
                logger.info(f"Feature '{feature.name}' planned with {len(parsed_tasks)} tasks. Sorting will occur before implementation.")

                if self._validate_plan(feature): 
                    logger.info(f"Plan validation passed for feature '{feature_name}' (Attempt {attempt}).")
                    feature.status = FeatureStatusEnum.PLANNED
                    self.memory_manager.save_project_state(self.project_state)
                    self.progress_callback({"increment": 25, "message": f"Plan generated for {feature_name}."})                   
                    self.progress_callback({
                        "agent_name": "Tars (Planner)",
                        "agent_message": f"Generated Plan for '{feature_name}':\n```markdown\n{markdown_plan_raw if markdown_plan_raw else '[No plan generated]'}\n```"
                    })
                    return True 
                else:
                    logger.error(f"Plan validation failed for '{feature.name}' on attempt {attempt}. Feedback: {feature.plan_markdown.splitlines()[-1] if feature.plan_markdown and feature.plan_markdown.strip() else 'N/A'}")
                    last_error = ValueError(f"Plan validation failed. {feature.plan_markdown.splitlines()[-1] if feature.plan_markdown else 'Unknown validation error.'}")
                    plan_request_messages.append({"role": "assistant", "content": markdown_plan_raw})
                    plan_request_messages.append({"role": "user", "content": f"The previous plan failed validation: {last_error}. Please correct the plan, paying close attention to task IDs, dependencies, and valid test steps."})
                    if attempt < MAX_PLANNING_ATTEMPTS: # Corrected: use < instead of &lt;
                        await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)
                        continue
                    else: 
                        break 

            except (RateLimitError, AuthenticationError) as api_err:
                logger.error(f"Tars (Planner) failed planning '{feature_name}' due to API error: {api_err}")
                self._report_error(f"Planning failed due to an API issue ({type(api_err).__name__}). Cannot proceed with this feature.", task_id=feature_id)
                feature.status = FeatureStatusEnum.PLANNING_FAILED # type: ignore
                self.memory_manager.save_project_state(self.project_state)
                return False 
            except InterruptedError as interrupted_e: # type: ignore
                logger.error(f"Planning for '{feature_name}' interrupted: {interrupted_e}") # type: ignore
                feature.status = FeatureStatusEnum.CANCELLED # type: ignore
                return False 
            except Exception as e:
                logger.exception(f"Error during planning attempt {attempt} for feature '{feature_name}': {e}")
                last_error = e
                plan_request_messages.append({"role": "assistant", "content": markdown_plan_raw or "[No previous response]"})
                plan_request_messages.append({"role": "user", "content": f"The previous attempt failed with an error: {e}. Please try generating the plan again, ensuring correct format."})
                if attempt < MAX_PLANNING_ATTEMPTS: # Corrected: use < instead of &lt;
                    await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)
                    continue
                else: 
                    break 

        error_msg = f"Planning failed for feature '{feature_name}' after {MAX_PLANNING_ATTEMPTS} attempts."
        if last_error:
            error_msg += f" Last error: {last_error}"
        validation_feedback_line = feature.plan_markdown.splitlines()[-1] if feature.plan_markdown and feature.plan_markdown.strip() and feature.plan_markdown.endswith("]") else None
        if validation_feedback_line and "PLAN VALIDATION FAILED" in validation_feedback_line:
             error_msg += f" Validation feedback: {validation_feedback_line}"
        logger.error(error_msg)
        self._report_error(f"Could not create a valid plan for '{feature_name}'. {last_error}", task_id=feature_id) # type: ignore
        feature.status = FeatureStatusEnum.PLANNING_FAILED
        if markdown_plan_raw and feature.plan_markdown and not feature.plan_markdown.endswith("FAILED]"): 
            feature.plan_markdown = (feature.plan_markdown or "") + f"\n\n[PLANNING FAILED after {MAX_PLANNING_ATTEMPTS} attempts. Last error: {last_error}]"
        self.memory_manager.save_project_state(self.project_state)
        return False

    def _sort_tasks_for_django_flow(self, tasks: List[FeatureTask]) -> List[FeatureTask]:
        """
        Reorders tasks based on a predefined priority reflecting logical Django workflow.
        Lower numbers run first.
        """
        if not self.project_state or not self.project_state.project_name:
            logger.warning("Cannot sort Django tasks: project_state or project_name not available. Returning original order.")
            return tasks

        sorted_tasks = sorted(tasks, key=lambda task: self._get_task_phase_priority(task))
        logger.info(f"Tasks sorted for Django flow. New order: {[t.task_id_str for t in sorted_tasks]}")
        return sorted_tasks

    def sort_tasks(self, feature: ProjectFeature): # Added feature argument
        """
        Sorts the project's task list based on the framework-specific priority logic.
        """
        if not self.project_state or not feature.tasks: # Check feature.tasks
            return

        logger.info(f"Sorting tasks for feature '{feature.name}' based on logical workflow priority...")
        # Sort feature.tasks in place
        feature.tasks.sort(key=lambda task: self._get_task_phase_priority(task))
        # Log the new order for debugging
        log_msg = f"Task order for feature '{feature.name}' after sorting:\n"
        for task_item in feature.tasks: # Renamed task to task_item to avoid conflict
            log_msg += f"  - Priority {self._get_task_phase_priority(task_item)}: {task_item.description}\n"
        logger.info(log_msg)

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
                            error_note = f"""\n\n[PLAN VALIDATION FAILED: Redundant 'Create directory {app_name_from_startapp}' before 'startapp {app_name_from_startapp}'. 'startapp' handles directory creation.]"""
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
    def _reorder_tasks_for_django_flow(self, tasks: List[FeatureTask]) -> List[FeatureTask]:
        """
        Sorts tasks to align with a logical Django development flow.
        This is a best-effort sorting and relies on well-defined dependencies for true order.
        """
        if not tasks:
            return []

        # The get_task_phase_priority function will be used as the key for sorting.
        # It needs access to self.project_state if it's to be a method of WorkflowManager.
        # For simplicity, if project_state is needed, it should be passed or accessed via self.
        # Assuming self.project_state is available:
        sorted_tasks = sorted(tasks, key=lambda task: self._get_task_phase_priority(task, self.project_state))

        # --- "Test Last" Principle Enforcement ---
        test_run_tasks = [t for t in sorted_tasks if t.action == "Run command" and "manage.py test" in t.target]
        other_tasks = [t for t in sorted_tasks if t not in test_run_tasks]
        if test_run_tasks:
            sorted_tasks = other_tasks + test_run_tasks # Move test run tasks to the end
            logger.info(f"Applied 'Test Last' principle for Django flow for feature.")

        logger.debug(f"Tasks reordered for Django flow. Original IDs: {[t.task_id_str for t in tasks]}. New Order IDs: {[t.task_id_str for t in sorted_tasks]}.")
        return sorted_tasks

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
                app_name = relative_path_parts[0] if len(relative_path_parts) > 1 and relative_path_parts[0] != getattr(self.project_state, 'project_name', '_unknown_project_') else "_project_level_"
                file_name = Path(file_path_str).name


                # Ensure app and file entries exist in the project_structure_map
                if app_name not in self.project_state.project_structure_map.apps:
                    from .project_models import AppStructureInfo # Local import
                    self.project_state.project_structure_map.apps[app_name] = AppStructureInfo() # type: ignore
                self.project_state.project_structure_map.apps[app_name].files[file_name] = parsed_file_info
                logger.info(f"Updated project structure map for app '{app_name}', file '{file_name}'.")
                # Consider saving project state here or let the caller handle it.
        except Exception as e:
            logger.error(f"Error updating project structure map for {file_path_str}: {e}")

    def _get_project_map_for_llm(self, max_depth: int = 3, max_items_per_dir: int = 10) -> str:
        """
        Generates a markdown representation of the project's directory structure
        for LLM context, with configurable depth and item limits.

        Args:
            max_depth: Maximum depth of directories to traverse.
            max_items_per_dir: Maximum number of files/subdirectories to list per directory.

        Returns:
            A string containing the markdown formatted directory structure.
        """
        if not self.file_system_manager:
            logger.error("FileSystemManager not initialized. Cannot get project map for LLM.")
            return "# Error: FileSystemManager not available for project map."
        
        try:
            project_map_str = self.file_system_manager.get_directory_structure_markdown(
                max_depth=max_depth,
                max_items_per_dir=max_items_per_dir
            )
            # Return only the map string, the calling method will format it with titles
            return project_map_str
        except Exception as e:
            logger.error(f"Error generating project map for LLM: {e}")
            return f"# Error generating project map: {e}"

    async def _execute_command_with_remediation(self, command: str, task: Optional[FeatureTask] = None) -> CommandOutput:
        """
        Executes a command via the UI, and if it fails, attempts to remediate it iteratively.
        This method invokes the self-contained, iterative remediation process in RemediationManager.
        """
        # --- NEW: Execute command via UI callback to allow user interaction ---
        task_id = task.task_id_str if task else f"setup_{int(time.time())}"
        description = task.description if task else f"Execute setup command: {command}"

        logger.info(f"Requesting UI execution for command: `{command}` (Task: {task_id})")
        self.progress_callback({"action_details": f"Waiting for user to run: {command}"})

        success, output_json = await self.request_command_execution_cb(
            task_id,
            command,
            description
        )

        # Parse the JSON output from the UI thread into a CommandOutput object
        try:
            result_data = json.loads(output_json)
            command_output = CommandOutput(
                command=result_data.get("command_str", command),
                stdout=result_data.get("stdout", ""),
                stderr=result_data.get("stderr", ""),
                exit_code=result_data.get("exit_code", 0 if success else 1)
            )
        except (json.JSONDecodeError, TypeError):
            # Fallback for non-JSON output (e.g., simple error string)
            command_output = CommandOutput(
                command=command,
                stdout=output_json if success else "",
                stderr="" if success else output_json,
                exit_code=0 if success else 1
            )

        if command_output.exit_code == 0:
            logger.info(f"Command '{command}' executed successfully via UI on the first try.")
            return command_output

        # --- Command Failed: Initiate Iterative Remediation ---
        logger.warning(f"Command '{command}' failed with exit code {command_output.exit_code}. Initiating iterative remediation process...")
        self.progress_callback({"message": "Command failed. Attempting automated remediation..."})

        try:
            # 1. Analyze the initial failure to get the first set of errors.
            initial_error_records, _ = self.remediation_manager.error_analyzer.analyze_logs(
                command, command_output.stdout, command_output.stderr, command_output.exit_code
            )

            if not initial_error_records:
                logger.error("Command failed but no errors could be analyzed. Cannot remediate.")
                raise CommandExecutionError("Command failed but error analysis returned no errors.", command_output)

            # 2. Call the new, self-contained, iterative remediate method.
            remediation_successful = await self.remediation_manager.remediate(
                command,
                initial_error_records,
                self.project_state
            )

            # 3. Handle the final result of the entire remediation process.
            if remediation_successful:
                logger.info("Iterative remediation process SUCCEEDED. Re-running final verification command.")
                final_verification_output = await asyncio.to_thread(self.command_executor.run_command, command)
                
                if final_verification_output.exit_code == 0:
                    logger.info("Final verification PASSED.")
                    return final_verification_output
                else:
                    logger.error("CRITICAL: Remediation reported success, but final verification command FAILED.")
                    raise CommandExecutionError("Remediation process finished, but final verification failed.", final_verification_output)
            else:
                logger.error("Iterative remediation process FAILED to fix the issue.")
                raise CommandExecutionError(f"Remediation failed to fix command '{command}'.", command_output)

        except (RateLimitError, AuthenticationError) as api_error:
            logger.error(f"API Error during remediation for task {task.task_id_str if task else 'N/A'}: {api_error}")
            self.progress_callback({"error": f"API Error during remediation: {api_error}"})
            raise CommandExecutionError(f"API Error during remediation for '{command}'.", command_output) from api_error
        except Exception as e:
            task_id_str = task.task_id_str if task else "N/A"
            logger.error(f"An unexpected error occurred during the remediation process for task {task_id_str}: {e}", exc_info=True)
            self.progress_callback({"error": f"An unexpected error during remediation: {e}"})
            raise CommandExecutionError(f"Unexpected error during remediation for '{command}'.", command_output) from e

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
        first_task_header_match = re.search(r"^\s*###\s+Task\s+[0-9\.]+", cleaned, re.MULTILINE)
        if first_task_header_match:
            cleaned = cleaned[first_task_header_match.start():]
        else:
            first_metadata_match = re.search(r"^\s*[-*]\s*`?[A-Za-z\s_]+?`?:", cleaned, re.MULTILINE)
            if first_metadata_match:
                cleaned = cleaned[first_metadata_match.start():]
            elif cleaned.strip(): # Content exists but no standard start
                logger.warning(
                    "Cleaned plan content does not start with '### Task' or a metadata list item. "
                    f"The plan might be malformed or entirely conversational. Original raw output started with: '{raw_output[:150]}...'"
                )

        logger.debug(f"Cleaned Markdown Output (final for parsing):\n---\n{cleaned[:500]}...\n---")
        return cleaned.strip()

    async def _implement_feature_tasks(self, feature: ProjectFeature):
        """
        Executes the detailed tasks for a feature sequentially, handling dependencies,
        validation via test steps, and self-correction/remediation for failures.
        Allows remediation attempts up to MAX_REMEDIATION_ATTEMPTS before failing.

        Args:
            feature: The ProjectFeature Pydantic model instance whose tasks need to be implemented.

        Updates the status of tasks and the feature within self.project_state.
        Updates self.workflow_context with task completion/failure status.
        Stops processing the feature if a task fails permanently after remediation attempts.
        """
        if not self.prompts or not self.project_state:
            raise RuntimeError("Cannot implement tasks: Prompts or project state not loaded.")

        feature_id = feature.id
        feature_name = feature.name
        self.progress_callback({"increment": 30, "message": f"Implementing: {feature_name}..."})
        logger.info(f"Starting implementation tasks for feature '{feature_name}'. Total tasks: {len(feature.tasks)}")

        tasks = feature.tasks # Use attribute access
        if not tasks:

            # If _plan_feature already marked it as planning_failed, this is redundant but safe.
            # If _plan_feature succeeded but parsing yielded no tasks, this is the critical catch.
            logger.error(
                f"CRITICAL: Feature '{feature.name}' ({feature.id}) has NO TASKS after planning or parsing. "
                "This is treated as a planning failure."
            )
            self._report_error( # type: ignore
                f"Planning for feature '{feature.name}' resulted in no actionable tasks. This feature cannot be implemented.",
                task_id=feature.id, is_fatal=True # is_fatal for this feature
            )
            feature.status = "planning_failed" # Mark as planning_failed
            self.memory_manager.save_project_state(self.project_state)
            return # Exit early

        total_tasks = len(tasks)
        base_progress = 30
        implementation_progress_range = 45
        progress_per_task = implementation_progress_range / total_tasks if total_tasks > 0 else 0

        # Sort tasks at the beginning of implementation
        if self.project_state and self.project_state.framework == "django":
            self.sort_tasks(feature) # Sorts feature.tasks in place
            tasks = feature.tasks # Re-assign tasks in case sort_tasks returned a new list (though it modifies in place)

        # --- Initialize/Load completed tasks from workflow_context ---
        if "steps" not in self.workflow_context or not isinstance(self.workflow_context["steps"], list):
            self.workflow_context["steps"] = []

        # CRITICAL FIX: completed_task_ids must be scoped to the current feature's tasks
        # and their status as per project_state. Do not use workflow_context here for this set,
        # as task IDs from planner are only unique within a feature.
        completed_task_ids = {t.task_id_str for t in tasks if t.status == "completed"}
        logger.debug(f"Initial completed tasks (from current feature's state '{feature.name}'): {completed_task_ids}")

        context_updated_in_pass = False # Initialize here!

        # --- Main Task Processing Loop ---
        while len(completed_task_ids) < total_tasks:
            tasks_processed_in_pass = 0
            made_progress_in_pass = False
            context_updated_in_pass = False # Reset for each pass

            for i, task in enumerate(tasks): # task is now a FeatureTask instance
                task_id_str = task.task_id_str # Use attribute access
                current_task_status = task.status # Use attribute access

                if task_id_str in completed_task_ids:
                    if current_task_status != "completed":
                         # This is a good safeguard. If the ID is in our set but the status isn't updated, fix it.
                         logger.debug(f"Task {task_id_str} found in completed set but status is {current_task_status}. Updating status.")
                         task.status = "completed"
                         context_updated_in_pass = True
                    continue

                if current_task_status in ["failed", "skipped"]:
                    continue

                # --- Dependency Check ---
                deps = task.dependencies or [] # Use attribute access
                valid_deps = {dep_id for dep_id in deps if dep_id and isinstance(dep_id, str) and dep_id.lower() != 'none'}
                deps_met = valid_deps.issubset(completed_task_ids)

                if not deps_met:
                    if current_task_status != "waiting_dependency":
                        task.status = "waiting_dependency"
                        unmet = valid_deps - completed_task_ids
                        logger.debug(f"Task {task_id_str} status set to 'waiting_dependency'. Unmet: {unmet}")
                    continue

                if current_task_status == "waiting_dependency":
                    logger.debug(f"Task {task_id_str} dependencies met. Changing status to 'pending'.")
                    task.status = "pending"
                    made_progress_in_pass = True # <-- THIS IS THE FIX
                    
                if task.status == "pending":
                    self.is_recovering = False # Mark that we are no longer in a recovery state at the start of a new task
                    task.status = "in_progress"
                    made_progress_in_pass = True
                    tasks_processed_in_pass += 1

                    task_progress_start = base_progress + (len(completed_task_ids) * progress_per_task)
                    self.progress_callback({ # Use attribute access
                        "increment": int(task_progress_start),
                        "message": f"Task {task_id_str}: {task.description[:40]}..."
                    })
                    logger.info(f"--- Starting Task {task_id_str} ({task.action}) ---")
                    logger.debug(f"Task Details: {task.model_dump()}") # Use attribute access

                    task_completed_successfully = False
                    # --- Inner Loop for Execution & Remediation Attempts (for this specific task) ---
                    while task.remediation_attempts <= MAX_REMEDIATION_ATTEMPTS_FOR_TASK:
                        # execution_success = False  <- This block is being replaced
                        # test_step_success = False
                        # execution_output = None
                        # test_step_output = None
                        
                        error_reason = None # This will hold the reason for the most recent failure within the loop
                        remediation_attempt_count = task.remediation_attempts
                        is_remediation_attempt = remediation_attempt_count > 0 # Flag if this is a retry after a fix

                        logger.info(f"Task {task_id_str}: Attempt {remediation_attempt_count + 1}/{MAX_REMEDIATION_ATTEMPTS_FOR_TASK + 1}")

                        # --- 1. Execute the task and its test step ---
                        execution_success, test_step_success, execution_output, test_step_output = await self._execute_and_test_single_task(task, feature)
                        
                        # --- 2. Check Success and Exit/Remediate ---
                        if execution_success and test_step_success:
                            task.status = "completed" # Individual task's action and test_step passed
                            task.result = execution_output or test_step_output or "Task completed successfully." # Use attribute access
                            completed_task_ids.add(task_id_str)
                            # --- ADDED: Update project structure map after successful task ---
                            if task.action in ["Create file", "Modify file", "Delete file"] and task.target: # Only for file operations
                                await self._update_project_structure_map(task.target)
                            # Pillar 2: Update artifact registry on successful task completion
                            await self._update_artifact_registry(task, task.result) # Use attribute access
                            task_completed_successfully = True
                            # Update workflow_context with a globally unique ID
                            global_task_id_for_context = f"{feature.id}_{task_id_str}"
                            self._update_workflow_context_step(global_task_id_for_context, "completed", str(task.result))
                            context_updated_in_pass = True
                            logger.info(f"--- Finished Task {task_id_str} (Status: completed) ---")
                            break # Exit the remediation attempt loop for this task
                        
                        # --- 3. Handle Failure ---
                        # If we are here, either the main action or the test step failed.
                        if not execution_success:
                            failure_reason = execution_output
                        elif not test_step_success:
                            failure_reason = test_step_output
                        else:
                            failure_reason = "Unknown task failure." # Should not be reached
                        logger.error(f"Task {task_id_str} failed. Reason: {failure_reason}")

                        # Determine the command that failed for the error analysis
                        # This is the critical fix:
                        # If the test step failed, that's the command.
                        # If the main action was a 'Run command' and it failed, that's the command.
                        # Otherwise, the test_step is the most relevant command context for the failure.
                        if not test_step_success:
                            command_that_failed = task.test_step
                        elif task.action == "Run command" and not execution_success:
                            command_that_failed = task.target
                        else:
                            # For failed file creation/modification, the test step is the verification command
                            command_that_failed = task.test_step

                        # Construct structured error from the command output JSON
                        stdout_str, stderr_str, exit_code = "", str(failure_reason), 1
                        try:
                            command_result_data = json.loads(str(failure_reason))
                            command_that_failed = command_result_data.get('command_str', command_that_failed)
                            stdout_str = command_result_data.get('stdout', '')
                            stderr_str = command_result_data.get('stderr', '') # Use a safe default
                            exit_code = command_result_data.get('exit_code', 1)
                        except (json.JSONDecodeError, TypeError):
                            logger.debug("Failure reason was not JSON, treating as raw stderr.")
                        
                        logger.info(f"Task {task_id_str} failed. Initiating new remediation process.")
                        self.progress_callback({"message": f"Task {task_id_str} failed. Attempting automated remediation..."})
                        
                        # --- 4. Initiate Remediation ---
                        if self.remediation_manager is None:
                            if not self.prompts: raise RemediationError("Cannot create RemediationManager because prompts have not been loaded.")
                            logger.info("Creating RemediationManager instance (just-in-time)...")
                            self.remediation_manager = RemediationManager(
                                agent_manager=self.agent_manager,
                                file_system_manager=self.file_system_manager,
                                command_executor=self.command_executor,
                                prompts=self.prompts,
                                remediation_config=self.remediation_config,
                                progress_callback=self.progress_callback,
                                request_network_retry_cb=self._request_network_retry_cb
                            )
                        
                        try:
                            error_records, test_summary = self.remediation_manager.error_analyzer.analyze_logs(
                                command_that_failed, stdout_str, stderr_str, exit_code
                            )
                            initial_bug_count = test_summary['total'] if test_summary else len(error_records)
                            logger.info(f"Remediation cycle started. Initial bug count from analysis: {initial_bug_count}")
                            
                            # Attach the triggering task to each error record for context.
                            for record in error_records:
                                record.triggering_task = task
                            
                            # Add a guard clause to ensure that if the analyzer finds a summary of errors
                            # but cannot parse them into structured records, we treat it as a failure.
                            if not error_records:
                                logger.error("Command failed but no structured errors could be analyzed. Cannot remediate.")
                                # This is a failure of the remediation attempt, not a success.
                                fix_successful = False
                            else:
                                # Correctly call the async remediate method with the proper arguments.
                                fix_successful = await self.remediation_manager.remediate(
                                    command_that_failed,
                                    list(error_records), # Pass a copy of the list to prevent side effects
                                    self.project_state
                                )
                        except (RateLimitError, AuthenticationError) as api_error:
                            logger.error(f"API Error during remediation for task {task.task_id_str}: {api_error}")
                            self.progress_callback({"error": f"API Error during remediation: {api_error}"})
                            fix_successful = False
                        except Exception as e:
                            logger.error(f"CRITICAL: The remediation system itself failed with an unhandled exception: {e}", exc_info=True)
                            if self.ui_communicator:
                                self.ui_communicator.update_task_in_ui(
                                    task.task_id_str, {"status": "FAILED", "summary": "Remediation system critical failure."}
                                )
                            fix_successful = False
                        
                        if fix_successful:
                            logger.info(f"Remediation cycle was successful for task {task_id_str}. Re-running original test step for final verification.")
                            # Re-run the original test step to confirm the fix
                            final_exec_success, final_test_success, _, final_test_output = await self._execute_and_test_single_task(task, feature)
                            if final_exec_success and final_test_success:
                                logger.info(f"Final verification PASSED for task {task_id_str}. Task is now completed.")
                                task.status = "completed"
                                completed_task_ids.add(task_id_str)
                                task_completed_successfully = True
                                break # Exit the remediation loop for this task
                            else:
                                logger.error(f"CRITICAL: Remediation reported success, but final verification FAILED for task {task_id_str}. Last error: {final_test_output}")
                                # The fix didn't work. Ask the user to retry the whole remediation.
                                fix_successful = False # Reset flag as verification failed
                                stderr_str = str(final_test_output) # Use the new error
                        else:
                        
                            logger.error(f"Automated remediation cycle failed for task {task_id_str}.")

                        if not fix_successful:
                            if self._request_remediation_retry_cb:
                                should_retry = await self._request_remediation_retry_cb(task_id_str, stderr_str)
                                if should_retry:
                                    logger.info(f"User chose to retry remediation for task {task_id_str}. Continuing loop.")
                                    continue # Go to the next iteration of the while loop to retry remediation

                            logger.error(f"Automated remediation failed and user did not retry for task {task_id_str}. Marking task as failed.")
                            task.status = "failed"; task.result = f"Automated remediation failed. Last error: {stderr_str}"; self._update_workflow_context_step(f"{feature.id}_{task_id_str}", "failed", task.result); context_updated_in_pass = True
                            break # Exit the remediation loop for this task

                    if task.status == "failed":
                        logger.error(f"Task {task_id_str} did not complete successfully after all attempts.")
                        if task.status != "failed": task.status = "failed" # Ensure status is failed
                        logger.error(f"Task {task_id_str} failed permanently. Marking feature '{feature_name}' as implementation_failed.")
                        feature.status = FeatureStatusEnum.IMPLEMENTATION_FAILED
                        self._report_error(f"Feature '{feature_name}' failed because Task {task_id_str} could not be completed.", task_id=task_id_str, is_fatal=True) # Report as fatal for this feature
                        self.memory_manager.save_project_state(self.project_state)
                        if context_updated_in_pass: self.memory_manager.save_workflow_context(self.workflow_context)
                        return

            logger.debug(f"Finished pass through tasks. Processed this pass: {tasks_processed_in_pass}. Made progress: {made_progress_in_pass}. Total completed: {len(completed_task_ids)}/{total_tasks}.")
            self.memory_manager.save_project_state(self.project_state)
            if context_updated_in_pass: self.memory_manager.save_workflow_context(self.workflow_context)

            if not made_progress_in_pass and len(completed_task_ids) < total_tasks:
                remaining_tasks = [t for t in tasks if t.status not in ["completed", "skipped"]]
                all_waiting_or_failed = all(t.status in ["waiting_dependency", "failed"] for t in remaining_tasks)
                if all_waiting_or_failed:
                    pending_deps = {}
                    failed_tasks_in_state = []
                    for t_stall in remaining_tasks: 
                        if t_stall.status == "waiting_dependency":
                            unmet = [dep for dep in (t_stall.dependencies or []) if dep and dep.lower() != 'none' and dep not in completed_task_ids]
                            if unmet: pending_deps[t_stall.task_id_str] = unmet
                        elif t_stall.status == "failed":
                            failed_tasks_in_state.append(t_stall.task_id_str)
                    error_msg = (f"Workflow stalled processing feature '{feature_name}'. No progress made. "
                                 f"Failed tasks: {failed_tasks_in_state}. Waiting on: {pending_deps}")
                    logger.error(error_msg)
                    feature.status = FeatureStatusEnum.IMPLEMENTATION_FAILED
                    self._report_error(f"Processing stalled for feature '{feature_name}'. Some tasks failed or are stuck waiting for dependencies.", task_id=feature.id, is_fatal=True)
                    self.memory_manager.save_project_state(self.project_state)
                    if context_updated_in_pass: self.memory_manager.save_workflow_context(self.workflow_context)
                    return
                elif not tasks_processed_in_pass and len(completed_task_ids) < total_tasks:
                    # This case means no tasks were even attempted in this pass,
                    # which implies a deeper issue if not all tasks are completed or waiting/failed. # type: ignore
                    # For now, let the existing all_waiting_or_failed logic handle the stall.
                    logger.error(f"Workflow stalled unexpectedly for feature '{feature_name}'. No progress, but some tasks not waiting/failed.")
                    feature.status = FeatureStatusEnum.IMPLEMENTATION_FAILED
                    self._report_error(f"Workflow stalled unexpectedly for '{feature_name}'.", task_id=feature.id, is_fatal=True)
                    self.memory_manager.save_project_state(self.project_state)
                    if context_updated_in_pass:
                        self.memory_manager.save_workflow_context(self.workflow_context)
                    return 
        
        if feature.status not in [FeatureStatusEnum.IMPLEMENTATION_FAILED, FeatureStatusEnum.PLANNING_FAILED, FeatureStatusEnum.CANCELLED]:
            logger.info(f"All individual tasks for feature '{feature_name}' implemented successfully or skipped appropriately.")
            feature.status = FeatureStatusEnum.TASKS_IMPLEMENTED # New status indicating readiness for feature-level testing
            self.memory_manager.save_project_state(self.project_state)
            if context_updated_in_pass: self.memory_manager.save_workflow_context(self.workflow_context)
            # The main run_feature_cycle will now pick this up for _generate_and_run_feature_tests
        else:
            logger.error(f"Implementation loop finished for '{feature_name}' but feature status is 'failed'.")
            if context_updated_in_pass: self.memory_manager.save_workflow_context(self.workflow_context) # type: ignore

    async def _execute_file_task_case(self, task: FeatureTask, feature: ProjectFeature, is_remediation: bool) -> str:
        """
        Handles 'Create file' and 'Modify file' tasks using the Case agent.
        Gathers context, calls Case with enhanced prompts, validates response,
        handles placeholders, writes file, and extracts/stores code summary.
        """
        if not self.prompts or not self.project_state: raise RuntimeError("Prompts or project state not loaded.")

        file_path_from_task = task.target
        action_desc = task.action # Use attribute access
        requirements_str = task.requirements or "" # Use attribute access
        # action_desc = task.action # Removed redundant assignment
        task_id_str = task.task_id_str

        # --- NEW: DIRECT HANDLING FOR SIMPLE __init__.py FILES ---
        # This block handles __init__.py files specifically if their requirement is to be empty or minimal.
        # It bypasses the Case agent for these simple cases.
        if file_path_from_task.endswith('__init__.py') and \
            (requirements_str.lower().strip() in ["file should be empty.", "empty file", "file should be empty", "file should be empty."]): # More precise check for __init__.py
            
            logger.info(f"Task {task_id_str}: Handling '{file_path_from_task}' directly as requirement is '{requirements_str}'. Bypassing Case agent.")
            content_to_write = "# Package initializer." # Standard comment, or use "" for truly empty
            
            await asyncio.to_thread(self.file_system_manager.write_file, file_path_from_task, content_to_write)
            logger.info(f"Task {task_id_str}: File '{file_path_from_task}' written with content: '{content_to_write}' (Directly by WM).")
            
            if self.project_state:
                self.project_state.code_summaries[file_path_from_task] = content_to_write
                self.project_state.historical_notes.append(f"Task {task_id_str}: Created/updated '{file_path_from_task}' with content: '{content_to_write}' (Directly by WM).")
                await self._update_project_structure_map(file_path_from_task)
                try:
                    await asyncio.to_thread(self.command_executor.run_command, f'git add "{file_path_from_task}"')
                    commit_msg = f"Task {task_id_str}: {task.description}"
                    await asyncio.to_thread(self.command_executor.run_command, f'git commit -m "{commit_msg}" --allow-empty')
                    logger.info(f"Task {task_id_str}: Committed changes for '{file_path_from_task}'.")
                except Exception as git_commit_e:
                    logger.warning(f"Failed to commit changes for '{file_path_from_task}' after task {task_id_str}: {git_commit_e}")
            return self._remove_summary_comment_from_code(content_to_write) # Return the content written
        # --- END NEW DIRECT __init__.py HANDLING ---

        feedback_for_case = str(task.result) if is_remediation and task.result is not None else None # Ensure string
        if feedback_for_case:
             logger.info(f"Task {task_id_str}: Initial feedback for Case (from Tars or previous validation): '{str(feedback_for_case)[:100]}...'")
             task.result = None

        last_error_for_case: Optional[Exception] = None
        generated_content_with_summary: Optional[str] = None # Will hold content + summary comment
        final_content_for_return: Optional[str] = None # To store the content that should be returned
        is_feature_test_file_creation = False
        for case_attempt in range(1, MAX_IMPLEMENTATION_ATTEMPTS + 1):
            logger.info(f"Task {task_id_str}: Requesting code from Case for {action_desc} '{file_path_from_task}' (Overall Attempt {task.remediation_attempts + 1}, Case Attempt {case_attempt})")
            self.progress_callback({"action_details": f"Generating code for: {file_path_from_task} (Attempt {case_attempt})..."})

            # 1. GATHER CONTEXT (Replaced _gather_related_file_context)
            holistic_context = await self._gather_related_file_context(feature, task)
            placeholder_context = self._get_placeholder_context_for_case()
            project_map_context = self._get_project_map_for_llm(max_depth=4, max_items_per_dir=20)

            current_app_name_for_test_file = None
            if self.project_state and self.project_state.framework == 'django' and \
               task.action == "Create file" and "/test/test_" in file_path_from_task and file_path_from_task.endswith(".py"):
                is_feature_test_file_creation = True
                path_parts = Path(file_path_from_task).parts
                if len(path_parts) > 2 and path_parts[-2] == 'test': # e.g., app_name/test/test_file.py
                    current_app_name_for_test_file = path_parts[-3]

            # --- Add API Contract details to Case prompt if referenced by the task ---
            api_contract_details_for_case = ""
            if task.api_contract_references and self.project_state:
                api_contract_details_for_case += "\n**Referenced API Contract Details:**\n"
                for contract_id in task.api_contract_references:
                    contract = self.project_state.get_api_contract_by_id(contract_id)
                    if contract:
                        api_contract_details_for_case += f"- Contract ID: {contract.contract_id}, Title: {contract.title}\n"
                        api_contract_details_for_case += f"  Description: {contract.description or 'N/A'}\n"
                        # Could serialize relevant parts of contract.endpoints here
                        api_contract_details_for_case += f"  (Full contract details available in project state if needed by planner for context)\n"
            # ---

            feature_plan_details = f"\n**Current Feature Plan Context ({feature.name} - Task {task_id_str}):**\n"
            if feature.plan_markdown:
                plan_lines = feature.plan_markdown.splitlines()
                feature_plan_details += "Relevant Plan Snippet:\n" + "\n".join(plan_lines[:20])
                if len(plan_lines) > 20: feature_plan_details += "\n... [plan truncated] ..."
            else:
                feature_plan_details += "No detailed plan markdown available for this feature."

            completed_feature_tasks_summary = "\n**Completed Tasks for This Feature:**\n"
            completed_task_ids_for_feature = [t.task_id_str for t in feature.tasks if t.status == 'completed']
            completed_feature_tasks_summary += ", ".join(completed_task_ids_for_feature) if completed_task_ids_for_feature else "None yet."
            
            # --- ADDED: Include existing code summaries in context for Case ---
            existing_code_summaries_context = "\n**Summaries of Existing Relevant Files:**\n"
            relevant_summary_count = 0
            # Pillar 2: Use artifact_registry to find relevant files for summaries
            if self.project_state and self.project_state.artifact_registry:
                # Heuristic: provide summaries for files in the same directory or common config files
                target_dir = Path(file_path_from_task).parent
                for path_str, summary_text in self.project_state.code_summaries.items():
                    if Path(path_str).parent == target_dir or "settings.py" in path_str or "urls.py" in path_str:
                        if path_str != file_path_from_task: # Don't include summary of the file being modified yet
                            existing_code_summaries_context += f"- `{path_str}`: {summary_text[:150]}...\n"
                            relevant_summary_count +=1
            if not relevant_summary_count:
                existing_code_summaries_context += "  - None available or relevant for this task's immediate context.\n"
            # --- END ---


            refinement_prompt = ""
            if feedback_for_case:
                refinement_prompt = f"\n--- Previous Attempt Feedback ---\n{feedback_for_case}\nPlease correct the code based on this feedback.\n---"

            case_system_prompt_obj = self.prompts.system_case_executor # Default
            user_message_content: str

            if is_feature_test_file_creation and self.prompts.system_test_agent_feature_tester and current_app_name_for_test_file:
                logger.info(f"Task {task_id_str}: Using TestAgent prompt for test file '{file_path_from_task}'.")
                case_system_prompt_obj = self.prompts.system_test_agent_feature_tester

                feature_name_snake_case = re.sub(r'\W+', '_', feature.name.lower()).strip('_')
                # feature_name_pascal_case = "".join(word.capitalize() for word in feature_name_snake_case.split('_')) # Not used in user message

                # Gather context of feature files for the TestAgent
                feature_files_context_for_test_agent = "\n**Feature Files Context (Code to be Tested):**\n"
                files_for_feature_set = set()
                for f_task_item in feature.tasks: # Iterate over tasks of the current feature
                    if f_task_item.action in ["Create file", "Modify file"] and isinstance(f_task_item.target, str) and \
                       not ("/test/test_" in f_task_item.target and f_task_item.target.endswith(".py")): # Exclude other test files
                        files_for_feature_set.add(f_task_item.target)
                
                for rel_path_str_ctx in sorted(list(files_for_feature_set)):
                    try:
                        content_ctx = await asyncio.to_thread(self.file_system_manager.read_file, rel_path_str_ctx)
                        feature_files_context_for_test_agent += f"--- File: `{rel_path_str_ctx}` ---\n```python\n{content_ctx}\n```\n"
                    except Exception as e_ctx_read:
                        feature_files_context_for_test_agent += f"--- File: `{rel_path_str_ctx}` ---\n[Error reading file: {e_ctx_read}]\n"
                if not files_for_feature_set:
                    feature_files_context_for_test_agent += "No primary feature files found to provide context for testing.\n"

                # Construct user message for the TestAgent based on its system prompt's expectations
                # The system_test_agent_content in django/prompts.py has "{requirements}"
                # We need to fill that {requirements} placeholder.
                user_requirements_for_test_agent = f"""
                Feature Name: {feature.name}
                Feature Description: {feature.description}
                App Name for tests: {current_app_name_for_test_file}
                Target Test File Path: {file_path_from_task}
                Framework Version: {self.project_state.framework if self.project_state else 'N/A'}

                Context of related feature files (models, views, etc.) that need testing:
                {feature_files_context_for_test_agent}

                Please generate the complete Python test code for the file `{file_path_from_task}`.
                Ensure your generated Python code for the test file uses correct relative imports
                (e.g., `from ..models import MyModel`) as it will be located in `{current_app_name_for_test_file}/test/`.
                Follow Django testing best practices. Cover model creation, view responses (GET/POST),
                form handling (if any), and edge cases.
                {refinement_prompt}
                """
                user_message_content = user_requirements_for_test_agent
            else:
                # Default user message construction for system_case_executor
                # Resolve placeholders in the system prompt's content
                resolved_system_prompt_content = await self._resolve_placeholders_in_prompt_text(case_system_prompt_obj['content'])
                
                # Create a new system prompt object with the resolved content
                final_system_prompt_obj: ChatMessage = {
                    "role": case_system_prompt_obj['role'],
                    "content": resolved_system_prompt_content
                }
                if 'name' in case_system_prompt_obj:
                    final_system_prompt_obj['name'] = case_system_prompt_obj['name']

                user_message_content = f"""
                **Project Goal:** {self.project_state.features[0].description if self.project_state and self.project_state.features else 'N/A'}
                **Current Feature Goal:** {feature.name} - {feature.description}
                **Project Framework:** {self.project_state.framework if self.project_state else 'N/A'}
                **Project Name:** {self.project_state.project_name if self.project_state else 'N/A'}

                **Project Map & Context (includes Artifact Registry if populated):**
                {project_map_context}
                {self._get_project_structure_map_for_analyzer_context()}
                {feature_plan_details}
                {completed_feature_tasks_summary}
                {api_contract_details_for_case}
                {placeholder_context}
                {existing_code_summaries_context}
                
                **Holistic Context Block:**
                {holistic_context}
                ---
                **Execute Task {task_id_str} (Attempt {case_attempt}/{MAX_IMPLEMENTATION_ATTEMPTS}):**
                Action: {action_desc}
                Target file path: `{file_path_from_task}` (This is the exact relative path from project root)

                **Code Requirements for `{file_path_from_task}`:**
                {requirements_str}
                {refinement_prompt}
                """

            case_request_messages: List[ChatMessage] = [
                final_system_prompt_obj,
                {"role": "user", "content": user_message_content}
            ]


            try:
                case_response_chat_message = await self._call_llm_with_error_handling("Case", case_request_messages, feature_or_task_id=task_id_str, temperature=0.1)
                # --- REMOVED: __init__.py specific handling from inside the Case attempt loop ---
                # This is now handled by the direct handling block at the start of this method.
                case_raw_output = case_response_chat_message['content']
                self.progress_callback({"agent_name": f"Case (Code Gen {case_attempt})", "agent_message": case_raw_output})

                parsed_path_str, raw_content_from_xml = self._parse_mcp_file_content(case_raw_output)

                sanitized_content = raw_content_from_xml.replace('\u00a0', ' ') if raw_content_from_xml is not None else None

                # --- FIX: Handle intentionally empty files as a success case ---
                is_intended_to_be_empty = any(phrase in (task.requirements or "").lower() for phrase in [
                    "file should be empty", "create an empty file", "empty file", "contain no content"
                ])

                if is_intended_to_be_empty and (sanitized_content is None or not sanitized_content.strip()):
                    logger.info(f"Task {task_id_str}: Case correctly returned empty content for an intentionally empty file '{file_path_from_task}'. Writing empty file.")
                    await asyncio.to_thread(self.file_system_manager.write_file, file_path_from_task, "")
                    final_content_for_return = "" # Set this to signal success and break the loop
                    break # Exit the case_attempt loop successfully
                # --- END FIX ---

                if sanitized_content is None: # This now only runs if an empty file was NOT intended
                    logger.info(f"Task {task_id_str}: Case returned no content or unparseable XML for '{file_path_from_task}'. Checking existing file.")
                    if await asyncio.to_thread(self.file_system_manager.file_exists, file_path_from_task):
                        existing_content = await asyncio.to_thread(self.file_system_manager.read_file, file_path_from_task)
                        # Validate existing content against task requirements
                        static_analysis_passed, static_analysis_feedback = self._validate_generated_code(
                            existing_content, task, file_path_from_task # Pass existing_content
                        )
                        if static_analysis_passed:
                            logger.info(f"Task {task_id_str}: Existing file '{file_path_from_task}' already meets requirements. Task considered successful without modification.")
                            final_content_for_return = existing_content # Store for return
                            # Update summaries/checksums based on existing file
                            if self.project_state:
                                code_summary = self._extract_summary_from_code(existing_content)
                                if code_summary:
                                    self.project_state.code_summaries[file_path_from_task] = code_summary
                                # Update checksum, etc.
                                await self._update_project_structure_map(file_path_from_task)
                            break # Successful execution (no change needed)
                        else:
                            logger.error(f"Task {task_id_str}: Existing file '{file_path_from_task}' does NOT meet requirements ({static_analysis_feedback}), and Case provided no valid change.")
                            last_error_for_case = ValueError(f"Existing file does not meet requirements, and Case provided no valid change. Feedback: {static_analysis_feedback}")
                            feedback_for_case = f"The existing file '{file_path_from_task}' does not meet requirements ({static_analysis_feedback}), and your previous response did not provide valid code. Please provide the complete, correct code for this file."
                            if case_attempt >= MAX_IMPLEMENTATION_ATTEMPTS:
                                # Raise CommandExecutionError for structured error handling
                                raise CommandExecutionError(
                                    message=f"Static analysis failed: {static_analysis_feedback}",
                                    stderr=static_analysis_feedback,
                                    exit_code=1
                                )
                            await asyncio.sleep(1.0 * case_attempt)
                            continue # Retry with Case
                    else: # File doesn't exist, and Case provided no content
                        logger.error(f"Task {task_id_str}: File '{file_path_from_task}' does not exist, and Case provided no content for creation (Action: {task.action}).")
                        last_error_for_case = ValueError("File does not exist, and Case provided no content for creation.")
                        feedback_for_case = "The file does not exist, and your previous response did not provide valid code for creation. Please provide the complete code."
                        if case_attempt >= MAX_IMPLEMENTATION_ATTEMPTS:
                            raise RuntimeError(f"Case failed to provide content for new file '{file_path_from_task}' after {MAX_IMPLEMENTATION_ATTEMPTS} attempts.")
                        await asyncio.sleep(1.0 * case_attempt)
                        continue # Retry with Case

                # 1. Clean the LLM output first
                # The _parse_mcp_file_content method already handles some cleaning,
                # but an explicit call to _clean_llm_code_output on the raw response
                # before XML parsing can be beneficial if the LLM wraps XML in markdown.

                # --- Pillar 2: Proactive Static Analysis (Step 2 of Universal Plan) ---
                # This happens *before* writing the file.
                # _validate_generated_code now serves as our static analysis.
                # We pass the sanitized_content (which might still have summary comments)
                # and _validate_generated_code will clean the summary before actual validation.
                static_analysis_passed, static_analysis_feedback = False, None
                if sanitized_content:
                    static_analysis_passed, static_analysis_feedback = self._validate_generated_code(
                        sanitized_content, task, file_path_from_task
                    )
                    if not static_analysis_passed:
                        logger.error(f"Task {task_id_str}: Static analysis (Pillar 2) FAILED for '{file_path_from_task}' (Case Attempt {case_attempt}): {static_analysis_feedback}")
                        last_error_for_case = ValueError(f"Static analysis failed: {static_analysis_feedback}")
                        feedback_for_case = f"Static analysis failed: {static_analysis_feedback}. Please correct the code. Ensure it's valid {self.project_state.framework if self.project_state else ''} code and does not contain placeholders."
                        if case_attempt >= MAX_IMPLEMENTATION_ATTEMPTS:
                            raise RuntimeError(f"Static analysis failed after {MAX_IMPLEMENTATION_ATTEMPTS} Case attempts: {static_analysis_feedback}")
                        await asyncio.sleep(1.0 * case_attempt) # Brief pause before Case retries
                        continue # Retry with Case to fix static analysis error
                    logger.info(f"Task {task_id_str}: Static analysis (Pillar 2) PASSED for '{file_path_from_task}'.")
                
                if sanitized_content: # This block now only runs if sanitized_content was not None initially
                    parsed_content_with_summary = self._clean_llm_code_output(sanitized_content)
                    generated_content_with_summary = parsed_content_with_summary # Store it
                else:
                    parsed_content_with_summary = None
                
                task.llm_interactions.append({
                    "agent": "Case", "attempt": case_attempt, "type": "code_generation",
                    "prompt_summary": user_message_content[:LOG_PROMPT_SUMMARY_LENGTH] + "...", # Log a summary of the prompt
                    "response": case_raw_output
                }) # Log this attempt regardless of path match

                if parsed_content_with_summary is None:
                    if "class Solution {" in case_raw_output or "leetcode" in case_raw_output.lower() or "**Answer:**" in case_raw_output:
                        logger.error(f"Task {task_id_str}: Case returned unexpected non-project code.")
                        raise ValueError("Case returned irrelevant code (example/markdown?).")
                    raise ValueError("Case failed to generate valid <file_content> XML or content was empty.")



                expected_path_from_task_norm = Path(file_path_from_task).as_posix()

                if not parsed_path_str: # Case didn't provide a path in its XML
                    logger.error(f"Task {task_id_str}: Case output XML is missing the 'path' attribute. Expected target: '{expected_path_from_task_norm}'.")
                    last_error_for_case = ValueError("Case output XML is missing the required 'path' attribute.")
                    feedback_for_case = (
                        "CRITICAL ERROR: Your output XML was missing the 'path' attribute in the <file_content> tag. "
                        f"The required path for this task is: path=\"{expected_path_from_task_norm}\"."
                    )
                    if case_attempt < MAX_IMPLEMENTATION_ATTEMPTS: continue
                    else: raise last_error_for_case # Max attempts for Case

                # Path provided by Case, now validate it
                if parsed_path_str: # This condition is now always true if we didn't 'continue' above
                    case_provided_path_norm = Path(parsed_path_str.strip()).as_posix()
                    if case_provided_path_norm != expected_path_from_task_norm:
                        logger.error(f"Task {task_id_str}: CRITICAL MISMATCH! Case XML path ('{case_provided_path_norm}') "
                                     f"differs significantly from task target ('{expected_path_from_task_norm}').")
                        last_error_for_case = ValueError(f"Path Mismatch: Expected '{expected_path_from_task_norm}', got '{case_provided_path_norm}'.")
                        feedback_for_case = (
                            f"CRITICAL ERROR: Path Mismatch in your XML output.\n"
                            f"Your XML specified: path=\"{case_provided_path_norm}\"\n"
                            f"The required path for this task is: path=\"{expected_path_from_task_norm}\"\n"
                            f"You MUST correct the 'path' attribute in your <file_content> tag to be EXACTLY '{expected_path_from_task_norm}' AND provide the content for that file."
                        )
                        if case_attempt < MAX_IMPLEMENTATION_ATTEMPTS: continue
                        else: raise last_error_for_case
                
                # Extract summary and clean code *before* validation
                code_summary = self._extract_summary_from_code(parsed_content_with_summary)
                clean_code_for_validation = self._remove_summary_comment_from_code(parsed_content_with_summary)
                # Validate syntax BEFORE writing to file
                # The static analysis (Pillar 2) using _validate_generated_code has already run.
                if static_analysis_passed:
                    logger.info(f"Code validation passed for Task {task_id_str} (Case Attempt {case_attempt}).")
                    processed_content_for_writing = await self._handle_placeholders_in_code(clean_code_for_validation) # Write clean code
                   
                    test_step_command = await self._handle_placeholders_in_code(task.test_step)

                    if not test_step_command:
                        logger.error(f"Model did not provide a test step, skipping test execution")
                        return False

                    # Validate the test command and make sure it is what the developer intended
                    if 'echo' in test_step_command:
                        raise ValueError(f"Model is sending test step {test_step_command} and this is not correct")
                    final_content_for_return = processed_content_for_writing # Store for return
                    await asyncio.to_thread(self.file_system_manager.write_file, file_path_from_task, processed_content_for_writing)
                    logger.info(f"Task {task_id_str}: File '{file_path_from_task}' {action_desc} successfully.")
                    
                    # --- Store Code Summary ---
                    if self.project_state:
                        if code_summary:
                            self.project_state.code_summaries[file_path_from_task] = code_summary # Ensure this is just the summary text
                            self.project_state.historical_notes.append(f"Task {task_id_str} ({action_desc} '{file_path_from_task}'): Summary - {code_summary[:100]}...")
                        else:
                            fallback_summary = f"Content {action_desc.lower()} for file '{file_path_from_task}' as per task requirements."
                            self.project_state.code_summaries[file_path_from_task] = fallback_summary
                            self.project_state.historical_notes.append(f"Task {task_id_str} ({action_desc} '{file_path_from_task}'): No explicit summary provided by Case. Basic note added.")
                        self.memory_manager.save_project_state(self.project_state) # Save state after summary
                    # --- End Store Code Summary ---                    

                    if self.project_state:
                        if self.code_intelligence_service:
                            try:
                                # summary = self.code_intelligence_service.get_file_summary(file_path_from_task) # This summary is for open_files_context
                                # Update project structure map after successful file operation
                                await self._update_project_structure_map(file_path_from_task)
                                logger.info(f"Updated project_structure_map for {file_path_from_task} after Case execution.")
                                # Update open_files_context with a fresh summary from CodeIntelligenceService
                                fresh_summary_for_open_files = self.code_intelligence_service.get_file_summary(file_path_from_task)
                                self.project_state.open_files_context[file_path_from_task] = fresh_summary_for_open_files
                                logger.debug(f"Updated open_files_context for {file_path_from_task} with fresh summary.")
                            except Exception as e_sum_struct:
                                logger.warning(f"Failed to update structure map or open_files_context for {file_path_from_task}: {e_sum_struct}")
                        
                        if self.file_system_manager:
                            try:
                                file_hash = self.file_system_manager.get_file_hash(file_path_from_task)
                                if file_hash:
                                    self.project_state.file_checksums[file_path_from_task] = file_hash
                                    logger.debug(f"Updated file_checksums for {file_path_from_task}")
                                else:
                                    logger.warning(f"Could not get hash for {file_path_from_task}")
                            except Exception as e_hash:
                                logger.warning(f"Failed to get hash for {file_path_from_task} for file_checksums: {e_hash}")
                        
                        # Git commit after all updates
                        try:
                            await asyncio.to_thread(self.command_executor.run_command, f'git add "{file_path_from_task}"')
                            commit_msg = f"Task {task_id_str}: {task.description}"
                            await asyncio.to_thread(self.command_executor.run_command, f'git commit -m "{commit_msg}" --allow-empty')
                            logger.info(f"Task {task_id_str}: Committed changes for '{file_path_from_task}'.")
                        except Exception as git_commit_e:
                            logger.warning(f"Failed to commit changes for '{file_path_from_task}' after task {task_id_str}: {git_commit_e}")
                    
                    break # Successful execution of file task
                # This 'else' for static_analysis_passed should not be reached due to the 'continue' above.
                # If it is, it's an error in logic.

            except (ValueError, RuntimeError, RateLimitError, AuthenticationError, InterruptedError) as e:
                last_error_for_case = e
                logger.error(f"Case execution failed for Task {task_id_str} (Case Attempt {case_attempt}): {e}")
                feedback_for_case = f"Case execution failed: {e}" 
                if isinstance(e, (RateLimitError, AuthenticationError, InterruptedError)):
                     raise e 
                if case_attempt == MAX_IMPLEMENTATION_ATTEMPTS:
                    raise RuntimeError(f"Case failed after {MAX_IMPLEMENTATION_ATTEMPTS} attempts: {e}") from e
                else:
                    await asyncio.sleep(1.5 * case_attempt) 
            except Exception as e:
                 last_error_for_case = e
                 logger.exception(f"Unexpected error during Case execution for Task {task_id_str} (Case Attempt {case_attempt}): {e}")
                 feedback_for_case = f"Unexpected error: {e}"
                 if case_attempt == MAX_IMPLEMENTATION_ATTEMPTS:
                      raise RuntimeError(f"Case failed unexpectedly after {MAX_IMPLEMENTATION_ATTEMPTS} attempts: {e}") from e
                 else:
                      await asyncio.sleep(1.5 * case_attempt)

        if final_content_for_return is not None:
            return self._remove_summary_comment_from_code(final_content_for_return) # Return clean code
        else:
            final_error_message = f"Task {task_id_str} failed after all Case attempts."
            if last_error_for_case:
                raise RuntimeError(final_error_message) from last_error_for_case
            else:
                raise RuntimeError(final_error_message + " No specific error recorded from last Case attempt.")


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

                # Handle cancellation
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

    def _validate_patch_guards(self, patch_content: str, error_report: Dict[str, Any]) -> bool:
        """Applies safety guardrails to the generated patch."""
        # Guardrail 1: Patch size limit
        if len(patch_content.splitlines()) > 50: # Example limit
            logger.warning("Guardrail FAIL: Patch exceeds 50 lines.")
            return False

        # Guardrail 2: File whitelist/blacklist (requires plugin system)
        # For now, we'll skip this, but the hook is here.

        logger.info("Patch passed safety guardrails.")
        return True
    
    async def _initiate_remediation(self, task: FeatureTask, error_output: str, original_command: Optional[str] = None) -> bool:
        """
        (Placeholder/Legacy) Orchestrates the remediation process for a failed task.

        NOTE: This method's logic has largely been superseded by the more robust,
        self-contained loop within the `RemediationManager`.
        """
        if not self.prompts or not self.agent_manager or not self.file_system_manager or not self.code_intelligence_service:
            raise RemediationError("Cannot initiate remediation: Core components missing.")
        self.is_recovering = True # Set recovery flag

        logger.info(f"Initiating autonomous remediation for task {task.task_id_str}...")
        # This method should delegate to the RemediationManager, just like _implement_feature_tasks does.
        
        # Construct a structured error from the raw output
        structured_error = {"errorType": "TaskFailedError", "message": error_output, "stack": []}
        try:
            # If error_output is a JSON string from CommandResult, parse it
            command_result_data = json.loads(error_output)
            if command_result_data.get('structured_error'):
                structured_error = command_result_data['structured_error']
            elif command_result_data.get('stderr'):
                    structured_error['message'] = command_result_data['stderr']
        except (json.JSONDecodeError, TypeError):
            pass # Use the generic error if parsing fails

        # Instantiate and run the remediation manager
        remediation_manager = RemediationManager(
            agent_manager=self.agent_manager,
            file_system_manager=self.file_system_manager,
            command_executor=self.command_executor,
            test_command=original_command or task.test_step # Use original command if available
        )
        
        self.progress_callback({"message": f"Task {task.task_id_str} failed. Attempting automated remediation..."})
        
        fix_successful = await remediation_manager.remediate(structured_error)

        if fix_successful:
            logger.info(f"Remediation successful for task {task.task_id_str}.")
            return True
        else:
            logger.error(f"Automated remediation failed for task {task.task_id_str} after all attempts.")
            self.is_recovering = False # Reset recovery flag on definitive failure
            raise RemediationError(f"Remediation failed after all attempts. Last error: {error_output}")

    async def _remediate_feature_after_test_failure(self, feature: ProjectFeature, test_failure_stderr: str) -> bool: # type: ignore
        """
        (Placeholder/Legacy) Attempts to remediate feature code after feature-level tests fail.

        NOTE: This logic has been superseded by the main remediation loop, which can
        handle test failures as the trigger for the self-healing process.
        """
        logger.warning(f"Feature '{feature.name}' test remediation triggered. Test stderr:\n{test_failure_stderr[:500]}")
        self._report_system_message(f"Feature '{feature.name}' tests failed. Analyzing for fixes...", task_id=feature.id)

        self.is_recovering = True # Set recovery flag
        # Create a dummy "task" to leverage existing _initiate_remediation
        # This task is temporary and its state won't be saved directly
        dummy_task_for_analysis = FeatureTask(
            task_id_str=f"{feature.id}_feature_test_failure",
            action="Run command", # This is a dummy action, the remediation will apply file changes
            target="echo 'Feature test failure remediation'",
            description=f"Remediate feature '{feature.name}' based on test failures.",
            requirements=f"The following tests failed for feature '{feature.name}':\n{test_failure_stderr}\nReview the feature's code files and fix the underlying issues."
        )
        dummy_task_for_analysis.remediation_attempts = getattr(feature, 'remediation_attempts_for_feature_tests', 0)
        
        try:
            remediation_successful = await self._initiate_remediation(
                dummy_task_for_analysis,
                test_failure_stderr # Pass the actual test failure stderr
            )
            if remediation_successful:
                logger.info(f"Remediation attempt for feature '{feature.name}' based on test failure was processed.")
                if hasattr(feature, 'remediation_attempts_for_feature_tests'):
                    feature.remediation_attempts_for_feature_tests = getattr(feature, 'remediation_attempts_for_feature_tests', 0) + 1
                return True
            else:
                logger.error(f"Automated remediation for feature '{feature.name}' test failure did not succeed.")
                return False
        except RemediationError as rem_e:
            logger.error(f"Definitive RemediationError during feature test remediation for '{feature.name}': {rem_e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error during feature test remediation for '{feature.name}': {e}")
            self.is_recovering = False # Reset recovery flag on unexpected error
            return False


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
             combined_pattern = r"\{\{\s*(" + "|".join(re.escape(k) for k in resolved_values.keys()) + r")\s*\}\}"
             def replace_match(m):
                 key = m.group(1)
                 return resolved_values.get(key, m.group(0)) # Return original match if key somehow missing

             processed_code = re.sub(combined_pattern, replace_match, code)
             logger.info(f"Placeholders replaced in code/command string.")

        return processed_code

    async def _gather_related_file_context(self, feature: ProjectFeature, current_task: FeatureTask) -> str:
        """
        Gathers snippets of existing files relevant to the current task to provide
        context to the AI. It prioritizes files directly related to the current
        task and also includes standard framework configuration files.
        """
        if not self.project_state: return "# Error: Project state not available for context gathering."

        relevant_paths = set()
        project_name = self.project_state.project_name or 'myproject' # Use attribute access
        framework = self.project_state.framework # Use attribute access
        root_path = self.file_system_manager.project_root # Get root Path object

        # --- Prioritize files directly related to the current task ---
        current_target = current_task.target # Use attribute access
        if current_task.action in ["Create file", "Modify file"] and current_target: # Use attribute access
            relevant_paths.add(str(current_target)) # Add the target file itself (to get existing content for modify)
            # Try to add related files based on framework conventions
            try:
                target_path_obj = Path(current_target)
                app_name = target_path_obj.parts[0] if len(target_path_obj.parts) > 1 and target_path_obj.parts[0] != project_name else None

                if framework == 'django' and app_name:
                    if target_path_obj.name == 'views.py':
                        relevant_paths.add(f"{app_name}/models.py")
                        relevant_paths.add(f"{app_name}/urls.py")
                        relevant_paths.add(f"{app_name}/forms.py") # Add forms
                        # Add related templates
                        template_dir = root_path / app_name / "templates" / app_name
                        if template_dir.exists():
                            for html_file in template_dir.glob("*.html"):
                                relevant_paths.add(html_file.relative_to(root_path).as_posix())
                    elif target_path_obj.name == 'models.py':
                        relevant_paths.add(f"{app_name}/admin.py")
                        relevant_paths.add(f"{app_name}/views.py")
                        relevant_paths.add(f"{app_name}/forms.py")
                    elif target_path_obj.name == 'urls.py':
                         relevant_paths.add(f"{app_name}/views.py")
                         relevant_paths.add(f"{project_name}/urls.py") # Project urls
                    elif target_path_obj.name == 'forms.py':
                         relevant_paths.add(f"{app_name}/views.py")
                         relevant_paths.add(f"{app_name}/models.py")

                # Add similar logic for Flask, Node, etc. if needed
                # elif framework == 'flask': ...
                # elif framework == 'node': ...

            except Exception as path_e:
                 logger.warning(f"Could not determine related files for '{current_target}': {path_e}")

        # Add standard framework configuration files if they exist
        if framework == 'django':
            if (root_path / project_name / "settings.py").exists(): relevant_paths.add(f"{project_name}/settings.py")
            if (root_path / project_name / "urls.py").exists(): relevant_paths.add(f"{project_name}/urls.py")
        elif framework == 'flask':
             if (root_path / "app.py").exists(): relevant_paths.add("app.py")
             if (root_path / "config.py").exists(): relevant_paths.add("config.py")
        elif framework == 'node':
             if (root_path / "package.json").exists(): relevant_paths.add("package.json")
             if (root_path / "server.js").exists(): relevant_paths.add("server.js")
             if (root_path / "app.js").exists(): relevant_paths.add("app.js")


        # Add files mentioned in other tasks of the same feature (less priority)
        for task in feature.tasks: # Use attribute access
            if task.action in ["Create file", "Modify file"] and task.target and isinstance(task.target, (str, Path)): # Use attribute access
                relevant_paths.add(task.target) # Use attribute access

        # --- Read file contents ---
        context_str = ""
        max_len_per_file = 1500 # Limit length of each snippet
        file_read_count = 0
        max_files_to_read = 10 # Limit number of files read for performance

        # Sort paths for consistent ordering
        sorted_paths = sorted(list(relevant_paths))

        for path_str in sorted_paths:
            if file_read_count >= max_files_to_read:
                 logger.warning(f"Context gathering reached limit of {max_files_to_read} files.")
                 context_str += "\n\n... [Context file limit reached] ..."
                 break

            # Skip reading the current target if the action is 'Create file' (it shouldn't exist yet)
            if current_task.action == "Create file" and path_str == current_target: # Use attribute access
                 logger.debug(f"Skipping context read for target of 'Create file' task: '{path_str}'")
                 continue

            try:
                # Use asyncio.to_thread as read_file can be blocking I/O
                content = await asyncio.to_thread(self.file_system_manager.read_file, path_str)
                
                # Check if the current file is the one being modified by the task
                if path_str == current_task.target:
                    snippet = content # Don't truncate the target file
                else:
                    snippet = content[:max_len_per_file] # Truncate other context files
                    if len(content) > max_len_per_file:
                        snippet += "\n... [TRUNCATED]"

                context_str += f"\n\n--- Content of `{path_str}` ---\n```\n{snippet}\n```\n"
                logger.debug(f"Added context from '{path_str}'")
                file_read_count += 1
            except FileNotFoundError:
                # Only log debug if file not found, as it's expected for new files
                logger.debug(f"Context file not found, skipping: '{path_str}'")
            except Exception as e:
                logger.warning(f"Error reading context file '{path_str}': {e}")

        return context_str if context_str else "# No relevant file context found or read."

    def _validate_generated_code(self, code: str, task: FeatureTask, file_path: str) -> tuple[bool, Optional[str]]:
        """
        Performs static analysis on code generated by the LLM before it's written to disk.

        This is a critical guardrail that checks for common LLM failure modes, such as
        including placeholder comments (e.g., `# TODO`), generating syntactically
        invalid code, or returning empty content when code was expected.
        """
        # --- NEW: Remove summary comment block first ---
        code_for_validation = self._remove_summary_comment_from_code(code)
        # --- END NEW ---

        # Use a simple regex to find 'eval(' - might have false positives but better than nothing
        if re.search(r'\beval\s*\(', code):
            logger.error(f"Pre-check failed for '{file_path}': Potential unsafe use of eval() detected.")
            return False, "Security Risk: Use of eval() detected. Use safer alternatives."

        # Ensure requirements is treated as a string
        task_requirements_str = task.requirements or ""
        task_requirements_lower_stripped = task_requirements_str.lower().strip()

        # --- NEW: More robust check for "empty file" requirements ---
        # This allows for variations in how the planner might phrase this.
        is_intended_to_be_empty = any(phrase in task_requirements_lower_stripped for phrase in [
            "file should be empty",
            "create an empty file",
            "empty file",
            "just be a placeholder"
        ])

        if is_intended_to_be_empty:
            # If the requirement is for an empty file, and the code is indeed empty, it's a pass.
            # This is the primary fix for the issue in the log.
            if not code_for_validation.strip():
                logger.debug(f"Validation passed for '{file_path}': Requirement is 'File should be empty.' and code is empty/whitespace.")
                return True, None
            else: # This 'else' now correctly corresponds to the first 'if'
                logger.warning(f"Pre-check failed for '{file_path}': Requirement is 'File should be empty.' but generated code is NOT empty.")
                return False, "Code was generated, but the requirement was 'File should be empty.'"

        # --- Check for completely empty code (if not required to be empty) ---
        if not code_for_validation.strip(): # Use code_for_validation
            allowed_empty_implicitly = [".gitignore", ".env", "__init__.py"] # Allow __init__.py to be empty
            if Path(file_path).name in allowed_empty_implicitly:
                 logger.debug(f"Pre-check allowing implicitly empty file: '{file_path}'")
                 return True, None
            logger.warning(f"Pre-check failed for '{file_path}': Generated code is empty or whitespace only (and requirement wasn't 'File should be empty.').")
            return False, "Generated code is empty or contains only whitespace."
        # --- Check for placeholder comments/strings (excluding 'pass' keyword here) ---
        comment_placeholders = [
            "# Implement logic here", "pass # Implement me", # Keep 'pass # ...' here as it's a comment
            "# TODO:", "// TODO:", "/* TODO:",
            "# Add your routes here", "// Add middleware here",
            "/* Add your styles here */",
            "# ...", "// ...",
            # DO NOT include the standalone "pass" keyword in this list
        ]
        code_lines = code_for_validation.splitlines() # Use code_for_validation
        for i, line in enumerate(code_lines):
            stripped_line = line.strip()

            # --- Specific check for standalone 'pass' keyword ---
            if stripped_line == "pass":
                # Allow pass if it's the only thing in a block (e.g., empty class/func def)
                # This is a heuristic and might not be perfect
                is_likely_placeholder = True
                if i > 0: # Check previous line for indentation/block start
                    prev_line = code_lines[i-1].strip()
                    # Check if previous line ends with ':' (func/class/if/else/try/except/finally/with/for/while def)
                    if prev_line.endswith(':'):
                         # Check indentation difference (simple check)
                         prev_indent = len(code_lines[i-1]) - len(code_lines[i-1].lstrip())
                         curr_indent = len(line) - len(line.lstrip())
                         if curr_indent > prev_indent:
                             is_likely_placeholder = False # Likely intended empty block
                if is_likely_placeholder:
                    logger.warning(f"Pre-check failed for '{file_path}': Found potentially placeholder 'pass' statement on line {i+1}.")
                    return False, "Code contains potentially placeholder 'pass' statement. Please implement the required logic."

            # --- Check for comment/string placeholders within the line ---
            for ph in comment_placeholders:
                # Check if the placeholder string exists anywhere in the line (case-insensitive)
                if ph.lower() in line.lower(): # Check the original line to catch comments accurately
                    logger.warning(f"Pre-check failed for '{file_path}': Found placeholder comment/string '{ph}' on line {i+1}.")
                    return False, f"Code contains placeholder comment/string: '{ph}'. Please replace it with actual implementation."

        # --- Check if code is effectively empty (only comments or whitespace) ---
        # Moved the check for empty/whitespace only to the beginning

        # --- Basic Syntax Check (Python only for now) ---
        if file_path.lower().endswith(".py"):
            try: # Use code_for_validation
                ast.parse(code_for_validation, filename=file_path) # Use ast.parse for syntax check
                logger.debug(f"Python syntax pre-check passed for '{file_path}'.")
            except SyntaxError as py_syntax_e:
                logger.warning(f"Python syntax pre-check failed for '{file_path}': {py_syntax_e}")
                # Provide specific line/offset if available
                err_detail = f"Generated Python code has a SyntaxError on line {py_syntax_e.lineno or '?'}, offset {py_syntax_e.offset or '?'}: {py_syntax_e.msg}"
                return False, err_detail
            except Exception as compile_e: # Catch other potential compilation errors like IndentationError # Use code_for_validation
                logger.warning(f"Python compilation pre-check failed for '{file_path}': {compile_e}")
                # --- ADDED: Check for urlpatterns in urls.py and AppConfig in apps.py ---
                if file_path.lower().endswith("urls.py"):
                # ast.parse can also raise other errors like IndentationError which are subclasses of SyntaxError or sometimes other exceptions
                    if "urlpatterns" not in code:
                        logger.warning(f"Pre-check failed for '{file_path}': `urlpatterns` list definition not found.")
                        return False, "Code for urls.py is missing the `urlpatterns` list definition."
                elif file_path.lower().endswith("apps.py"): # Use code_for_validation
                    # Check for class XConfig(AppConfig): and name = 'X'
                    if not re.search(r"class\s+\w+Config\(AppConfig\):", code_for_validation) or \
                       not re.search(r"name\s*=\s*['\"]\w+['\"]", code_for_validation):
                        # Corrected indentation for the logger.warning line
                        logger.warning(f"Pre-check failed for '{file_path}': Missing `AppConfig` class or `name` attribute.")
                        return False, "Code for apps.py is missing a correctly defined `AppConfig` class with a `name` attribute."
                elif self.project_state and self.project_state.framework == 'django' and Path(file_path).name == "settings.py": # Use code_for_validation
                    if "INSTALLED_APPS" not in code_for_validation or "DATABASES" not in code_for_validation:
                        logger.warning(f"Pre-check failed for '{file_path}': Missing `INSTALLED_APPS` or `DATABASES`.")
                        return False, "Code for settings.py is missing `INSTALLED_APPS` or `DATABASES`."
                return False, f"Python compilation error: {compile_e}"

        # Add checks for other languages (JS, HTML, CSS) if needed using linters or basic regex

        logger.debug(f"Basic code pre-check passed for '{file_path}'.")
        return True, None # All checks passed

    # --- Feature Lifecycle Simulation Methods ---

    async def _test_feature(self, feature: ProjectFeature):
        """
        (Placeholder) Simulates the testing phase for a feature.

        In a future implementation, this could involve running a broader suite of
        integration tests or using an LLM to evaluate the feature's correctness.
        """
        feature_name = feature.name # Use attribute access
        feature_id = feature.id # Use attribute access
        self.progress_callback({"increment": 75, "message": f"Testing feature: {feature_name}..."})
        logger.info(f"Simulating testing phase for feature '{feature_name}' ({feature_id}).")

        failed_tasks = [t.task_id_str for t in feature.tasks if t.status == "failed"] # Use attribute access

        if failed_tasks:
             logger.error(f"Feature '{feature_name}' failed testing phase because underlying tasks failed: {failed_tasks}")
             feature.status = "failed" # Mark feature as failed # Use attribute access
             # feature.result = f"Testing failed due to task failures: {', '.join(failed_tasks)}" # ProjectFeature has no 'result' field
             self._report_error(f"Feature '{feature_name}' failed testing (tasks {', '.join(failed_tasks)} failed).", task_id=feature_id)
        else:
             logger.info(f"Simulated testing passed for feature '{feature_name}' (all tasks completed).")
             self._report_system_message(f"Feature '{feature_name}' passed testing.", task_id=feature_id)
             # Status remains 'testing', indicating readiness for the next phase (review)


    async def _review_feature(self, feature: ProjectFeature):
        """
        (Placeholder) Simulates the code review phase for a feature.

        This could be extended to use an LLM to review the generated code for
        quality, style, and adherence to best practices.
        """
        feature_name = feature.name # Use attribute access
        feature_id = feature.id # Use attribute access
        self.progress_callback({"increment": 85, "message": f"Reviewing feature: {feature_name}..."})
        logger.info(f"Simulating code review phase for feature '{feature_name}' ({feature_id}).")

        # Placeholder: Simulate review passing if testing passed.
        if feature.status == "failed": # Use attribute access
             logger.error(f"Simulated review skipped for '{feature_name}' as it failed in previous stages.")
             self._report_system_message(f"Review skipped for failed feature '{feature_name}'.", task_id=feature_id)
        else:
             # Simulate a brief delay for review
             await asyncio.sleep(0.1)
             logger.info(f"Simulated code review passed for feature '{feature_name}'.")
             self._report_system_message(f"Feature '{feature_name}' passed review.", task_id=feature_id)
             # Status remains 'reviewing', indicating readiness for the next phase (merge)


    async def _merge_feature(self, feature: ProjectFeature):
        """
        Simulates merging a completed feature.

        This method updates the project's cumulative documentation with a summary
        of the changes made for the completed feature.
        """
        feature_name = feature.name # Use attribute access
        feature_id = feature.id # Use attribute access
        branch_name = feature.branch_name or f"feature/{feature_id}" # Use attribute access
        self.progress_callback({"increment": 95, "message": f"Merging feature: {feature_name}..."})
        logger.info(f"Simulating merge for feature '{feature_name}' from branch '{branch_name}'.")

        # --- Update Cumulative Documentation ---
        if self.project_state:
             doc_update = f"\n\n## Feature: {feature_name} ({feature_id})\n\n"
             doc_update += f"**Status:** Merged\n"
             if branch_name: doc_update += f"**Branch:** `{branch_name}`\n"
             doc_update += f"\n**Description:**\n{feature.description}\n\n" # Use attribute access

             completed_tasks = [t for t in feature.tasks if t.status == "completed"] # Use attribute access
             if completed_tasks:
                 doc_update += "**Summary of Changes (Tasks Completed):**\n"
                 # List first few tasks as a summary
                 for task in completed_tasks[:7]:
                     action = task.action or 'Task' # Use attribute access
                     target = task.target or 'N/A' # Use attribute access
                     desc = (task.description or '')[:50] # Shorten description # Use attribute access
                     doc_update += f"- `{task.task_id_str or '?'}` {action}: `{target}` ({desc}...)\n" # Use attribute access
                 if len(completed_tasks) > 7: doc_update += "- ... and more.\n"

             # Append update to existing docs
             current_docs = self.project_state.cumulative_docs # Use attribute access
             if not isinstance(current_docs, str): current_docs = "" # Ensure it's a string
             self.project_state.cumulative_docs = current_docs + doc_update # Use attribute access
             logger.info("Updated cumulative project documentation.")
             self._report_system_message("Updated project documentation.", task_id=feature_id)
        else:
             logger.warning("Cannot update documentation: Project state is not available.")

        # Simulate a brief delay for merge
        await asyncio.sleep(0.1)
        logger.info(f"Simulated merge successful for feature '{feature_name}'.")
        # The main loop will set the status to 'merged' after this method returns.


    def _get_placeholder_context_for_case(self) -> str:
        """
        Gathers information about available placeholders (user-provided inputs)
        to include in the context for the Case (coder) agent.
        """
        if not self.project_state: return "# Error: Project state not available."

        context_parts = ["\n**Available Placeholders (Use `{{PLACEHOLDER_NAME}}` syntax):**"]
        placeholders = self.project_state.placeholders # Use attribute access
        if placeholders:
            for key, value in placeholders.items():
                 is_sensitive = "KEY" in key or "SECRET" in key or "TOKEN" in key or "PASSWORD" in key
                 status = "(Set, Sensitive)" if is_sensitive else f"(Set, Value: {str(value)[:20]}...)"
                 context_parts.append(f"- `{{{{{key}}}}}`: {status}")
        else:
            context_parts.append("- None defined yet.")
        return "\n".join(context_parts)


    def _parse_mcp_file_content(self, case_output: str) -> tuple[Optional[str], Optional[str]]:
        """
        Parses the file path and content from the Case agent's XML-like output.

        It's designed to be robust, using BeautifulSoup to handle potentially
        malformed XML and extracting content from a `<file_content>` tag.
        """
        if not case_output: return None, None
        # --- AGGRESSIVE PRE-CLEANING of entire Case output ---
        # Remove any leading/trailing markdown fences from the entire raw output
        # This helps if the LLM wraps its XML in markdown.
        cleaned_case_output = case_output.strip()
        cleaned_case_output = re.sub(r"^\s*```(?:[a-zA-Z0-9\-\_]+)?\s*\n?", "", cleaned_case_output, flags=re.IGNORECASE | re.MULTILINE)
        cleaned_case_output = re.sub(r"\n?\s*```\s*$", "", cleaned_case_output, flags=re.MULTILINE).strip()
        # --- END AGGRESSIVE PRE-CLEANING ---

        logger.debug(f"Attempting to parse Case output (first 500 chars): {case_output[:500]}...")
        try:
            # Attempt to find the start of the <file_content> tag to isolate the XML block
            xml_start_index = cleaned_case_output.find("<file_content") # Use pre-cleaned output
            if xml_start_index == -1:
                logger.warning("Could not find start of <file_content> tag in Case output.")
                if not cleaned_case_output.strip().startswith("<") and (":\n" in cleaned_case_output or "```" in cleaned_case_output): # Check original cleaned output
                    logger.warning("Case output (pre-cleaned) seems to be conversational or unformatted code, not the expected XML.")
                return None, None

            # Try to find the corresponding end tag to get a cleaner block
            xml_end_index = case_output.rfind("</file_content>")
            xml_block_to_parse = case_output
            if xml_end_index != -1 and xml_end_index > xml_start_index:
                xml_block_to_parse = case_output[xml_start_index : xml_end_index + len("</file_content>")]
            elif xml_start_index != -1 : # Only start tag found
                xml_block_to_parse = cleaned_case_output[xml_start_index:] # Use pre-cleaned
            else: # Neither start nor end tag found in pre-cleaned output
                xml_block_to_parse = cleaned_case_output


            try:
                # Use BeautifulSoup to parse the XML block, preferring the 'xml' parser (lxml)
                soup = BeautifulSoup(xml_block_to_parse, 'xml')
            except FeatureNotFound:
                # If lxml is not installed, bs4 raises FeatureNotFound.
                # Fall back to the built-in html.parser, which is usually sufficient for this simple XML.
                logger.warning("XML parser 'lxml' not found. Falling back to 'html.parser'. For best results, please `pip install lxml`.")
                soup = BeautifulSoup(xml_block_to_parse, 'html.parser')

            file_content_tag = soup.find('file_content')

            if file_content_tag and file_content_tag.has_attr('path'):
                path_attr = file_content_tag['path']
                
                # --- FIX: Use get_text() for robust content extraction ---
                # This correctly handles empty tags, empty CDATA, and normal content without complex branching.
                content = file_content_tag.get_text()

                # --- FIX: Only clean content if it's not None. An empty string is valid content. ---
                if content:
                    # --- Content Cleaning (remains important as a secondary step) ---
                    # This cleans fences *inside* the CDATA, if any.
                    # Remove leading/trailing markdown fences (e.g., ```python ... ```)
                    # Make stripping more aggressive: strip leading/trailing whitespace first, then regex
                    content = content.strip() # Strip leading/trailing whitespace from the whole CDATA content first
                    # Regex to remove leading and trailing fences, including optional language specifier
                    content = re.sub(r"^\s*```(?:[a-zA-Z0-9\-\_]+)?\s*\n?", "", content, flags=re.IGNORECASE | re.MULTILINE)
                    content = re.sub(r"\n?\s*```\s*$", "", content, flags=re.MULTILINE).strip() # Strip again after regex

                if path_attr and content is not None: # Ensure content is not None
                    normalized_path = Path(path_attr.strip()).as_posix() # Ensure path_attr is also stripped
                    logger.debug(f"Parsed path='{normalized_path}' from <file_content> using BeautifulSoup.")
                    return normalized_path, content
                else:
                    logger.warning(f"Parsed <file_content> tag but path ('{path_attr}') or content is missing/invalid.")
                    return None, None
            else:
                logger.warning("Could not find valid <file_content> tag with 'path' attribute using BeautifulSoup.")
                logger.debug(f"XML block attempted for parsing (from pre-cleaned output): {xml_block_to_parse[:500]}...")
                return None, None

        except Exception as e:
            logger.error(f"Error parsing Case file content XML with BeautifulSoup: {e}", exc_info=True)
            logger.debug(f"Original pre-cleaned Case output that failed parsing: {cleaned_case_output[:1000]}...")
            return None, None

    def _update_workflow_context_step(self, task_id: str, status: Literal["completed", "failed"], details: Optional[str] = None):
        """
        Updates the non-sensitive `workflow_context.json` file with the status of
        a completed or failed task. This is used for logging and potentially for
        providing high-level context to the AI in future sessions.
        """
        if not task_id: return

        # Ensure 'steps' list exists
        if "steps" not in self.workflow_context or not isinstance(self.workflow_context["steps"], list):
            self.workflow_context["steps"] = []

        # Check if task already exists in context
        existing_step_index = -1
        for i, step in enumerate(self.workflow_context["steps"]):
            if isinstance(step, dict) and step.get("id") == task_id:
                existing_step_index = i
                break

        step_data = {
            "id": task_id,
            "status": status,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) # Add timestamp
        }
        if details:
            step_data["details"] = details[:500] # Limit detail length

        if existing_step_index != -1:
            # Update existing entry
            self.workflow_context["steps"][existing_step_index] = step_data
            logger.debug(f"Updated workflow context for step '{task_id}' to status '{status}'.")
        else:
            # Add new entry
            self.workflow_context["steps"].append(step_data)
            logger.debug(f"Added workflow context entry for step '{task_id}' with status '{status}'.")

        # Note: Saving the context is handled by the calling method (_implement_feature_tasks)
        # after each pass or at the end.
    # --- Main Feature Development Cycle ---

    async def run_feature_cycle(self):
        """
        Runs the main development cycle, processing all eligible features sequentially.

        This is the primary loop of the application. It selects the next feature,
        plans it, implements its tasks, and handles testing and merging.
        """
        if not self.prompts:
            logger.error("Cannot run feature cycle: Framework prompts not loaded.")
            self._report_error("Cannot run cycle: Framework prompts missing.", is_fatal=True)
            return # Return None or handle appropriately, bool might not be right here
        if not self.project_state:
            logger.error("Cannot run feature cycle: Project state not initialized.")
            self._report_error("Cannot run cycle: Project state missing.", is_fatal=True)
            return

        logger.info("Starting feature development cycle...")
        if hasattr(self, 'ui_updater') and self.ui_updater:
            self.ui_updater.update_status("Starting feature development...")
        else:
            self.progress_callback({"message": "Starting feature development..."})

        # --- Start of Resilient Feature Cycle Loop ---
        try:
            while True:
                next_feature = self._select_next_feature()

                # Check feature status at the beginning of the loop
                if next_feature and next_feature.status == FeatureStatusEnum.MERGED:
                    logger.info(f"Skipping already completed feature: {next_feature.name}")
                    continue

                if not next_feature:
                    logger.info("No more eligible features to process or workflow halted.")
                    if hasattr(self, 'ui_updater') and self.ui_updater:
                        self.ui_updater.update_status("Workflow complete or halted.")
                    else:
                        self.progress_callback({"message": "Workflow complete or halted."})
                    break # Exit the main while loop

                self.project_state.current_feature_id = next_feature.id
                self.memory_manager.save_project_state(self.project_state)
                feature_name = next_feature.name
                feature_id = next_feature.id
                
                if hasattr(self, 'ui_updater') and self.ui_updater:
                    self.ui_updater.update_current_feature(feature_name)
                else:
                    self.progress_callback({"message": f"Processing Feature: {feature_name}"})

                logger.info(f"--- Processing Feature: '{feature_name}' ({feature_id}) ---")

                # --- Planning Stage ---
                if next_feature.status == FeatureStatusEnum.IDENTIFIED:
                    logger.info(f"Feature '{feature_name}' is identified. Starting planning phase.")
                    if hasattr(self, 'ui_updater') and self.ui_updater:
                        logger.info(f"Clearing agent chat history before planning feature '{next_feature.name}'.")
                        # self.agent_manager.clear_chat_history() # Assuming clear_chat_history exists
                        self.ui_updater.update_status(f"Planning feature: {feature_name}...")
                    else:
                        self.progress_callback({"message": f"Planning feature: {feature_name}..."})

                    plan_generated_successfully = await self._plan_feature(next_feature)
                    self.memory_manager.save_project_state(self.project_state)

                    current_feature_reloaded_after_plan = self.project_state.get_feature_by_id(feature_id)
                    if not current_feature_reloaded_after_plan:
                        logger.error(f"Critical error: Feature {feature_id} not found in state after planning attempt.")
                        self._report_error(f"Critical state error for feature {feature_name}. Workflow halted.", task_id=feature_id, is_fatal=True)
                        break # Halt on critical state error
                    next_feature = current_feature_reloaded_after_plan

                    if not plan_generated_successfully or next_feature.status == FeatureStatusEnum.PLANNING_FAILED:
                        logger.error(f"Planning phase failed for '{feature_name}'. Status: {next_feature.status}. Stopping ALL feature processing.")
                        if hasattr(self, 'ui_updater') and self.ui_updater:
                             self.ui_updater.update_status(f"ERROR: Planning failed for {feature_name}. Workflow halted.")
                             self.ui_updater.update_feature_status(feature_id, next_feature.status)
                        else:
                            self.progress_callback({
                                "error": f"Planning failed for {feature_name} (Status: {next_feature.status}). Workflow halted."
                            })
                        self.project_state.current_feature_id = None # Clear current feature
                        self.memory_manager.save_project_state(self.project_state)
                        break # Halt workflow

                # --- Implementation Stage --- (Ensure next_feature is reloaded if planning happened)
                if next_feature.status == FeatureStatusEnum.PLANNED or next_feature.status == FeatureStatusEnum.IMPLEMENTING:
                    logger.info(f"Feature '{feature_name}' is planned/implementing. Starting/Continuing implementation phase.")
                    if hasattr(self, 'ui_updater') and self.ui_updater:
                        # self.agent_manager.clear_chat_history() # Assuming clear_chat_history exists
                        self.ui_updater.update_status(f"Implementing feature: {feature_name}...")
                    else:
                        self.progress_callback({"message": f"Implementing feature: {feature_name}..."})
                    
                    if next_feature.status == FeatureStatusEnum.PLANNED: # Only set to implementing if it was just planned
                        next_feature.status = FeatureStatusEnum.IMPLEMENTING
                        self.memory_manager.save_project_state(self.project_state)

                    await self._implement_feature_tasks(next_feature) # This updates feature status internally
                    self.memory_manager.save_project_state(self.project_state) # Save after tasks

                    current_feature_reloaded_after_impl = self.project_state.get_feature_by_id(feature_id)
                    if not current_feature_reloaded_after_impl:
                        logger.error(f"Critical error: Feature {feature_id} not found after implementation tasks.")
                        break # Halt on critical state error
                    next_feature = current_feature_reloaded_after_impl
                    if next_feature.status == FeatureStatusEnum.PLANNING_FAILED:
                        logger.error(f"Implementation phase for '{feature_name}' skipped due to planning failure (e.g., empty task list). Status: {next_feature.status}. Stopping ALL feature processing.")
                        self._report_error(f"Feature '{feature_name}' had no tasks to implement or planning failed. Workflow halted.", task_id=feature_id, is_fatal=True)
                        self.project_state.current_feature_id = None
                        self.memory_manager.save_project_state(self.project_state)
                        break # Halt workflow
                    elif next_feature.status != FeatureStatusEnum.TASKS_IMPLEMENTED: # If not ready for feature tests
                        logger.error(f"Implementation phase failed for '{feature_name}'. Status: {next_feature.status}. Stopping ALL feature processing.")
                        if hasattr(self, 'ui_updater') and self.ui_updater:
                            self.ui_updater.update_status(f"ERROR: Implementation failed for {feature_name}. Workflow halted.")

                            self.ui_updater.update_feature_status(feature_id, next_feature.status)
                        else:
                            self.progress_callback({"error": f"Implementation failed for {feature_name} (Status: {next_feature.status}). Workflow halted."})
                        self.project_state.current_feature_id = None
                        self.memory_manager.save_project_state(self.project_state)
                        break # Halt workflow

                # --- Post-Implementation Stages ---
                # If all tasks were implemented successfully, the feature is ready for review/merge.
                # The final `manage.py test` task in the plan serves as the feature-level test.
                if next_feature.status == FeatureStatusEnum.TASKS_IMPLEMENTED:
                    logger.info(f"Feature '{feature_name}' implementation complete. Moving to review phase.")
                    next_feature.status = FeatureStatusEnum.REVIEWING # Transition to next phase
                    self.memory_manager.save_project_state(self.project_state)

                # --- Review Stage ---
                if next_feature.status == FeatureStatusEnum.REVIEWING: # This will now be triggered after TASKS_IMPLEMENTED
                    logger.info(f"Feature '{feature_name}' is ready for review. Starting review phase.")
                    next_feature.status = FeatureStatusEnum.REVIEWING
                    self.memory_manager.save_project_state(self.project_state)
                    await self._review_feature(next_feature)
                    self.memory_manager.save_project_state(self.project_state)

                    if next_feature.status == FeatureStatusEnum.IMPLEMENTATION_FAILED: # If _review_feature sets it to failed
                        logger.error(f"Review phase failed for '{feature_name}'. Status: {next_feature.status}. Stopping ALL feature processing.")
                        if hasattr(self, 'ui_updater') and self.ui_updater:
                            self.ui_updater.update_status(f"ERROR: Review failed for {feature_name}. Workflow halted.")
                            self.ui_updater.update_feature_status(feature_id, next_feature.status)
                        else:
                            self.progress_callback({"error": f"Review failed for {feature_name}. Workflow halted."})
                        self.project_state.current_feature_id = None # type: ignore
                        self.memory_manager.save_project_state(self.project_state)
                        break # Halt on critical state error

                # --- Merge Stage ---
                if next_feature.status == FeatureStatusEnum.REVIEWING:
                    logger.info(f"Feature '{feature_name}' passed review. Starting merge phase.")
                    await self._merge_feature(next_feature)
                    next_feature.status = FeatureStatusEnum.MERGED # Use MERGED status
                    self.memory_manager.save_project_state(self.project_state)
                    logger.info(f"--- Feature '{feature_name}' ({feature_id}) successfully merged. ---")
                    if hasattr(self, 'ui_updater') and self.ui_updater:
                        self.ui_updater.update_feature_status(feature_id, "merged")
                        self.ui_updater.update_status(f"Feature '{feature_name}' completed.")
                    else:
                        self.progress_callback({"message": f"Feature '{feature_name}' completed.", "increment": 100})

                # Clear current feature ID after processing this feature (successful or handled failure that didn't break the loop)
                self.project_state.current_feature_id = None # type: ignore
                self.memory_manager.save_project_state(self.project_state)

        # --- End of Resilient Feature Cycle Loop ---
        except InterruptedError as e:
            logger.warning(f"Feature cycle interrupted by user: {e}")
            if self.project_state and self.project_state.current_feature_id: # Check if project_state exists
                current_f = self.project_state.get_feature_by_id(self.project_state.current_feature_id) # Use attribute access
                if current_f: current_f.status = FeatureStatusEnum.CANCELLED # Use attribute access
            self._report_error(f"Operation cancelled by user: {e}", is_fatal=False)
        except (RateLimitError, AuthenticationError) as api_err:
            logger.error(f"API Error during feature cycle: {api_err}", exc_info=True)
            if self.project_state and self.project_state.current_feature_id: # Check if project_state exists
                current_f = self.project_state.get_feature_by_id(self.project_state.current_feature_id) # Use attribute access
                if current_f: current_f.status = FeatureStatusEnum.IMPLEMENTATION_FAILED # Use attribute access
            self._report_error(f"API Error halted workflow: {api_err}", is_fatal=True)
        except Exception as e_main_loop:
            logger.exception(f"Unexpected error in main feature cycle: {e_main_loop}")
            if self.project_state and self.project_state.current_feature_id: # Check if project_state exists
                current_f = self.project_state.get_feature_by_id(self.project_state.current_feature_id) # Use attribute access
                if current_f: current_f.status = FeatureStatusEnum.IMPLEMENTATION_FAILED # Or a new "system_error" status # Use attribute access
                self._report_error(f"System error processing feature '{current_f.name if current_f else 'Unknown'}': {e_main_loop}", task_id=current_f.id if current_f else None, is_fatal=True) # Use attribute access
            else:
                self._report_error(f"System error in workflow: {e_main_loop}", is_fatal=True)
        finally:
            # Ensure current_feature_id is cleared and state is saved if an exception broke the loop
            if self.project_state: # Check if project_state exists
                self.project_state.current_feature_id = None
                self.memory_manager.save_project_state(self.project_state) # Use attribute access

        logger.info("Feature development cycle ended.")
        if self.project_state: # Check if project_state exists
            self.project_state.current_feature_id = None
            self.project_state.last_error_context = None 
            self.memory_manager.save_project_state(self.project_state)

    def _clean_markdown_for_parsing(self, markdown: str) -> str:
        """
        (Legacy/Helper) Removes common LLM artifacts and ensures a Markdown plan starts
        with a recognizable task header or metadata line before parsing.
        """
        if not markdown or markdown.isspace():
            return ""

        # Remove potential code fences around the whole plan
        markdown = re.sub(r"^```(?:markdown|json)?\s*\n", "", markdown, flags=re.IGNORECASE | re.MULTILINE)
        markdown = re.sub(r"\n```\s*$", "", markdown, flags=re.MULTILINE)
        markdown = markdown.strip()

        # Remove any leading text before the first task header
        first_task_match = re.search(r"^\s*###\s+Task\s+[0-9\.]+", markdown, re.MULTILINE)
        if first_task_match:
            markdown = markdown[first_task_match.start():]
        else:
            logger.warning("No '### Task ID:' header found at the beginning of the plan after cleaning.")
            # Attempt aggressive cleaning of list items if headers are missing
            lines = markdown.splitlines()
            potential_task_lines = [
                line for line in lines if
                re.match(r"^\s*[-*]\s*`?[A-Za-z\s_]+?`?:", line) # Look for metadata lines
            ]
            if potential_task_lines:
                logger.warning("Found metadata lines without '### Task' headers. Attempting to parse as single block.")
                markdown = "\n".join(potential_task_lines) # Treat as one block if headers missing
            else:
                logger.warning("No task headers or metadata lines found. Cannot parse.")
                return "" # Cannot parse if no headers or metadata found

        return markdown.strip()

    def _parse_detailed_markdown_plan(self, markdown: str) -> List[FeatureTask]:
        """
        Parses a detailed Markdown plan generated by the Tars agent into a list of
        structured `FeatureTask` Pydantic models. It uses helper methods to extract
        task blocks and parse their metadata, making it resilient to variations in
        the LLM's output format.
        """
        tasks: List[FeatureTask] = []

        # --- 1. Pre-process markdown ---
        # The 'markdown' input to this function is already cleaned by _clean_llm_markdown_output in _plan_feature.
        # The _clean_markdown_for_parsing step here was redundant and potentially problematic.
        if not markdown or markdown.isspace(): # Check the input 'markdown' directly
            logger.warning("Markdown plan content is empty or whitespace after cleaning. Cannot parse tasks.")
            return tasks
        # --- ADDED: Initialize cleaned_markdown here ---
        # This variable is used later in the method, ensure it's defined.
        cleaned_markdown: str = markdown # Initialize with the input markdown

        logger.debug(f"Markdown for Parsing (received from _plan_feature after _clean_llm_markdown_output):\n---\n{markdown[:1000]}...\n---") # Log input

        # --- 2. Extract Blocks ---
        task_blocks = self._extract_task_blocks(markdown) # Pass the input markdown directly
        if not task_blocks:
            logger.warning("Markdown plan parser did not extract any task blocks.")
            return tasks

        # --- 3. Parse and Validate Each Block ---
        explicit_id_found_in_any_block = False
        for task_id_hdr, task_title, content_block in task_blocks:
            logger.debug(f"--- Processing Task Block: {task_id_hdr}. '{task_title}' ---")
            logger.debug(f"Raw Task Content Block:\n---\n{content_block}\n--- End Block ---")

            task_data = self._parse_metadata(content_block)

            # Add title and potentially override ID
            task_data.setdefault("description", task_title)
            if "task_id_str" in task_data:
                explicit_id_found_in_any_block = True
            else:
                # Use ID from header only if no explicit 'ID:' metadata was found in *this* block
                task_data["task_id_str"] = task_id_hdr
                logger.debug(f"Using ID '{task_id_hdr}' from header as no explicit 'ID:' metadata found in this block.")

            # Post-validate and create FeatureTask model
            validated_task = self._post_validate_and_create_task(task_data)
            if validated_task:
                tasks.append(validated_task)

        # Final check: If fallback parsing was used (no headers) and no explicit ID was found
        # in the metadata either, log a warning.
        if len(task_blocks) == 1 and task_blocks[0][0] == "0.0" and not explicit_id_found_in_any_block:
            logger.warning("Fallback parsing in _extract_task_blocks was likely used, and no explicit 'ID:' metadata found in the content block. Task ID defaulted to '0.0'.")

        if not tasks and cleaned_markdown:
            logger.warning("Markdown plan parser did not extract any *valid* tasks from the provided content.")

        return tasks
    def _convert_debugger_actions_to_feature_tasks(self, debugger_actions: List[Dict[str, Any]], original_task: FeatureTask) -> List[FeatureTask]:
        """Converts actions from Tars Debugger's plan into FeatureTask objects."""
        recovery_tasks: List[FeatureTask] = []
        for i, action_item in enumerate(debugger_actions):
            rec_action_type = action_item.get("action")
            rec_target = action_item.get("target")
            rec_instructions = action_item.get("instructions")

            if not rec_action_type or not rec_target or not rec_instructions:
                logger.warning(f"Skipping incomplete recovery action from debugger: {action_item}")
                continue
            
            # For now, only support "Modify file" from debugger
            if rec_action_type == "Modify file":
                try:
                    recovery_task = FeatureTask(
                        task_id_str=f"{original_task.task_id_str}_recovery_{i+1}",
                        action="Modify file",
                        target=rec_target,
                        description=f"Recovery: Apply fix to '{rec_target}' for original task '{original_task.task_id_str}'. Original error: {str(original_task.result)[:100]}...",
                        requirements=rec_instructions, # Debugger's instructions become Case's requirements
                        test_step=f"python -m py_compile {rec_target.replace('/', '\\\\')}" if rec_target.endswith(".py") else f"echo 'Manual check for recovery task on {rec_target}'",
                    )
                    recovery_tasks.append(recovery_task)
                except ValidationError as ve:
                    logger.error(f"Failed to create FeatureTask for debugger recovery action {action_item}: {ve}")
            else:
                logger.warning(f"Unsupported recovery action type '{rec_action_type}' from Tars Debugger. Skipping.")

    def _extract_task_blocks(self, markdown: str) -> List[Tuple[str, str, str]]:
        """Extracts (id, title, content_block) tuples from cleaned markdown. Helper for _parse_detailed_markdown_plan.""" # Added this block back
        task_blocks = []
        # Regex to find the start of a task item (matching '### Task X.Y: Title' format)
        task_start_regex = re.compile(
            r"^\s*###\s+Task\s+" # Matches '### Task ' (ensure it's at the start of a line)
            r"([0-9\.]+)"        # Capture the hierarchical ID (e.g., 1.1, 2.3.4) - Group 1
            r":\s*"              # Matches the colon and whitespace
            r"(.*?)"             # Capture the task title (non-greedy) - Group 2
            r"\s*$",             # Optional whitespace until end of line
            re.MULTILINE
        )
        task_matches = list(task_start_regex.finditer(markdown))
        logger.debug(f"Found {len(task_matches)} potential task start markers using '### Task' regex.")

        if not task_matches and markdown.strip():
            # Fallback: No '### Task' headers, treat entire content as one block
            logger.warning("'### Task' start regex failed. Parsing entire content as one task block.")
            first_id_match = re.search(r"^\s*[-*]\s*`?ID`?:\s*([0-9\.]+)", markdown, re.MULTILINE)
            fallback_id = first_id_match.group(1) if first_id_match else "0.0"
            fallback_title = "Fallback Task (Parsing Error)"
            logger.warning(f"Using fallback ID '{fallback_id}' and title '{fallback_title}'.")
            task_blocks.append((fallback_id, fallback_title, markdown))
            return task_blocks # Return immediately after fallback

        for i, match in enumerate(task_matches):
            task_id = match.group(1)
            task_title = match.group(2).strip()
            start_index = match.end()
            end_index = task_matches[i+1].start() if i + 1 < len(task_matches) else len(markdown)
            content_block = markdown[start_index:end_index].strip()
            task_blocks.append((task_id, task_title, content_block))

        return task_blocks
   # --- NEW HELPER: Parse metadata from a task content block ---
    def _parse_metadata(self, content_block: str) -> Dict[str, Any]:
        """
        Parses key-value metadata (like ID, Action, Target) from a single task's
        content block in the Markdown plan.
        """
        metadata_dict: Dict[str, Any] = {}
        
        # Regex for a single metadata line start
        metadata_line_start_regex = re.compile(r"""
            ^\s*[-*]\s*                                     # List item marker
            (?:
                \*\*(?P<key_bold_content>[A-Za-z\s_:]+?)\*\* |
                `(?P<key_backtick_content>[A-Za-z\s_:]+?)` |
                (?P<key_plain_text>[A-Za-z\s_]+?)
            )
            (?P<external_colon_and_space>\s*:\s*)?          # Optional external colon
        """, re.VERBOSE)

        # Known top-level keys to identify the end of a multi-line 'Requirements' block
        KNOWN_TOP_LEVEL_KEYS = {"id", "action", "target", "description", "requirements", "dependencies", "test_step", "doc_update", "resources_defined"}

        lines = content_block.splitlines()
        current_line_idx = 0

        while current_line_idx < len(lines):
            line = lines[current_line_idx]
            match_obj = metadata_line_start_regex.match(line)

            if not match_obj:
                current_line_idx += 1
                continue

            key_content_from_bold = match_obj.group("key_bold_content")
            key_content_from_backtick = match_obj.group("key_backtick_content")
            key_content_from_plain = match_obj.group("key_plain_text")
            external_colon_matched = bool(match_obj.group("external_colon_and_space"))

            key_raw_content = None
            if key_content_from_bold is not None: key_raw_content = key_content_from_bold
            elif key_content_from_backtick is not None: key_raw_content = key_content_from_backtick
            elif key_content_from_plain is not None: key_raw_content = key_content_from_plain

            key_part_end_index = -1
            if key_content_from_bold: key_part_end_index = match_obj.end("key_bold_content")
            elif key_content_from_backtick: key_part_end_index = match_obj.end("key_backtick_content")
            elif key_content_from_plain: key_part_end_index = match_obj.end("key_plain_text")
            
            value_part_raw_from_line = ""
            if key_part_end_index != -1: # Should always be true if match_obj is not None and key_raw_content is not None
                if external_colon_matched:
                    value_part_raw_from_line = line[match_obj.end("external_colon_and_space"):]
                elif key_raw_content and key_raw_content.endswith(':'): # Internal colon
                     value_part_raw_from_line = line[key_part_end_index:] 
                # If no colon matched here but key_raw_content doesn't end with ':', it will be caught below

            if key_raw_content is None:
                logger.warning(f"Could not determine key content from line: {line}")
                current_line_idx += 1
                continue

            colon_is_internal = key_raw_content.endswith(':')

            if not colon_is_internal and not external_colon_matched:
                # This check is important. If a key is formatted (bold/backtick) but has no colon,
                # it might be a list item within Requirements.
                # However, our metadata_line_start_regex is quite broad.
                # For plain text keys, a colon is mandatory.
                if key_content_from_plain: # Plain text keys MUST have a colon
                     logger.warning(f"Plain key '{key_raw_content}' missing its colon separator. Line: {line}")
                     current_line_idx += 1
                     continue
                # For formatted keys, if no colon, it might be a list item.
                # The multi-line "requirements" logic should handle not misinterpreting these.
                # If we are not in "requirements" parsing, and a formatted key has no colon, it's an issue.
                # For now, let's assume the "requirements" block handles its own sub-items.
                # If this line is reached outside "requirements" parsing, it's a malformed key.
                logger.debug(f"Formatted key '{key_raw_content}' without a clear colon separator. Line: '{line}'. Assuming it's part of a multi-line value if inside one, or skipping.")
                current_line_idx += 1
                continue
            
            key_for_dict = key_raw_content
            if colon_is_internal:
                key_for_dict = key_for_dict[:-1].strip() 
            
            key = key_for_dict.strip().lower().replace(' ', '_')
            
            # FIX 1: Correct order of stripping for value_first_line
            value_first_line = value_part_raw_from_line.strip('`').strip()


            if key == "requirements":
                requirements_value_buffer = [value_first_line]
                current_line_idx += 1 
                
                while current_line_idx < len(lines):
                    next_line_to_check = lines[current_line_idx]
                    
                    # FIX 2: Improved logic to detect end of requirements block
                    potential_next_key_match = metadata_line_start_regex.match(next_line_to_check)
                    is_new_top_level_key = False
                    if potential_next_key_match:
                        pk_bold = potential_next_key_match.group("key_bold_content")
                        pk_btick = potential_next_key_match.group("key_backtick_content")
                        pk_plain = potential_next_key_match.group("key_plain_text")
                        
                        pk_raw_content_next = None
                        if pk_bold: pk_raw_content_next = pk_bold
                        elif pk_btick: pk_raw_content_next = pk_btick
                        elif pk_plain: pk_raw_content_next = pk_plain

                        if pk_raw_content_next:
                            # Check if the colon exists for this potential next key
                            pk_colon_internal_next = pk_raw_content_next.endswith(':')
                            pk_colon_external_next = bool(potential_next_key_match.group("external_colon_and_space"))
                            
                            if pk_colon_internal_next or pk_colon_external_next:
                                pk_clean_next = pk_raw_content_next.strip(':').strip().lower().replace(' ', '_')
                                if pk_clean_next in KNOWN_TOP_LEVEL_KEYS:
                                    is_new_top_level_key = True
                    
                    if is_new_top_level_key:
                        break # End of requirements block
                    else:
                        # It's part of the requirements value
                        requirements_value_buffer.append(next_line_to_check.strip())
                        current_line_idx += 1
                
                full_requirements_text = "\n".join(requirements_value_buffer).strip()
                # Clean code fences from requirements
                full_requirements_text = re.sub(r"^```(?:python|html|css|javascript|text|markdown)?\s*\n", "", full_requirements_text, flags=re.IGNORECASE | re.MULTILINE)
                full_requirements_text = re.sub(r"\n```\s*$", "", full_requirements_text, flags=re.MULTILINE)
                metadata_dict["requirements"] = full_requirements_text.strip() # Final strip
                logger.debug(f"Extracted Requirements for '{key}':\n{metadata_dict['requirements'][:200]}...")
            else:
                # Single-line value
                if key == "id": metadata_dict["task_id_str"] = value_first_line
                elif key == "action": metadata_dict["action"] = value_first_line
                elif key == "target": metadata_dict["target"] = value_first_line.strip('`') # Commands in target are often backticked
                elif key == "description": metadata_dict["description"] = value_first_line
                elif key == "dependencies": metadata_dict["dependencies"] = value_first_line
                elif key == "test_step": metadata_dict["test_step"] = value_first_line.strip('`') # Test steps also often backticked
                elif key == "doc_update": metadata_dict["doc_update"] = value_first_line
                elif key == "resources_defined": metadata_dict["resources_defined"] = value_first_line
                else:
                    logger.warning(f"Unknown metadata key '{key}' (from raw content '{key_raw_content}'). Line: {line}")
                current_line_idx += 1
        
        return metadata_dict

    # --- NEW HELPER: Validate parsed data and create FeatureTask ---
    # --- NEW HELPER: Validate parsed data and create FeatureTask ---
    def _post_validate_and_create_task(self, task_data: Dict[str, Any]) -> Optional[FeatureTask]:
        """
        Performs final validation on the parsed data for a single task and, if valid,
        creates a `FeatureTask` Pydantic model instance.
        """
        try:
            # Pydantic validation (includes default test step and dependency parsing)
            task_model = FeatureTask.model_validate(task_data)

            # Post-Pydantic Checks
            target_val = task_model.target.strip('`') # Strip backticks here
            action_val = task_model.action

            # --- Refined Placeholder/HTML Check (Consider removing if too broad) ---
            # This check might be overly aggressive. Relying on path/command validation might be better.
            if action_val not in ["Run command", "Prompt user input"]:
                unescaped_target = html.unescape(target_val) # target_val is already stripped of backticks
                if "<" in unescaped_target or ">" in unescaped_target or "{{" in unescaped_target: # Check for literal <, > or {{
                    logger.warning(f"Task '{task_model.task_id_str}' target '{target_val}' contains potential unescaped HTML or placeholder-like syntax. Skipping.")
                    return None
            # --- End Refined Check ---

            # Django-specific path validation (app name check)
            if self.project_state and self.project_state.framework == 'django':
                if action_val in ["Create file", "Modify file", "Create directory"]:
                    try:
                        target_path = Path(target_val)
                        if not target_path.is_absolute():
                            # Check if the first part of the path is intended to be an app name
                            is_potential_app_related_path = False
                            if action_val == "Create directory" and len(target_path.parts) == 1:
                                is_potential_app_related_path = True
                            elif action_val in ["Create file", "Modify file"] and len(target_path.parts) > 1:
                                is_potential_app_related_path = True
                            
                            if is_potential_app_related_path:
                                first_part = target_path.parts[0]
                                # Standard project-level directories that are not apps
                                standard_project_dirs = {'static', 'templates', 'media', 'docs', 'user_assets', 'venv'}
                                # Project config directory name
                                project_config_dir_name = self.project_state.project_name # Assuming project_name is the config dir

                                if first_part != project_config_dir_name and first_part not in standard_project_dirs:
                                    # Now, first_part is likely an app name, validate it
                                    if not IDENTIFIER_REGEX.match(first_part):
                                        logger.error(f"Task '{task_model.task_id_str}' target '{target_val}' uses invalid app/module name '{first_part}'. Skipping task.")
                                        return None
                    except Exception as path_e:
                        logger.warning(f"Path validation failed for task '{task_model.task_id_str}' target '{target_val}': {path_e}")
                        return None

            logger.debug(f"Successfully parsed and validated task: {task_model.model_dump()}")
            return task_model

        except ValidationError as e:
            logger.error(f"Pydantic validation failed for parsed task data: {e}. Data: {task_data}")
            # logger.error(f"Pydantic Errors:\n{e.json(indent=2)}") # Uncomment for detailed errors
            return None
        except Exception as post_val_e:
            logger.error(f"Post-validation check failed for task data: {post_val_e}. Data: {task_data}")
            return None
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



    async def _execute_and_test_single_task(self, task: FeatureTask, feature: ProjectFeature) -> Tuple[bool, bool, Optional[str], Optional[str]]:
        """
        Executes the main action and then the test step for a single task.

        This function is the core execution unit for one step in the plan. It dispatches
        to the appropriate helper method based on the task's action type and then runs
        the associated test step to verify the outcome. It does not handle remediation.
        """
        execution_success = False
        test_step_success = False
        execution_output = None
        test_step_output = None
        task_id_str = task.task_id_str
        # --- Prepare for potential block and substitution ---
        effective_test_command = ""
        original_test_command_for_feedback = "" # To store the command that was initially blocked
        block_description_for_feedback = ""
        is_safe_alternative_run = False
        # 1. Execute Main Task Action
        try:
            if task.action == "Create file" or task.action == "Modify file":
                execution_output = await self._execute_file_task_case(task, feature, is_remediation=False) # Assume not remediation for direct exec
                execution_success = True
            elif task.action == "Run command":
                command_to_run_raw = task.target
                command_to_run = await self._handle_placeholders_in_code(command_to_run_raw)

                # --- NEW: Proactive check for existing Django app before running 'startapp' ---
                if "manage.py startapp" in command_to_run:
                    app_name_match = re.search(r"startapp\s+([a-zA-Z_][a-zA-Z0-9_]*)", command_to_run)
                    if app_name_match:
                        app_name = app_name_match.group(1)
                        # Check if a key file like apps.py already exists. This is a reliable indicator.
                        if self.file_system_manager and await asyncio.to_thread(self.file_system_manager.file_exists, f"{app_name}/apps.py"):
                            logger.info(f"Task {task.task_id_str}: Proactively skipping 'startapp {app_name}' because app already exists ('{app_name}/apps.py' found).")
                            execution_output = "Command skipped: App already exists."
                            execution_success = True
                            # Since we skipped the main action, we can also consider the test step successful.
                            test_step_success = True
                            test_step_output = "Test step skipped as app already exists."
                            return execution_success, test_step_success, execution_output, test_step_output
                # --- END NEW ---

                description = task.description or f"Run: {command_to_run[:30]}..."
                logger.info(f"Task {task_id_str}: Requesting UI execution for command: `{command_to_run}`")
                self.progress_callback({"action_details": f"Waiting for user to run: {command_to_run}"})
                exec_success_cmd, exec_output_cmd = await self.request_command_execution_cb(
                    task_id_str, command_to_run, description
                )
                execution_output = exec_output_cmd
                execution_success = exec_success_cmd # Set success flag directly from the execution result

                # --- ENHANCED: Intelligent handling for 'startapp' name conflict ---
                if not execution_success and "manage.py startapp" in command_to_run:
                    stderr_str = ""
                    try:
                        result_data = json.loads(str(execution_output))
                        stderr_str = result_data.get("stderr", "")
                    except (json.JSONDecodeError, TypeError):
                        stderr_str = str(execution_output) # Fallback for non-JSON error
                    
                    if "conflicts with the name of an existing Python module" in stderr_str:
                        # The command failed. Now, verify if the app *actually* exists.
                        app_name_match = re.search(r"startapp\s+([a-zA-Z_][a-zA-Z0-9_]*)", command_to_run)
                        if app_name_match:
                            app_name = app_name_match.group(1)
                            # Check for a key file that `startapp` creates, like apps.py
                            if self.file_system_manager and await asyncio.to_thread(self.file_system_manager.file_exists, f"{app_name}/apps.py"):
                                logger.info(f"Task {task_id_str}: 'startapp {app_name}' failed with name conflict, but '{app_name}/apps.py' exists. Treating as success and skipping remediation.")
                                execution_success = True # Override to True, the app is already there.
                                execution_output = "Command skipped: App already exists."
                            else:
                                logger.warning(f"Task {task_id_str}: 'startapp {app_name}' failed with a real name conflict (e.g., with project name). The app directory does not exist. Allowing remediation to proceed.")
                                # Do nothing, let execution_success remain False so remediation is triggered.
                        else:
                            logger.warning(f"Task {task_id_str}: 'startapp' failed with name conflict, but could not parse app name from command. Allowing remediation.")
                # --- END NEW ---

                if not exec_success_cmd:
                    task.execution_history.append({"command_str": command_to_run, "success": False, "stderr": exec_output_cmd, "notes": "Execution via UI failed or skipped."})
                    # Do not raise an exception. Let the failure propagate via the 'execution_success' flag.
                else:
                    task.execution_history.append({"command_str": command_to_run, "success": True, "stdout": exec_output_cmd, "notes": "Execution via UI successful."})
            elif task.action == "Create directory":
                await self._execute_directory_task_fs(task)
                execution_success = True
            elif task.action == "Delete file": # New action handling
                await asyncio.to_thread(self.file_system_manager.delete_file, task.target)
                execution_output = f"File '{task.target}' deleted successfully."
                execution_success = True
            elif task.action == "Prompt user input":
                await self._execute_prompt_user_task(task)
                execution_success = True
                test_step_success = True # Prompt tasks usually don't have test steps
            elif task.action == "delete_app_tests_py":
                app_name = task.target
                if not app_name or not isinstance(app_name, str):
                    raise ValueError("Target for delete_app_tests_py must be a valid app name string.")
                deleted = await asyncio.to_thread(self.file_system_manager.delete_default_tests_py_for_app, app_name)
                if deleted:
                    execution_output = f"Default tests.py for app '{app_name}' deleted successfully."
                else:
                    # This case could mean the file didn't exist or an error occurred.
                    # The file_system_manager logs the specifics. We'll treat as non-fatal.
                    execution_output = f"Attempted to delete default tests.py for app '{app_name}'. File may not have existed or an error occurred (see logs)."
                execution_success = True
            else:
                raise ValueError(f"Unknown task action type: {task.action}")
        except (ValueError, RuntimeError, InterruptedError) as main_action_exc:
            logger.error(f"Task {task_id_str}: Main action execution failed: {main_action_exc}")
            execution_output = str(main_action_exc)
            execution_success = False
        
        # 2. Execute Test Step (if main action succeeded and test step exists)
        test_command_raw = task.test_step
        if execution_success and test_command_raw and not test_step_success:
            test_command_raw_stripped = test_command_raw.strip().strip('`')
            if not test_command_raw_stripped:
                # --- MODIFICATION: Check if task.test_step (from model validator) already set a default ---
                if task.test_step and task.test_step.startswith('echo "Default test step - Check manually'):
                    logger.info(f"Task {task_id_str}: Test step was empty, using model's default: '{task.test_step}'")
                    test_command_raw_stripped = task.test_step
                else:
                    logger.warning(f"Task {task_id_str}: Test step was empty after stripping and no model default. Defaulting to echo.")
                test_command_raw_stripped = 'echo "Default test step - Check manually (empty original)"'
            
            initial_test_command = await self._handle_placeholders_in_code(test_command_raw_stripped)
            original_test_command_for_feedback = initial_test_command # Store for feedback if blocked
            try:
                # Check for blocked command before attempting execution via UI callback
                if self.command_executor: # Ensure command_executor is available
                    self.command_executor.check_command_for_block(initial_test_command)
                effective_test_command = initial_test_command # If not blocked, use initial command

            except BlockedCommandException as e:
                self._report_system_message(f"⚠️ Command blocked by security filter: {e.original_command}")
                self._report_system_message(f"✅ Running safe alternative: {e.safe_alternative}")
                effective_test_command = e.safe_alternative
                is_safe_alternative_run = True
                block_description_for_feedback = e.description
                # --- ADDED: Record security feedback immediately when BlockedCommandException is caught ---
                if self.project_state:
                    feedback_entry = {
                        "feature_id": feature.id, # Use attribute access
                        "task_id_str": task.task_id_str, # Use attribute access
                        "blocked_command": e.original_command,
                        "reason": e.description,
                        "executed_alternative": e.safe_alternative,
                        "outcome": "Pending Execution of Alternative" # Will be updated after alternative runs
                    }
                    self.project_state.security_feedback_history.append(feedback_entry)
                    # No immediate save here, will be saved after the alternative runs or task completes/fails
                # --- END ADDED ---
                # Feedback recording will happen after the safe alternative is run
            except Exception as pre_check_err:
                logger.error(f"Error during test command pre-check for task {task_id_str}: {pre_check_err}")
                test_step_success = False # Mark test step as failed
                test_step_output = f"Test command pre-check error: {pre_check_err}"
                # This will flow into the failure handling logic below

            if test_step_output is None: # Only proceed if pre-check didn't immediately fail
                if platform.system() == "Windows": # Auto-correction for Windows dir/type
                    cmd_strip = effective_test_command.strip()
                    original_effective_cmd_for_log = effective_test_command # For logging auto-correction
                    if cmd_strip.startswith("dir "):
                        parts = cmd_strip.split(maxsplit=1)
                        if len(parts) == 2: effective_test_command = f"dir {parts[1].rstrip('/\\\\ ')}"
                    elif cmd_strip.startswith("type "):
                        effective_test_command = cmd_strip.replace('/', '\\')
                    if effective_test_command != original_effective_cmd_for_log:
                        logger.warning(f"Task {task_id_str}: Auto-correcting test step '{original_effective_cmd_for_log}' to '{effective_test_command}' before execution.")

                logger.info(f"Task {task_id_str}: Running test step: `{effective_test_command}`")
                self.progress_callback({"action_details": f"Running test: {effective_test_command}"})

                try:
                    test_exec_success, test_exec_output_cmd = await self.request_command_execution_cb(
                        f"{task_id_str}_test_initial",
                        effective_test_command,
                        f"Run test step for Task {task_id_str}"
                    )
                    test_step_output = test_exec_output_cmd # Store output
                    task.execution_history.append({"command_str": effective_test_command, "success": test_exec_success, "output": test_exec_output_cmd, "type": "test_step", "is_safe_alt": is_safe_alternative_run})

                    test_step_success = test_exec_success # Assume success unless specific conditions met
                    if not test_exec_success and "Exit Code 1" in str(test_exec_output_cmd): # Check for string output
                        is_makemigrations_check = effective_test_command.startswith("python manage.py makemigrations") and "--check" in effective_test_command
                        if is_makemigrations_check:
                            logger.info(f"Task {task_id_str}: Test step 'makemigrations --check' detected changes (Exit Code 1) - treating as success.")
                            test_step_success = True # Override success
                            test_step_output = "Changes detected, migration needed (Expected)."
                    
                    if not test_step_success: # If still not successful
                        raise RuntimeError(f"Test step failed or skipped: {test_exec_output_cmd}")
                    
                    logger.info(f"Task {task_id_str}: Test step successful.")
                    self._report_system_message(f"Test step passed: {effective_test_command}", task_id=task_id_str)
                except Exception as test_e:
                    test_step_success = False
                    if test_step_output is None: test_step_output = str(test_e) # Ensure output is set
                    logger.error(f"Task {task_id_str}: Test step '{effective_test_command}' failed: {test_e}")
                    self._report_system_message(f"Test step FAILED: {effective_test_command} ({test_e})", task_id=task_id_str)

            # --- Agent Feedback Loop for Blocked Commands (after execution attempt) ---
            if is_safe_alternative_run and self.project_state and self.project_state.security_feedback_history:
                # The actual execution and success determination for the safe alternative
                # has already happened. Here we just record the feedback.
                # Update the last entry if it matches the current blocked command scenario
                last_feedback_entry = self.project_state.security_feedback_history[-1]
                if last_feedback_entry.get("blocked_command") == original_test_command_for_feedback and \
                   last_feedback_entry.get("task_id_str") == task.task_id_str: # Use attribute access
                    last_feedback_entry["outcome"] = "Success" if test_step_success else "Failure"
                    last_feedback_entry["final_executed_command"] = effective_test_command # Log what was actually run
                    logger.info(f"Updated security feedback for task {task.task_id_str} with outcome: {last_feedback_entry['outcome']}") # Use attribute access
                else: # Should not happen if logic is correct, but as a fallback, add new
                    logger.warning("Could not find matching pending security feedback to update. Appending new.")
                    self.project_state.security_feedback_history.append({
                        "feature_id": feature.id, "task_id_str": task.task_id_str, # Use attribute access
                        "blocked_command": original_test_command_for_feedback, "reason": block_description_for_feedback,
                        "executed_alternative": effective_test_command, "outcome": "Success" if test_step_success else "Failure"
                    })
                self.memory_manager.save_project_state(self.project_state) # Save state after updating feedback
            # --- End Agent Feedback Loop ---

        elif execution_success and not test_command_raw: 
            if task.action != "Prompt user input":
                 logger.warning(f"Task {task_id_str}: No test step defined. Assuming success for now.")
            test_step_success = True 

        return execution_success, test_step_success, execution_output, test_step_output

    def _get_project_context_for_planning(self) -> str:
        """
        Assembles a comprehensive string of project context for the Tars planning agent.

        This is one of the most critical context-providing methods. It includes the
        project's file structure, feature status, code summaries, historical decisions,
        and feedback from the security system to give the planner a rich understanding
        of the current state of the project.
        """
        if not self.project_state: return "Error: Project state not available."

        context_parts = []
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
    def _extract_summary_from_code(self, code_content: str) -> Optional[str]:
        """
        Extracts a special summary comment from code generated by the LLM.

        The Case agent is prompted to include a summary in the format:
        `<!-- SUMMARY_START -->...<!-- SUMMARY_END -->`. This function extracts that text.
        """
        summary_match = re.search(r"<!-- SUMMARY_START -->(.*?)<!-- SUMMARY_END -->", code_content, re.DOTALL)
        if summary_match:
            summary = summary_match.group(1).strip()
            logger.debug(f"Extracted code summary: {summary[:100]}...")
            return summary
        logger.debug("No summary comment found in code content.")
        return None
    # --- New Helper Method: _get_error_history_for_analyzer_context ---
    def _get_error_history_for_analyzer_context(self, task: FeatureTask) -> str:
        if not task.llm_interactions:
            return "\nError History Context: No previous analysis attempts for this task.\n"
        
        history_str = "\n**Error History Context (Previous Remediation Attempts for this Task):**\n"
        # Filter for Tars (Analyzer) interactions related to remediation analysis
        analysis_attempts = [
            item for item in task.llm_interactions 
            if item.get("agent") == "Tars (Analyzer)" and "remediation_analysis" in item.get("type", "")
        ]

        if not analysis_attempts:
            return "\nError History Context: No previous analysis attempts recorded for this task.\n"

        for i, attempt_log in enumerate(analysis_attempts[-3:], 1): # Show last 3 attempts
            # Attempt to determine the remediation attempt number more accurately
            # This is an approximation as llm_interactions might store other things.
            approx_remediation_attempt_num = (task.remediation_attempts + 1) - (len(analysis_attempts) - i)
            history_str += f"- Attempt {max(1, approx_remediation_attempt_num)} (LLM Interaction Log Index {i}):\n"
            history_str += f"  - Analyzer Proposal (Summary): {str(attempt_log.get('response'))[:200]}...\n"
            history_str += f"  - Parsed Action: {attempt_log.get('parsed_action', 'N/A')}\n"
            if attempt_log.get('parsed_target'):
                history_str += f"  - Parsed Target: {attempt_log.get('parsed_target')}\n"
            if attempt_log.get('error'): # If the analysis itself had an error
                    history_str += f"  - Analysis Error: {attempt_log.get('error')}\n"
            # To show the outcome of the remediation, we'd need to correlate this with task.result *after* the remediation action was taken.
            # For now, this focuses on what the Analyzer proposed.
        return history_str
    # --- New Helper Method: _get_project_structure_map_for_analyzer_context ---
    def _get_project_structure_map_for_analyzer_context(self) -> str:
        """
        Generates a concise summary of the project's code structure (classes, functions)
        to provide as context to the error analysis agent.
        """
        if not self.project_state or not self.project_state.project_structure_map or not self.project_state.project_structure_map.apps:
            return "\nProject Structure Map: Not available or empty.\n"

        context_str = "\n**Project Structure Map (Key Python Elements):**\n"
        for app_name, app_info in self.project_state.project_structure_map.apps.items():
            context_str += f"- App: `{app_name}`\n"
            if not app_info.files:
                context_str += "    - (No files parsed for this app yet)\n"
                continue
            for file_name, file_info_obj in app_info.files.items():
                if file_info_obj.file_type == "python" and file_info_obj.python_details:
                    context_str += f"  - File: `{file_name}` (Python)\n"
                    if file_info_obj.python_details.functions:
                        func_details = [f"{f.name}({', '.join(p.name for p in f.params)})" for f in file_info_obj.python_details.functions]
                        context_str += f"    - Functions: {', '.join(func_details[:3])}{'...' if len(func_details) > 3 else ''}\n"
                    if file_info_obj.python_details.classes:
                        class_names = [c.name for c in file_info_obj.python_details.classes]
                        context_str += f"    - Classes: {', '.join(class_names[:3])}{'...' if len(class_names) > 3 else ''}\n"
                elif file_info_obj.file_type == "django_model" and file_info_obj.django_model_details:
                    context_str += f"  - File: `{file_name}` (Django Models)\n"
                    if file_info_obj.django_model_details.models:
                        model_names = [m.name for m in file_info_obj.django_model_details.models]
                        context_str += f"    - Models: {', '.join(model_names[:3])}{'...' if len(model_names) > 3 else ''}\n"
                elif file_info_obj.file_type == "django_view" and file_info_obj.django_view_details:
                    context_str += f"  - File: `{file_name}` (Django Views)\n"
                    if file_info_obj.django_view_details.views:
                        view_names = [v.name for v in file_info_obj.django_view_details.views]
                        context_str += f"    - Views: {', '.join(view_names[:3])}{'...' if len(view_names) > 3 else ''}\n"
                elif file_info_obj.file_type == "django_admin" and file_info_obj.django_admin_details:
                    context_str += f"  - File: `{file_name}` (Django Admin)\n"
                    if file_info_obj.django_admin_details.admin_classes:
                        admin_class_names = [ac.name for ac in file_info_obj.django_admin_details.admin_classes]
                        context_str += f"    - Admin Classes: {', '.join(admin_class_names[:3])}{'...' if len(admin_class_names) > 3 else ''}\n"
        return context_str

    def _remove_summary_comment_from_code(self, code_content: str) -> str:
        """
        Removes the special summary comment block from the code content before it's
        written to a file, ensuring only the functional code is saved.
        """
        return re.sub(r"<!-- SUMMARY_START -->.*?<!-- SUMMARY_END -->\s*", "", code_content, flags=re.DOTALL).strip()
