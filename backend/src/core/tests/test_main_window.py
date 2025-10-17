# backend/src/core/tests/test_main_window.py
import sys
import pytest
import tkinter as tk
from unittest.mock import MagicMock, patch, ANY
import queue
import threading

# Mock customtkinter before it's imported by main_window
from src.core.tests.mock_customtkinter import mock_ctk
sys.modules['customtkinter'] = mock_ctk

from src.ui.main_window import MainWindow, QUEUE_MSG_UPDATE_UI
from src.core.project_models import ProjectState

# --- Pytest Fixtures ---

@pytest.fixture(scope="module")
def root_window():
    """Creates a root Tk window for the tests."""
    try:
        root = tk.Tk()
        yield root
        root.destroy()
    except tk.TclError:
        # Handle cases where a display is not available (e.g., in CI)
        pytest.skip("Tkinter display not available for testing.")

@pytest.fixture
def main_window(root_window):
    """
    Provides a MainWindow instance with its dependencies mocked.
    This allows testing the UI logic in isolation.
    """
    # Patch all backend managers that are instantiated within MainWindow
    with patch('src.ui.main_window.WorkflowManager') as MockWorkflowManager, \
         patch('src.ui.main_window.AgentManager') as MockAgentManager, \
         patch('src.ui.main_window.MemoryManager') as MockMemoryManager, \
         patch('src.ui.main_window.ConfigManager') as MockConfigManager, \
         patch('src.ui.main_window.FileSystemManager') as MockFileSystemManager, \
         patch('src.ui.main_window.CommandExecutor') as MockCommandExecutor, \
          patch('src.ui.main_window.simpledialog') as mock_simpledialog, \
         patch('src.ui.main_window.messagebox') as mock_messagebox, \
         patch('src.ui.main_window.filedialog') as mock_filedialog:

        # Instantiate the window
        window = MainWindow(root_window)

        # Attach mocks to the instance for easy access in tests
        window.mock_workflow_manager_class = MockWorkflowManager
        window.mock_agent_manager_class = MockAgentManager
        window.mock_memory_manager_class = MockMemoryManager
        window.mock_config_manager_class = MockConfigManager
        window.mock_fs_manager_class = MockFileSystemManager
        window.mock_command_executor_class = MockCommandExecutor
        window.mock_simpledialog = mock_simpledialog
        window.mock_messagebox = mock_messagebox
        window.mock_filedialog = mock_filedialog

        # Mock the instances that get created during initialization
        window.workflow_manager_instance = MockWorkflowManager()
        window.agent_manager = MockAgentManager()
        window.memory_manager = MockMemoryManager()
        window.config_manager = MockConfigManager()
        window.file_system_manager = MockFileSystemManager()
        window.command_executor = MockCommandExecutor()

        yield window


# --- Test Cases ---

