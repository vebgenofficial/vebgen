# backend/src/core/adaptive_agent.py
import json
import logging
from json_repair import repair_json
import re
from datetime import datetime
import asyncio
import textwrap
from pathlib import Path
from typing import Any, Callable, Optional, Dict, List,Tuple
from typing import Awaitable
import shlex
import ast
from .agent_manager import AgentManager
from .file_system_manager import FileSystemManager
from .command_executor import CommandExecutor
from .memory_manager import MemoryManager
from .code_intelligence_service import CodeIntelligenceService
from .project_models import ProjectState, FeatureTask, CommandOutput
from .context_manager import ContextManager
from .secure_storage import retrieve_credential, store_credential
from .security_utils import sanitize_and_validate_input
from .exceptions import InterruptedError
from .adaptive_prompts import (
    TARS_FEATURE_BREAKDOWN_PROMPT,
    CASE_FRONTEND_STANDARDS,
    TARS_VERIFICATION_PROMPT,
    CASE_NEXT_STEP_PROMPT,
    TARS_CHECKPOINT_PROMPT,
    CONTENT_AVAILABILITY_INSTRUCTIONS,
)

# Type Hints for UI Callbacks
from .validators.frontend_validator import FrontendValidator
ShowInputPromptCallable = Callable[[str, bool, Optional[str]], Optional[str]]
ShowFilePickerCallable = Callable[[str], Optional[str]]

RequestCommandExecutionCallable = Callable[[str, str, str], Awaitable[Tuple[bool, str]]]

class TarsPlanner:
    """
    The TARS agent, responsible for high-level planning and quality assurance.
    TARS acts as the "senior architect," breaking down user requests into features
    and later verifying the work done by the CASE agent.
    """

    def __init__(self, agent_manager: AgentManager, tech_stack: str):
        self.logger = logging.getLogger(__name__)
        self.agent_manager = agent_manager
        self.tech_stack = tech_stack
    def break_down_feature(self, user_request: str) -> List[str]:
        """Breaks down a high-level user request into a list of smaller, actionable features."""
        self.logger.info(f"TARS: Breaking down user request: '{user_request[:100]}...'")
        prompt = TARS_FEATURE_BREAKDOWN_PROMPT.format(
            user_request=user_request, tech_stack=self.tech_stack
        )
        system_prompt = {
            "role": "system",
            "content": "You are TARS, a senior project planner. Your task is to break down a user request into a list of actionable development features.",
        }
        user_prompt = {"role": "user", "content": prompt}

        response = self.agent_manager.invoke_agent(system_prompt, [user_prompt], 0.1)
        features_text = response.get("content", "")

        # The LLM is prompted to return a list of features, one per line.
        features = [ # type: ignore
            line.strip()
            for line in features_text.split("\n")
            if line.strip() and not line.startswith("#")
        ]
        self.logger.info(f"TARS: Identified {len(features)} sub-features.")
        return features

    def verify_feature_completion(
        self, feature_description: str, work_log: List[str], project_structure: str
    ) -> Tuple[int, List[str]]:
        """
        Verifies if a feature was completed successfully by reviewing the work log
        and the modified code.

        Returns:
            A tuple containing the completion percentage (0-100) and a list of
            any identified issues or suggestions for remediation.
        """
        self.logger.info(
            f"TARS: Verifying completion of feature: '{feature_description}'"
        )
        prompt = TARS_VERIFICATION_PROMPT.format(
            feature_description=feature_description,
            work_log="\n".join(work_log),
            code_written=project_structure, # This contains the full content of all modified files.
        )
        system_prompt = {
            "role": "system",
            "content": "You are TARS, an automated quality assurance investigator. Your job is to analyze the work done by a developer agent (CASE) to determine if a feature has been successfully implemented and to what degree. Your response MUST be in JSON format.",
        }
        user_prompt = {"role": "user", "content": prompt}

        response = self.agent_manager.invoke_agent(system_prompt, [user_prompt], 0.1)
        verification_result_raw = response.get("content", "").strip()

        try:
            data = None
            try:
                # First, try standard parsing with leniency for control characters.
                data = json.loads(verification_result_raw, strict=False)
            except json.JSONDecodeError:
                # If that fails, try to find a JSON block inside markdown fences.
                json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", verification_result_raw, re.DOTALL)
                json_str_to_parse = json_match.group(1) if json_match else verification_result_raw
                
                self.logger.warning("TARS verification JSON decode failed, attempting repair.")
                try:
                    # Repair the JSON string.
                    repaired_json = repair_json(json_str_to_parse)
                    data = json.loads(repaired_json)
                    self.logger.info("✅ Successfully repaired malformed TARS verification JSON")
                except Exception as repair_error:
                    self.logger.error(f"TARS JSON repair also failed: {repair_error}")
                    raise
            if not data:
                raise json.JSONDecodeError("Could not parse or repair JSON from TARS response.", verification_result_raw, 0)
            completion = data.get("completion_percentage", 0)
            issues = data.get("issues", ["Verification agent returned invalid data."])
            self.logger.info(f"TARS Verification: {completion}% complete. Issues: {issues if issues else 'None'}")
            return completion, issues
        except json.JSONDecodeError as e:
            self.logger.error(f"TARS verification response was not valid JSON: {verification_result_raw}", exc_info=True)
            return 0, [f"The verification agent returned a malformed (non-JSON) response: {verification_result_raw}. Error: {e}"]


