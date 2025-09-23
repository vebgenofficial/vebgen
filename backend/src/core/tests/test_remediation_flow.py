# c:\Users\rames\WebGen\send\opensource\web_agent270\backend\src\core\tests\test_remediation_flow.py
import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import shutil
from pathlib import Path

# To run these tests, navigate to the 'backend' directory and run:
# python -m unittest discover src/core/tests
# This ensures that 'src' is treated as a top-level package.

# Import the classes we need to test and mock
from src.core.remediation_manager import RemediationManager
from src.core.error_analyzer import ErrorRecord, ErrorType
from src.core.project_models import ProjectState, FixLogicTask

class TestRemediationFlow(unittest.TestCase):

    def setUp(self):
        """Set up mock objects for each test."""
        # Create a temporary directory for the test to prevent file system side effects
        self.temp_dir = Path("temp_test_project_for_remediation").resolve()
        self.temp_dir.mkdir(exist_ok=True)

        self.mock_agent_manager = MagicMock()
        self.mock_agent_manager.model_id = "test_model"
        # Configure the mock to return a simple string for case_model_id to prevent JSON serialization errors.
        self.mock_agent_manager.case_model_id = "mock/test-model"

        self.mock_file_system_manager = MagicMock()
        self.mock_command_executor = MagicMock()
        self.mock_prompts = MagicMock()
        self.mock_progress_callback = MagicMock()
        self.mock_request_network_retry_cb = AsyncMock()

        # CRITICAL FIX: Configure the mock file system manager's project_root to be a real Path object.
        self.mock_file_system_manager.project_root = self.temp_dir

        # Configure the mock to return a valid 3-element tuple for apply_atomic_file_updates.
        # This fixes the "not enough values to unpack" ValueError.
        self.mock_file_system_manager.apply_atomic_file_updates.return_value = (True, ["app/urls.py"], {"app/urls.py": Path("/fake/path/app/urls.py.bak")})

        # Configure the mock for read_file to prevent malformed prompts
        self.mock_file_system_manager.read_file.return_value = "import django\n# some original code to be fixed"

        # Mock the planner to return a predictable plan
        self.mock_planner = MagicMock()
        self.mock_planner.create_plan.return_value = [
            FixLogicTask(
                original_error=ErrorRecord(error_type=ErrorType.LogicError, file_path="app/urls.py", message="Test error", command="test"),
                description="A test fix",
                files_to_fix=["app/urls.py"]
            )
        ]

    def tearDown(self):
        """Clean up the temporary directory after each test."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)


    @patch('src.core.remediation_manager.RemediationPlanner')
    def test_remediate_receives_error_records(self, MockRemediationPlanner):
        """
        Tests that the RemediationManager.remediate method correctly receives
        the error_records list and processes it.
        """
        # Arrange
        MockRemediationPlanner.return_value = self.mock_planner

        # Instantiate the RemediationManager with our mocks
        remediation_manager = RemediationManager(
            agent_manager=self.mock_agent_manager,
            file_system_manager=self.mock_file_system_manager,
            command_executor=self.mock_command_executor,
            prompts=self.mock_prompts,
            progress_callback=self.mock_progress_callback,
            request_network_retry_cb=self.mock_request_network_retry_cb,
            remediation_config={'allow_fixlogic': True} # Enable the fix type
        )

        # Create a sample list of ErrorRecord objects, just like the analyzer would
        sample_error_records = [
            ErrorRecord(
                error_type=ErrorType.LogicError,
                file_path="calculator/test/test_calculation_logic.py",
                line_number=26,
                message="django.urls.exceptions.NoReverseMatch: Reverse for 'calculate' not found.",
                command="python manage.py test"
            )
        ]
        
        # Create a mock project state
        mock_project_state = ProjectState(
            project_name="test_project",
            framework="django",
            root_path="/fake/path"
        )

        # Mock the LLM call within the remediation manager to avoid real API calls
        remediation_manager._call_llm_with_error_handling = AsyncMock(
            return_value={'content': '<file_content path="app/urls.py"><![CDATA[corrected_code]]></file_content>'}
        )
        # Mock the verification step to simulate success
        remediation_manager._verify_fix = MagicMock(
            return_value=MagicMock(exit_code=0, stdout="Success", stderr="")
        )

        # Act
        # Run the async remediate method
        result = asyncio.run(remediation_manager.remediate(
            command="python manage.py test",
            initial_error_records=sample_error_records,
            project_state=mock_project_state
        ))

        # Assert
        self.assertTrue(result, "Remediation should return True on success")
        
        # The most important assertion: check that create_plan was called with our records
        self.mock_planner.create_plan.assert_called_once()
        call_args, _ = self.mock_planner.create_plan.call_args
        self.assertEqual(len(call_args[0]), 1, "create_plan should have been called with one error record")
        self.assertIsInstance(call_args[0][0], ErrorRecord, "The item passed to create_plan should be an ErrorRecord")

if __name__ == '__main__':
    unittest.main()
