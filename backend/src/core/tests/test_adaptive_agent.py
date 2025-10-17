# c:\Users\navee\Music\VebGen\vebgen sharp modified\backend\src\core\test_adaptive_agent.py
import pytest
import itertools
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import textwrap
# Import the class to be tested
from src.core.adaptive_agent import AdaptiveAgent
from src.core.agent_manager import AgentManager, ShowInputPromptCallable
from src.core.context_manager import ContextManager
from src.core.project_models import ProjectState, CommandOutput
from src.core.code_intelligence_service import CodeIntelligenceService
from src.core.exceptions import InterruptedError

# --- Pytest Fixtures for Mocking Dependencies ---

@pytest.fixture
def mock_agent_manager():
    """Mocks the AgentManager to control LLM responses during tests."""
    mock = MagicMock(spec=AgentManager)
    # The real invoke_agent is synchronous, so the mock should be synchronous too.
    mock.invoke_agent = MagicMock()
    return mock

@pytest.fixture
def mock_file_system_manager(tmp_path):
    """Mocks the FileSystemManager."""
    fs_manager = MagicMock()
    fs_manager.project_root = tmp_path
    fs_manager.get_directory_structure_markdown.return_value = "# Mock Project Structure"
    # Mock the async create_snapshot method
    fs_manager.create_snapshot = AsyncMock(return_value={"file.txt": "snapshot_content"})
    # Mock the async write_snapshot method, which is called during a ROLLBACK
    fs_manager.write_snapshot = AsyncMock(return_value=None)
    # FIX: You cannot mock a method on a real Path object.
    # Instead, we make the `project_root` attribute of the mock `fs_manager`
    # a MagicMock itself, which then has a mockable `rglob` method.
    fs_manager.project_root = MagicMock(spec=Path, return_value=tmp_path)
    fs_manager.project_root.rglob.return_value = []  # Default to finding no files
    return fs_manager

@pytest.fixture
def mock_command_executor():
    """Mocks the CommandExecutor."""
    mock = MagicMock()
    # The run_command method will be configured on a per-test basis.
    return mock

@pytest.fixture
def mock_memory_manager():
    """Mocks the MemoryManager."""
    return MagicMock()

@pytest.fixture
def mock_code_intelligence_service():
    """Mocks the CodeIntelligenceService."""
    mock = MagicMock(spec=CodeIntelligenceService)
    mock.get_file_summary.return_value = "Mock file summary"
    mock._extract_summary_from_code.return_value = "A utility file."
    return mock

@pytest.fixture
def mock_project_state(tmp_path):
    """Provides a basic ProjectState object for tests."""
    return ProjectState(project_name="test_project", framework="test_framework", root_path=str(tmp_path))

@pytest.fixture
def adaptive_agent(mock_agent_manager, mock_project_state, mock_file_system_manager, mock_command_executor, mock_memory_manager, mock_code_intelligence_service):
    """Instantiates the AdaptiveAgent with all its dependencies mocked."""
    agent = AdaptiveAgent(
        agent_manager=mock_agent_manager,
        tech_stack="test_framework",
        framework_rules="",
        project_state=mock_project_state,
        file_system_manager=mock_file_system_manager, # type: ignore
        command_executor=mock_command_executor,
        memory_manager=mock_memory_manager,
        code_intelligence_service=mock_code_intelligence_service,
        show_input_prompt_cb=MagicMock(),
        progress_callback=MagicMock(),
        show_file_picker_cb=MagicMock(),
        stop_event=asyncio.Event(), # Add the missing stop_event
    )
    # Mock the context_manager methods that will be called by GET_FULL_FILE_CONTENT
    return agent

# --- Test Cases for Circuit Breaker ---

@pytest.mark.asyncio
async def test_circuit_breaker_consecutive_failures(adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock, mock_command_executor: MagicMock):
    """
    Tests that the circuit breaker triggers a RuntimeError after 3 consecutive failures
    of the exact same action.
    """
    print("\n--- Testing Circuit Breaker: 3 Consecutive Failures ---")

    # 1. Configure the mock LLM to always return the same failing command.
    failing_action_response = {
        "role": "assistant",
        "content": '{"thought": "I will run a command that always fails.", "action": "RUN_COMMAND", "parameters": {"command": "test-fail"}}'
    }
    mock_agent_manager.invoke_agent.return_value = failing_action_response

    # 2. Configure the mock CommandExecutor to always raise an exception for that command.
    mock_command_executor.run_command.side_effect = RuntimeError("Command failed intentionally")

    # 3. Execute the feature and assert that it raises a RuntimeError.
    with pytest.raises(RuntimeError, match="failed 3 times in a row"):
        await adaptive_agent.execute_feature("Test feature")

    # 4. Verify that the LLM was called 3 times (for the 3 attempts).
    assert mock_agent_manager.invoke_agent.call_count == 3
    print("✅ Circuit breaker correctly triggered on 3 consecutive failures.")

@pytest.mark.asyncio
@patch('asyncio.sleep', new_callable=AsyncMock) # Mock asyncio.sleep to prevent long test delays
async def test_circuit_breaker_repetitive_action_cycle(mock_sleep, adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock):
    """
    Tests that the circuit breaker triggers a RuntimeError if the agent gets stuck
    in a repetitive action cycle (e.g., WRITE -> ROLLBACK -> WRITE).
    """
    print("\n--- Testing Circuit Breaker: Repetitive Action Cycle ---")

    # 1. Define the sequence of actions the mock LLM will return.
    action_sequence = [
        # Step 1: Write a file
        {"role": "assistant", "content": '```json\n{"thought": "I will write a file.", "action": "WRITE_FILE", "parameters": {"file_path": "a.txt", "content": "hello"}}\n```'},
        # Step 2: Decide to roll back
        {"role": "assistant", "content": '```json\n{"thought": "I made a mistake, I will roll back.", "action": "ROLLBACK", "parameters": {}}\n```'},
        # Step 3: Decide to write the same file again (completing the A -> B -> A cycle)
        {"role": "assistant", "content": '```json\n{"thought": "I will try writing that file again.", "action": "WRITE_FILE", "parameters": {"file_path": "a.txt", "content": "hello"}}\n```'}
    ]
    # 2. Configure the mock LLM to return actions from the sequence synchronously.
    # Use itertools.cycle to prevent StopIteration if the agent loop continues after the test's exception is caught.
    mock_agent_manager.invoke_agent.side_effect = itertools.cycle(action_sequence)

    # 3. Execute the feature and assert that it raises a RuntimeError indicating a cycle.
    with pytest.raises(RuntimeError, match="Repetitive action cycle detected"):
        await adaptive_agent.execute_feature("Test feature")

    # 4. Verify the LLM was called 3 times, once for each step in the cycle.
    assert mock_agent_manager.invoke_agent.call_count == 3, "The agent should have been invoked 3 times to detect the A->B->A cycle."
    print("✅ Circuit breaker correctly triggered on repetitive action cycle.")

