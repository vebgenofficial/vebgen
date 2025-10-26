# backend/src/core/context_manager.py
import logging
from typing import List, Optional, Tuple, Dict, Any, Callable
import asyncio
from .project_models import ProjectState
from .agent_manager import AgentManager
import re
logger = logging.getLogger(__name__)




def build_and_prune_context(
    project_state: ProjectState,
    work_history: List[str],
    requested_full_content: Optional[str],
    last_modified_file: Optional[str],
    max_context_size: int = 25000,  # ✅ CHANGED FROM 8000
) -> Tuple[str, str]:
    """
    DEPRECATED. This logic is being integrated into the ContextManager class.
    Kept for reference during refactoring.

    Builds a context string for the LLM by gathering, scoring, and pruning various pieces of information.

    Args:
        project_state: The current state of the project.
        work_history: The agent's work history for the current feature.
        requested_full_content: Full content of a file explicitly requested by the agent.
        last_modified_file: The path of the file most recently modified.
        max_context_size: The maximum character count for the combined context.

    Returns:
        A tuple containing (pruned_code_context, pruned_work_history).
    """
    scored_context = []

    # 1. Score "Full File Content" (Highest Priority) - Type 'code'
    if requested_full_content:
        scored_context.append((100, requested_full_content, "code"))

    # 2. Score "Last Modified File Summary" (High Priority) - Type 'code'
    if last_modified_file and project_state.code_summaries:
        summary = project_state.code_summaries.get(last_modified_file)
        if summary:
            # Don't add if it's already part of the full requested content
            if not (requested_full_content and last_modified_file in requested_full_content):
                scored_context.append((90, f"--- Summary of Last Modified File: `{last_modified_file}` ---\n{summary}\n", "code"))

    # 3. Score "Other File Summaries" (Medium Priority) - Type 'code'
    if project_state.code_summaries:
        for path, summary in project_state.code_summaries.items():
            # Skip if it's the last modified file (already handled) or part of full content
            if path == last_modified_file or (requested_full_content and path in requested_full_content):
                continue
            scored_context.append((60, f"--- Summary of `{path}` ---\n{summary}\n", "code"))

    # 4. Score "Work History" (Recent is more important) - Type 'history'
    for i, entry in enumerate(reversed(work_history)):
        # Score recent entries higher
        score = 80 - (i * 5)
        if score < 40:
            score = 40
        scored_context.append((score, entry, "history"))

    # Sort context items by score (descending)
    scored_context.sort(key=lambda x: x[0], reverse=True)

    # Build the final context strings, respecting the max size
    current_size = 0
    final_code_context_parts: List[str] = []
    final_history_parts: List[str] = []

    # Iterate through the globally sorted context and build the strings
    for score, text, item_type in scored_context:
        if current_size + len(text) > max_context_size:
            logger.warning(f"Pruning context. Max size {max_context_size} reached. Skipping item with score {score}.")
            continue # Skip this item and try the next lower-priority one
        
        if item_type == "history":
            final_history_parts.insert(0, text)  # Insert at the beginning to maintain chronological order
        else:
            final_code_context_parts.append(text)
        
        current_size += len(text)

    code_context_str = "\n".join(final_code_context_parts) or "No code context available."
    work_history_str = "\n".join(final_history_parts) or "No work history yet."

    logger.info(f"Built context of size {current_size} characters.")

    return code_context_str, work_history_str