class TestMainWindowStateManagement:
    """Tests for methods that control the UI's state."""

    def test_set_ui_initial_state(self, main_window: MainWindow):
        """Verifies that initial state correctly disables interactive widgets."""
        main_window._set_ui_initial_state()

        assert main_window.prompt_entry.configure.call_args.kwargs['state'] == 'disabled'
        assert main_window.send_button.configure.call_args.kwargs['state'] == 'disabled'
        assert main_window.provider_dropdown.configure.call_args.kwargs['state'] == 'disabled'
        assert main_window.model_dropdown.configure.call_args.kwargs['state'] == 'disabled'
        assert main_window.framework_dropdown.configure.call_args.kwargs['state'] == 'disabled'
        # Check that the project selection button is enabled
        main_window.select_project_button.configure.assert_any_call(state='normal')

    def test_set_ui_project_selected_state(self, main_window: MainWindow):
        """Verifies that selecting a project enables the correct widgets."""
        main_window.available_frameworks = ["django", "flask"] # Simulate finding frameworks
        main_window._set_ui_project_selected_state()

        assert main_window.prompt_entry.configure.call_args.kwargs['state'] == 'normal'
        assert main_window.provider_dropdown.configure.call_args.kwargs['state'] == 'readonly'
        assert main_window.framework_dropdown.configure.call_args.kwargs['state'] == 'readonly'
        # The send button should remain disabled until Stage 2 init is complete
        assert main_window.send_button.configure.call_args.kwargs['state'] == 'disabled'

    def test_set_ui_running_state_running(self, main_window: MainWindow):
        """Verifies that UI is correctly disabled when a workflow is running."""
        main_window.is_running = True
        main_window._set_ui_running_state(True)

        # Check that the send button becomes a "Stop" button
        main_window.send_button.configure.assert_any_call(text='⏹️ Stop', state='normal', fg_color=ANY, hover_color=ANY)

        # Check that other controls are disabled
        assert main_window.prompt_entry.configure.call_args.kwargs['state'] == 'disabled'
        assert main_window.provider_dropdown.configure.call_args.kwargs['state'] == 'disabled'
        assert main_window.select_project_button.configure.call_args.kwargs['state'] == 'disabled'

    def test_set_ui_running_state_stopped_can_continue(self, main_window: MainWindow):
        """Verifies that the UI correctly shows a 'Continue' button when possible."""
        main_window.is_running = False
        main_window.is_continuing_run = True # Simulate a stoppable state
        main_window._set_ui_running_state(False)

        # Check that the send button becomes a "Continue" button
        main_window.send_button.configure.assert_any_call(text='▶️ Continue', state='normal', fg_color=ANY, hover_color=ANY)
        assert main_window.prompt_entry.configure.call_args.kwargs['state'] == 'disabled'


class TestMainWindowWorkflowHandling:
    """Tests for methods that start, stop, and manage workflows."""

    @patch('src.ui.main_window.threading.Thread')
    def test_handle_start_workflow_new_project(self, mock_thread, main_window: MainWindow):
        """Tests starting a workflow for a new project."""
        main_window.core_components_initialized = True
        main_window.is_new_project.set(True)
        main_window.prompt_entry.get.return_value = "Create a blog"
        main_window.framework_var.set("django")
        # Mock the button text to ensure the correct logic path is taken
        # This simulates the state where the user sees "Start" and clicks it.
        main_window.project_root = "/fake/project" # FIX: Set project_root to trigger correct logic
        main_window.send_button.cget.return_value = "▶️ Start"

        main_window.handle_start_workflow()

        # Verify the correct thread target was chosen
        mock_thread.assert_called_once_with(
            target=main_window._run_initial_workflow_thread,
            args=("Create a blog", "django", True),
            daemon=True
        )
        assert main_window.is_running is True

    @patch('src.ui.main_window.threading.Thread')
    def test_handle_start_workflow_continue_run(self, mock_thread, main_window: MainWindow):
        """Tests continuing a previously stopped workflow."""
        main_window.core_components_initialized = True
        main_window.is_continuing_run = True
        main_window.send_button.cget.return_value = "▶️ Continue" # Mock button text
        main_window.prompt_entry.get.return_value = "" # No new prompt
        main_window.framework_var.set("django")

        main_window.handle_start_workflow()

        # Verify the correct thread target was chosen for continuation
        mock_thread.assert_called_once_with(
            target=main_window._run_new_feature_thread,
            args=("",), # Empty prompt signals continuation
            daemon=True
        )
        assert main_window.is_running is True

    def test_handle_stop_workflow(self, main_window: MainWindow):
        """Tests that the stop handler calls the workflow manager's stop method."""
        main_window.is_running = True
        main_window.workflow_manager_instance = MagicMock()

        main_window.handle_stop_workflow()

        main_window.workflow_manager_instance.request_stop.assert_called_once()