@pytest.mark.asyncio
async def test_escalation_on_three_rollbacks(adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock, mock_file_system_manager: MagicMock):
    """
    Tests that the escalation system triggers a RuntimeError after 3 ROLLBACK actions.
    """
    print("\n--- Testing Escalation System: 3 Rollbacks ---")

    # 1. Configure the mock LLM to always return the ROLLBACK action.
    rollback_action_response = {
        "role": "assistant",
        "content": '{"thought": "I am stuck, I will roll back.", "action": "ROLLBACK", "parameters": {}}'
    }
    mock_agent_manager.invoke_agent.return_value = rollback_action_response

    # 2. Execute the feature and assert that it raises a RuntimeError.
    with pytest.raises(RuntimeError, match="Feature failed after 3 rollbacks"):
        await adaptive_agent.execute_feature("Test rollback escalation")

    # 3. Verify that the LLM was called 3 times for the 3 attempts.
    assert mock_agent_manager.invoke_agent.call_count == 3

    # 4. Verify that the snapshotting and writing logic was called for each rollback.
    # The agent creates a snapshot at the start of each loop, so it's called 3 times.
    # It writes the snapshot on the first two rollbacks. The third triggers the error before writing.
    assert mock_file_system_manager.create_snapshot.call_count == 3
    print("✅ Escalation system correctly triggered on 3 rollbacks.")

# --- Test Cases for Security Validation ---

@pytest.mark.asyncio
async def test_security_validation_blocks_eval(adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock):
    """
    Tests that the security validation correctly blocks a WRITE_FILE action
    containing a call to `eval()`.
    """
    print("\n--- Testing Security Validation: Block eval() ---")

    # 1. Configure the mock LLM to return a WRITE_FILE action with malicious content.
    malicious_action_response = {
        "role": "assistant",
        "content": '{"thought": "I will try to use eval().", "action": "WRITE_FILE", "parameters": {"file_path": "malicious.py", "content": "import os\\nresult = eval(\'os.system(\\"echo pwned\\")\')"} }'
    }
    mock_agent_manager.invoke_agent.return_value = malicious_action_response

    # 2. Execute the feature. The security check will raise a ValueError, which the agent's
    #    main loop will catch. Since the mock LLM is stubborn, the agent will retry,
    #    triggering the consecutive failure circuit breaker. We assert for the final RuntimeError.
    with pytest.raises(RuntimeError, match="Action 'WRITE_FILE' failed 3 times in a row"):
        await adaptive_agent.execute_feature("Test feature with eval")

    # 3. Verify that the LLM was called 3 times, once for each failed attempt.
    assert mock_agent_manager.invoke_agent.call_count == 3
    print("✅ Security validation correctly blocked a file write with eval().")

@pytest.mark.asyncio
async def test_request_user_input_action(adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock):
    """
    Tests that the REQUEST_USER_INPUT action correctly calls the UI callback
    and processes the user's response.
    """
    print("\n--- Testing REQUEST_USER_INPUT Action ---")

    # 1. Configure the mock LLM to return the REQUEST_USER_INPUT action first,
    #    then a FINISH_FEATURE action to stop the loop.
    action_sequence = [
        {"role": "assistant", "content": '{"thought": "I need to know the name of the new model.", "action": "REQUEST_USER_INPUT", "parameters": {"prompt": "What should the new model be named?"}}'},
        {"role": "assistant", "content": '{"thought": "I have the name, I can finish now.", "action": "FINISH_FEATURE", "parameters": {}}'}
    ]
    mock_agent_manager.invoke_agent.side_effect = action_sequence

    # 2. Configure the mock UI callback to return a specific user response.
    user_response = "Product"
    adaptive_agent.show_input_prompt_cb.return_value = user_response

    # 3. Execute the feature.
    _, work_log = await adaptive_agent.execute_feature("Create a new model.")

    # 4. Assert that the UI callback was called with the correct prompt.
    adaptive_agent.show_input_prompt_cb.assert_called_once_with(
        "Agent Needs Input", False, "What should the new model be named?"
    )

    # 5. Assert that the user's response was added to the work history for context.
    assert f"User provided input: '{user_response}'" in work_log

    print("✅ REQUEST_USER_INPUT action correctly handled user interaction.")

