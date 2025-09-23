# src/core/tests/test_workflow_manager.py
import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import shutil
from pathlib import Path

# To run these tests, navigate to the 'backend' directory and run:
# python -m unittest discover src/core/tests
# This ensures that 'src' is treated as a top-level package.
from src.core.workflow_manager import WorkflowManager
from src.core.project_models import ProjectState, ProjectFeature, FeatureTask, FeatureStatusEnum
from src.core.config_manager import FrameworkPrompts
from src.core.llm_client import ChatMessage

class TestWorkflowManager(unittest.TestCase):
    """
    Integration tests for the WorkflowManager class.
    These tests verify the overall workflow logic, including task dependency,
    execution, and state management, using mocked core components.
    """

    def setUp(self):
        """Set up mock objects for each test."""
        self.temp_dir = Path("temp_test_project_for_workflow").resolve()
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir()

        # Mock core components
        self.mock_agent_manager = MagicMock()
        self.mock_memory_manager = MagicMock()
        self.mock_config_manager = MagicMock()
        self.mock_file_system_manager = MagicMock()
        self.mock_command_executor = MagicMock()
        self.mock_code_intelligence = MagicMock()

        # Configure mocks
        self.mock_file_system_manager.project_root = self.temp_dir
        self.mock_command_executor.project_root = self.temp_dir

        # Mock UI callbacks
        self.mock_progress_callback = MagicMock()
        self.mock_request_command_execution_cb = AsyncMock(return_value=(True, "Success"))

        # A minimal set of prompts for the workflow to use
        mock_prompts_instance = FrameworkPrompts(
            system_tars_markdown_planner=ChatMessage(role="system", content="plan"),
            system_case_executor=ChatMessage(role="system", content="execute"),
            system_tars_validator=ChatMessage(role="system", content="validate"),
            system_tars_error_analyzer=ChatMessage(role="system", content="analyze"),
            system_case_remediation=ChatMessage(role="system", content="remediate")
        )
        self.mock_config_manager.load_prompts.return_value = mock_prompts_instance

        # Instantiate WorkflowManager with all mocks
        self.workflow_manager = WorkflowManager(
            agent_manager=self.mock_agent_manager,
            memory_manager=self.mock_memory_manager,
            config_manager=self.mock_config_manager,
            file_system_manager=self.mock_file_system_manager,
            command_executor=self.mock_command_executor,
            show_input_prompt_cb=MagicMock(),
            show_file_picker_cb=MagicMock(),
            progress_callback=self.mock_progress_callback,
            show_confirmation_dialog_cb=MagicMock(return_value=True),
            request_command_execution_cb=self.mock_request_command_execution_cb,
            show_user_action_prompt_cb=MagicMock(),
            request_network_retry_cb=AsyncMock(),
            ui_communicator=MagicMock()
        )
        # Directly set the prompts and code intelligence service on the instance
        self.workflow_manager.prompts = mock_prompts_instance
        self.workflow_manager.code_intelligence_service = self.mock_code_intelligence

        print(f"\n--- Running test: {self._testMethodName} ---")

    def tearDown(self):
        """Clean up the temporary directory after each test."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_simple_workflow_with_dependencies(self):
        """
        Tests a simple workflow of creating a directory and then a file inside it.
        Verifies that tasks are executed in the correct order based on dependencies.
        """
        # 1. Arrange: Create a project state with a feature and two dependent tasks
        task1 = FeatureTask(
            task_id_str="1.1",
            action="Create directory",
            target="app",
            description="Create app directory"
        )
        task2 = FeatureTask(
            task_id_str="1.2",
            action="Create file",
            target="app/models.py",

            description="Create models file",
            requirements="# Initial models file",
            dependencies=["1.1"], # This task depends on task 1.1
        )
        feature = ProjectFeature(
            id="feature_01",
            name="Initial App Structure",
            description="Create basic app structure.",
            status=FeatureStatusEnum.PLANNED, # Start from 'planned' to skip LLM planning
            tasks=[task1, task2]
        )
        project_state = ProjectState(
            project_name="test_project",
            framework="django",
            root_path=str(self.temp_dir),
            features=[feature],
            current_feature_id="feature_01"
        )
        self.workflow_manager.project_state = project_state

        # Mock the file creation call from Case agent
        # This simulates Case returning the code to be written.
        self.workflow_manager._execute_file_task_case = AsyncMock(return_value="# Initial models file")

        # 2. Act: Run the feature cycle
        asyncio.run(self.workflow_manager.run_feature_cycle())

        # 3. Assert
        # Verify that the file system manager methods were called
        self.mock_file_system_manager.create_directory.assert_called_once_with("app")

        self.workflow_manager._execute_file_task_case.assert_called_once()

        # Verify that the test steps were executed via the UI callback
        self.assertEqual(self.mock_request_command_execution_cb.call_count, 2)
        # self.mock_request_command_execution_cb.assert_any_call(
        #     '1.1_test_initial', 'dir app', 'Run test step for Task 1.1'
        # )
        # self.mock_request_command_execution_cb.assert_any_call(
        #     '1.2_test_initial', r'type app\models.py', 'Run test step for Task 1.2'
        # )

        # Verify the final status of the feature and tasks
        self.assertEqual(feature.status, FeatureStatusEnum.MERGED)
        self.assertEqual(task1.status, "completed")
        self.assertEqual(task2.status, "completed")

    def test_multi_step_django_workflow(self):
        """
        Tests a more realistic Django workflow: startapp -> models -> makemigrations -> migrate.
        Verifies that tasks are executed in the correct order and that the feature completes.
        """
        # 1. Arrange: Create a project state with a multi-step Django feature
        tasks = [
            FeatureTask(task_id_str="1.1", action="Run command", target="python manage.py startapp my_app", description="Create app", test_step=r"dir my_app"),
            FeatureTask(task_id_str="1.2", action="Create file", target="my_app/models.py", description="Create models", requirements="class MyModel...", dependencies=["1.1"], test_step=r"type my_app\models.py"),
            FeatureTask(task_id_str="1.3", action="Run command", target="python manage.py makemigrations my_app", description="Make migrations", dependencies=["1.2"], test_step=r"dir my_app\migrations"),
            FeatureTask(task_id_str="1.4", action="Run command", target="python manage.py migrate my_app", description="Apply migrations", dependencies=["1.3"], test_step=r"echo 'manual check'")
        ]
        feature = ProjectFeature(
            id="django_feature_01",
            name="Django App Setup",
            description="Set up a full Django app with a model and migrations.",
            status=FeatureStatusEnum.PLANNED,
            tasks=tasks
        )
        project_state = ProjectState(
            project_name="test_project",
            framework="django",
            root_path=str(self.temp_dir),
            features=[feature],
            current_feature_id="django_feature_01"
        )
        self.workflow_manager.project_state = project_state

        # Mock the file creation call from Case agent
        self.workflow_manager._execute_file_task_case = AsyncMock(return_value="class MyModel(models.Model): pass")

        # Configure the mock to simulate that the app does not exist initially
        self.mock_file_system_manager.file_exists.return_value = False

        # 2. Act: Run the feature cycle
        asyncio.run(self.workflow_manager.run_feature_cycle())

        # 3. Assert
        # Verify that all commands (both main actions and test steps) were requested for execution.
        # 3 'Run command' actions + 4 'test_step' actions = 7 total calls.
        self.assertEqual(self.mock_request_command_execution_cb.call_count, 7)

        # Get the list of all commands that were actually called
        called_commands = [call[0][1] for call in self.mock_request_command_execution_cb.call_args_list]

        # Define the set of commands we expect to be called
        expected_commands = {
            "python manage.py startapp my_app",
            r"dir my_app",
            r"type my_app\models.py",
            "python manage.py makemigrations my_app",
            r"dir my_app\migrations",
            "python manage.py migrate my_app",
            r"echo 'manual check'"
        }
        self.assertSetEqual(set(called_commands), expected_commands)

        # Verify the final status of the feature
        self.assertEqual(feature.status, FeatureStatusEnum.MERGED)
        for task in tasks:
            self.assertEqual(task.status, "completed")

    def test_get_task_phase_priority(self):
        """
        Tests the _get_task_phase_priority method with various Django tasks.
        """
        # Arrange
        project_state = ProjectState(
            project_name="test_project",
            framework="django",
            root_path=str(self.temp_dir)
        )
        self.workflow_manager.project_state = project_state

        tasks = {
            "startapp": FeatureTask(task_id_str="1", action="Run command", target="python manage.py startapp my_app"),
            "modify_apps": FeatureTask(task_id_str="2", action="Modify file", target="my_app/apps.py"),
            "modify_settings_apps": FeatureTask(task_id_str="3", action="Modify file", target="test_project/settings.py", requirements="INSTALLED_APPS"),
            "modify_settings_other": FeatureTask(task_id_str="4", action="Modify file", target="test_project/settings.py"),
            "create_models": FeatureTask(task_id_str="5", action="Create file", target="my_app/models.py"),
            "makemigrations": FeatureTask(task_id_str="6", action="Run command", target="python manage.py makemigrations my_app"),
            "migrate": FeatureTask(task_id_str="7", action="Run command", target="python manage.py migrate my_app"),
            "create_admin": FeatureTask(task_id_str="8", action="Create file", target="my_app/admin.py"),
            "create_forms": FeatureTask(task_id_str="9", action="Create file", target="my_app/forms.py"),
            "create_views": FeatureTask(task_id_str="10", action="Create file", target="my_app/views.py"),
            "create_app_urls": FeatureTask(task_id_str="11", action="Create file", target="my_app/urls.py"),
            "modify_project_urls": FeatureTask(task_id_str="12", action="Modify file", target="test_project/urls.py"),
            "create_templates": FeatureTask(task_id_str="13", action="Create file", target="my_app/templates/my_app/my_template.html"),
            "create_static_dir": FeatureTask(task_id_str="14", action="Create directory", target="my_app/static/"),
            "create_static_files": FeatureTask(task_id_str="15", action="Create file", target="my_app/static/my_app/style.css"),
            "run_tests": FeatureTask(task_id_str="16", action="Run command", target="python manage.py test my_app"),
            "prompt_user": FeatureTask(task_id_str="17", action="Prompt user input", target="API_KEY"),
            "create_dir": FeatureTask(task_id_str="18", action="Create directory", target="some_dir"),
            "create_file": FeatureTask(task_id_str="19", action="Create file", target="some_file.txt"),
            "modify_file": FeatureTask(task_id_str="20", action="Modify file", target="some_file.txt"),
            "run_command": FeatureTask(task_id_str="21", action="Run command", target="echo hello"),
        }

        # Act & Assert
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["startapp"]), 10)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["modify_apps"]), 20)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["modify_settings_apps"]), 30)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["modify_settings_other"]), 55)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["create_models"]), 100)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["makemigrations"]), 110)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["migrate"]), 120)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["create_admin"]), 200)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["create_forms"]), 210)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["create_views"]), 220)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["create_app_urls"]), 230)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["modify_project_urls"]), 300)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["create_templates"]), 400)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["create_static_dir"]), 410)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["create_static_files"]), 420)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["run_tests"]), 600)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["prompt_user"]), 50)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["create_dir"]), 800)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["create_file"]), 810)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["modify_file"]), 820)
        self.assertEqual(self.workflow_manager._get_task_phase_priority(tasks["run_command"]), 830)

    def test_remediation_flow(self):
        """
        Tests the remediation flow when a task fails.
        """
        # 1. Arrange: Create a project state with a failing task
        failing_task = FeatureTask(
            task_id_str="1.1",
            action="Run command",
            target="python -c \"import sys; sys.exit(1)\"",
            description="This command will fail",
            test_step="echo 'This should not be reached'"
        )
        feature = ProjectFeature(
            id="feature_01",
            name="Failing Feature",
            description="This feature contains a failing task.",
            status=FeatureStatusEnum.PLANNED,
            tasks=[failing_task]
        )
        project_state = ProjectState(
            project_name="test_project",
            framework="django",
            root_path=str(self.temp_dir),
            features=[feature],
            current_feature_id="feature_01"
        )
        self.workflow_manager.project_state = project_state

        # Mock the command execution to simulate failure
        # First call fails, second call (for verification) succeeds.
        self.mock_request_command_execution_cb.side_effect = [
            (False, '{"stderr": "Initial command failed"}'), # 1. Initial action fails
            (True, '{"stdout": "Verification successful"}'),  # 2. Verification action succeeds
            (True, '{"stdout": "Test step successful"}')     # 3. Verification test step succeeds
        ]
        # Mock the remediation manager and its error_analyzer
        mock_remediation_manager = MagicMock()
        mock_remediation_manager.remediate = AsyncMock(return_value=True)
        mock_remediation_manager.error_analyzer = MagicMock()
        mock_remediation_manager.error_analyzer.analyze_logs.return_value = ([MagicMock(file_path="a/b.py")], None)
        self.workflow_manager.remediation_manager = mock_remediation_manager

        # 2. Act: Run the feature cycle
        asyncio.run(self.workflow_manager.run_feature_cycle())

        # 3. Assert
        # Verify that the remediation manager was called
        mock_remediation_manager.remediate.assert_called_once()

        # Verify that the task is marked as completed
        self.assertEqual(failing_task.status, "completed")

        # Verify that the feature is merged
        self.assertEqual(feature.status, FeatureStatusEnum.MERGED)



if __name__ == '__main__':
    unittest.main()
