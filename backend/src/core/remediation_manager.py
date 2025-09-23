# src/core/remediation_manager.py
import logging
from typing import Optional, List, Dict, Callable, Awaitable, Tuple, Any, Literal
from bs4 import BeautifulSoup
import re
from enum import Enum
import pathlib
from pathlib import Path
import asyncio
import requests
# Imports for new workflow
from .error_analyzer import ErrorAnalyzer
from .remediation_planner import RemediationPlanner
from .patch_generator import PatchGenerator
from .code_intelligence_service import CodeIntelligenceService
from .parsing_utils import extract_file_contents_from_llm_output
from .project_models import CommandOutput, RemediationTask, ErrorRecord, ProjectState, AnyRemediationTask, CreateFileTask, FixSyntaxTask, FixCommandTask, FixLogicTask, FixBundleTask
from .metrics_tracker import MetricsTracker

# Existing imports from the old file that are still needed
from .agent_manager import AgentManager
from .file_system_manager import FileSystemManager
from .command_executor import CommandExecutor
from .llm_client import RateLimitError, ChatMessage, AuthenticationError

logger = logging.getLogger(__name__)

from .config_manager import FrameworkPrompts

# --- Type Hints for UI Callbacks (to avoid circular import from workflow_manager) ---
ProgressCallback = Callable[[Dict[str, Any]], None]
# A callback to ask the user if a network request that failed should be retried.
RequestNetworkRetryCallable = Callable[[str, str], Awaitable[bool]]

# Define InterruptedError locally to avoid circular dependency with workflow_manager
class InterruptedError(Exception):
    """
    Custom exception raised when a workflow is intentionally stopped by the user,
    for example, by cancelling a confirmation dialog or an API key prompt.
    """
    pass

# New Enum to represent the status of a single remediation cycle
class RemediationCycleStatus(Enum):
    """Defines the possible outcomes of a single attempt to fix a set of errors."""
    SUCCESS = "success"
    PROGRESS_MADE = "progress_made"
    NO_PROGRESS = "no_progress"
    PLAN_FAILED = "plan_failed"
    EXECUTION_FAILED = "execution_failed"

