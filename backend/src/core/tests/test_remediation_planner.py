# src/core/tests/test_remediation_planner.py
import unittest
import shutil
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.core.remediation_planner import RemediationPlanner
from src.core.project_models import ErrorRecord, ErrorType, ProjectState, FixLogicTask


class TestRemediationPlannerStrategies(unittest.TestCase):
    """
    Unit tests for the RemediationPlanner class.
    These tests ensure that specific error types are correctly diagnosed and
    that the resulting remediation tasks are targeted and comprehensive.
    """

    def setUp(self):
        """Set up a temporary project directory and a planner instance for each test."""
        self.test_dir = Path("temp_test_project_for_planner").resolve()
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True, exist_ok=True)

        self.planner = RemediationPlanner()
        print(f"\n--- Running test: {self._testMethodName} ---")

    def tearDown(self):
        """Clean up the temporary directory."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_strategy_no_reverse_match_plan(self):
        """
        Verify that a NoReverseMatch error generates a multi-file FixLogicTask
        that includes the root urls.py, app urls.py, and app views.py.
        """
        # Arrange
        # 1. Mock the project state
        mock_project_state = ProjectState(
            project_name="my_project",
            framework="django",
            root_path=str(self.test_dir) # Use the real temporary directory
        )

        # 2. Create the dummy files and directories the planner will look for.
        (self.test_dir / "my_project").mkdir()
        (self.test_dir / "my_project" / "settings.py").write_text("ROOT_URLCONF = 'my_project.urls'")
        (self.test_dir / "my_project" / "urls.py").write_text("urlpatterns = [path('calculator/', include('calculator.urls'))]")
        (self.test_dir / "calculator").mkdir()
        (self.test_dir / "calculator" / "urls.py").write_text("app_name = 'calculator'\nurlpatterns = []")
        (self.test_dir / "calculator" / "views.py").touch()
        (self.test_dir / "calculator" / "templates" / "calculator").mkdir(parents=True, exist_ok=True)
        (self.test_dir / "calculator" / "templates" / "calculator" / "index.html").write_text("{% url 'calculator:add' %}")

        # 3. Create a sample NoReverseMatch error record
        error_message = (
            "django.urls.exceptions.NoReverseMatch: Reverse for 'add' not found. "
            "'add' is not a valid view function or pattern name."
        )
        error_record = ErrorRecord(
            error_type=ErrorType.LogicError,
            file_path="calculator/templates/calculator/index.html", # This path is relative to project root
            line_number=10,
            message=error_message,
            summary="NoReverseMatch: Reverse for 'add' not found.",
            command="python manage.py test"
        )

        # Act
        # Call the specific strategy method we want to test.
        tasks, remaining_errors = self.planner._apply_no_reverse_match_strategy([error_record], mock_project_state) # type: ignore

        # Assert
        self.assertEqual(len(tasks), 1, "The planner should have created one task for NoReverseMatch.")
        self.assertEqual(len(remaining_errors), 0, "The NoReverseMatch error should be consumed.")

        task = tasks[0]
        self.assertIsInstance(task, FixLogicTask)

        # Check that the task targets the correct files for the fix
        expected_files_to_fix = sorted([
            "my_project/urls.py",    # Root urls.py
            "calculator/urls.py",    # App's urls.py
            "calculator/views.py",   # App's views.py,
            "calculator/templates/calculator/index.html" # The template that triggered the error
        ])
        self.assertEqual(sorted(task.files_to_fix), expected_files_to_fix)

        # Check that the description provides a good diagnosis
        self.assertIn("DIAGNOSIS: The URL name 'add' could not be found", task.description)
        self.assertIn("`calculator/urls.py`", task.description)
        self.assertIn("`my_project/urls.py`", task.description)
        self.assertIn("`calculator/views.py`", task.description)

    def test_strategy_template_does_not_exist(self):
        """
        Verify the 'TemplateDoesNotExist' strategy creates a FixLogicTask
        targeting both the view and the missing template file.
        """
        # Arrange
        mock_project_state = ProjectState(
            project_name="test_project",
            framework="django",
            root_path=str(self.test_dir)
        )
        error_message = "django.template.exceptions.TemplateDoesNotExist: my_app/missing_template.html"
        error_record = ErrorRecord(
            error_type=ErrorType.TemplateError,
            file_path="my_app/views.py", # The view that tried to render the template
            line_number=42,
            message=error_message,
            summary="TemplateDoesNotExist: my_app/missing_template.html",
            command="python manage.py test"
        )

        # Act
        tasks, remaining_errors = self.planner._apply_template_does_not_exist_strategy([error_record], mock_project_state)

        # Assert
        self.assertEqual(len(tasks), 1, "Should create exactly one remediation task.")
        self.assertEqual(len(remaining_errors), 0, "The error should be consumed.")
        
        task = tasks[0]
        self.assertIsInstance(task, FixLogicTask)

        # Check that the task targets both the view and the missing template
        expected_files = sorted(["my_app/views.py", "my_app/missing_template.html"])
        self.assertEqual(sorted(task.files_to_fix), expected_files)

        # Check that the description is helpful
        self.assertIn("`my_app/views.py`", task.description)
        self.assertIn("`my_app/missing_template.html`", task.description)
        self.assertIn("Create the missing template file", task.description)
        self.assertIn("Correct the view", task.description)

    def test_strategy_assertion_error_in_view_test(self):
        """
        Verify the 'AssertionError' strategy creates a FixLogicTask targeting
        both the test file and the corresponding application view file.
        """
        # Arrange
        mock_project_state = ProjectState(
            project_name="test_project",
            framework="django",
            root_path=str(self.test_dir)
        )
        error_message = (
            "FAIL: test_home_page_status_code (products.test.test_views.TestProductViews)\n"
            "AssertionError: 404 != 200"
        )
        error_record = ErrorRecord(
            error_type=ErrorType.TestFailure,
            file_path="products/test/test_views.py", # The test file where the error occurred
            line_number=30,
            message=error_message,
            summary="AssertionError: 404 != 200",
            command="python manage.py test products"
        )

        # Act
        tasks, remaining_errors = self.planner._apply_assertion_error_strategy([error_record], mock_project_state)

        # Assert
        self.assertEqual(len(tasks), 1, "Should create exactly one remediation task.")
        self.assertEqual(len(remaining_errors), 0, "The error should be consumed.")
        
        task = tasks[0]
        self.assertIsInstance(task, FixLogicTask)

        # Check that the task targets both the view file and the test file
        expected_files = sorted(["products/views.py", "products/test/test_views.py"])
        self.assertEqual(sorted(task.files_to_fix), expected_files)

        # Check that the description gives the LLM permission to fix the test
        self.assertIn("`products/test/test_views.py`", task.description)
        self.assertIn("`products/views.py`", task.description)
        self.assertIn("You have permission to modify the test file", task.description)

    def test_strategy_str_representation_error(self):
        """
        Verify that an AssertionError in a test named 'test_str_representation'
        correctly generates a FixLogicTask targeting the model's __str__ method.
        """
        # Arrange
        mock_project_state = ProjectState(
            project_name="test_project",
            framework="django",
            root_path=str(self.test_dir)
        )
        # 2. Create a sample error record for a __str__ test failure
        error_message = (
            "FAIL: test_str_representation (products.test.test_models.TestProductModel)\n"
            "Traceback (most recent call last):\n"
            "  File \"/fake/project/root/products/test/test_models.py\", line 25, in test_str_representation\n"
            "    self.assertEqual(str(self.product), 'Test Product')\n"
            "AssertionError: 'Product object (1)' != 'Test Product'"
        )
        error_record = ErrorRecord(
            error_type=ErrorType.TestFailure,
            file_path="products/test/test_models.py", # The test file where the error occurred
            line_number=25,
            message=error_message,
            summary="AssertionError: 'Product object (1)' != 'Test Product'",
            command="python manage.py test products"
        )

        # Act
        # Call the specific strategy we want to test
        tasks, remaining_errors = self.planner._apply_str_representation_strategy([error_record], mock_project_state)

        # Assert
        self.assertEqual(len(tasks), 1, "Should create exactly one remediation task.")
        self.assertEqual(len(remaining_errors), 0, "The error should be handled and not remain.")

        task = tasks[0]
        self.assertIsInstance(task, FixLogicTask)

        # Check that the task targets the correct models.py file
        # FIX: Normalize path separators for cross-platform compatibility
        self.assertEqual([p.replace('\\', '/') for p in task.files_to_fix], ["products/models.py"])

        # Check that the description is helpful
        self.assertIn("string representation of the 'Product' model is incorrect", task.description)
        self.assertIn("add or correct the `__str__` method", task.description)

if __name__ == '__main__':
    unittest.main()