@pytest.mark.asyncio
async def test_agent_uses_get_full_content_before_patch(adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock, mock_file_system_manager: MagicMock):
    """
    Tests that the agent correctly uses GET_FULL_FILE_CONTENT before attempting a PATCH
    when it only has a summary of the file, based on the new context availability logic.
    """
    print("\n--- Testing Agent Logic: GET_FULL_FILE_CONTENT before PATCH ---")
    # --- FIX: Start with a clean project state with no summaries ---
    # This ensures the initial state for 'settings.py' is None, forcing the agent
    # to correctly go through the None -> GET_FULL_FILE_CONTENT -> FULL_CONTENT -> PATCH flow.
    adaptive_agent.project_state.code_summaries = {}
    adaptive_agent.context_manager.content_availability = {}

    # 1. Define the sequence of actions the mock LLM will return.
    action_sequence = [
        # Step 1: Agent tries to patch, but validation will fail because it only has a summary.
        # The agent's internal logic will add a correction instruction.
        {"role": "assistant", "content": '```json\n{"thought": "I will try to patch settings.py.", "action": "PATCH_FILE", "parameters": {"file_path": "settings.py", "patch": "--- a/settings.py\\n+++ b/settings.py\\n@@ -1 +1,2 @@\\n-INSTALLED_APPS = []\\n+INSTALLED_APPS = [\\"myapp\\"]"}}\n```'},
        # Step 2: Agent sees the correction and now gets the full content.
        {"role": "assistant", "content": '```json\n{"thought": "I need to patch settings.py, but I only have a summary. I must get the full content first.", "action": "GET_FULL_FILE_CONTENT", "parameters": {"file_path": "settings.py"}}\n```'},
        # Step 3: Agent now has the full content and proceeds with the patch.
        {"role": "assistant", "content": '```json\n{"thought": "I have the full content of settings.py, now I can apply the patch.", "action": "PATCH_FILE", "parameters": {"file_path": "settings.py", "patch": "--- a/settings.py\\n+++ b/settings.py\\n@@ -1 +1,2 @@\\n-INSTALLED_APPS = []\\n+INSTALLED_APPS = [\\"myapp\\"]"}}\n```'},
        # Step 4: Agent finishes the feature.
        {"role": "assistant", "content": '```json\n{"thought": "The patch is applied, the feature is complete.", "action": "FINISH_FEATURE", "parameters": {}}\n```'}
    ]
    mock_agent_manager.invoke_agent.side_effect = action_sequence

    # 2. Mock the file system to provide content when read.
    mock_file_system_manager.read_file.return_value = "INSTALLED_APPS = []"
    # The real apply_patch is synchronous, but it's called via asyncio.to_thread.
    # Mocking it as an AsyncMock is a valid way to test this interaction.
    mock_file_system_manager.apply_patch.return_value = None
    mock_file_system_manager.file_exists.return_value = True # FIX: Ensure file_exists returns True for validation

    # 3. Execute the feature.
    await adaptive_agent.execute_feature("Patch the settings file.")

    # 4. Assertions
    # Assert that the LLM was called for each step in the sequence.
    assert mock_agent_manager.invoke_agent.call_count == 4

    # Assert that the agent first tried to read the file (for GET_FULL_FILE_CONTENT).
    # The read_file method is called once for GET_FULL_FILE_CONTENT.
    assert mock_file_system_manager.read_file.call_count >= 1
    mock_file_system_manager.read_file.assert_any_call("settings.py")

    # Assert that the agent then applied the patch.
    # Since apply_patch is called via asyncio.to_thread, it's a synchronous call
    # from the perspective of the mock object, not an await.
    mock_file_system_manager.apply_patch.assert_called_once()

    print("✅ Agent correctly used GET_FULL_FILE_CONTENT before PATCH_FILE.")

@pytest.mark.asyncio
async def test_get_full_file_content_small_file_formatting(adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock, mock_file_system_manager: MagicMock):
    """
    Tests that GET_FULL_FILE_CONTENT correctly formats small files with line numbers.
    """
    print("\n--- Testing GET_FULL_FILE_CONTENT: Small File Formatting ---")

    adaptive_agent.context_manager.set_requested_full_content = MagicMock()
    adaptive_agent.context_manager.mark_full_content_loaded = MagicMock()

    filepath = "small_file.txt"
    raw_content = "Line 1\nLine 2\nLine 3"
    
    # 1. Configure the mock LLM to return GET_FULL_FILE_CONTENT action.
    action_sequence = [
        {"role": "assistant", "content": f'```json\n{{"thought": "I need the full content of {filepath}.", "action": "GET_FULL_FILE_CONTENT", "parameters": {{"file_path": "{filepath}"}}}}\n```'},
        {"role": "assistant", "content": '```json\n{"thought": "I have the content, now I can finish.", "action": "FINISH_FEATURE", "parameters": {}}\n```'}
    ]
    mock_agent_manager.invoke_agent.side_effect = action_sequence

    # 2. Mock the file system to provide the raw content.
    mock_file_system_manager.read_file.return_value = raw_content
    mock_file_system_manager.file_exists.return_value = True # Ensure file_exists returns True for validation

    # 3. Execute the feature.
    await adaptive_agent.execute_feature("Get content of a small file.")

    # 4. Assertions
    # Ensure read_file was called
    mock_file_system_manager.read_file.assert_called_once_with(filepath)

    # Ensure set_requested_full_content was called with the correctly formatted content.
    adaptive_agent.context_manager.set_requested_full_content.assert_called_once()
    formatted_content = adaptive_agent.context_manager.set_requested_full_content.call_args[0][0]

    assert f"📄 FULL CONTENT: {filepath} (3 lines)" in formatted_content
    assert "⚠️  Line numbers (before │) are for REFERENCE ONLY" in formatted_content
    assert "   1 │Line 1" in formatted_content
    assert "   2 │Line 2" in formatted_content
    assert "   3 │Line 3" in formatted_content
    assert "NOTE: Line numbers have been omitted" not in formatted_content # Ensure this is NOT present

    # Ensure mark_full_content_loaded was called
    adaptive_agent.context_manager.mark_full_content_loaded.assert_called_once_with(filepath, "Agent requested full content")
    
    print("✅ Small file content correctly formatted with line numbers.")


@pytest.mark.asyncio
async def test_get_full_file_content_large_file_formatting(adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock, mock_file_system_manager: MagicMock):
    """
    Tests that GET_FULL_FILE_CONTENT correctly formats large files by omitting line numbers.
    """
    print("\n--- Testing GET_FULL_FILE_CONTENT: Large File Formatting ---")

    adaptive_agent.context_manager.set_requested_full_content = MagicMock()
    adaptive_agent.context_manager.mark_full_content_loaded = MagicMock()

    filepath = "large_file.txt"
    raw_content = "\n".join([f"Line {i}" for i in range(1, 600)]) # 599 lines
    
    action_sequence = [
        {"role": "assistant", "content": f'```json\n{{"thought": "I need the full content of {filepath}.", "action": "GET_FULL_FILE_CONTENT", "parameters": {{"file_path": "{filepath}"}}}}\n```'},
        {"role": "assistant", "content": '```json\n{"thought": "I have the content, now I can finish.", "action": "FINISH_FEATURE", "parameters": {}}\n```'}
    ]
    mock_agent_manager.invoke_agent.side_effect = action_sequence
    mock_file_system_manager.read_file.return_value = raw_content
    mock_file_system_manager.file_exists.return_value = True
    await adaptive_agent.execute_feature("Get content of a large file.")
    adaptive_agent.context_manager.set_requested_full_content.assert_called_once()
    formatted_content = adaptive_agent.context_manager.set_requested_full_content.call_args[0][0]
    assert f"📄 FULL CONTENT: {filepath} (599 lines)" in formatted_content
    assert "NOTE: Line numbers have been omitted as the file is large." in formatted_content
    assert raw_content in formatted_content
    assert "1    │ Line 1" not in formatted_content
    adaptive_agent.context_manager.mark_full_content_loaded.assert_called_once_with(filepath, "Agent requested full content")
    print("✅ Large file content correctly formatted without line numbers.")