class AdaptiveAgent:
    """
    The CASE agent, responsible for the hands-on work of implementing features.
    CASE operates in a step-by-step loop, deciding on and executing a single
    action at a time (e.g., writing a file, running a command) until the
    feature is complete or it requires guidance.
    """

    # A list of common configuration files that are often targets for patching.
    # The "Smart Auto-Fetch" logic uses this to proactively load these files into context.
    KNOWN_PATCH_TARGETS: List[str] = [
        'settings.py',
        'urls.py',
        'wsgi.py',
        'asgi.py'
    ]
    def __init__(
        self,
        agent_manager: AgentManager,
        tech_stack: str,
        framework_rules: str, # New parameter for framework-specific rules
        project_state: ProjectState,
        file_system_manager: FileSystemManager,
        command_executor: CommandExecutor,
        memory_manager: MemoryManager,
        code_intelligence_service: CodeIntelligenceService,
        show_input_prompt_cb: ShowInputPromptCallable,
        progress_callback: Callable[[Dict[str, Any]], None],
        show_file_picker_cb: ShowFilePickerCallable,
        stop_event: asyncio.Event, # NEW: Pass the stop event
        request_command_execution_cb: Optional[RequestCommandExecutionCallable] = None
    ):
        self.logger = logging.getLogger(__name__)
        self.agent_manager = agent_manager
        self.tech_stack = tech_stack
        self.framework_rules = framework_rules
        self.project_state = project_state
        self.file_system_manager = file_system_manager
        self.command_executor = command_executor
        self.memory_manager = memory_manager
        self.code_intelligence_service = code_intelligence_service
        self.show_input_prompt_cb = show_input_prompt_cb
        self.progress_callback = progress_callback
        self.show_file_picker_cb = show_file_picker_cb
        self.stop_event = stop_event # NEW: Store the stop event
        self.request_command_execution_cb = request_command_execution_cb
        # Give the agent manager a reference to the stop event so it can interrupt long-running API calls.
        self.agent_manager.stop_event = self.stop_event

        # The ContextManager is responsible for assembling the prompt context for the LLM.
        self.context_manager = ContextManager(
            agent_manager=self.agent_manager,
            project_state=self.project_state,
            tech_stack=self.tech_stack,
            framework_rules=self.framework_rules,
            get_project_structure_callback=self.file_system_manager.get_directory_structure_markdown
        )
        self.work_history: List[str] = []
        # Tracks detailed information about failed actions to detect repetitive failure patterns.
        self.action_failures: List[Dict[str, Any]] = []
        # --- NEW: Track patch failures per file to escalate to WRITE_FILE ---
        from collections import defaultdict
        self.patch_failures: Dict[str, int] = defaultdict(int)



    async def execute_feature(self, feature_description: str, correction_instructions: Optional[str] = None) -> tuple[list[str], list[str]]:
        """
        Develops a feature by iteratively deciding on and executing actions.

        This is the main entry point for the agent's execution loop. It includes
        a "Smart Auto-Fetch" pre-execution step that preloads common configuration
        files into context if the feature description suggests they might be
        needed, improving efficiency.

        Args:
            feature_description: The description of the feature to implement.
            correction_instructions: Optional instructions from TARS to correct previous work.

        Returns:
            A tuple containing (list of modified file paths, work history log).
        """
        # Smart Auto-Fetch: If the feature seems to involve configuration, preload common config files.
        if self._feature_needs_configuration(feature_description):
            self.logger.info("Feature seems to require configuration changes. Preloading common config files...")
            await self._preload_config_files()

        return await self._execute_feature_steps(feature_description, correction_instructions)

    async def _execute_feature_steps(
        self, feature_description: str, correction_instructions: Optional[str] = None
    ) -> tuple[list[str], list[str]]:
        """
        The core step-by-step execution loop for developing a feature.

        Args:
            feature_description: The description of the feature to implement.
            correction_instructions: Optional instructions from TARS to correct previous work.

        Returns:
            A tuple containing (list of modified file paths, work history log).
        """
        self.context_manager.work_history = [] # Reset history in the context manager
        self.context_manager.content_availability = {} # Reset content availability at the start of a new feature
        self.context_manager.clear_requested_full_content() # Clear any full content from previous runs.
        recent_action_signatures_for_cycle_detection: List[str] = [] # Reset cycle detection history
        self.patch_failures.clear() # Reset patch failure counts for the new feature

        # This set tracks all files modified during this execution run, including
        # files that were only inspected via GET_FULL_FILE_CONTENT. This is crucial
        # for providing complete context to the TARS verification agent.
        modified_files: set[str] = set()

        # Holds a snapshot of the project state before an action is executed.
        # This allows the ROLLBACK action to revert to a known good state.
        last_known_good_snapshot: Dict[str, Any] = {}
        rollback_count = 0

        # State for the "Circuit Breaker" mechanism to prevent infinite loops.
        consecutive_error_count = 0
        last_error_action_signature = ""

        max_steps = 15  # Safety break

        for step_num in range(max_steps):
            # At the start of each step, check if the user has requested to stop.
            if self.stop_event.is_set():
                self.logger.info("CASE agent received stop signal. Halting feature execution.")
                raise InterruptedError("Workflow stopped by user.")

            self.logger.info(
                f"CASE Agent: Step {step_num + 1}/{max_steps} for feature '{feature_description[:50]}...'"
            )
            # Create a snapshot at the start of the loop. This captures the state
            # that a subsequent ROLLBACK action will revert to.
            last_known_good_snapshot = await self.file_system_manager.create_snapshot()

            framework_rules_str, code_context_str, work_history_str, content_availability_note = await self.context_manager.get_context_for_prompt()

            prompt_content = CASE_NEXT_STEP_PROMPT.format(
                frontend_development_standards=CASE_FRONTEND_STANDARDS,
                feature_description=feature_description,
                tech_stack=self.tech_stack,
                content_availability_instructions=CONTENT_AVAILABILITY_INSTRUCTIONS,
                content_availability_note=content_availability_note, # Pass the note to the prompt
                framework_specific_rules=framework_rules_str,
                work_history=work_history_str,
                code_context=code_context_str, # Includes project structure, summaries, and full file content.
                correction_instructions=correction_instructions
                or "No corrections needed.",
            )
            correction_instructions = None  # Consume correction instructions after using them once

            system_prompt = {
                "role": "system",
                "content": "You are an autonomous software developer, CASE. Your task is to decide and execute the single next best action to complete the given feature, considering the project context and your past actions.",
            }
            user_prompt = {"role": "user", "content": prompt_content}

            response_cm = await asyncio.to_thread(self.agent_manager.invoke_agent,
                system_prompt, [user_prompt], 0.1
            )
            response_text = response_cm["content"]
            action_json = self._parse_json_response(response_text)

            if not action_json:
                self.logger.warning(f"Could not parse LLM response: {response_text[:200]}")
                
                # Try to diagnose the specific JSON issue for better feedback.
                if '\\n' in response_text and '\\\\n' not in response_text:
                    correction_instructions = (
                        "Your previous response had UNESCAPED NEWLINES in the JSON. "
                        "Remember: inside JSON strings, newlines must be \\\\n (double backslash + n), not \\n. "
                        "Example: \"patch\": \"<<<<<<< SEARCH\\\\ncode\\\\n=======\" "
                        "Please try again with properly escaped newlines."
                    )
                else:
                    correction_instructions = (
                        "Your previous response was not valid JSON and could not be parsed. "
                        "You MUST respond with a single, valid JSON object containing 'thought', 'action', and 'parameters'. "
                        "Ensure all string content within the JSON is properly escaped (use \\\\n for newlines, \\\" for quotes)."
                    )
                continue
            
            if not action_json.get("action"):
                self.logger.warning("LLM response missing required 'action' field")
                self.context_manager.add_work_history("System: Failed to decide next step (missing 'action'). Retrying.")
                correction_instructions = "Your JSON was parsed successfully but is missing the required 'action' field. Please include it."
                continue

            action = action_json.get("action")

            parameters = action_json.get("parameters", {})
            # Before executing, perform a pre-emptive validation of the action and its parameters.
            is_valid, validation_error = self._validate_action(action, parameters)
            if not is_valid:
                self.logger.error(f"Action validation failed: {validation_error}. Re-prompting agent.")
                # Feed the validation error back to the agent as a correction instruction.
                correction_instructions = f"Your last action was invalid and was not executed. Reason: {validation_error}. Please choose a valid action."
                continue

            thought = action_json.get("thought", "No thought provided.")
            self.progress_callback({"agent_name": "CASE", "agent_message": f"Thought: {thought}\nAction: {action}\nParameters: {parameters}"})
            self.context_manager.add_work_history(f"Thought: {thought}")

            if action == "TARS_CHECKPOINT":
                self.logger.info("CASE agent is requesting a checkpoint from TARS.")
                reason = parameters.get("reason", "No reason provided.")
                self.context_manager.add_work_history(f"Action: {action}, Reason: {reason}")

                # Ask TARS for guidance
                checkpoint_prompt = TARS_CHECKPOINT_PROMPT.format(
                    feature_description=feature_description,
                    work_log="\n".join(self.context_manager.work_history),
                    checkpoint_reason=reason
                )
                system_prompt = {"role": "system", "content": "You are TARS, a senior project architect providing real-time guidance."}
                user_prompt = {"role": "user", "content": checkpoint_prompt}

                # Use the agent's own manager to invoke the TARS persona
                response = self.agent_manager.invoke_agent(system_prompt, [user_prompt], 0.2)
                guidance = response.get("content", "TARS provided no guidance. Continue with your best judgment.").strip()

                self.logger.info(f"TARS Checkpoint Guidance Received: {guidance}")
                self.progress_callback({"agent_name": "TARS", "agent_message": f"Checkpoint Guidance:\n{guidance}"})
                correction_instructions = guidance # Inject TARS's guidance as the new correction instructions
                continue # Continue to the next loop iteration to re-evaluate with the new guidance

            if action == "GET_FULL_FILE_CONTENT":
                filepath = parameters['file_path']
                
                # Security validation
                if not self.validate_file_access(filepath):
                    raise ValueError(f"Access denied to file: {filepath}")
                
                try:
                    # Read file content
                    raw_content = await asyncio.to_thread(
                        self.file_system_manager.read_file, filepath
                    )
                    
                    lines = raw_content.splitlines() # Still useful for getting line count
                    formatted_content = textwrap.dedent(f"""
                    ## FULL CONTENT: {filepath} ({len(lines)} lines)
                    
                    {raw_content}
                    """).strip()
                    
                    # Set the full content in the context manager for the next turn
                    self.context_manager.set_requested_full_content(formatted_content)
                    self.context_manager.add_work_history(f"Action: {action}, Parameters: {{'file_path': '{filepath}'}}. Full content retrieved and will be available in the next step.")
                    # Mark the file as having its full content loaded in the context manager's status map.
                    # Also, add the inspected file to the set of modified files for this run.
                    # This is crucial so TARS can verify the content of files that were only inspected, not changed.
                    modified_files.add(filepath)
                    self.context_manager.mark_full_content_loaded(filepath, "Agent requested full content")
                    self.logger.info(f"Content for '{filepath}' fetched. Re-evaluating next action immediately.")
                    correction_instructions = "You have just fetched the full content for a file. Now, decide your next action based on this new information."
                except (FileNotFoundError, Exception) as e:
                    error_msg = f"Failed to read full content of {filepath}: {e}"
                    self.logger.error(error_msg)
                    raise RuntimeError(error_msg) from e
                continue # Skip to the next loop iteration to re-prompt with the new context. The snapshot is NOT updated.

            # Circuit Breaker: Stuck Detection Logic
            # Create a unique signature for the current action to detect loops.
            # For file operations, the path is the most important part. For commands, the command itself.
            current_action_signature = action
            if "file_path" in parameters:
                current_action_signature += f":{parameters['file_path']}"
            elif "command" in parameters:
                current_action_signature += f":{parameters['command']}"

            # Check for repetitive action cycles (e.g., WRITE -> ROLLBACK -> WRITE)
            # This logic detects A -> B -> A patterns, which indicate a stuck loop.
            if len(recent_action_signatures_for_cycle_detection) > 1 and current_action_signature == recent_action_signatures_for_cycle_detection[-2] and current_action_signature != recent_action_signatures_for_cycle_detection[-1]:
                self.logger.critical(f"Circuit Breaker: Repetitive action cycle detected: {recent_action_signatures_for_cycle_detection[-2:] + [current_action_signature]}. Escalating failure.")
                # ✅ FIX: Add loop detection note to work history
                loop_detection_note = (
                    f"⚠️ LOOP DETECTED: Action pattern {' -> '.join(recent_action_signatures_for_cycle_detection[-2:] + [current_action_signature])} "
                    f"indicates repetitive cycle. Completed {len(modified_files)} file(s) before detection: {list(modified_files)[:3]}. "
                    f"Stopping feature execution to preserve progress."
                )
                self.context_manager.add_work_history(loop_detection_note)
                
                # ✅ FIX: Exit loop gracefully instead of raising error
                self.logger.warning(
                    f"Breaking out of step loop gracefully. "
                    f"Returning partial progress: {len(modified_files)} modified file(s)."
                )
                break  # Exit the while loop, return what we've completed

            # Add the signature to history *before* handling rollback to ensure the
            # list is up-to-date for the next iteration's cycle check.
            recent_action_signatures_for_cycle_detection.append(current_action_signature)
            if len(recent_action_signatures_for_cycle_detection) > 3: recent_action_signatures_for_cycle_detection.pop(0) # Keep only the last 3
 
            if action == "ROLLBACK":
                rollback_count += 1
                rollback_reason = parameters.get("reason", "No reason provided.")
                # The rollback count check is handled by the agent itself, not just in tests.
                # This ensures robust behavior in production.
                # The test `test_escalation_on_three_rollbacks` will correctly test this behavior. 
                # The `test_circuit_breaker_repetitive_action_cycle` will now pass because the cycle 
                # is detected *before* this check is reached for the third time. 
                self.logger.info(f"Rollback action initiated. Total rollbacks for this feature: {rollback_count}.")
                if rollback_count >= 3:
                    self.logger.critical(f"Escalation: Feature has been rolled back {rollback_count} times. Aborting.")
                    raise RuntimeError(f"Feature failed after {rollback_count} rollbacks, indicating a persistent strategic error.")

                self.logger.warning("CASE agent initiated a ROLLBACK action.")
                if not last_known_good_snapshot:
                    self.context_manager.add_work_history(f"Action: {action}, Result: FAILED. No previous state snapshot was available.")
                else:
                    await self.file_system_manager.write_snapshot(last_known_good_snapshot) # type: ignore
                    self.context_manager.add_work_history(f"Action: {action}, Reason: {rollback_reason}, Result: Project state has been reverted to the state before the previous action.")
                    self.logger.info("Rollback complete. Proceeding to the next step with the restored state.")
                # Inject the reason for the rollback as a correction for the next step
                correction_instructions = f"You just performed a rollback for the following reason: '{rollback_reason}'. Re-evaluate your strategy to avoid repeating this mistake."
                continue # Continue to the next loop iteration to re-evaluate from the restored state

            if action == "FINISH_FEATURE":
                # --- NEW: Comprehensive Frontend Validation before Finishing ---
                self.logger.info("Running comprehensive frontend validation before finishing feature...")
                validator = FrontendValidator(self.project_state.project_structure_map)
                report = validator.validate()
                critical_issues = [issue for issue in report.issues if issue.severity in ["critical", "high"]]

                if critical_issues:
                    self.logger.warning(f"FINISH_FEATURE blocked. Found {len(critical_issues)} critical/high severity frontend issues.")
                    # Format issues for the correction prompt
                    issue_summary = "\n".join([f"- {issue.file_path}: {issue.message}" for issue in critical_issues[:5]])
                    correction_instructions = (
                        "CRITICAL: Your feature cannot be finished because frontend validation failed. "
                        "The following issues were found:\n"
                        f"{issue_summary}\n\n"
                        "Review the file content and apply the necessary fixes (e.g., add missing attributes, correct structure)."
                    )
                    recent_action_signatures_for_cycle_detection.clear()
                    continue # Re-prompt the agent with instructions to fix the issues

            if action == "FINISH_FEATURE":
                # Validation passed, feature is complete.
                self.logger.info("CASE agent decided feature is complete.")
                break

            try:
                step_result, modified_path = await self._execute_action(
                    action, parameters, modified_files
                )
                # Log action and result separately for clarity.
                if action == "REQUEST_USER_INPUT":
                    self.context_manager.add_work_history(f"Action: {action}, Parameters: {parameters}")
                    self.context_manager.add_work_history(step_result) # Log the "User provided input: ..." as a separate entry
                else:
                    self.context_manager.add_work_history(f"Action: {action}, Parameters: {parameters}, Result: {step_result}")
                # Reset the circuit breaker's consecutive error counter on a successful action.
                consecutive_error_count = 0
                last_error_action_signature = ""
                # Add a note to the project's permanent history log.
                target_param = parameters.get('file_path') or parameters.get('command')
                if isinstance(target_param, list):
                    target_param = ' '.join(target_param)
                await self._add_historical_note(f"Action: {action}, Target: {target_param}, Result: {step_result[:100]}...")
                if modified_path:
                    modified_files.add(modified_path)
                    self.context_manager.set_last_modified_file(modified_path)

                    # --- NEW: Immediate Frontend Validation on file change ---
                    if any(modified_path.endswith(ext) for ext in ['.html', '.css', '.js']):
                        self.logger.info(f"Frontend file '{modified_path}' modified. Running immediate validation...")
                        validator = FrontendValidator(self.project_state.project_structure_map)
                        report = validator.validate()
                        file_issues = [issue for issue in report.issues if issue.file_path == modified_path]
                        if file_issues:
                            issue_summary = "\n".join([f"- {issue.message} (Severity: {issue.severity})" for issue in file_issues])
                            self.context_manager.add_work_history(f"Validation issues found in {modified_path}:\n{issue_summary}")
                            # If critical issues are found, inject a correction for the next step
                            if any(issue.severity in ["critical", "high"] for issue in file_issues):
                                correction_instructions = f"CRITICAL: You just introduced validation errors in {modified_path}. Review the work history and fix them in your next action."
            except Exception as e:
                error_message = f"Error during action '{action}': {e}"
                # Circuit Breaker: Increment consecutive failure counter for the same action.
                if current_action_signature == last_error_action_signature:
                    consecutive_error_count += 1
                    self.logger.warning(f"Consecutive failure count for action '{current_action_signature}' is now {consecutive_error_count}.")
                else:
                    consecutive_error_count = 1
                    last_error_action_signature = current_action_signature
                    self.logger.info(f"New error detected for action '{current_action_signature}'. Resetting consecutive failure count to 1.")

                # --- FIX: The general circuit breaker should NOT trigger for PATCH_FILE failures,
                # as they have their own specific escalation logic. ---
                if consecutive_error_count >= 3 and action != "PATCH_FILE":
                    self.logger.critical(f"Circuit Breaker: Action '{current_action_signature}' has failed {consecutive_error_count} consecutive times. Escalating failure.")
                    raise RuntimeError(f"Action '{action}' failed {consecutive_error_count} times in a row. Aborting feature.")

                # --- NEW: Centralized Failure Recording and Escalation Logic ---
                failure_record = {
                    'action': action,
                    'parameters': parameters,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat(),
                    'context_type': self.context_manager.get_content_type_for_file(parameters.get('file_path'))
                }
                self.action_failures.append(failure_record)

                if action == "PATCH_FILE":
                    filepath = parameters.get('file_path')
                    if filepath:
                        self.patch_failures[filepath] += 1
                        if self.patch_failures[filepath] >= 3:
                            self.logger.warning(f"PATCH_FILE has failed {self.patch_failures[filepath]} times for '{filepath}'. Escalating to WRITE_FILE strategy.")
                            correction_instructions = (
                                f"CRITICAL: You have failed to PATCH the file '{filepath}' multiple times. "
                                "The patch is likely invalid or the context is wrong. "
                                "DO NOT try to PATCH this file again. Instead, you MUST now use the "
                                "WRITE_FILE action to overwrite the file with the complete, correct content. "
                                "First, use GET_FULL_FILE_CONTENT to ensure you have the latest version, then "
                                "construct the full file content with your intended changes and use WRITE_FILE."
                            )
                            self.patch_failures[filepath] = 0 # Reset counter after escalating

                self.logger.error(error_message, exc_info=True)
                self.context_manager.add_work_history(f"System: {error_message}")
        else:
            self.logger.warning(
                f"CASE agent reached max steps ({max_steps}) for feature. Finishing automatically."
            )

        # Add a summary of any failures to the final work log for TARS to review.
        if self.action_failures:
            failure_summary = "\n--- Summary of Failures Encountered ---\n"
            for failure in self.action_failures:
                failure_summary += f"- Action: {failure['action']}, Target: {failure['parameters'].get('file_path', 'N/A')}, Error: {failure['error'][:100]}...\n"
            self.context_manager.add_work_history(failure_summary)
        # Save the complete work log from this run to the feature object in the project state.
        if self.project_state and (feature := self.project_state.get_feature_by_id(self.project_state.current_feature_id)):
            feature.work_log.extend(self.context_manager.work_history)

        return list(modified_files), self.context_manager.work_history

    def _is_repeated_failure(self, new_failure: Dict[str, Any]) -> bool:
        """
        Checks if a similar failure (same action on the same file) has occurred recently.
        """
        # Look at the last 5 failures to see if a pattern is emerging.
        recent_failures = self.action_failures[-6:-1]
        
        # We only care about failures on specific files
        target_file = new_failure['parameters'].get('file_path')
        if not target_file:
            return False

        count = 0
        for old_failure in recent_failures:
            if (old_failure['action'] == new_failure['action'] and 
                old_failure['parameters'].get('file_path') == target_file):
                count += 1
        
        # If we've seen this same action/file failure at least once before in the recent history, it's a repeat.
        return count >= 1

    def validate_file_access(self, file_path: str) -> bool:
        """
        Performs a basic security check to ensure the agent is not trying to
        access sensitive or irrelevant files.
        """
        # This is a critical security boundary to prevent directory traversal attacks.
        if '..' in file_path or file_path.startswith('/'):
            self.logger.error(f"Security validation failed: Attempt to access an absolute or parent path '{file_path}'.")
            return False
        return True

    def _validate_action(self, action: Optional[str], parameters: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validates an action before execution to catch errors early.
        """
        if not action:
            return False, "No action specified."

        if action == "PATCH_FILE":
            return self._validate_patch_action(parameters)
        elif action == "WRITE_FILE":
            # Placeholder for future write action validation
            return True, None
        # Add other validations for WRITE_FILE, RUN_COMMAND etc. here if needed.
        return True, None

    def _validate_patch_action(self, parameters: dict) -> tuple[bool, Optional[str]]:
        """Validates the parameters and context for a PATCH_FILE action."""
        filepath = parameters.get('file_path')
        if not filepath:
            return False, "PATCH_FILE requires a 'file_path'."

        # 1. Check if the file exists before trying to patch it.
        if not self.file_system_manager.file_exists(filepath):
            return False, f"Cannot PATCH non-existent file: {filepath}. Use WRITE_FILE to create it first."

        # 2. Check if the agent has the full file content in its context.
        content_type = self.context_manager.get_content_type_for_file(filepath)
        if content_type != 'FULL_CONTENT':
            return False, f"Cannot PATCH {filepath} - only have {content_type}. Use GET_FULL_FILE_CONTENT first."

        return True, None


    def _feature_needs_configuration(self, feature_description: str) -> bool:
        """
        Heuristically determines if a feature is likely to involve changes to
        common configuration files.


        Returns:
            True if the feature description contains keywords suggesting configuration work.
        """
        config_keywords = ['install', 'setup', 'configure', 'add', 'app', 'middleware', 'database', 'url', 'route']
        return any(kw in feature_description.lower() for kw in config_keywords)

    def _find_project_files(self, filename: str) -> List[str]:
        """
        Finds all files within the project that match a specific filename.
        This is used to locate all instances of `settings.py`, `urls.py`, etc.
        """
        found_files: List[str] = []
        try:
            # Use rglob to recursively search the entire project directory
            for path in self.file_system_manager.project_root.rglob(filename):
                if path.is_file():
                    # CRITICAL: Skip virtual environment files!
                    # This check must be done on the Path object before converting to a string.
                    if 'venv' not in path.parts and 'site-packages' not in path.parts:
                        # Convert the absolute path to a relative path string for consistency
                        relative_path = str(path.relative_to(self.file_system_manager.project_root)).replace('\\', '/')
                        found_files.append(relative_path)
        except Exception as e:
            self.logger.error(f"Error finding project files for '{filename}': {e}")

        self.logger.debug(f"Found files for '{filename}': {found_files}")
        return found_files

    async def _preload_config_files(self):
        """
        Finds and preloads the full content of common configuration files
        into the agent's context for the upcoming execution loop.
        """
        for target_filename in self.KNOWN_PATCH_TARGETS:
            # Find all files in the project matching the target name (e.g., 'settings.py')
            files_to_load = self._find_project_files(target_filename)

            # To avoid excessive context, skip preloading if we find too many files with the same name.
            if len(files_to_load) > 5:
                self.logger.warning(f"Found {len(files_to_load)} files matching '{target_filename}'. Skipping preload to avoid excessive context.")
                continue

            for filepath in files_to_load:
                try:
                    # Check if the content is already loaded to avoid redundant work
                    if self.context_manager.get_content_type_for_file(filepath) == 'FULL_CONTENT':
                        self.logger.debug(f"Skipping preload for '{filepath}', content is already loaded.")
                        continue
                    
                    self.logger.info(f"Preloading content for '{filepath}'...")
                    # Load files directly into the context manager.
                    await asyncio.to_thread(
                        self.file_system_manager.read_file, filepath
                    )
                    self.context_manager.mark_full_content_loaded(filepath, "Preloaded for context")
                    self.context_manager.add_work_history(f"System: Preloaded configuration file '{filepath}' for context.")
                except Exception as e:
                    self.logger.warning(f"Could not preload configuration file '{filepath}': {e}")

    async def _execute_action(
        self, action: str, params: dict, modified_files_set: set[str]
    ) -> tuple[str, str | None]:
        """Executes a single action decided by the LLM."""
        modified_path = None
        # --- NEW: Create a snapshot before file operations for rollback consistency ---
        # This snapshot is used for the diff view in the UI after a successful patch.
        last_known_good_snapshot = await self.file_system_manager.create_snapshot()
        self.logger.debug("Created pre-action snapshot for potential rollback.")

        if action == "WRITE_FILE":
            file_path: str = params["file_path"]
            content: str = params["content"]

            # Perform security validation *before* replacing placeholders to catch hardcoded secrets.
            is_safe, reason = self._perform_security_validation(content, file_path)
            if not is_safe:
                self.logger.error(f"Security validation failed for WRITE_FILE on '{file_path}': {reason}")
                if self.project_state:
                    self.project_state.security_feedback_history.append({
                        "action": "WRITE_FILE",
                        "reason": reason or "Unknown",
                    })
                # --- END BUG FIX #8 ---
                raise ValueError(f"Security validation failed: {reason}")

            processed_content = await self._handle_placeholders_in_code(content)

            self.file_system_manager.write_file(file_path, processed_content)
            # After writing the file, update our understanding of the project state.
            if file_path.endswith("models.py"):
                await self._update_defined_models_from_content(file_path, processed_content)
            elif "settings.py" in file_path: # type: ignore
                await self._update_registered_apps_from_content(file_path, processed_content)
            await self._update_project_structure_map(file_path, processed_content) # This was the missing await
            modified_path = file_path
            return f"Successfully wrote to file {file_path}", modified_path
        elif action == "PATCH_FILE":
            file_path = params["file_path"]
            patch_content = params["patch"]

            # Security validation for patches is a heuristic that checks the patch content itself.
            is_safe, reason = self._perform_security_validation(patch_content, file_path)
            if not is_safe:
                self.logger.error(f"Security validation failed for PATCH_FILE on '{file_path}': {reason}")
                if self.project_state:
                    self.project_state.security_feedback_history.append({
                        "action": "PATCH_FILE",
                        "reason": reason or "Unknown",
                    })
                # --- END BUG FIX #8 ---
                raise ValueError(f"Security validation failed: {reason}")

            patch_result = await asyncio.to_thread(
                self.file_system_manager.apply_patch, file_path, patch_content
            )

            # --- FIX: Send diff data to UI, whether from strict or fuzzy patch ---
            # If patch_result is None, it means a strict patch was successful but didn't return data.
            # We construct the diff data manually. If it's a dict, it came from a successful fuzzy patch.
            if patch_result and isinstance(patch_result, dict):
                diff_data = patch_result
                self.logger.info(f"Received diff data from successful fuzzy patch for '{file_path}'.")
            else:
                # This path is taken for successful strict patches which don't return data.
                self.logger.info(f"Constructing diff data manually for successful strict patch on '{file_path}'.")
                diff_data = {
                    'filepath': file_path,
                    'original_content': self.file_system_manager.read_file(file_path, from_snapshot=last_known_good_snapshot),
                    'modified_content': self.file_system_manager.read_file(file_path)
                }

            if diff_data:
                self.progress_callback({'display_code_diff': True, **diff_data})

            # After patching, update our understanding of the project state.
            if "settings.py" in file_path:
                updated_content = self.file_system_manager.read_file(file_path)
                await self._update_registered_apps_from_content(file_path, updated_content) # type: ignore
            updated_content = self.file_system_manager.read_file(file_path)
            await self._update_project_structure_map(file_path, updated_content)
            modified_path = file_path
            return f"Successfully patched file {file_path}", modified_path
        elif action == "GET_FULL_FILE_CONTENT":
            file_path = params["file_path"]
            # The actual file reading and context update is handled in the main loop.
            modified_path = file_path
            return f"Successfully inspected file {file_path} and loaded its full content into context.", modified_path
        elif action == "REQUEST_USER_INPUT":
            prompt_to_user = params.get("prompt", "The agent has a question for you.")
            self.logger.info(f"Agent is requesting user input: {prompt_to_user}")
            user_response = await asyncio.to_thread(
                self.show_input_prompt_cb,
                "Agent Needs Input",
                False, # is_password
                prompt_to_user
            )
            if user_response is None:
                raise InterruptedError("User cancelled the input prompt.")
            
            return f"User provided input: '{user_response}'", None
        elif action == "RUN_COMMAND":
            # Handle structured commands that separate the command from its arguments.
            command_base = params.get("command")
            command_args = params.get("args", [])

            if not command_base:
                raise ValueError("RUN_COMMAND action is missing the required 'command' parameter.")

            # Construct the full command string from the base and arguments
            if command_args:
                full_command_str = command_base + " " + " ".join(map(shlex.quote, command_args))
            else:
                full_command_str = command_base
            processed_command = await self._handle_placeholders_in_code(full_command_str)

            # To detect new files created by commands (e.g., `manage.py startapp`),
            # we get a snapshot of the file system before and after execution.
            excluded_dirs = {"venv", ".venv", "node_modules", ".git", "__pycache__", ".vebgen"}
            
            def get_project_files():
                files = set()
                for p in self.file_system_manager.project_root.rglob("*"):
                    if p.is_file() and not any(part in excluded_dirs for part in p.parts):
                        files.add(p.relative_to(self.file_system_manager.project_root).as_posix())
                return files

            files_before = get_project_files()

            command_to_run: str
            if isinstance(processed_command, list):
                self.logger.warning(f"Received command as a list, safely joining to string: {processed_command}")
                command_to_run = shlex.join(processed_command)
            else:
                command_to_run = str(processed_command)

            # Use the UI callback for command execution if available, otherwise execute directly.
            if self.request_command_execution_cb:
                success, output_json = await self.request_command_execution_cb(
                    f"agent_step_{self.project_state.current_feature_id or 'setup'}", # A unique-ish ID
                    command_to_run,
                    f"Agent action: {command_to_run}"
                )
                try:
                    result_data = json.loads(output_json, strict=False)
                except json.JSONDecodeError:
                    self.logger.warning("Command output JSON malformed, attempting repair...")
                    repaired = repair_json(output_json)
                    result_data = json.loads(repaired, strict=False)

                # The result_data from the UI only contains command_str, stdout, stderr, exit_code.
                # The CommandOutput model requires a 'command' field. # type: ignore
                result_data['command'] = result_data.get('command_str', command_to_run)
                result = CommandOutput(**result_data) # Now this will pass validation
            else:
                # Fallback to direct execution if no UI callback is provided
                self.logger.warning("Executing command directly without UI interaction (request_command_execution_cb not set).")
                result = await asyncio.to_thread(self.command_executor.run_command, command_to_run)

            if result['exit_code'] != 0:
                error_summary = (
                    result['stderr'] or result['stdout'] or "Command failed with no output."
                )
                raise RuntimeError(
                    f"Command '{processed_command}' failed with exit code {result['exit_code']}. Error: {error_summary}"
                )

            files_after = get_project_files()
            newly_found_files = list(files_after - files_before)

            # --- BUG FIX: Add all new files to the set and return only the last one as the "primary" modification ---
            if newly_found_files:
                self.logger.info(f"Detected {len(newly_found_files)} new file(s) after RUN_COMMAND. Analyzing...")
                for file_path_str in newly_found_files:
                    # Batch file analysis and save state once after the loop.
                    # We update the checksum here, and the state is saved after
                    modified_files_set.add(file_path_str) # Add to the main set
                    # all new files have been processed.
                    if self.project_state:
                        file_hash = self.file_system_manager.get_file_hash(file_path_str)
                        if file_hash:
                            self.project_state.file_checksums[file_path_str] = file_hash
                            self.logger.debug(f"Updated checksum for new file: {file_path_str}")
                    # --- END BUG FIX #11 --- # type: ignore
                    content = self.file_system_manager.read_file(file_path_str)
                    self.logger.info(f"New file found: {file_path_str}. Analyzing...")
                    await self._update_project_structure_map(file_path_str, content)
                
                if newly_found_files:
                    modified_path = newly_found_files[-1] # Set last modified to the last new file found

            return f"Command executed successfully. Output: {result['stdout']}", modified_path
        else:
            raise ValueError(f"Unknown action: {action}")

    def _parse_json_response(self, response_text: str) -> dict | None:
        """Safely parses a JSON string from the LLM's response."""
        json_str = response_text
        try:
            # First, look for a JSON object enclosed in markdown code fences.
            match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL
            )
            if match:
                json_str = match.group(1).strip()
                self.logger.debug("Found JSON object inside markdown code fence.")
            else:
                # If no fence is found, assume the whole response might be the JSON object.
                self.logger.debug("No markdown fence found. Attempting to parse entire response as JSON.")
                json_str = response_text.strip()

            # Sometimes the LLM returns a string like `"thought": "...", "action": "..."}`
            # This adds the missing opening brace if it's detected.
            if json_str.strip().startswith('"') and not json_str.strip().startswith('{'):
                self.logger.warning("Malformed JSON detected (missing opening brace). Attempting to fix.")
                json_str = "{" + json_str
            
            # First, try standard parsing, which is faster.
            return json.loads(json_str, strict=False)
        except json.JSONDecodeError as e:
            self.logger.warning(f"Standard JSON parsing failed: {e}. Attempting to repair.")
            try:
                repaired_json_str = repair_json(response_text) # Use original response_text for repair
                self.logger.info("✅ Successfully repaired malformed JSON.")
                return json.loads(repaired_json_str)
            except Exception as repair_error:
                self.logger.error(f"Could not decode or repair JSON from response: {response_text}", exc_info=True)
                return None

    def _perform_security_validation(self, code_content: str, file_path: str) -> tuple[bool, str | None]:
        """
        Performs basic security checks on the generated code content.
        Returns (is_safe, reason_if_not_safe).
        """
        # 1. Check for eval() usage (most dangerous)
        if re.search(r'\beval\s*\(', code_content):
            return False, "Potential security risk: Use of eval() detected. Use safer alternatives like `json.loads` for data parsing."

        # 2. Check for hardcoded secrets (heuristic)
        # Looks for common secret key names assigned to long string literals.
        secret_pattern = re.compile(r"(SECRET_KEY|API_KEY|PASSWORD|TOKEN)\s*=\s*['\"][\w\d\-.@!#%^&*()+=]{20,}", re.IGNORECASE)
        if secret_pattern.search(code_content):
            return False, "Potential security risk: Hardcoded secret detected. Use placeholder variables like `{{ SECRET_KEY }}` instead."

        # 3. Check for Raw SQL (Django specific)
        if self.tech_stack == 'django':
            # Matches .raw("SELECT ...") or .extra(select=...)
            raw_sql_pattern = re.compile(r"\.(raw|extra)\s*\(") # type: ignore
            if raw_sql_pattern.search(code_content):
                return False, "Potential SQL injection risk: Use of raw SQL detected. Use the Django ORM instead."

        # 4. Check for XSS vulnerabilities (Django template specific)
        if file_path.endswith((".html", ".djt")):
            # Matches `{{ variable|safe }}` or `{{ variable|safe }}`
            xss_pattern = re.compile(r"\{\{\s*.*?\|safe\s*\}\}", re.IGNORECASE) # type: ignore
            if xss_pattern.search(code_content):
                # This is a heuristic. Sometimes `|safe` is necessary, but it's risky.
                # We flag it to make the agent reconsider if it's truly needed.
                return False, "Potential XSS risk: Use of the '|safe' filter detected in template. Ensure user-generated content is properly escaped."

        self.logger.debug(f"Security validation passed for '{file_path}'.")
        return True, None




    async def _update_project_structure_map(self, file_path_str: str, content: Optional[str] = None):
        """Updates the project_structure_map in ProjectState after a file is modified."""
        if not self.project_state or not self.code_intelligence_service:
            self.logger.warning("Cannot update structure map: ProjectState or CodeIntelligenceService not available.")
            return

        try:
            content = self.file_system_manager.read_file(file_path_str)
            if content is None: # type: ignore
                self.logger.warning(f"Cannot update structure map: File content for '{file_path_str}' is empty or could not be read.")
                return

            # Ensure the file's summary comment is extracted and stored in the project state.
            summary_comment = self.code_intelligence_service._extract_summary_from_code(content)
            if summary_comment:
                self.project_state.code_summaries[file_path_str] = summary_comment
            # Persist the newly extracted summary to disk.
            await asyncio.to_thread(
                self.memory_manager.save_project_state,
                self.project_state
            )
            parsed_file_info = self.code_intelligence_service.parse_file(file_path_str, content)

            if parsed_file_info:
                # Determine app_name based on the file's path relative to project_root
                relative_path_parts = Path(file_path_str).parts
                file_name = Path(file_path_str).name

                if len(relative_path_parts) == 1:
                    # Project-root file (utils.py, manage.py, etc.)
                    self.project_state.project_structure_map.global_files[file_name] = parsed_file_info # type: ignore
                    self.logger.info(f"Updated structure map for global file '{file_name}'.")
                else:
                    # App-level file (integrations/utils.py)
                    app_name = relative_path_parts[0]
                    # Ensure app and file entries exist in the project_structure_map
                    if app_name not in self.project_state.project_structure_map.apps: # type: ignore
                        from .project_models import AppStructureInfo
                        self.project_state.project_structure_map.apps[app_name] = AppStructureInfo() # type: ignore
                    self.project_state.project_structure_map.apps[app_name].files[file_name] = parsed_file_info # type: ignore
                    self.logger.info(f"Updated project structure map for app '{app_name}', file '{file_name}'.")
                
                # Persist the newly parsed file information to disk.
                await asyncio.to_thread(
                    self.memory_manager.save_project_state,
                    self.project_state
                )
                file_hash = self.file_system_manager.get_file_hash(file_path_str)
                if file_hash:
                    self.project_state.file_checksums[file_path_str] = file_hash
                await asyncio.to_thread(
                    self.memory_manager.save_project_state,
                    self.project_state
                )
        except Exception as e:
            self.logger.error(f"Error updating project structure map for {file_path_str}: {e}", exc_info=True)

    async def _handle_placeholders_in_code(self, code: str) -> str:
        """Finds and replaces placeholders like `{{ API_KEY }}` in code."""
        if not self.project_state:
            self.logger.warning("Cannot handle placeholders: Project state not loaded.")
            return code

        placeholder_regex = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")
        processed_code = code
        placeholders_found = list(placeholder_regex.finditer(code))

        if not placeholders_found:
            return code

        resolved_values: Dict[str, str] = {}

        for match in placeholders_found:
            full_match = match.group(0)
            placeholder_name = match.group(1)

            if placeholder_name in resolved_values:
                continue

            self.logger.debug(f"Processing placeholder: {full_match}")
            stored_value: Optional[str] = None
            is_secret = "KEY" in placeholder_name or "SECRET" in placeholder_name or "TOKEN" in placeholder_name

            if is_secret:
                stored_value = retrieve_credential(placeholder_name)
            elif placeholder_name in self.project_state.placeholders:
                stored_value = self.project_state.placeholders[placeholder_name]

            if stored_value is None:
                self.logger.warning(f"Placeholder {full_match} value not found. Prompting user.")
                try:
                    # Use the UI callback to prompt the user for the missing value
                    user_input = await asyncio.to_thread(
                        self.show_input_prompt_cb,
                        f"Input required for: {placeholder_name}",
                        is_secret,
                        f"Enter the value for {placeholder_name}",
                    )
                    if user_input is None:
                        raise InterruptedError(f"User cancelled input for {placeholder_name}")

                    # Sanitize and validate the user's input as a security measure.
                    stored_value = sanitize_and_validate_input(user_input)

                    if is_secret:
                        store_credential(placeholder_name, stored_value)
                    else:
                        self.project_state.placeholders[placeholder_name] = stored_value
                        self.memory_manager.save_project_state(self.project_state)

                except Exception as e:
                    self.logger.error(f"Failed to get value for required placeholder {full_match}: {e}")
                    raise ValueError(f"Failed to resolve placeholder {full_match}") from e

            resolved_values[placeholder_name] = stored_value

        for name, value in resolved_values.items():
            processed_code = re.sub(r"\{\{\s*" + re.escape(name) + r"\s*\}\}", value, processed_code)

        return processed_code

    def _extract_django_models(self, file_content: str) -> List[str]:
        """
        Extracts only Django model class names from models.py content by checking
        for inheritance from 'models.Model'.
        """
        try:
            tree = ast.parse(file_content)
            model_names = []
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Check if class inherits from models.Model
                    for base in node.bases:
                        # Handle: class Post(models.Model)
                        if isinstance(base, ast.Attribute):
                            if base.attr == 'Model' and isinstance(base.value, ast.Name):
                                # This is a heuristic; a more robust check would verify `base.value.id` is an alias for `django.db.models`
                                model_names.append(node.name)
                                break
                        # Handle: from django.db.models import Model; class Post(Model)
                        elif isinstance(base, ast.Name) and base.id == 'Model':
                            model_names.append(node.name)
                            break
            
            return model_names
        except Exception as e:
            self.logger.warning(f"Failed to parse models for state tracking: {e}")
            return []

    async def _add_historical_note(self, note: str):
        """Adds a note to the historical log and saves the project state."""
        if not self.project_state:
            self.logger.warning("Cannot add historical note: ProjectState is not initialized.")
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_note = f"[{timestamp}] {note}"
        
        self.project_state.historical_notes.append(full_note)
        
        # Save the state to persist the new note
        await asyncio.to_thread(
            self.memory_manager.save_project_state, self.project_state
        )
        self.logger.debug(f"Added historical note: {full_note}")
    async def _update_defined_models_from_content(self, file_path: str, content: str):
        """Parses models.py content and updates the project state with defined models."""
        app_name = Path(file_path).parent.name
        model_names = self._extract_django_models(content)
        if model_names:
            # Merge instead of overwrite to handle multiple models.py files in one app (rare but possible)
            if app_name in self.project_state.defined_models:
                existing_models = set(self.project_state.defined_models[app_name])
                new_models = [m for m in model_names if m not in existing_models]
                self.project_state.defined_models[app_name].extend(new_models)
            else:
                self.project_state.defined_models[app_name] = model_names
            for model_name in model_names:
                artifact_key = f"django_model:{app_name}.{model_name}"
                self.project_state.artifact_registry[artifact_key] = {
                    "type": "django_model",
                    "app": app_name,
                    "class_name": model_name,
                    "defined_in": file_path
                }
            self.logger.info(f"Artifact Registry: Updated with {len(model_names)} models from app '{app_name}'.")
            self.logger.info(f"State Tracking: Updated defined models for app '{app_name}': {self.project_state.defined_models[app_name]}")
            # Save the project state to persist the newly discovered models.
            await asyncio.to_thread(
                self.memory_manager.save_project_state,
                self.project_state
            )

    async def _update_registered_apps_from_content(self, file_path: str, content: str):
        """Parses settings.py content and updates the registered_apps set in the project state."""
        if "settings.py" not in file_path:
            return
        
        try:
            tree = ast.parse(content)
            self.project_state.registered_apps.clear() # Clear old apps first to handle removals
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'INSTALLED_APPS' for t in node.targets):
                    if isinstance(node.value, ast.List):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                app_full_str = elt.value
                                # Handle both 'blog' and 'blog.apps.BlogConfig' -> 'blog'
                                app_name = app_full_str.split('.')[0]
                                self.project_state.registered_apps.add(app_name)
                        self.logger.info(f"State Tracking: Updated registered apps from settings.py: {self.project_state.registered_apps}")
                        # Save the project state to persist the updated app list.
                        await asyncio.to_thread(
                            self.memory_manager.save_project_state,
                            self.project_state
                        )
                        return # Stop after finding the first INSTALLED_APPS list
        except Exception as e:
            self.logger.warning(f"Could not parse INSTALLED_APPS from {file_path} for state tracking: {e}")