class ContextManager:
    """
    MAX_WORK_HISTORY_STEPS = 20  # Keep last 20 detailed steps

    Manages the context for the adaptive agent, including history summarization and caching.
    """
    def __init__(
        self,
        agent_manager: AgentManager,
        project_state: ProjectState,
        tech_stack: str,
        framework_rules: str,
        get_project_structure_callback: Callable[[], str],
        max_context_size: int = 25000,  # ✅ CHANGED FROM 8000
        history_summary_threshold: int = 5,
    ):
        self.agent_manager = agent_manager
        self.project_state = project_state
        self.tech_stack = tech_stack
        self.framework_rules = framework_rules
        self.get_project_structure = get_project_structure_callback
        self.max_context_size = max_context_size
        self.history_summary_threshold = history_summary_threshold

        self.MAX_WORK_HISTORY_STEPS = 20  # Keep last 20 detailed steps
        self.work_history: List[str] = []
        self.history_summary: Optional[str] = None
        self.last_modified_file: Optional[str] = None
        self.requested_full_content: Optional[str] = None
        self.content_availability: Dict[str, str] = {}

        # Cache for static parts of the context
        self.static_context_cache: Dict[str, str] = {
            "framework_rules": self.framework_rules,
            "project_structure": self.get_project_structure(),
        }

    def add_work_history(self, entry: str):
        """Adds a new entry to the work history."""
        """Add entry and auto-prune if needed"""
        self.work_history.append(entry)
        
        # Auto-prune if exceeds limit
        if len(self.work_history) > self.MAX_WORK_HISTORY_STEPS:
            self._prune_work_history()

    def set_last_modified_file(self, file_path: Optional[str]):
        """Updates the last modified file."""
        self.last_modified_file = file_path

    def set_requested_full_content(self, content: Optional[str]):
        """Sets the full content of a requested file for the next context build."""
        self.requested_full_content = content

    def clear_requested_full_content(self):
        """Clears the requested full content after it has been used."""
        self.requested_full_content = None

    def get_content_type_for_file(self, file_path: Optional[str]) -> Optional[str]:
        """Gets the availability status for a specific file."""
        if not file_path:
            return None
        return self.content_availability.get(file_path)

    def mark_full_content_loaded(self, file_path: str, reason: str):
        """Marks a file as having its full content loaded in the availability map."""
        if not file_path:
            return
        self.content_availability[file_path] = 'FULL_CONTENT'
        logger.debug(f"Marked '{file_path}' as FULL_CONTENT. Reason: {reason}")

    def _prune_work_history(self):
        """Smart pruning that keeps critical context while preserving chronological order."""
        keep_first = 3
        keep_last = 10
        history_len = len(self.work_history)

        # No need to prune if the history is already short.
        if history_len <= keep_first + keep_last:
            return

        indices_to_keep = set()

        # 1. Keep first `keep_first` indices.
        indices_to_keep.update(range(keep_first))

        # 2. Keep last `keep_last` indices.
        indices_to_keep.update(range(history_len - keep_last, history_len))

        # 3. Keep indices of failures.
        for i, s in enumerate(self.work_history):
            if any(keyword in s for keyword in ['Error', 'Failed', 'FAILED', 'Exception']):
                indices_to_keep.add(i)

        # 4. Build the new list preserving order.
        new_history = [step for i, step in enumerate(self.work_history) if i in indices_to_keep]

        if len(new_history) < history_len:
            self.work_history = new_history
            logger.info(f"Work history pruned to {len(new_history)} steps from {history_len}")



    async def _summarize_history(self):
        """Uses an LLM to summarize the current work history."""
        if not self.work_history:
            return

        logger.info("Summarizing work history to conserve tokens...")
        history_to_summarize = "\n".join(self.work_history)
        
        prompt = (
            "You are a summarization agent. Below is a log of actions taken by a developer agent. "
            "Create a concise, one-paragraph summary of the progress made. "
            "Focus on what has been achieved, not the step-by-step process.\n\n"
            f"Previous Summary (if any):\n{self.history_summary or 'None'}\n\n"
            f"New Actions to Summarize:\n{history_to_summarize}\n\n"
            "New Comprehensive Summary:"
        )

        system_prompt = {"role": "system", "content": "You are an expert summarization assistant."}
        user_prompt = {"role": "user", "content": prompt}
        
        try:
            response = await asyncio.to_thread(
                self.agent_manager.invoke_agent, system_prompt, [user_prompt], 0.1
            )
            self.history_summary = response.get("content", "Summary could not be generated.").strip()
            self.work_history = []  # Clear the detailed history after summarization
            logger.info(f"History summarized. New summary: {self.history_summary[:150]}...")
        except Exception as e:
            logger.error(f"Failed to summarize history: {e}")
            # Don't clear history if summarization fails

    async def get_context_for_prompt(self) -> Tuple[str, str, str, str]:
        """
        Assembles and prunes the context for the main agent prompt.
        This now acts as the "Shared Memory" component, gathering all relevant
        information (code summaries, history, project structure) into a single
        pruned block. This method now also intelligently summarizes history.
        """
        # --- FIX: Trigger history summarization if threshold is met ---
        if len(self.work_history) >= self.history_summary_threshold:
            await self._summarize_history()
        # --- END FIX ---


        # The history is now pruned automatically in `add_work_history`. No need for summarization logic here.

        # 2. Assemble all context pieces with scores and their type
        # This list represents the shared memory pool, where items are
        # prioritized based on relevance scores.
        all_scored_items = []

        # --- NEW: Add Explicit Project State to Context (Highest Priority) ---
        state_parts = ["**Project State (Verified Facts):**"]
        if self.project_state.registered_apps:
            state_parts.append(f"- Apps Registered: {sorted(list(self.project_state.registered_apps))}")
        if self.project_state.defined_models:
            models_str = "; ".join([f"{app}: {', '.join(models)}" for app, models in self.project_state.defined_models.items()])
            state_parts.append(f"- Models Defined: {models_str}")
        
        if len(state_parts) > 1:
            project_state_context = "\n".join(state_parts)
            # Give this factual state the highest priority after full content
            all_scored_items.append((98, project_state_context, "code"))
        # --- END NEW ---

        # --- REFACTORED LOGIC ---
        # 1. Prioritize full content first. Identify the file path from it.
        file_in_full_content_path = None
        if self.requested_full_content:
            all_scored_items.append((100, self.requested_full_content, "code"))
            file_in_full_content_path = self._extract_path_from_full_content(self.requested_full_content)
            if file_in_full_content_path:
                self.content_availability[file_in_full_content_path] = 'FULL_CONTENT'

        # 2. Add summaries, making sure to skip the file that already has full content.

        # High priority: Summary of the last modified file.
        if self.last_modified_file and self.project_state.code_summaries:
            summary = self.project_state.code_summaries.get(self.last_modified_file)
            # *** PROACTIVE BUG FIX: ***
            # Prevent adding the summary if it's for the same file we already have full content for.
            if summary and self.last_modified_file != file_in_full_content_path:
                all_scored_items.append((90, f"--- Summary of Last Modified File: `{self.last_modified_file}` ---\n{summary}\n", "code"))
                # Only mark as SUMMARY_ONLY if it's not already FULL_CONTENT
                if self.last_modified_file not in self.content_availability:
                    self.content_availability[self.last_modified_file] = 'SUMMARY_ONLY'

        # Medium priority: Other file summaries.
        if self.project_state.code_summaries:
            for path, summary in self.project_state.code_summaries.items():
                # This check now works correctly because file_in_full_content was determined earlier.
                if path != self.last_modified_file and path != file_in_full_content_path:
                    all_scored_items.append((60, f"--- Summary of `{path}` ---\n{summary}\n", "code"))
                    if path not in self.content_availability: # type: ignore
                        self.content_availability[path] = 'SUMMARY_ONLY'

        # --- History Context ---
        if self.history_summary:
            all_scored_items.append((85, f"Summary of work done so far:\n{self.history_summary}", "history"))
        if self.work_history:
            # Score recent history entries higher
            for i, entry in enumerate(reversed(self.work_history)):
                score = 80 - (i * 5)
                all_scored_items.append((max(score, 40), entry, "history"))
        # --- END REFACTORED LOGIC ---

        # Sort all context items by score (descending)
        all_scored_items.sort(key=lambda x: x[0], reverse=True)

        # Consume requested_full_content AFTER all scoring is complete
        self.clear_requested_full_content()

        # 3. Retrieve static parts from cache and add to context
        framework_rules = self.static_context_cache["framework_rules"]
        project_structure = self.static_context_cache["project_structure"]
 
        # 4. Initialize final context parts
        final_code_context_parts: List[str] = []
        final_history_parts: List[str] = []

        # Start with space available after framework rules
        remaining_space = self.max_context_size - len(framework_rules)
        print(f"[DEBUG] Initial remaining_space: {remaining_space}")

        # Always try to include project structure first, if it fits
        if len(project_structure) + 4 <= remaining_space: # +4 for separators
            final_code_context_parts.append(project_structure)
            remaining_space -= (len(project_structure) + 4)
            print(f"[DEBUG] After project_structure (len={len(project_structure)}), remaining_space: {remaining_space}")
        else:
            logger.warning("Project structure could not fit into context. This is highly unusual.")

        # Iterate through all scored items and add them if they fit
        for score, text, item_type in all_scored_items: # Iterate through sorted, high-priority items first
            print(f"[DEBUG] Considering item with score {score}, len {len(text)}")
            if len(text) + 4 <= remaining_space: # Use <= to be exact, +4 for separators
                if item_type == "code":
                    final_code_context_parts.append(text)
                elif item_type == "history":
                    final_history_parts.append(text)
                remaining_space -= (len(text) + 4)
                print(f"[DEBUG] Added item. Remaining space: {remaining_space}")
            else:
                print(f"[DEBUG] Pruned item.")
                logger.debug(f"Pruning item (score {score}, type {item_type}) due to context size limit. Remaining space: {remaining_space}")

        code_context = "\n\n".join(final_code_context_parts)
        
        # --- FINAL FIX: Build history context with correct headers ---
        history_parts_for_join = []
        summary_part = next((p for p in final_history_parts if p.startswith("Summary of work done so far")), None)
        if summary_part:
            history_parts_for_join.append(summary_part)
        
        detailed_entries = [p for p in final_history_parts if not p.startswith("Summary of work done so far")]
        # --- BUG FIX: Only add the "Recent actions" header if there are detailed entries ---
        if detailed_entries:
            # --- BUG FIX: Reverse the entries to be in correct chronological order ---
            detailed_entries.reverse()
            history_parts_for_join.append("Recent actions in this session:\n" + "\n".join(detailed_entries))
        history_context = "\n\n".join(p for p in history_parts_for_join if p)

        # --- Build Content Availability Note ---
        content_note_parts = ["Files available for this step:"]
        if self.content_availability:
            for filepath, content_type in sorted(self.content_availability.items()):
                icon = "📄 FULL" if content_type == 'FULL_CONTENT' else "📋 SUMMARY"
                content_note_parts.append(f"  - {icon}: {filepath}")
        content_availability_note = "\n".join(content_note_parts)

        # 5. Final Safeguard: Truncate if still too large (should be rare with this new logic)
        # --- BUG FIX: Account for separators in total length calculation ---
        total_len = len(framework_rules) + len(code_context) + len(history_context)
        if code_context: total_len += 4 # For \n\n and other formatting separators
        if history_context: total_len += 4 # For \n\n and other formatting separators

        if total_len > self.max_context_size:
            logger.warning("Combined context exceeds max size even after pruning. Truncating as a final measure.")
            
            # Prioritize rules, then code, then history.
            available_for_code_and_history = self.max_context_size - len(framework_rules)
            if available_for_code_and_history < 0:
                code_context = ""
                history_context = ""
            else:
                # Distribute remaining space proportionally or by fixed priority
                # Let's say 70% for code, 30% for history if both are present
                code_target_len = int(available_for_code_and_history * 0.7)
                history_target_len = available_for_code_and_history - code_target_len

                if len(code_context) > code_target_len:
                    code_context = code_context[:code_target_len] + "\n... [Code context truncated]"
                
                if len(history_context) > history_target_len:
                    # --- BUG FIX: Ensure the truncated marker is always visible ---
                    trunc_marker = "\n... [History truncated]"
                    history_context = history_context[:history_target_len - len(trunc_marker)] + trunc_marker
                
                # Re-check total length after proportional truncation
                if len(framework_rules) + len(code_context) + len(history_context) > self.max_context_size:
                    # If still too large, aggressively truncate history
                    remaining_for_history = self.max_context_size - (len(framework_rules) + len(code_context))
                    if remaining_for_history < 0: remaining_for_history = 0
                    history_context = history_context[:remaining_for_history]
                    if len(history_context) > len(trunc_marker):
                         history_context = history_context[:-len(trunc_marker)] + trunc_marker

        return framework_rules.strip(), code_context.strip(), history_context.strip(), content_availability_note.strip()

    def _extract_path_from_full_content(self, full_content: Optional[str]) -> Optional[str]:
        """Extracts the file path from the formatted full content string."""
        if not full_content:
            return None
        # This robust regex handles formats like: --- FULL CONTENT: path/file.py ---
        # --- FULL CONTENT of file: `path/file.py` --- 📄 FULL CONTENT: path/file.py
        match = re.search(r"FULL CONTENT(?: of file)?:?\s*`?([^`\n]+?)`?(?:\s*---|\s*$)", full_content, re.IGNORECASE)
        if match:
            # The captured group is the file path. Strip any trailing junk.
            return match.group(1).strip()
        return None
    
    