# --- Test Cases for Action Validation ---

class TestValidationLogic:
    @pytest.mark.asyncio
    async def test_patch_validation_fails_without_full_content(self, adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock, mock_file_system_manager: MagicMock):
        """
        Tests that PATCH_FILE is blocked if the context only has a summary,
        and that the agent is re-prompted with the validation error.
        """
        print("\n--- Testing Action Validation: Block PATCH without full content ---")

        # 1. Configure the mock LLM to return a sequence of actions.
        action_sequence = [
            # Attempt 1: Tries to PATCH with only a summary (will be blocked by validation).
            {"role": "assistant", "content": '{"thought": "I will patch the settings file.", "action": "PATCH_FILE", "parameters": {"file_path": "settings.py", "patch": "..."}}'},
            # Attempt 2: Agent sees the validation error and now gets the full content.
            {"role": "assistant", "content": '{"thought": "Validation failed. I must get the full content first.", "action": "GET_FULL_FILE_CONTENT", "parameters": {"file_path": "settings.py"}}'},
            # Attempt 3: Agent finishes the feature.
            {"role": "assistant", "content": '{"thought": "I have the content now, I will patch in the next feature.", "action": "FINISH_FEATURE", "parameters": {}}'}
        ]
        mock_agent_manager.invoke_agent.side_effect = action_sequence

        # 2. Mock the file system and context manager state.
        mock_file_system_manager.file_exists.return_value = True
        # FIX: Mock the specific method on the context_manager instance, not the method itself.
        adaptive_agent.context_manager.get_content_type_for_file = MagicMock(return_value='SUMMARY_ONLY')

        # 3. Execute the feature.
        await adaptive_agent.execute_feature("Patch settings.py")

        # 4. Assertions
        # The agent should have been invoked 3 times for the 3 steps.
        assert mock_agent_manager.invoke_agent.call_count == 3

        # The second call to the LLM should have included the validation error as a correction.
        second_call_args = mock_agent_manager.invoke_agent.call_args_list[1]
        prompt_for_second_call = second_call_args.args[1][0]['content']
        assert "Your last action was invalid" in prompt_for_second_call
        assert "Cannot PATCH settings.py - only have SUMMARY_ONLY" in prompt_for_second_call
        
        # The agent should have read the file during the GET_FULL_FILE_CONTENT step.
        mock_file_system_manager.read_file.assert_called_once_with("settings.py")
        print("✅ PATCH_FILE was correctly blocked, and the agent was re-prompted with the error.")

    @pytest.mark.asyncio
    async def test_patch_validation_fails_for_non_existent_file(self, adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock, mock_file_system_manager: MagicMock):
        """
        Tests that PATCH_FILE is blocked if the target file does not exist.
        """
        print("\n--- Testing Action Validation: Block PATCH on non-existent file ---")

        # 1. Configure LLM to try to patch a file that doesn't exist.
        action_sequence = [
            {"role": "assistant", "content": '{"thought": "I will patch a file that does not exist.", "action": "PATCH_FILE", "parameters": {"file_path": "non_existent.py", "patch": "..."}}'},
            {"role": "assistant", "content": '{"thought": "Okay, I will finish.", "action": "FINISH_FEATURE", "parameters": {}}'}
        ]
        mock_agent_manager.invoke_agent.side_effect = action_sequence

        # 2. Mock the file system to report that the file does not exist.
        mock_file_system_manager.file_exists.return_value = False

        # Mock the _execute_action method on the agent instance to track its calls.
        adaptive_agent._execute_action = AsyncMock()

        # 3. Execute the feature.
        await adaptive_agent.execute_feature("Patch a non-existent file.")

        # 4. Assert that _execute_action was never called because validation failed.
        adaptive_agent._execute_action.assert_not_called()
        print("✅ PATCH_FILE was correctly blocked for a non-existent file.")

@pytest.mark.asyncio
async def test_run_command_with_structured_args(adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock, mock_command_executor: MagicMock):
    """
    Tests that a RUN_COMMAND with structured 'command' and 'args' parameters
    is correctly assembled and executed. This verifies the fix for the bug where
    only the base command was being run.
    """
    print("\n--- Testing Action Execution: RUN_COMMAND with structured args ---")

    # --- FIX: Configure the mock to return a successful CommandOutput ---
    mock_command_executor.run_command.return_value = CommandOutput(
        command="python manage.py migrate", stdout="Migrations applied.", stderr="", exit_code=0
    )

    # 1. Configure the mock LLM to return a structured RUN_COMMAND action.
    structured_command_action = {
        "role": "assistant",
        "content": '''{
            "thought": "I will run a command with separate arguments.",
            "action": "RUN_COMMAND",
            "parameters": {
                "command": "python",
                "args": ["manage.py", "migrate"]
            }
        }'''
    }
    mock_agent_manager.invoke_agent.return_value = structured_command_action

    # 2. Execute the action via the agent's internal execution method.
    await adaptive_agent._execute_action("RUN_COMMAND", {"command": "python", "args": ["manage.py", "migrate"]}, modified_files_set=set())

    # 3. Assert that the command executor was called with the correctly assembled command string.
    # The `shlex.join` logic in the implementation should produce 'python manage.py migrate'.
    mock_command_executor.run_command.assert_called_once_with("python manage.py migrate")
    print("✅ RUN_COMMAND with structured args was correctly assembled and executed.")