class TestMainWindowUIUpdates:
    """Tests for the UI update mechanism via the queue."""

    def test_update_progress_safe_puts_on_queue(self, main_window: MainWindow):
        """Verifies that update_progress_safe correctly queues a message."""
        progress_data = {"message": "Testing queue"}
        main_window.update_progress_safe(progress_data)

        assert not main_window.ui_queue.empty()
        msg_type, data = main_window.ui_queue.get()
        assert msg_type == QUEUE_MSG_UPDATE_UI
        assert data == progress_data

    def test_update_ui_elements_sets_status_message(self, main_window: MainWindow):
        """Verifies that _update_ui_elements correctly updates the status bar."""
        main_window.status_var = MagicMock()
        # FIX: Use a message that contains a keyword the method looks for.
        progress_data = {"message": "Agent is now planning..."}

        main_window.update_ui_elements(progress_data)

        main_window.status_var.set.assert_called_once_with("Agent is now planning...")

    def test_update_ui_elements_handles_error(self, main_window: MainWindow):
        """Verifies that an 'issue' in progress data is logged as an error."""
        main_window.status_var = MagicMock()
        main_window.add_log_message = MagicMock()
        progress_data = {"issue": "Something went wrong"}

        main_window.update_ui_elements(progress_data)

        main_window.status_var.set.assert_called_once_with("Notice: Something went wrong...")
        main_window.add_log_message.assert_called_with("ERROR", "System", "Something went wrong")

    def test_finalize_run_ui_success(self, main_window: MainWindow):
        """Verifies that the UI is correctly re-enabled after a successful run."""
        main_window.is_running = True
        main_window.core_components_initialized = True # FIX: Set this flag to True
        main_window.project_root = "/fake/project"
        main_window.framework_var.set("django")
        main_window.workflow_manager_instance.can_continue.return_value = None # No continuable feature

        main_window._finalize_run_ui(success=True)

        assert main_window.is_running is False
        assert main_window.is_continuing_run is False
        # Check that the UI is unlocked
        main_window.send_button.configure.assert_any_call(text='▶️ Start', state='normal', fg_color=ANY, hover_color=ANY) # type: ignore
        assert "Workflow finished successfully" in main_window.status_var.get()

    def test_finalize_run_ui_stopped_can_continue(self, main_window: MainWindow):
        """Verifies that the UI is correctly set to 'Continue' after a graceful stop."""
        main_window.is_running = True
        main_window.project_root = "/fake/project"
        main_window.framework_var.set("django")
        # Mock that a feature is now in a continuable state
        main_window.workflow_manager_instance.can_continue.return_value = MagicMock(name="In-progress Feature")

        main_window._finalize_run_ui(success=False, stopped=True)

        assert main_window.is_running is False
        assert main_window.is_continuing_run is True
        # Check that the UI is unlocked and shows "Continue"
        main_window.send_button.configure.assert_any_call(text='▶️ Continue', state='normal', fg_color=ANY, hover_color=ANY)
        assert "Ready to continue feature" in main_window.status_var.get()


class TestMainWindowDialogs:
    """Tests for methods that handle dialog interactions."""

    def test_handle_dialog_request_input(self, main_window: MainWindow):
        """Verifies that an 'input' dialog request calls simpledialog."""
        event = threading.Event()
        dialog_data = {
            "type": "input",
            "title": "Test Input",
            "prompt": "Enter value:",
            "is_password": True,
            "event": event
        }
        main_window.mock_simpledialog.askstring.return_value = "secret_value"

        main_window._handle_dialog_request(dialog_data)

        main_window.mock_simpledialog.askstring.assert_called_once_with(
            "Test Input", "Enter value:", show='*', parent=main_window.master
        )
        assert main_window.dialog_result == "secret_value"
        assert event.is_set()

    def test_handle_dialog_request_confirmation(self, main_window: MainWindow):
        """Verifies that a 'confirmation' dialog request calls messagebox."""
        event = threading.Event()
        dialog_data = {
            "type": "confirmation",
            "title": "Confirm",
            "prompt": "Are you sure?",
            "event": event
        }
        main_window.mock_messagebox.askyesno.return_value = True

        main_window._handle_dialog_request(dialog_data)

        main_window.mock_messagebox.askyesno.assert_called_once_with(
            "Confirm", "Are you sure?", parent=main_window.master
        )
        assert main_window.dialog_result is True
        assert event.is_set()
