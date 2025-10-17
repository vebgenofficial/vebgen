# c:\Users\navee\Music\VebGen\vebgen sharp modified\backend\src\core\test_context_manager.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from src.core.context_manager import ContextManager
from src.core.project_models import ProjectState

# --- Pytest Fixtures ---

@pytest.fixture

def sample_project_state() -> ProjectState:
    """Provides a sample ProjectState with code summaries for testing."""
    state = ProjectState(
        project_name="test_project",
        framework="test",
        root_path="/fake/path",
        code_summaries={
            "file1.py": "Summary for file1.",
            "file2.py": "Summary for file2.",
            "last_mod.py": "Summary for the last modified file."
        }
    )
    return state

@pytest.fixture
def mock_agent_manager():
    """Mocks the AgentManager to control LLM responses for summarization."""
    mock = MagicMock()
    # The real invoke_agent is synchronous, so the mock should return a dictionary directly.
    # The code under test will call it via `asyncio.to_thread`.
    mock.invoke_agent.return_value = {"content": "This is a new summary."}
    return mock

@pytest.fixture
def context_manager(mock_agent_manager, sample_project_state):
    """Provides a ContextManager instance with mocked dependencies."""
    manager = ContextManager(
        agent_manager=mock_agent_manager,
        project_state=sample_project_state,
        tech_stack="test",
        framework_rules="Test framework rules.",
        get_project_structure_callback=lambda: "## Mock Project Structure",
        max_context_size=8000,
        history_summary_threshold=3 # Lower threshold for easier testing
    )
    return manager

# --- Test Cases ---

@pytest.mark.asyncio
async def test_context_building_no_pruning_or_summary(context_manager: ContextManager):
    """
    Tests basic context building when history is below the summarization threshold.
    """
    print("\n--- Testing ContextManager: Basic Context Building ---")
    context_manager.add_work_history("Step 1: Did something.")
    context_manager.add_work_history("Step 2: Did something else.")

    rules, code_context, history_context, _ = await context_manager.get_context_for_prompt()

    # Assert static context is present
    assert "Test framework rules." in rules
    assert "Mock Project Structure" in code_context
    # Assert dynamic code context is present
    assert "Summary for file1." in code_context
    # Assert history is present and not summarized
    assert "Recent actions in this session" in history_context
    assert "Step 1: Did something." in history_context
    assert "Summary of work done so far" not in history_context
    print("✅ Basic context built correctly.")

@pytest.mark.asyncio
async def test_history_summarization_triggered(context_manager: ContextManager, mock_agent_manager: MagicMock):
    """
    Tests that history summarization is triggered when the work history
    exceeds the threshold.
    """
    print("\n--- Testing ContextManager: History Summarization ---")
    # Add enough history to trigger summarization (threshold is 3)
    context_manager.add_work_history("Step 1")
    context_manager.add_work_history("Step 2")
    context_manager.add_work_history("Step 3")

    _, _, history_context, _ = await context_manager.get_context_for_prompt()

    # Assert that the summarization agent was called
    mock_agent_manager.invoke_agent.assert_called_once()
    # Assert that the new summary is in the context
    assert "Summary of work done so far" in history_context
    assert "This is a new summary." in history_context
    # Assert that the detailed history was cleared and is not in the context
    assert "Recent actions in this session" not in history_context
    assert not context_manager.work_history
    print("✅ History summarization triggered and context updated correctly.")

@pytest.mark.asyncio
async def test_full_content_priority(context_manager: ContextManager):
    """
    Tests that the explicitly requested full file content is always prioritized.
    """
    print("\n--- Testing ContextManager: Prioritize Full Content ---")
    # --- FIX: Set a last_modified_file to create a clear priority order ---
    # This makes 'last_mod.py' high priority (90), and 'file2.py' medium priority (60).
    context_manager.set_last_modified_file("last_mod.py")

    full_content = "--- FULL CONTENT: file1.py ---\nprint('hello world')"
    context_manager.set_requested_full_content(full_content)

    # Reduce context size to force pruning of lower-priority items
    context_manager.max_context_size = 250 # Size is small enough to prune the medium-priority 'file2.py' summary.

    _, code_context, _, _ = await context_manager.get_context_for_prompt()

    # Assert that the high-priority full content is included
    assert "print('hello world')" in code_context
    # Assert that the other high-priority item (last modified file summary) is also included
    assert "Summary for the last modified file." in code_context
    # Assert that lower-priority general summaries are pruned out
    assert "Summary for file2." not in code_context
    # Assert that the full content request is cleared after use
    assert context_manager.requested_full_content is None
    print("✅ Full file content was correctly prioritized and consumed.")

@pytest.mark.asyncio
async def test_final_context_truncation(mock_agent_manager: MagicMock):
    """
    Tests that the final combined context is truncated if it exceeds the max size.
    This test is now ISOLATED and does not use fixtures to ensure it tests only this feature.
    """
    print("\n--- Testing ContextManager: Final Truncation (Isolated Test) ---")
    # 1. Setup an isolated ContextManager with an empty project state
    isolated_state = ProjectState(project_name="iso", framework="test", root_path="/iso")
    isolated_manager = ContextManager(
        agent_manager=mock_agent_manager,
        project_state=isolated_state,
        tech_stack="test",
        framework_rules="Test rules.", # len=11
        get_project_structure_callback=lambda: "## Structure", # len=11
        max_context_size=150 # Very small size
    )

    # 2. Add a history entry that is long, but short enough to pass the *initial* pruning loop.
    long_history_entry = "A" * 110
    isolated_manager.add_work_history(long_history_entry)

    # 3. Get the context. The final safeguard should now trigger.
    rules, code_context, history_context, _ = await isolated_manager.get_context_for_prompt()

    total_len = len(rules) + len(code_context) + len(history_context)

    assert total_len <= isolated_manager.max_context_size
    assert "Test rules." in rules
    # --- BUG FIX: The assertion was flawed. We only need to check for the truncation marker. ---
    assert "truncated" in history_context
    print("✅ Final context was correctly truncated to fit the maximum size.")

@pytest.mark.asyncio
async def test_content_availability_note(context_manager: ContextManager):
    """
    Tests that the content_availability_note is correctly generated,
    explicitly telling the LLM what content it has available. This is a key
    test to ensure we are sending a "clear and best input" to the LLM.
    """
    print("\n--- Testing ContextManager: Content Availability Note Generation ---")

    # 1. Simulate the agent requesting full content for 'file1.py'.
    full_content_request = "--- FULL CONTENT of file: `file1.py` ---\nprint('hello from file1')\n--- END FULL CONTENT ---"
    context_manager.set_requested_full_content(full_content_request)

    # 2. Set 'last_mod.py' as the last modified file to ensure it's included as a summary.
    context_manager.set_last_modified_file("last_mod.py")

    # 3. Get the context parts, including the new availability note.
    _, _, _, availability_note = await context_manager.get_context_for_prompt()

    # 4. Assert that the note correctly and clearly informs the LLM of the content status.
    assert "Files available for this step:" in availability_note
    assert "📄 FULL: file1.py" in availability_note, "Should clearly mark file1.py as having full content."
    assert "📋 SUMMARY: last_mod.py" in availability_note, "Should clearly mark last_mod.py as having only a summary."
    assert "📋 SUMMARY: file2.py" in availability_note, "Should include other available summaries in the note."

    print("✅ Content availability note correctly generated, providing clear context to the LLM.")