@pytest.mark.asyncio
async def test_execute_feature_returns_modified_files_on_finish(adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock, mock_file_system_manager: MagicMock):
    """
    Tests that when the agent's last action is FINISH_FEATURE, the `execute_feature`
    method still correctly returns the list of all files modified during its run.
    This fixes the bug where TARS verification would fail because it received an empty file list.
    """
    print("\n--- Testing `execute_feature` returns file list on FINISH_FEATURE ---")

    # 1. Define the sequence of actions: a WRITE followed by a FINISH.
    action_sequence = [
        # Step 1: Agent writes a file.
        {"role": "assistant", "content": '```json\n{"thought": "I will write a file.", "action": "WRITE_FILE", "parameters": {"file_path": "final.txt", "content": "all done"}}\n```'},
        # Step 2: Agent decides the feature is complete.
        {"role": "assistant", "content": '```json\n{"thought": "The file is written, the feature is complete.", "action": "FINISH_FEATURE", "parameters": {}}\n```'}
    ]
    mock_agent_manager.invoke_agent.side_effect = action_sequence

    # 2. Execute the feature.
    modified_files, work_log = await adaptive_agent.execute_feature("Finish the feature.")

    # 3. Assertions
    # CRITICAL: Assert that the returned list of modified files is NOT empty.
    assert "final.txt" in modified_files
    assert len(modified_files) == 1
    print("✅ `execute_feature` correctly returned the modified file list upon `FINISH_FEATURE`.")

@pytest.mark.asyncio
async def test_execute_feature_returns_modified_files_on_finish(adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock, mock_file_system_manager: MagicMock):
    """
    Tests that when the agent's last action is FINISH_FEATURE, the `execute_feature`
    method still correctly returns the list of all files modified during its run.
    This fixes the bug where TARS verification would fail because it received an empty file list.
    """
    print("\n--- Testing `execute_feature` returns file list on FINISH_FEATURE ---")

    # 1. Define the sequence of actions: a WRITE followed by a FINISH.
    action_sequence = [
        # Step 1: Agent writes a file.
        {"role": "assistant", "content": '```json\n{"thought": "I will write a file.", "action": "WRITE_FILE", "parameters": {"file_path": "final.txt", "content": "all done"}}\n```'},
        # Step 2: Agent decides the feature is complete.
        {"role": "assistant", "content": '```json\n{"thought": "The file is written, the feature is complete.", "action": "FINISH_FEATURE", "parameters": {}}\n```'}
    ]
    mock_agent_manager.invoke_agent.side_effect = action_sequence

    # 2. Mock the file system manager's write_file to do nothing.
    mock_file_system_manager.write_file.return_value = None

    # 3. Execute the feature.
    modified_files, work_log = await adaptive_agent.execute_feature("Finish the feature.")

    # 4. Assertions
    # The agent should have been invoked twice.
    assert mock_agent_manager.invoke_agent.call_count == 2
    # The `write_file` method on the mock should have been called.
    mock_file_system_manager.write_file.assert_called_once_with("final.txt", "all done")
    # CRITICAL: Assert that the returned list of modified files is NOT empty.
    assert "final.txt" in modified_files
    assert len(modified_files) == 1
    print("✅ `execute_feature` correctly returned the modified file list upon `FINISH_FEATURE`.")

@pytest.mark.asyncio
async def test_get_full_file_content_adds_to_modified_files(adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock, mock_file_system_manager: MagicMock):
    """
    Tests that a GET_FULL_FILE_CONTENT action correctly adds the file path
    to the returned `modified_files` set, which is the core of the bug fix.
    """
    print("\n--- Testing `GET_FULL_FILE_CONTENT` adds to modified files list ---")

    # 1. Define the sequence of actions: a GET_FULL_FILE_CONTENT followed by a FINISH.
    action_sequence = [
        {"role": "assistant", "content": '```json\n{"thought": "I will inspect a file.", "action": "GET_FULL_FILE_CONTENT", "parameters": {"file_path": "inspected_file.txt"}}\n```'},
        {"role": "assistant", "content": '```json\n{"thought": "I have inspected the file, I am done.", "action": "FINISH_FEATURE", "parameters": {}}\n```'}
    ]
    mock_agent_manager.invoke_agent.side_effect = action_sequence

    # 2. Mock the file system to return some content for the read operation.
    mock_file_system_manager.read_file.return_value = "some content"
    mock_file_system_manager.file_exists.return_value = True

    # 3. Execute the feature.
    modified_files, work_log = await adaptive_agent.execute_feature("Inspect a file.")

    # 4. Assertions
    # CRITICAL: Assert that the returned list of modified files contains the inspected file.
    assert "inspected_file.txt" in modified_files
    assert len(modified_files) == 1
    print("✅ `GET_FULL_FILE_CONTENT` correctly added the inspected file to the returned list.")