class RemediationManager:
    """
    Orchestrates the automated, multi-step remediation of code errors.

    This class is responsible for the entire self-healing loop. It takes a set of
    analyzed errors, creates a plan to fix them using an LLM, executes that plan
    (which may involve modifying multiple files), and then verifies if the fix was
    successful by re-running the original command that failed.
    """

    def __init__(self, agent_manager: AgentManager, 
                 file_system_manager: FileSystemManager, 
                 command_executor: CommandExecutor, 
                 prompts: FrameworkPrompts, 
                 progress_callback: ProgressCallback,
                 request_network_retry_cb: Optional[RequestNetworkRetryCallable],
                 test_command: Optional[str] = None, 
                 remediation_config: dict = None):
        """
        Initializes the RemediationManager.

        Args:
            agent_manager: Manages interaction with the LLM clients.
            file_system_manager: Handles safe file system operations.
            command_executor: Executes shell commands securely.
            prompts: Contains the system prompts for the AI agents.
            progress_callback: A thread-safe callback to send UI updates.
            request_network_retry_cb: A callback to ask the user to retry network errors.
            test_command: The original command that failed, used for verification.
            remediation_config: A dictionary controlling which remediation actions are allowed.
        """
        self.agent_manager = agent_manager
        self.file_system_manager = file_system_manager
        self.command_executor = command_executor
        self.prompts = prompts
        self.test_command = test_command
        self.remediation_config = remediation_config or {}
        self.progress_callback = progress_callback
        self._request_network_retry_cb = request_network_retry_cb
        # Ensure project_root is a Path object before passing it
        # Initialize all the necessary service components for the remediation process.
        project_root_path = Path(file_system_manager.project_root)
        self.error_analyzer = ErrorAnalyzer(project_root=project_root_path, file_system_manager=self.file_system_manager)
        self.remediation_planner = RemediationPlanner()
        self.patch_generator = PatchGenerator()
        self.code_intelligence_service = CodeIntelligenceService(project_root_path)
        # Set up a dedicated logger for remediation metrics to track agent performance.
        # Store metrics inside the project's .codenow directory
        metrics_log_path = file_system_manager.project_root / ".vebgen" / "remediation_metrics.jsonl"
        metrics_log_path.parent.mkdir(exist_ok=True) # Ensure .codenow directory exists
        self.metrics_tracker = MetricsTracker(log_file_path=str(metrics_log_path))

    async def _call_llm_with_error_handling(
        self,
        agent_type_str: Literal["Tars", "Case"],
        messages: List[ChatMessage],
        task_id: str,
        temperature: float
    ) -> ChatMessage:
        """
        Helper method to call an LLM agent's chat method with robust error handling
        for API key issues and network problems. This centralizes retry logic.
        """
        logger.debug(f"Remediation LLM call for '{task_id}' with temp: {temperature}")
        if not self.agent_manager:
            raise RuntimeError("AgentManager not available in RemediationManager.")

        # This loop handles retries for transient network errors or API key updates.
        while True:
            try:
                # Use the unified invoke_agent method
                system_prompt = messages[0]
                user_messages = messages[1:]
                response = await asyncio.to_thread(self.agent_manager.invoke_agent, system_prompt, user_messages, temperature)
                return response
            except (AuthenticationError, RateLimitError) as api_error:
                # If an API error occurs, use the agent_manager's handler to prompt the user.
                logger.warning(f"API error during remediation LLM call for {task_id}: {api_error}")
                self.progress_callback({"message": f"API Error. Waiting for API key update..."})
                error_type_str = "AuthenticationError" if isinstance(api_error, AuthenticationError) else "RateLimitError"
                resolved = await self.agent_manager.handle_api_error_and_reinitialize(error_type_str, str(api_error))
                if resolved:
                    # If the user provided a new key or chose to retry, continue the loop.
                    self.progress_callback({"message": f"API key updated/confirmed. Retrying..."})
                    continue
                else:
                    logger.error(f"User cancelled API key update during remediation for {task_id}.")
                    raise InterruptedError(f"User cancelled API key update.") from api_error
            except requests.exceptions.RequestException as net_error:
                logger.error(f"Network error during remediation LLM call for {task_id}: {net_error}")
                # If a network error occurs, use the UI callback to ask the user if they want to retry.
                if self._request_network_retry_cb:
                    self.progress_callback({"message": f"Network error. Waiting for user to retry..."})
                    should_retry_network = await self._request_network_retry_cb(f"Agent ({self.agent_manager.model_id})", str(net_error))
                    if should_retry_network:
                        self.progress_callback({"message": f"Retrying network call..."})
                        await asyncio.sleep(2)
                        continue
                    else:
                        logger.error(f"User chose not to retry network error during remediation for {task_id}.")
                        raise InterruptedError(f"Network error and user chose not to retry.") from net_error
                else:
                    logger.error(f"No network retry callback available. Raising error.")
                    # If no callback is configured, we have no choice but to fail.
                    raise
    
    def _parse_multi_file_mcp_response(self, case_output: str) -> Dict[str, str]:
        """
        Parses an LLM response that may contain multiple <file_content> tags into a dictionary.

        Args:
            case_output: The raw string output from the Case LLM.

        Returns:
            A dictionary mapping file paths to their new content.
        """
        if not case_output:
            logger.warning("Parsing LLM response: Input is empty.")
            return {}

        # Use the robust regex-based utility to extract file contents.
        # This function is designed to ignore conversational text and markdown.
        # It's a crucial guardrail against messy or conversational LLM outputs.
        try:
            updates = extract_file_contents_from_llm_output(case_output)
            if updates:
                logger.info(f"Successfully parsed {len(updates)} file(s) from LLM output.")

            # Also check for a command tag, for FixCommandTask
            command_match = re.search(r"<command><!\[CDATA\[(.*?)\]\]></command>", case_output, re.DOTALL)
            if command_match:
                updates['command'] = command_match.group(1).strip()
                logger.info("Successfully parsed <command> tag from LLM output.")
            return updates
        except Exception as e:
            logger.error(f"An unexpected error occurred during LLM response parsing: {e}", exc_info=True)
            return {}

    def _normalize_text_for_diff(self, text: str) -> str:
            """
            A robust function to normalize text content before diffing.
            This is a crucial step to prevent meaningless diffs caused by
            inconsistent line endings or trailing whitespace.
            Handles line endings, strips trailing whitespace from each line,
            and replaces non-breaking spaces.
            """
            if not isinstance(text, str):
                return ""
            # Replace non-breaking spaces with regular spaces
            text = text.replace('\u00a0', ' ')
            # Normalize all line endings to '\n' and split
            lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
            # Strip trailing whitespace from each line
            normalized_lines = [line.rstrip() for line in lines]
            # Join back together, ensuring a single trailing newline for POSIX compliance
            return "\n".join(normalized_lines)
    
    def _build_remediation_prompt(self, task: AnyRemediationTask) -> str:
        """
        Builds a targeted, multi-file prompt for the LLM based on the remediation task.

        This method assembles all necessary context—the error log, the contents of
        all relevant files, and a high-level instruction—into a single, comprehensive
        prompt for the code-generation agent (Case).
        """
        # --- NEW: Special handling for ImportError to guide the LLM better ---
        if task.original_error.error_type == "ImportError":
            import_error_match = re.search(r"cannot import name '(.+?)' from '(.+?)'", task.original_error.message)
            if import_error_match:
                missing_name = import_error_match.group(1)
                source_module = import_error_match.group(2)
                importer_file = task.original_error.file_path

                # Convert module path (e.g., 'calculator.admin') to file path
                source_file_path = source_module.replace('.', '/') + ".py"

                # Override the task's files_to_fix to focus on the source of the import
                task.files_to_fix = [source_file_path]
                logger.info(f"ImportError detected. Overriding files_to_fix to target the source: {source_file_path}")

                # Create a more targeted high-level instruction
                task.description = (
                    f"An `ImportError` occurred in `{importer_file}` because it tried to import `{missing_name}` from `{source_module}`, but `{missing_name}` is not defined or exported in `{source_file_path}`. "
                    f"Your task is to MODIFY the file `{source_file_path}` to correctly define and export `{missing_name}`."
                )

        # This logic handles multi-file tasks like FixLogicTask and FixBundleTask,
        # which are common for complex errors.

        # --- Multi-file prompt generation for FixLogicTask and FixBundleTask ---
        files_to_fix = getattr(task, 'files_to_fix', [task.original_error.file_path])
        high_level_instruction = getattr(task, 'description', task.original_error.message)
        full_error_context = task.original_error.message

        # Build the context block with all file contents
        file_context_block = ""
        for file_path in files_to_fix:
            file_context_block += f"\n--- START OF FILE: {file_path} ---\n"
            try:
                content = self.file_system_manager.read_file(file_path)
                file_context_block += content
            except FileNotFoundError:
                file_context_block += "[File does not exist or is not yet created]"
            except Exception as e:
                file_context_block += f"[Error reading file: {e}]"
            file_context_block += f"\n--- END OF FILE: {file_path} ---\n"

    # Build the final prompt
        prompt = f"""You are an expert AI software engineer. Your task is to fix a bug based on the provided error log and file contents.

**High-level Instruction:**
{high_level_instruction}

**Full Error Log:**
---
{full_error_context}
---

**Relevant File Contents:**
{file_context_block}

**CRITICAL INSTRUCTIONS:**
1. Analyze the error log and all provided file contents to understand the root cause.
2. Your response MUST contain the complete, corrected content for ALL of the following files: {', '.join(files_to_fix)}.
3. Each file's content MUST be wrapped in its own `<file_content path="path/to/file.ext"><![CDATA[...]]></file_content>` tag.
4. Do NOT output anything else besides the `<file_content>` tags. No explanations, no commentary, no markdown. Your response should only contain the file content tags.
"""

        return prompt.strip()


    def _verify_fix(self, original_command: str) -> CommandOutput:
        """
        Verifies the fix by running the provided command(s) and returns the complete output.
        Handles chained commands (e.g., using '&&') by splitting and running them sequentially.

        This is the crucial "is it fixed yet?" step. It re-runs the original command that
        failed to see if the LLM's proposed changes actually solved the problem.
        """
        if not original_command:
            logger.warning("Cannot verify fix: No command provided.")
            return CommandOutput(stdout="", stderr="No command provided for verification.", exit_code=1)

        # Split command string by '&&' to handle chained commands safely without using shell=True
        commands_to_run = [cmd.strip() for cmd in original_command.split('&&') if cmd.strip()]
        
        final_result = CommandOutput(command=original_command, stdout="", stderr="", exit_code=0)

        logger.info(f"Verifying fix by running command(s): {commands_to_run}")

        for i, cmd in enumerate(commands_to_run):
            logger.info(f"Executing verification step {i+1}/{len(commands_to_run)}: `{cmd}`")
            # Use the secure command executor to run the verification step.
            result = self.command_executor.run_command(cmd)
            
            # Aggregate stdout and stderr from each command in the chain
            if result.stdout:
                final_result.stdout += f"--- Output from '{cmd}' ---\n{result.stdout}\n"
            if result.stderr:
                final_result.stderr += f"--- Errors from '{cmd}' ---\n{result.stderr}\n"

            if result.exit_code != 0:
                # If any command in the chain fails, the entire verification fails.
                logger.error(f"Verification command '{cmd}' failed with exit code {result.exit_code}. Halting chain.")
                final_result.exit_code = result.exit_code # Set the final exit code to the first failure
                return final_result # Stop on first failure

        logger.info(f"All verification commands in the chain executed successfully.")
        return final_result

    async def _process_single_task(self, task: AnyRemediationTask) -> Tuple[bool, Dict[str, Path], Optional[str]]:
        """
        Processes a single remediation task, including its retry loop for LLM interaction and fix application.

        This is the core execution unit for one item in the remediation plan. It involves:
        1. Building the prompt for the LLM.
        2. Calling the LLM and handling retries.
        3. Parsing the LLM's response (the proposed code fix).
        4. Applying the fix to the file system atomically.

        Args:
            task: The remediation task to process.

        Returns:
            A tuple containing:
            - bool: True if the task was successfully completed, False otherwise.
            - Dict[str, Path]: A dictionary of backup paths created for this task.
            - Optional[str]: The new command if the task was a FixCommandTask, otherwise None.
        """
        MAX_ATTEMPTS = 3  # This could be a class constant
        feedback_for_llm = ""  # Initialize feedback for the retry loop
        all_backup_paths_for_task: Dict[str, Path] = {}
        corrected_command_from_task: Optional[str] = None
        
        # The inner loop for a single task, allowing multiple attempts to get a valid fix from the LLM.
        for attempt in range(1, MAX_ATTEMPTS + 1):
            logger.info(f"Executing remediation task: {type(task).__name__} (Attempt {attempt}/{MAX_ATTEMPTS})")
            self.metrics_tracker.log_remediation_event({
                'event_type': 'remediation_attempt_started',
                'task_type': task.type,
                'file_path': task.original_error.file_path,
                'attempt_number': attempt
            })

            prompt = ""

            # If a previous attempt failed, add the failure reason to the prompt for the next attempt.
            if feedback_for_llm:
                prompt += f"\n\nATTENTION: The previous attempt failed with the following error. Please analyze this feedback and provide a corrected response.\nPREVIOUS ATTEMPT FAILED: {feedback_for_llm}\n"
                feedback_for_llm = ""  # Clear feedback after using it

            is_file_path_missing = not task.original_error.file_path or task.original_error.file_path == "Unknown"

            if isinstance(task, FixCommandTask) and is_file_path_missing:
                # Handle the simpler case of fixing a command string.
                # This logic remains for simple command fixes, but most work will now be file-based.
                prompt += f"""Task: Correct an invalid command.
Offending Command: {task.original_error.command}
Error Message: {task.original_error.message}
Your output MUST be ONLY the corrected command string, wrapped in a single <command><![CDATA[...]]></command> XML tag."""
            else:
                # This is the main path for all file-based fixes (logic, syntax, etc.).
                # This now handles FixLogicTask, FixBundleTask, CreateFileTask, and FixSyntaxTask
                logger.info(f"Building multi-file prompt for task type: {type(task).__name__}")
                prompt += self._build_remediation_prompt(task)

            if not prompt:
                logger.error("Could not build a prompt for this task. Skipping attempt.")
                continue

            logger.debug(f"Remediation prompt for LLM:\n{prompt}")
            logger.info("Requesting code correction from LLM...")

            # Get the appropriate system prompt for the remediation agent.
            case_system_prompt_message = self.prompts.system_case_remediation
            if not case_system_prompt_message:
                logger.error("Remediation system prompt not found in configuration. Aborting task.")
                return False, {}

            messages = [case_system_prompt_message, {"role": "user", "content": prompt}]

            try:
                # Call the LLM with our robust error-handling wrapper.
                response_message = await self._call_llm_with_error_handling("Case", messages, f"remediation_{task.type}", 0.1)
                suggested_fix = response_message.get('content', '')
            except InterruptedError as e:
                logger.warning(f"Remediation cancelled by user during LLM call: {e}")
                return False, all_backup_paths_for_task, None

            logger.debug(f"LLM suggested raw output:\n{suggested_fix}")
            
            # Parse the LLM's response to extract file paths and their new content.
            parsed_updates = self._parse_multi_file_mcp_response(suggested_fix)

            if not parsed_updates:
                logger.warning("Could not parse any <file_content> tags from LLM response. Skipping this attempt.")
                feedback_for_llm = "Your response was empty or did not contain any valid `<file_content>` XML tags. Please provide the complete, corrected content for all requested files, each in its own tag."
                continue

            task_successful_this_attempt = False
            try:
                if isinstance(task, FixCommandTask):
                    # Handle the case where the LLM suggested a corrected command.
                    corrected_command = parsed_updates.get('command')
                    if not corrected_command:
                        feedback_for_llm = "Your response for FixCommandTask did not contain a valid <command> tag. Please provide the corrected command."
                        continue

                    # The fix for a command task IS to run the corrected command.
                    logger.info(f"Attempting to run corrected command: `{corrected_command}`")
                    # Use the existing _verify_fix method as a generic command runner.
                    command_result = self._verify_fix(corrected_command)
                    if command_result.exit_code == 0:
                        task_successful_this_attempt = True
                        corrected_command_from_task = corrected_command # Pass it back for final verification
                        logger.info(f"Corrected command '{corrected_command}' executed successfully during remediation task.")
                    else:
                        task_successful_this_attempt = False
                        feedback_for_llm = f"The corrected command '{corrected_command}' also failed. Stderr: {command_result.stderr}"
                        logger.error(f"Corrected command '{corrected_command}' also failed. Stderr: {command_result.stderr}")

                else:
                    # This is the main logic path for tasks that modify files.
                    # --- This is the logic for file-based tasks (FixLogic, FixSyntax, etc.) ---
                    
                    # --- FIX: Normalize path separators for robust comparison ---
                    def normalize_path_set(paths: list[str]) -> set[str]:
                        return {str(Path(p)).replace('\\', '/') for p in paths if p}

                    requested_files_set = normalize_path_set(getattr(task, 'files_to_fix', [task.original_error.file_path]))
                    returned_files_set = normalize_path_set([k for k in parsed_updates.keys() if k != 'command'])

                    # A critical guardrail: ensure the LLM returned exactly the files we asked for.
                    if requested_files_set != returned_files_set:
                        missing_files = requested_files_set - returned_files_set
                        extra_files = returned_files_set - requested_files_set
                        feedback_for_llm = f"Response is incomplete or incorrect. Missing files: {missing_files or 'None'}. Unexpected files: {extra_files or 'None'}. You MUST provide content for all and only these files: {requested_files_set}."
                        logger.error(f"LLM response did not match requested files. {feedback_for_llm}")
                        continue

                    # Another guardrail: check for basic syntax errors before writing to disk.
                    # Validate syntax for all returned Python files
                    syntax_error_feedback = ""
                    for file_path, code in parsed_updates.items():
                        if file_path.endswith(".py"):
                            try:
                                import ast
                                ast.parse(code)
                            except SyntaxError as e:
                                syntax_error_feedback += f"File '{file_path}' has a syntax error: {e}. "
                    if syntax_error_feedback:
                        feedback_for_llm = f"Generated code has syntax errors. Please fix them. Details: {syntax_error_feedback}"
                        logger.error(feedback_for_llm)
                        continue

                    # If all checks pass, apply the changes to the file system atomically.
                    # If all validation passes, apply the file updates
                    try:
                        success, _, backup_paths = self.file_system_manager.apply_atomic_file_updates(parsed_updates)
                        if success:
                            if backup_paths: all_backup_paths_for_task.update(backup_paths)
                            logger.info(f"Successfully applied atomic changes to {len(parsed_updates)} files.")
                            task_successful_this_attempt = True
                        else:
                            logger.warning(f"Failed to apply atomic changes.")
                    except Exception as apply_e:
                        logger.error(f"Error applying atomic changes: {apply_e}", exc_info=True)
                        self.file_system_manager.rollback_from_backup(all_backup_paths_for_task)

            except Exception as e:
                logger.error(f"Error applying atomic changes: {e}", exc_info=True)
                self.file_system_manager.rollback_from_backup(all_backup_paths_for_task)

            if task_successful_this_attempt:
                # If the task succeeded, log it and return.
                self.metrics_tracker.log_remediation_event({'event_type': 'remediation_task_success', 'task_type': task.type, 'file_path': task.original_error.file_path, 'llm_model_used': self.agent_manager.model_id, 'attempts': attempt})
                return True, all_backup_paths_for_task, corrected_command_from_task
            else:
                logger.warning(f"Attempt {attempt} failed for task {type(task).__name__}.")
                self.metrics_tracker.log_remediation_event({'event_type': 'remediation_task_failure', 'task_type': task.type, 'file_path': task.original_error.file_path, 'llm_model_used': self.agent_manager.model_id, 'attempts': attempt, 'final_failure': False})
                if attempt < MAX_ATTEMPTS:
                    import time
                    time.sleep(1)

        # If all attempts for this single task fail, return False.
        return False, all_backup_paths_for_task, None

    async def remediate(self, command: str, initial_error_records: List[ErrorRecord], project_state: ProjectState) -> bool:
            """
            Orchestrates an iterative remediation process. It repeatedly analyzes errors,
            applies fixes, and verifies them until the command succeeds, no progress is made,
            or the maximum number of cycles is reached.

            This is the main public method of the manager. It controls the high-level
            remediation loop, deciding whether to continue to another cycle or to give up
            and roll back changes.
            """
            logger.info("Starting remediation cycle.")
            MAX_CYCLES = 5  # This could be moved to config
            current_errors = list(initial_error_records)
            all_backup_paths_for_session: Dict[str, Path] = {}
            
            for cycle in range(1, MAX_CYCLES + 1):
                logger.info(f"--- Starting Remediation Cycle {cycle}/{MAX_CYCLES} ---")
                self.progress_callback({"message": f"Starting remediation cycle {cycle}/{MAX_CYCLES}..."})

                # Perform one full cycle: plan -> execute -> verify.
                status, new_errors, cycle_backups = await self._perform_one_remediation_cycle(
                    command, current_errors, project_state
                )
                
                # Aggregate all backups made during this session
                if cycle_backups:
                    all_backup_paths_for_session.update(cycle_backups)
    
                if status == RemediationCycleStatus.SUCCESS:
                    # If the fix is successful, clean up the backups and return True.
                    logger.info("SUCCESS: Remediation successful! Command passed verification.")
                    self.file_system_manager.cleanup_backups(all_backup_paths_for_session)
                    return True
                
                if status == RemediationCycleStatus.PROGRESS_MADE:
                    # If progress was made but the issue isn't fully fixed,
                    # update the errors and continue to the next cycle.
                    logger.info("PROGRESS_MADE: Remediation cycle made progress. Continuing to next cycle with new errors.")
                    current_errors = new_errors
                    # The backups from this cycle are kept, as we are keeping the changes.
                    continue  # To the next iteration of the for loop
                    
                if status == RemediationCycleStatus.NO_PROGRESS:
                    # If the agent is stuck (producing the same errors), stop and roll back.
                    logger.error("NO PROGRESS: Remediation cycle made no progress. Halting and rolling back session.")
                    self.file_system_manager.rollback_from_backup(all_backup_paths_for_session)
                    return False # Stop the entire remediation process
                    
                if status in [RemediationCycleStatus.PLAN_FAILED, RemediationCycleStatus.EXECUTION_FAILED]:
                    # If planning or execution fails, stop and roll back.
                    logger.error(f"FAILED: Remediation cycle failed ({status.value}). Halting and rolling back session.")
                    self.file_system_manager.rollback_from_backup(all_backup_paths_for_session)
                    return False

            # If loop finishes without success
            logger.error(f"Remediation failed to converge after {MAX_CYCLES} cycles. Rolling back all changes from this session.")
            self.file_system_manager.rollback_from_backup(all_backup_paths_for_session)
            return False

    async def _perform_one_remediation_cycle(
        self, command: str, error_records: List[ErrorRecord], project_state: ProjectState
    ) -> Tuple[RemediationCycleStatus, List[ErrorRecord], Dict[str, Path]]:
        """
        Performs a single cycle of remediation: plan, execute, verify.

        This method does not perform rollbacks on its own, but returns the status
        and backup paths for the main `remediate` method to handle. This keeps the
        state management (rollback vs. commit) at the highest level.
        """

        logger.info("Performing a single remediation cycle.")
        if not error_records:
            logger.error("Cannot perform remediation cycle: No structured error records were provided.")
            return RemediationCycleStatus.PLAN_FAILED, error_records, {}

        try:
            remediation_plan = self.remediation_planner.create_plan(error_records, project_state)
        except Exception as e:
            # If the planner itself throws an error, we can't proceed.
            logger.error(f"Error creating remediation plan: {e}", exc_info=True)
            return RemediationCycleStatus.PLAN_FAILED, error_records, {}

        if not remediation_plan:
            logger.info("No remediation plan could be created for the current errors.")
            return RemediationCycleStatus.PLAN_FAILED, error_records, {} # Pass original errors back

        all_tasks_successful = True
        all_backup_paths_for_cycle: Dict[str, Path] = {}
        corrected_command_from_cycle: Optional[str] = None # Track if a command was corrected in this cycle
        
        # Execute each task in the generated plan.
        # --- Main loop over each task in the generated plan ---
        for task in remediation_plan:
            if not hasattr(task, 'original_error') or not task.original_error:
                logger.error(f"Task {type(task).__name__} is missing an original_error. Skipping.")
                continue
            is_file_path_missing = not task.original_error.file_path or task.original_error.file_path == "Unknown"

            # A file path is required for any task *except* a FixCommandTask.
            if is_file_path_missing and not isinstance(task, FixCommandTask):
                logger.critical(f"Error record for task {type(task).__name__} is malformed (file_path is required but is '{task.original_error.file_path}'). Skipping.")
                all_tasks_successful = False
                continue

            # Add these lines as a safeguard
            if not hasattr(task, 'type') or not task.type:
                logger.error(f"FATAL: Remediation task of type {task.__class__.__name__} was created without a 'type' attribute. Aborting remediation.")
                return False

            # Check if the remediation action is allowed by the user's configuration.
            task_type_key = f"allow_{task.type.replace('Task', '').lower()}"

            if self.remediation_config.get(task_type_key, False):
                print(f"✅ Safety check passed. Proceeding with {task.type}.")
            else:
                print(f"❌ Safety check failed. Remediation for {task.type} is disabled by config. Aborting.")
                all_tasks_successful = False
                break # A disabled task means the plan cannot be completed.
            
            # Process the single task. It now returns the corrected command if applicable.
            task_successful, backup_paths, corrected_command = await self._process_single_task(task)

            if backup_paths:
                all_backup_paths_for_cycle.update(backup_paths)

            # If the task was to fix the command, update the command we'll use for verification.
            if corrected_command:
                corrected_command_from_cycle = corrected_command # Store the corrected command

            if not task_successful:
                all_tasks_successful = False
                logger.error(f"All attempts failed for task: {type(task).__name__}. Halting plan execution for this cycle.")
                break # This breaks the `for task in remediation_plan:` loop

        if not all_tasks_successful:
            # If any task in the plan failed, the entire cycle fails.
            # If a task failed, the orchestrator will roll back this cycle's changes.
            return RemediationCycleStatus.EXECUTION_FAILED, error_records, all_backup_paths_for_cycle

        # --- NEW, MORE ROBUST VERIFICATION LOGIC ---
        if corrected_command_from_cycle and all_tasks_successful:
            # A command was corrected. Instead of re-running the command,
            # use the original task's test_step for verification.
            # This avoids idempotency issues with commands like `startapp`.
            original_task = error_records[0].triggering_task if error_records and hasattr(error_records[0], 'triggering_task') else None
            if original_task and original_task.test_step:
                # --- FIX: More robustly find the changed argument and substitute it in the test step ---
                verification_command = original_task.test_step
                try:
                    import shlex
                    original_parts = shlex.split(error_records[0].command)
                    corrected_parts = shlex.split(corrected_command_from_cycle)

                    old_arg_to_replace = None
                    new_arg_for_replacement = None

                    # Find the first differing argument between the two commands
                    if len(original_parts) == len(corrected_parts):
                        for orig_part, corrected_part in zip(original_parts, corrected_parts):
                            if orig_part != corrected_part:
                                old_arg_to_replace = orig_part
                                new_arg_for_replacement = corrected_part
                                break
                    
                    if old_arg_to_replace and new_arg_for_replacement:
                        # Perform the replacement in the test step string
                        verification_command = original_task.test_step.replace(old_arg_to_replace, new_arg_for_replacement)
                        logger.info(f"Adapting test step. Original: '{original_task.test_step}'. New: '{verification_command}'")
                    else:
                        logger.warning("Could not determine differing argument to adapt test step. Using original test step.")

                except Exception as e:
                    logger.error(f"Error adapting test step for corrected command: {e}. Using original test step.")
                    verification_command = original_task.test_step
                # --- END FIX ---

                logger.info(f"FixCommandTask succeeded. Verifying with adapted test step: `{verification_command}`")
                verification_result = self._verify_fix(verification_command)
            else:
                # Fallback if no test step is available, assume success.
                logger.warning("FixCommandTask succeeded, but no original test_step found to verify. Assuming success.")
                return RemediationCycleStatus.SUCCESS, [], all_backup_paths_for_cycle
        else:
            # --- Verification for other task types (e.g., FixLogic, FixSyntax) ---
            # If no command was corrected, we must re-run the original command to see if the fix worked.
            logger.info(f"All planned tasks for this cycle were executed. Performing verification with original command: `{command}`")
            verification_result = self._verify_fix(command)

        
        if verification_result.exit_code == 0:
            # Success! The original command now passes.
            # The command now succeeds.
            return RemediationCycleStatus.SUCCESS, [], all_backup_paths_for_cycle
        else:
            # The command still fails. Analyze the new errors to see if we made progress.
            # --- SMART PROGRESS CHECK ---
            logger.warning("Verification command failed. Analyzing results to check for progress...")
            new_error_records, new_test_summary = self.error_analyzer.analyze_logs(
                verification_result.command,
                verification_result.stdout,
                verification_result.stderr,
                verification_result.exit_code
            )
            
            # Create a "signature" of the errors to compare before and after the fix.
            def get_error_signature(records: List[ErrorRecord]) -> set:
                # Using the summary is a good balance. Full message can be too noisy with line numbers.
                return {e.summary for e in records if e.summary}

            old_error_signatures = get_error_signature(error_records)
            new_error_signatures = get_error_signature(new_error_records)

            # Check if at least one of the original errors has been resolved.
            # --- NEW, MORE INTELLIGENT PROGRESS CHECK ---
            # Progress is made if at least one of the original errors is now gone.
            # We are willing to accept new errors appearing as long as we are fixing the old ones.
            original_errors_resolved = not (old_error_signatures <= new_error_signatures)

            count_before = len(old_error_signatures)
            count_after = len(new_error_signatures)

            logger.info(f"Remediation impact analysis: Errors before: {count_before}, Errors after: {count_after}. Original errors resolved: {original_errors_resolved}")

            if original_errors_resolved:
                # If we made progress, return the new set of errors for the next cycle.
                logger.info(f"PROGRESS DETECTED: At least one original error was resolved. Continuing remediation with {count_after} new error(s).")
                return RemediationCycleStatus.PROGRESS_MADE, new_error_records, all_backup_paths_for_cycle
            else:
                # If no original errors were fixed, we're stuck or made things worse.
                # Check if the error signatures are identical. If so, the agent is stuck.
                if old_error_signatures == new_error_signatures:
                    logger.error("NO PROGRESS: The exact same errors were produced after the fix. The agent is stuck.")
                # Check if the error count increased.
                elif count_after > count_before:
                    logger.error(f"REGRESSION DETECTED: Error count increased from {count_before} to {count_after}.")
                else: # count_after == count_before but signatures are different
                    logger.error(f"NO IMPROVEMENT: The number of errors ({count_after}) did not decrease.")
                return RemediationCycleStatus.NO_PROGRESS, error_records, all_backup_paths_for_cycle