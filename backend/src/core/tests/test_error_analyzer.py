# src/core/tests/test_error_analyzer.py
import unittest
import shutil
from pathlib import Path

from src.core.error_analyzer import ErrorAnalyzer
from src.core.file_system_manager import FileSystemManager
from src.core.project_models import ErrorType

class TestErrorAnalyzer(unittest.TestCase):
    """
    Unit tests for the ErrorAnalyzer class.
    These tests verify that different types of raw error logs are correctly
    parsed into structured ErrorRecord objects.
    """

    def setUp(self):
        """Set up a temporary project directory and the analyzer instance."""
        self.test_dir = Path("temp_test_project_for_analyzer").resolve()
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir()

        self.fs_manager = FileSystemManager(self.test_dir)

        # Create dummy files that the tracebacks will reference
        self.fs_manager.create_directory("my_app/templates/my_app")
        self.fs_manager.write_file("my_app/templates/my_app/my_template.html", "<html></html>")
        self.fs_manager.write_file("my_app/views.py", "from django.http import HttpResponse")
        self.fs_manager.create_directory("my_project")
        self.fs_manager.write_file("my_project/urls.py", "from django.urls import path")
        self.fs_manager.write_file("my_app/utils.py", "def my_func(arg1, arg2)") # For syntax error test

        self.analyzer = ErrorAnalyzer(project_root=self.test_dir, file_system_manager=self.fs_manager)
        print(f"\n--- Running test: {self._testMethodName} ---")

    def tearDown(self):
        """Clean up the temporary directory."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_parse_django_no_reverse_match(self):
        """
        Verify that a Django NoReverseMatch error is parsed correctly,
        including extracting hints for the planner.
        """
        # Arrange: A sample stderr log for a NoReverseMatch error
        stderr_log = f"""
Traceback (most recent call last):
  File "{self.test_dir / 'my_app' / 'views.py'}", line 50, in some_view
    return render(request, 'my_app/my_template.html', context)
  File "{self.test_dir / 'my_app' / 'templates' / 'my_app' / 'my_template.html'}", line 10, in render
    <a href="{{% url 'my_app:non_existent_view' %}}">Link</a>
django.urls.exceptions.NoReverseMatch: Reverse for 'non_existent_view' not found. 'my_app' is not a registered namespace.
"""
        # Act
        error_records, _ = self.analyzer.analyze_logs("python manage.py test", "", stderr_log, 1)

        # Assert
        self.assertEqual(len(error_records), 1)
        error = error_records[0]

        self.assertEqual(error.error_type, ErrorType.LogicError)
        # The most relevant file is the template where the error occurred
        self.assertEqual(Path(error.file_path), Path("my_app/templates/my_app/my_template.html"))
        self.assertEqual(error.line_number, 10)
        self.assertIn("NoReverseMatch", error.summary)
        self.assertIsNotNone(error.hints)
        self.assertIn("candidate_files", error.hints)
        # Check that the analyzer correctly identified candidate files for the fix
        self.assertIn("my_app/urls.py", error.hints['candidate_files'])
        self.assertIn("my_app/views.py", error.hints['candidate_files'])

    def test_parse_simple_syntax_error(self):
        """
        Verify that a basic Python SyntaxError is parsed correctly.
        """
        # Arrange: A sample stderr log for a SyntaxError
        stderr_log = f"""
  File "{self.test_dir / 'my_app' / 'utils.py'}", line 5
    def my_func(arg1, arg2)
                           ^
SyntaxError: expected ':'
"""
        # Act
        error_records, _ = self.analyzer.analyze_logs("python -m py_compile my_app/utils.py", "", stderr_log, 1)

        # Assert
        self.assertEqual(len(error_records), 1)
        error = error_records[0]

        self.assertEqual(error.error_type, ErrorType.SyntaxError)
        self.assertEqual(Path(error.file_path), Path("my_app/utils.py"))
        self.assertEqual(error.line_number, 5)
        self.assertEqual(error.summary, "SyntaxError: expected ':'")
        self.assertIsNone(error.hints) # No special hints for a simple syntax error

    def test_parse_attribute_error(self):
        """
        Verify that a Django AttributeError is correctly parsed.
        This is a common error when a view is not defined but referenced in urls.py.
        """
        # Arrange: A sample stderr log for an AttributeError
        # This simulates 'my_app/urls.py' trying to import a view that doesn't exist
        # in 'my_app/views.py'.
        stderr_log = f"""
Traceback (most recent call last):
  File "{self.test_dir / 'my_project' / 'urls.py'}", line 5, in <module>
    path('my_app/', include('my_app.urls')),
  File "{self.test_dir / 'my_app' / 'urls.py'}", line 4, in <module>
    path('', views.home_view, name='home'),
AttributeError: module 'my_app.views' has no attribute 'home_view'
"""
        # Act
        error_records, _ = self.analyzer.analyze_logs("python manage.py runserver", "", stderr_log, 1)

        # Assert
        self.assertEqual(len(error_records), 1)
        error = error_records[0]

        self.assertEqual(error.error_type, ErrorType.LogicError)
        self.assertEqual(Path(error.file_path), Path("my_app/urls.py"))
        self.assertEqual(error.line_number, 4)
        self.assertEqual(error.summary, "AttributeError: module 'my_app.views' has no attribute 'home_view'")

if __name__ == '__main__':
    unittest.main()