@pytest.mark.asyncio
async def test_run_command_returns_all_new_files(adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock, mock_command_executor: MagicMock, mock_file_system_manager: MagicMock):
    """
    Tests that a RUN_COMMAND action that creates multiple files correctly
    identifies and adds all of them to the `modified_files` set. This is the
    fix for the TARS verification bug where only the last file was being reported.
    """
    print("\n--- Testing `RUN_COMMAND` returns all created files ---")

    # 1. Define the action sequence
    action_sequence = [
        {"role": "assistant", "content": '```json\n{"thought": "I will run startapp.", "action": "RUN_COMMAND", "parameters": {"command": "python", "args": ["manage.py", "startapp", "blog"]}}\n```'},
        {"role": "assistant", "content": '```json\n{"thought": "I am done.", "action": "FINISH_FEATURE", "parameters": {}}\n```'}
    ]
    mock_agent_manager.invoke_agent.side_effect = action_sequence

    # FIX: Configure the mock command executor to return a successful result.
    mock_command_executor.run_command.return_value = CommandOutput(
        command="python manage.py startapp blog", stdout="Success", stderr="", exit_code=0
    )

    # 2. Mock the file system to simulate file creation
    # Before the command, rglob finds no files.
    files_before = []
    # After the command, rglob finds the new app files.
    files_after = [
        MagicMock(spec=Path, parts=('blog', 'models.py'), relative_to=lambda x: Path('blog/models.py'), is_file=lambda: True),
        MagicMock(spec=Path, parts=('blog', 'views.py'), relative_to=lambda x: Path('blog/views.py'), is_file=lambda: True),
        MagicMock(spec=Path, parts=('blog', 'admin.py'), relative_to=lambda x: Path('blog/admin.py'), is_file=lambda: True),
    ]
    # FIX: The side_effect needs to handle calls from _preload_config_files as well.
    # We'll return empty lists for those and the correct lists for the RUN_COMMAND action.
    mock_file_system_manager.project_root.rglob.side_effect = [
        [], [], [], [], # For settings.py, urls.py, wsgi.py, asgi.py in _preload
        files_before, files_after # For the actual command execution
    ]

    # 3. Execute the feature
    modified_files, work_log = await adaptive_agent.execute_feature("Create a blog app.")

    # 4. Assertions
    assert len(modified_files) == 3
    assert "blog/models.py" in modified_files
    assert "blog/views.py" in modified_files
    assert "blog/admin.py" in modified_files
    print("✅ `RUN_COMMAND` correctly identified and returned all newly created files.")


# --- NEW Test Class for State Persistence (Data Loss Bugs) ---

class TestStatePersistence:
    """
    Tests that the AdaptiveAgent correctly persists changes to the ProjectState
    to prevent data loss, addressing the 5 critical bugs.
    """

    @pytest.mark.asyncio
    async def test_bug_1_and_4_project_structure_and_summaries_are_saved(self, adaptive_agent: AdaptiveAgent, mock_memory_manager: MagicMock):
        """
        Verifies that after updating the project structure map (which also handles
        summaries), the state is saved to disk.
        """
        print("\n--- Testing Data Loss Bug #1 & #4: Save after structure/summary update ---")
        
        # 1. Mock the file system to return some content for a file.
        file_path = "utils.py" # Test with a root-level file
        file_content = "# <!-- SUMMARY_START -->\n# A utility file.\n# <!-- SUMMARY_END -->\ndef helper_function(): pass"
        adaptive_agent.file_system_manager.read_file.return_value = file_content

        # 2. Call the method that updates the structure map.
        await adaptive_agent._update_project_structure_map(file_path)

        # 3. Assert that `save_project_state` was called on the memory manager.
        mock_memory_manager.save_project_state.assert_called()
        assert mock_memory_manager.save_project_state.call_count >= 1
        
        # 4. Assert that the summary was correctly extracted and added to the state object.
        assert adaptive_agent.project_state.code_summaries[file_path] == "A utility file."
        # 5. Assert that the file was added to global_files, not apps.
        assert "utils.py" in adaptive_agent.project_state.project_structure_map.global_files
        assert "_project_level_" not in adaptive_agent.project_state.project_structure_map.apps
        print("✅ Bug #1 & #4 Fix Verified: Project state is saved after updating structure map and code summaries for a global file.")
 
    @pytest.mark.asyncio
    async def test_bug_2_registered_apps_are_saved(self, adaptive_agent: AdaptiveAgent, mock_memory_manager: MagicMock):
        """
        Verifies that after parsing INSTALLED_APPS from settings.py, the state is saved.
        """
        print("\n--- Testing Data Loss Bug #2: Save after app registration update ---")
        
        # 1. Define mock settings content.
        settings_content = "INSTALLED_APPS = ['django.contrib.admin', 'new_app']"

        # 2. Call the method that updates registered apps.
        await adaptive_agent._update_registered_apps_from_content("proj/settings.py", settings_content)

        # 3. Assert that the state was updated and saved.
        assert 'new_app' in adaptive_agent.project_state.registered_apps
        mock_memory_manager.save_project_state.assert_called_with(adaptive_agent.project_state)
        print("✅ Bug #2 Fix Verified: Project state is saved after updating registered apps.")

    @pytest.mark.asyncio
    async def test_bug_3_defined_models_are_saved(self, adaptive_agent: AdaptiveAgent, mock_memory_manager: MagicMock):
        """
        Verifies that after parsing models from a models.py file, the state is saved.
        """
        print("\n--- Testing Data Loss Bug #3: Save after model definition update ---")

        # 1. Define mock models.py content.
        models_content = "from django.db import models\nclass Product(models.Model):\n    pass"

        # 2. Mock the helper that extracts model names.
        adaptive_agent._extract_django_models = MagicMock(return_value=["Product"])

        # 3. Call the method that updates defined models.
        await adaptive_agent._update_defined_models_from_content("inventory/models.py", models_content)

        # 4. Assert that the state was updated and saved.
        assert "Product" in adaptive_agent.project_state.defined_models["inventory"]
        # The method should be called with just the project state.
        mock_memory_manager.save_project_state.assert_called_with(adaptive_agent.project_state)
        print("✅ Bug #3 Fix Verified: Project state is saved after updating defined models.")

    @pytest.mark.asyncio
    async def test_bug_12_artifact_registry_is_populated(self, adaptive_agent: AdaptiveAgent):
        """
        Verifies that after parsing models, the artifact_registry is populated.
        """
        print("\n--- Testing State Tracking Bug #12: Populate Artifact Registry ---")
        
        # 1. Define mock models.py content.
        models_content = "from django.db import models\nclass User(models.Model):\n    pass"
        
        # 2. Mock the helper that extracts model names.
        adaptive_agent._extract_django_models = MagicMock(return_value=["User"])

        # 3. Call the method that updates defined models.
        await adaptive_agent._update_defined_models_from_content("profiles/models.py", models_content)

        # 4. Assert that the artifact registry was updated.
        registry = adaptive_agent.project_state.artifact_registry
        artifact_key = "django_model:profiles.User"
        assert artifact_key in registry
        assert registry[artifact_key]["class_name"] == "User"
        print("✅ Bug #12 Fix Verified: Artifact registry is populated with defined models.")

    @pytest.mark.asyncio
    async def test_bug_5_historical_notes_are_saved(self, adaptive_agent: AdaptiveAgent, mock_memory_manager: MagicMock):
        """
        Verifies that the _add_historical_note method correctly adds a note
        to the project state and then saves it.
        """
        print("\n--- Testing Data Loss Bug #5: Save after adding historical note ---")
        
        # 1. Ensure the historical notes list is initially empty.
        adaptive_agent.project_state.historical_notes = []
        assert not adaptive_agent.project_state.historical_notes

        # 2. Call the new method to add a note.
        note_text = "This is a test note."
        await adaptive_agent._add_historical_note(note_text)

        # 3. Assert that the note was added to the state object.
        assert len(adaptive_agent.project_state.historical_notes) == 1
        assert note_text in adaptive_agent.project_state.historical_notes[0]

        # 4. Assert that the state was saved to disk.
        mock_memory_manager.save_project_state.assert_called_with(adaptive_agent.project_state)
        print("✅ Bug #5 Fix Verified: Historical notes are correctly added and saved.")

# --- Test Cases for Smart Auto-Fetch ---

# --- Test Cases for Smart Auto-Fetch ---

@pytest.mark.parametrize("feature_description, expected", [
    ("Install the 'corsheaders' app.", True),
    ("Configure the database settings.", True),
    ("Add a new URL route for the about page.", True),
    ("Set up a new Django app named 'profiles'.", True),
    ("Refactor the user model logic.", False),
    ("Fix a typo in the main template.", False),
])
def test_feature_needs_configuration(adaptive_agent: AdaptiveAgent, feature_description: str, expected: bool):
    """
    Tests the _feature_needs_configuration heuristic.
    """
    print(f"\n--- Testing Smart Auto-Fetch: Heuristic for '{feature_description}' ---")
    
    result = adaptive_agent._feature_needs_configuration(feature_description)
    
    assert result is expected
    print(f"✅ Heuristic correctly returned {expected}.")

class TestSmartAutoFetch:
    """Tests for the 'Smart Auto-Fetch' preloading logic."""

    def test_find_project_files_filters_venv(self, adaptive_agent: AdaptiveAgent, mock_file_system_manager: MagicMock):
        """
        Tests that _find_project_files correctly ignores files inside 'venv' and 'site-packages'.
        This corresponds to: "Filter out venv files in _find_project_files()".
        """
        print("\n--- Testing Smart Auto-Fetch: _find_project_files venv filtering ---")
        
        # 1. Setup a mock file system structure by mocking what rglob returns
        project_root = mock_file_system_manager.project_root
        mock_path_configs = [
            # (mock_path_object, parts_tuple, expected_relative_path_string)
            (("my_app", "settings.py"), "my_app/settings.py"),
            (("project_name", "settings.py"), "project_name/settings.py"),
            (("venv", "lib", "site-packages", "django", "conf", "settings.py"), "venv/lib/site-packages/django/conf/settings.py"),
        ]
        
        # Create a list of just the mock path objects to return from rglob
        rglob_return_values = []
        for parts_tuple, rel_path_str in mock_path_configs:
            # --- FIX: Create a new MagicMock for each path to avoid reuse ---
            p = MagicMock(spec=Path)
            p.is_file.return_value = True
            p.parts = parts_tuple  # Mock the .parts attribute to return a real tuple
            # --- FIX: Mock the relative_to method to return a predictable string ---
            p.relative_to.return_value = rel_path_str
            rglob_return_values.append(p)

        # Configure the rglob mock on the project_root Path object
        mock_file_system_manager.project_root.rglob.return_value = rglob_return_values

        # 2. Call the method under test
        found_files = adaptive_agent._find_project_files("settings.py")

        # 3. Assertions
        assert len(found_files) == 2, "Should find 2 project files and ignore the venv file."
        assert "my_app/settings.py" in found_files
        assert "project_name/settings.py" in found_files
        assert "venv/lib/site-packages/django/conf/settings.py" not in found_files
        print("✅ _find_project_files correctly filtered out venv/site-packages files.")

    @pytest.mark.asyncio
    async def test_preload_config_files_direct_read(self, adaptive_agent: AdaptiveAgent, mock_file_system_manager: MagicMock):
        """
        Tests that _preload_config_files reads files directly instead of using _execute_action.
        This corresponds to: "Remove snapshot creation from preload".
        """
        print("\n--- Testing Smart Auto-Fetch: _preload_config_files direct read ---")
        
        # 1. Mock _find_project_files to return a specific file to preload
        adaptive_agent._find_project_files = MagicMock(return_value=["my_app/settings.py"])
        
        # 2. Mock the methods we want to track
        adaptive_agent._execute_action = AsyncMock()
        mock_file_system_manager.read_file.return_value = "file content"

        # 3. Execute the preload logic
        await adaptive_agent._preload_config_files()

        # 4. Assertions
        mock_file_system_manager.read_file.assert_called_once_with("my_app/settings.py")
        adaptive_agent._execute_action.assert_not_called()
        print("✅ _preload_config_files correctly used direct file read, not _execute_action.")

    @pytest.mark.asyncio
    async def test_preload_config_files_skips_on_too_many_matches(self, adaptive_agent: AdaptiveAgent, mock_file_system_manager: MagicMock, caplog):
        """
        Tests that preloading is skipped if too many matching files are found.
        This corresponds to: "Add timeout for preload attempts".
        """
        print("\n--- Testing Smart Auto-Fetch: Preload skip on too many files ---")
        # 1. Mock _find_project_files to return more than 5 files
        adaptive_agent._find_project_files = MagicMock(return_value=[f"file_{i}.js" for i in range(6)])
        await adaptive_agent._preload_config_files()

        assert "Skipping preload to avoid excessive context" in caplog.text
        mock_file_system_manager.read_file.assert_not_called()
        print("✅ _preload_config_files correctly skipped when too many files were found.")


        # --- NEW Test Class for State Tracking ---
class TestStateTracking:
    """Tests for the explicit state tracking logic in AdaptiveAgent."""

    @pytest.mark.asyncio
    async def test_update_registered_apps_from_content(self, adaptive_agent: AdaptiveAgent):
        """
        Tests that _update_registered_apps_from_content correctly parses settings.py
        and updates the project_state.
        """
        print("\n--- Testing State Tracking: App Registration Parsing ---")
 
        settings_content = textwrap.dedent("""
            INSTALLED_APPS = [
                'django.contrib.admin',
                'blog',
                'users.apps.UsersConfig',
            ]
            # Some other settings
            DEBUG = True
        """)
 
        # Initially, no apps should be registered
        adaptive_agent.project_state.registered_apps.clear()
        assert not adaptive_agent.project_state.registered_apps

        # Call the method under test
        await adaptive_agent._update_registered_apps_from_content("project/settings.py", settings_content)

        # Assert that the state was updated correctly
        registered_apps = adaptive_agent.project_state.registered_apps
        assert 'django' in registered_apps
        assert 'blog' in registered_apps
        assert 'users' in registered_apps
        assert len(registered_apps) == 3
        print("✅ App registration parsing works correctly.")

        # Test that it clears old state before adding new ones
        new_settings_content = "INSTALLED_APPS = ['api']"
        await adaptive_agent._update_registered_apps_from_content("project/settings.py", new_settings_content)
        assert 'api' in adaptive_agent.project_state.registered_apps
        assert 'blog' not in adaptive_agent.project_state.registered_apps
        assert len(adaptive_agent.project_state.registered_apps) == 1
        print("✅ App registration correctly clears old state.")

    def test_extract_django_models(self, adaptive_agent: AdaptiveAgent):
        """
        Tests that _extract_django_models correctly identifies only Django models,
        ignoring helper classes or other non-model classes in the file.
        """
        print("\n--- Testing State Tracking: Django Model Extraction ---")
        
        models_content = textwrap.dedent("""
            from django.db import models

            class PostManager(models.Manager):
                # This is not a model
                pass

            class Post(models.Model):
                title = models.CharField(max_length=100)

            class HelperClass:
                # This is also not a model
                pass

            class Comment(models.Model):
                text = models.TextField()
        """)

        model_names = adaptive_agent._extract_django_models(models_content)

        assert 'Post' in model_names
        assert 'Comment' in model_names
        assert 'PostManager' not in model_names
        assert 'HelperClass' not in model_names
        assert len(model_names) == 2
        print("✅ Django model extraction correctly filters for models.Model subclasses.")

    @pytest.mark.asyncio
    async def test_execute_action_triggers_state_tracking(self, adaptive_agent: AdaptiveAgent, mock_file_system_manager: MagicMock):
        """
        Tests that _execute_action calls the appropriate state tracking methods
        after a successful WRITE_FILE operation on models.py or settings.py.
        """
        print("\n--- Testing State Tracking: Integration with _execute_action ---")
        
        # Mock the state tracking methods to verify they are called
        adaptive_agent._update_defined_models_from_content = AsyncMock() # This one is async
        adaptive_agent._update_registered_apps_from_content = AsyncMock() # This one is async

        # 1. Test WRITE_FILE on models.py
        await adaptive_agent._execute_action("WRITE_FILE", {"file_path": "blog/models.py", "content": "class Post(models.Model): pass"}, modified_files_set=set())
        adaptive_agent._update_defined_models_from_content.assert_awaited_once()
        adaptive_agent._update_registered_apps_from_content.assert_not_awaited()
        print("✅ _execute_action correctly called model tracking for models.py.")

        # Reset mocks for the next test
        adaptive_agent._update_defined_models_from_content.reset_mock()

        # 2. Test WRITE_FILE on settings.py
        await adaptive_agent._execute_action("WRITE_FILE", {"file_path": "my_project/settings.py", "content": "INSTALLED_APPS = ['blog']"}, modified_files_set=set())
        adaptive_agent._update_defined_models_from_content.assert_not_awaited()
        adaptive_agent._update_registered_apps_from_content.assert_awaited_once()
        print("✅ _execute_action correctly called app registration tracking for settings.py.")

    @pytest.mark.asyncio
    async def test_bug_6_work_history_is_saved(self, adaptive_agent: AdaptiveAgent, mock_agent_manager: MagicMock):
        """
        Verifies that the work history from a feature execution is saved back to the feature object.
        """
        print("\n--- Testing Data Loss Bug #6: Save work history ---")
        
        # 1. Mock the agent to perform one action and then finish.
        action_sequence = [
            {"role": "assistant", "content": '{"thought": "I will write a file.", "action": "WRITE_FILE", "parameters": {"file_path": "a.txt", "content": "hello"}}'},
            {"role": "assistant", "content": '{"thought": "I am done.", "action": "FINISH_FEATURE", "parameters": {}}'}
        ]
        mock_agent_manager.invoke_agent.side_effect = action_sequence

        # 2. Create a feature and set it as current.
        from src.core.project_models import ProjectFeature
        feature = ProjectFeature(id="feat_test_hist", name="Test History", description="Test")
        adaptive_agent.project_state.features.append(feature)
        adaptive_agent.project_state.current_feature_id = "feat_test_hist"

        # 3. Execute the feature.
        await adaptive_agent.execute_feature(feature.description)

        # 4. Assert that the feature object in the project state now contains the work log.
        saved_feature = adaptive_agent.project_state.get_feature_by_id("feat_test_hist")
        assert saved_feature is not None
        assert len(saved_feature.work_log) > 0
        assert "Action: WRITE_FILE" in saved_feature.work_log[-2] # Check one of the log entries
        print("✅ Bug #6 Fix Verified: Work history is saved to the feature object.")

    @pytest.mark.asyncio
    async def test_bug_7_file_checksums_are_populated(self, adaptive_agent: AdaptiveAgent):
        """Verifies that file checksums are populated after file write operations."""
        print("\n--- Testing Data Loss Bug #7: Populate file checksums ---")
        await adaptive_agent._execute_action("WRITE_FILE", {"file_path": "checksum_test.txt", "content": "data"}, modified_files_set=set())
        assert "checksum_test.txt" in adaptive_agent.project_state.file_checksums
        assert adaptive_agent.project_state.file_checksums["checksum_test.txt"] is not None
        print("✅ Bug #7 Fix Verified: File checksums are populated after file writes.")
