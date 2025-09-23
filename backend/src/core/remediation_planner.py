# backend/src/core/remediation_planner.py
from pathlib import Path
import logging
import difflib
from typing import List, Optional, Tuple, Dict, Callable, cast, Any
import re
# Assuming ErrorRecord is in error_analyzer.py
from pydantic import ValidationError

from .error_analyzer import ErrorRecord
from .project_models import (
    ErrorType,
    FixLogicTask,
    AnyRemediationTask,
    FixBundleTask,
    CreateFileTask,
    FixSyntaxTask,
    FixCommandTask,
    ProjectState,

)
from .file_system_manager import FileSystemManager

logger = logging.getLogger(__name__)

# Type hint for a strategic planner function
StrategicPlanner = Callable[[List[ErrorRecord], ProjectState], Tuple[List[AnyRemediationTask], List[ErrorRecord]]]


class RemediationPlanner:
    """
    Analyzes a list of structured errors and creates a strategic, prioritized plan
    of remediation tasks to fix them.

    This class acts as the "brain" of the self-healing mechanism. It uses a series
    of specialized "strategic planners" to diagnose common, high-confidence error
    patterns (like Django's NoReverseMatch). For errors that don't match a specific
    strategy, it falls back to creating more generic fix tasks.
    """

    # --- NEW: Define the strategic planners as a class attribute ---
    STRATEGIC_PLANNERS: List[Callable[..., Tuple[List[AnyRemediationTask], List[ErrorRecord]]]] = [
        # This list defines the order of specialist functions that attempt to handle
        # specific, common error patterns. The planner will try each of these in
        # sequence. If a strategy handles an error, it's removed from the list
        # for subsequent strategies. This prioritizes high-confidence fixes.
        # Each function takes (self, errors, project_state) and returns (tasks, remaining_errors)
        lambda self, errors, state: self._apply_no_reverse_match_strategy(errors, state),
        lambda self, errors, state: self._apply_template_does_not_exist_strategy(errors, state),
        lambda self, errors, state: self._apply_assertion_error_strategy(errors, state),
        lambda self, errors, state: self._apply_str_representation_strategy(errors, state),
        lambda self, errors, state: self._apply_attribute_error_strategy(errors, state),
        lambda self, errors, state: self._apply_import_error_strategy(errors, state),
        lambda self, errors, state: self._apply_test_failure_redirection_strategy(errors, state),
    ]

    def _get_file_info(self, project_state: ProjectState, file_path_str: str) -> Optional[Any]:
        """
        A helper function to safely retrieve structured file information
        from the project's code map.
        """
        if not project_state.project_structure_map:
            return None
        for app_info in project_state.project_structure_map.apps.values():
            if file_path_str in app_info.files:
                return app_info.files[file_path_str]
        return None

    def _create_no_reverse_match_plan(
        self, error_record: ErrorRecord, project_state: ProjectState, fsm: FileSystemManager
    ) -> Optional[FixLogicTask]:
        """
        Creates a single, high-confidence, multi-file task for NoReverseMatch errors.

        This is a powerful diagnostic function. It understands that a NoReverseMatch error
        can stem from issues in multiple files (the template, the app's urls.py, the
        project's urls.py, or the view itself). It bundles all these files into a
        single `FixLogicTask` to give the LLM maximum context to solve the problem.
        """
        if "NoReverseMatch" not in error_record.message:
            return None

        # 1. Enhanced Extraction of URL name / namespace.
        # This new regex is more robust. It prioritizes finding the actual `reverse('...')`
        # call within the traceback, which is more reliable than just the final error message.
        # 1. Enhanced Extraction of URL name / namespace from the full error message.
        # This regex is more robust, trying multiple patterns to find the URL name.
        url_name_match = re.search(
            r"reverse\(['\"]([^'\"]+)['\"]\)|"  # Look for reverse('name') first
            r"Reverse for '([^']*)' not found|"      # Fallback to error message
            r"'([^']*)' is not a registered namespace", # Fallback to error message
            error_record.message
        )
        if not url_name_match:
            logger.warning("Could not extract a URL name or namespace from the NoReverseMatch error.")
            logger.warning("Could not extract a URL name or namespace from the NoReverseMatch error message.")
            return None

        # Find the first non-None captured group
        full_url_name = next((g for g in url_name_match.groups() if g is not None), None)
        if not full_url_name:
            logger.warning("Regex matched but no URL name/namespace group was captured.")
            return None

        logger.info(f"Detected NoReverseMatch error for URL name/namespace: '{full_url_name}'. Analyzing URL structure.")

        # --- FIX: Correctly parse namespace and view_name, then infer namespace if missing ---
        # A URL name can be 'namespace:view_name' or just 'view_name'.
        app_namespace, view_name = full_url_name.split(":", 1) if ":" in full_url_name else (None, full_url_name)

        # If a namespace wasn't explicitly part of the URL name, infer it from the file path
        # where the error occurred. This is a powerful heuristic.
        if not app_namespace and error_record.file_path:
            path_parts = Path(error_record.file_path).parts
            if path_parts:
                app_namespace = path_parts[0]
                logger.info(f"Inferred app namespace '{app_namespace}' from error file path '{error_record.file_path}'.")

        if not project_state.project_name or not app_namespace:
            logger.warning("Cannot create NoReverseMatch plan: project_name or app_namespace is not available.")
        if not project_state.project_name:
            logger.warning("Cannot create NoReverseMatch plan: project_name is not available.")
            return None

        # 3. Find the root urls.py by reading the ROOT_URLCONF from the settings file.
        settings_file_path = f"{project_state.project_name}/settings.py"
        try:
            settings_content = fsm.read_file(settings_file_path)
        except FileNotFoundError:
            logger.warning(f"Could not find settings file at {settings_file_path}. Cannot create NoReverseMatch plan.")
            return None

        root_urlconf_match = re.search(r"ROOT_URLCONF\s*=\s*'([^']+)'", settings_content)
        if not root_urlconf_match:
            logger.warning(f"Could not find ROOT_URLCONF in {settings_file_path}. Cannot create plan.")
            return None
        root_urlconf_module = root_urlconf_match.group(1)
        root_urlconf_path = root_urlconf_module.replace('.', '/') + '.py'
        logger.info(f"Discovered root urlconf path: {root_urlconf_path}")
        try:
            root_urls_content = fsm.read_file(root_urlconf_path)
        except FileNotFoundError:
            logger.warning(f"Could not find root urlconf file at {root_urlconf_path}. Cannot create NoReverseMatch plan.")
            return None

        # 4. Diagnose the specific failure and build a comprehensive description for the LLM.
        files_to_fix = {root_urlconf_path} # Start with the root urls.py
        descriptions = []

        # --- FUZZY MATCHING: Find the most likely app name, correcting for typos ---
        # This helps if the user made a typo in a template, e.g., {% url 'calulator:add' %}
        discovered_apps = fsm.discover_django_apps()
        app_names = [p.name for p in discovered_apps]

        # --- FIX: Use the error_record.file_path directly if it's an HTML file ---
        template_path_to_add = None
        if error_record.file_path and error_record.file_path.endswith('.html'):
            template_path_to_add = error_record.file_path
        else: # Fallback to regex for other cases
            template_path_match = re.search(r'File "([^"]+\.html)"', error_record.message)
            if template_path_match:
                template_path_to_add = template_path_match.group(1)

        corrected_app_namespace = app_namespace

        # If the detected namespace doesn't match any known app, suggest a correction.
        if app_namespace not in app_names:
            close_matches = difflib.get_close_matches(app_namespace, app_names, n=1, cutoff=0.7)
            if close_matches:
                corrected_app_namespace = close_matches[0]
                descriptions.append(
                    f"DIAGNOSIS (Typo Detected): The URL namespace '{app_namespace}' was not found. "
                    f"A close match '{corrected_app_namespace}' was found and will be used for analysis. "
                    "This might indicate a typo in a template's `{% url %}` tag or in an `include()` statement."
                )
            else:
                descriptions.append(
                    f"DIAGNOSIS: The URL namespace '{app_namespace}' was not found, and no close matches could be identified among existing apps: {app_names}. "
                    "The app may not exist or is not configured correctly."
                )
        
        # --- DIAGNOSIS A: Issues in the root urls.py ---
        
        # Check if the app's URLs are even included in the main project urls.py.
        # Regex to find an include statement for the app, e.g., include('calculator.urls')
        # This is now more flexible to catch typos, using the corrected_app_namespace.
        include_pattern = re.compile(f"include\\(\\s*['\"]{re.escape(corrected_app_namespace)}\\.urls['\"]")
        potential_match = include_pattern.search(root_urls_content)
        
        if potential_match:
            # A1: The app's namespace is included but is missing the `namespace` argument.
            # This is a common cause of NoReverseMatch.
            line_with_include_match = re.search(f"path\\(.*{re.escape(potential_match.group(0))}.*\\)", root_urls_content)
            if line_with_include_match and f"namespace='{corrected_app_namespace}'" not in line_with_include_match.group(0):
                descriptions.append(
                    f"DIAGNOSIS: The URL namespace '{corrected_app_namespace}' is included in `{root_urlconf_path}` but is missing the `namespace` argument. "
                    f"The correct pattern is `path('{corrected_app_namespace}/', include('{corrected_app_namespace}.urls', namespace='{corrected_app_namespace}'))`. "
                    "This is essential for correct URL reversing with namespacing."
                )
        else:
            # A2: The app's urls are not included in the project's urls.py at all.
            descriptions.append(
                f"DIAGNOSIS: The URLs for the '{corrected_app_namespace}' app are not included in the project's main URL configuration (`{root_urlconf_path}`). "
                f"You may need to modify the `urlpatterns` list in `{root_urlconf_path}` to include the app's URLs. "
                f"For example, add: `path('{corrected_app_namespace}/', include('{corrected_app_namespace}.urls'))`. "
                f"Also ensure `from django.urls import include` is present at the top of the file."
            )

        # --- DIAGNOSIS B: Issues in the app's urls.py ---
        # Check the app's own urls.py for missing `app_name` or the specific URL pattern.
        app_urls_path = f"{corrected_app_namespace}/urls.py"
        try:
            app_urls_content = fsm.read_file(app_urls_path)
            files_to_fix.add(app_urls_path) # Add for context even if no errors found in it

            # B1: Is app_name missing?
            if f"app_name = '{corrected_app_namespace}'" not in app_urls_content:
                descriptions.append(
                    f"DIAGNOSIS: The `app_name` variable in `{app_urls_path}` is missing or incorrect. "
                    f"It must be defined as `app_name = '{corrected_app_namespace}'` for namespacing to work correctly."
                )

            # B2: Is the specific view name missing from urlpatterns?
            if view_name and f"name='{view_name}'" not in app_urls_content:
                descriptions.append(
                    f"DIAGNOSIS: The URL name '{view_name}' could not be found in `{app_urls_path}`. "
                    f"You may need to add or correct a `path()` entry in the `urlpatterns` list to have `name='{view_name}'`."
                )
        except Exception as e:
            logger.warning(f"Could not read app urls file at: {app_urls_path}: {e}. This might be the issue.")
            descriptions.append(f"DIAGNOSIS: The app's URL configuration file `{app_urls_path}` could not be read or does not exist. It may need to be created.")
            files_to_fix.add(app_urls_path) # Add for creation

        # --- DIAGNOSIS C: Add the app's views.py for context ---
        # The view file is crucial context, as it contains the function the URL points to.
        app_views_path = f"{corrected_app_namespace}/views.py"
        if fsm.file_exists(app_views_path):
            files_to_fix.add(app_views_path)
            descriptions.append(f"CONTEXT: The related view file `{app_views_path}` is included for context, as it defines the view functions referenced by the URLs.")
        else:
            descriptions.append(f"DIAGNOSIS: The app's view file `{app_views_path}` could not be found. It may need to be created if it's missing.")
            files_to_fix.add(app_views_path)

        # Add the template file that triggered the error to the context.
        if template_path_to_add and fsm.file_exists(template_path_to_add):
            files_to_fix.add(template_path_to_add)
            descriptions.append(f"CONTEXT: The error was triggered from template `{template_path_to_add}`, which is included for context. The typo might be in a `{{% url %}}` tag within this file.")

        # --- Assemble the final multi-file task ---
        # Combine all diagnoses into a single, detailed description for the LLM.
        if not descriptions:
            logger.warning("No specific NoReverseMatch diagnosis could be made, but creating a general task.")
            return None

        final_description = (
            "A `NoReverseMatch` error occurred, which often involves multiple files. "
            "Please analyze the following diagnoses and the content of all provided files to create a comprehensive fix.\n\n"
            + "\n\n".join(descriptions)
        )

        # The primary file for the error record should be the one that is most likely the root cause.
        # The root urls.py is a good candidate as it's the entry point for URL resolution.
        # The root urls.py is a good candidate.
        primary_error_file = root_urlconf_path

        task = FixLogicTask(
            original_error=ErrorRecord(error_type=ErrorType.LogicError, file_path=primary_error_file, message=error_record.message, command=error_record.command),
            description=final_description,
            files_to_fix=sorted(list(files_to_fix)) # Sort for consistent order
        )
        return task

    def _create_str_representation_fixes(
        self, error_records: List[ErrorRecord]
    ) -> Tuple[List[FixLogicTask], List[ErrorRecord]]:
        """
        A specialized strategy to handle test failures related to a model's __str__ method.

        It looks for specific test failure patterns (e.g., test names like `test_str_representation`
        or default error messages like 'Model object (1)') and creates a targeted `FixLogicTask`
        that points directly to the relevant `models.py` file.
        Returns a plan and a list of errors that were NOT handled by this heuristic.
        """
        plan: List[FixLogicTask] = []
        unhandled_errors: List[ErrorRecord] = []

        for error_record in error_records:
            # Regex to find errors like: AssertionError: 'MyModel object (1)' != 'some_value'
            # This is the default string representation if __str__ is not defined.
            default_str_match = re.search(r"AssertionError:.*'([A-Z][a-zA-Z0-9_]+) object \(\d+\)'.*", error_record.message, re.IGNORECASE)
            # --- FIX: Make regex more specific to avoid false positives ---
            is_str_test_failure = (
                "AssertionError" in error_record.message and
                (re.search(r"test_.*__str__", error_record.message, re.IGNORECASE) or
                 re.search(r"test_.*str_representation", error_record.message, re.IGNORECASE))
            )

            if (default_str_match or is_str_test_failure) and error_record.error_type in [ # type: ignore
                ErrorType.TestFailure,
                ErrorType.LogicError,
            # This strategy handles both explicit test failures and other logic errors that match the pattern.
            ]:  # type: ignore
                model_name = None
                model_name_search = None # Initialize model_name_search
                if default_str_match:
                    model_name = default_str_match.group(1)
                elif is_str_test_failure: # Only check this if default_str_match is None
                    # Heuristic: Extract model name from the test class name, e.g., 'TestCalculatorModel' -> 'Calculator'
                    # This more robust regex looks for the pattern `Test<ModelName>Model` or `Test<ModelName>` or `Test<ModelName>View`
                    # within the test class name, which is a common convention.
                    model_name_search = re.search(r"Test([A-Z][a-zA-Z0-9_]+?)(?:Model|View)?\b", error_record.message)
                    if model_name_search:
                        model_name = model_name_search.group(1)

                if not model_name:
                    logger.warning(f"Detected __str__ related failure but could not extract model name from: {error_record.message}")
                    unhandled_errors.append(error_record)
                    continue

                if not error_record.file_path or error_record.file_path == "Unknown":
                    logger.warning(f"Cannot determine app name for __str__ fix because test file path is unknown.")
                    unhandled_errors.append(error_record)
                    continue

                # Infer the app name from the path of the test file that failed.
                test_file_path = Path(error_record.file_path)
                app_name = test_file_path.parts[0] if len(test_file_path.parts) > 1 else None

                if not app_name:
                    logger.warning(
                        f"Could not determine app name from test file path '{error_record.file_path}' to fix __str__ method."
                    )
                    unhandled_errors.append(error_record)
                    continue

                # Construct the path to the likely models.py file.
                model_file_path = str(Path(app_name) / "models.py") # Use pathlib for robustness

                targeted_error = ErrorRecord(
                    error_type=ErrorType.LogicError,
                    file_path=model_file_path,
                    line_number=None,
                    message=f"The __str__ method for the '{model_name}' model is incorrect or missing. It should return a meaningful string representation, likely from one of its fields.",
                    command=error_record.command,
                )

                # Create a detailed task description for the LLM.
                fix_task = FixLogicTask(
                    original_error=targeted_error,
                    description=(
                        f"The test failed because the string representation of the '{model_name}' model is incorrect. "
                        f"Modify the '{model_name}' class in '{model_file_path}' to add or correct the `__str__` method. "
                        f"It should likely return one of the model's fields, such as `self.name`, `self.title`, or `self.display_value`."
                    ),
                    files_to_fix=[model_file_path],
                )

                plan.append(fix_task)
                logger.info(f"Created targeted __str__ fix for '{model_file_path}'.")
            else:
                unhandled_errors.append(error_record)

        return plan, unhandled_errors

    def _create_view_fix_from_test_error(
        self, error_record: ErrorRecord, description: str
    ) -> Optional[FixLogicTask]:
        """A helper to create a FixLogicTask that redirects a test failure to a corresponding view file.

        This is based on the heuristic that a test failure in a file like
        `app/test/test_views.py` is most likely caused by a bug in `app/views.py`.
        It creates a task that gives the LLM context from both files.
        """
        if not error_record.file_path or "test" not in error_record.file_path:
            logger.warning(f"Could not create view fix for error as file_path is missing or not a test file: {error_record.message}")
            return None

        test_file_path = Path(error_record.file_path)
        # Heuristic: assume the view file is in the parent directory of the test file's directory.
        # e.g., 'calculator/test/test_logic.py' -> 'calculator/views.py'
        app_dir = test_file_path.parent.parent
        view_file_path = app_dir / "views.py"

        # The description is critical. It tells the LLM to use the test file as the "source of truth"
        # for what the view's output *should* be.
        # The description is critical. It tells the LLM to use the test file as the "source of truth"
        # for what the view's output *should* be.
        fix_task = FixLogicTask(
            original_error=error_record,  # Keep original error for context
            description=description.format(view_file_path=view_file_path, test_file_path=error_record.file_path),
            files_to_fix=[str(view_file_path)],
        )
        return fix_task

    def _create_redirected_view_fixes(
        self,
        error_records: List[ErrorRecord],
        error_keyword: str,
        description_template: str,
    ) -> Tuple[List[FixLogicTask], List[ErrorRecord]]:
        """Generic helper to create view fixes for specific errors found in test files.

        This function generalizes the pattern of finding a specific error keyword (like 'KeyError')
        in a test failure and creating a `FixLogicTask` using a provided description template.
        Returns a plan and a list of errors that were NOT handled by this heuristic.
        """
        plan: List[FixLogicTask] = []
        unhandled_errors: List[ErrorRecord] = []
        for error_record in error_records:
            is_matching_error_in_test = (
                error_record.error_type == ErrorType.TestFailure
                and error_keyword in error_record.message
                and error_record.file_path
                and "test" in error_record.file_path
            )

            # If the error matches our criteria, create a fix task.
            if is_matching_error_in_test:
                logger.info(
                    f"Detected {error_keyword} in test file '{error_record.file_path}'. Planning a fix for the corresponding view."
                )
                # Create a specific description if needed
                final_description = description_template
                if "{missing_key}" in description_template:
                    # For KeyErrors, we can extract the missing key to make the prompt more specific.
                    key_match = re.search(r'KeyError: \'([^\']*)\'', error_record.message)
                    missing_key = key_match.group(1) if key_match else "unknown"
                    final_description = description_template.format(
                        missing_key=missing_key,
                        test_file_path=error_record.file_path,
                        view_file_path="{view_file_path}", # Keep this as a placeholder for the next step
                    )
                # Prepare arguments for formatting the description template.
                # This avoids runtime KeyErrors if a template doesn't use all possible placeholders.
                format_args = {
                    # These placeholders will be filled in by the `_create_view_fix_from_test_error` helper.
                    "test_file_path": error_record.file_path,
                    "view_file_path": "{view_file_path}",  # This is a placeholder for the next step
                }

                # If the error is a KeyError, extract the missing key and add it to the args.
                if error_keyword == "KeyError":
                    key_match = re.search(r"KeyError: '([^']*)'", error_record.message)
                    format_args["missing_key"] = key_match.group(1) if key_match else "unknown"

                final_description = description_template.format(**format_args)

                fix_task = self._create_view_fix_from_test_error(error_record, final_description)
                if fix_task:
                    plan.append(fix_task)
                else:
                    unhandled_errors.append(error_record)
            else:
                unhandled_errors.append(error_record)
        return plan, unhandled_errors

    def _apply_test_failure_redirection_strategy(
        self, errors: List[ErrorRecord], project_state: ProjectState
    ) -> Tuple[List[AnyRemediationTask], List[ErrorRecord]]:
        """
        A "smart" strategy that catches failures during a 'test' command and redirects the fix.

        It scans the full traceback of an error to find the deepest file path that is
        *within the project* and is a test file. This is powerful because it correctly
        identifies the source of a test failure even if the final exception is raised
        deep inside a library file (e.g., `json/decoder.py` or a Django session backend),
        which would otherwise be missed by simpler file-path-based heuristics.
        """
        view_file_to_errors: Dict[str, List[ErrorRecord]] = {}
        unhandled_errors: List[ErrorRecord] = []

        # Broader set of keywords that indicate a test is exercising application logic
        test_failure_keywords = {"AssertionError", "KeyError", "JSONDecodeError", "ValueError", "TypeError", "DoesNotExist", "NoReverseMatch"}
        project_root = Path(project_state.root_path).resolve()

        for error_record in errors:
            is_triggered_by_test_command = error_record.command and "test" in error_record.command.lower()
            is_relevant_error_type = any(keyword in error_record.message for keyword in test_failure_keywords)

            if is_triggered_by_test_command and is_relevant_error_type:
                # This is the core logic: walk the traceback from the bottom up.
                # Actively find the deepest project test file from the full traceback.
                traceback_files = re.findall(r'File "([^"]+)"', error_record.message)
                project_test_file = None
                for file_path_str in reversed(traceback_files):
                    # --- FIX: More robust path validation and filtering. Check for library paths FIRST. ---
                    try:
                        # Normalize path separators for consistent checking
                        # Exclude common library paths to focus on project code.
                        normalized_path_str = file_path_str.replace('\\', '/')
                        if 'site-packages' in normalized_path_str or '/lib/python' in normalized_path_str:
                            logger.debug(f"Skipping library path from traceback: {file_path_str}")
                            continue

                        # Now, resolve and check containment
                        abs_path = (project_root / file_path_str).resolve() if not Path(file_path_str).is_absolute() else Path(file_path_str).resolve()
                        # This is the security and relevance check.
                        abs_path.relative_to(project_root) # This will raise ValueError if outside

                        # Heuristic: Check if 'test' is in the path to identify it as a test file
                        is_test_file = 'test' in abs_path.parts or abs_path.name.lower().startswith('test_')
                        if is_test_file: # No need for the redundant 'site-packages' check here
                            project_test_file = abs_path.relative_to(project_root).as_posix()
                            logger.debug(f"Identified project test file '{project_test_file}' from traceback for error: {error_record.summary}")
                            break
                    except (ValueError, Exception):
                        # This will catch paths outside the project root or other resolution errors.
                        logger.debug(f"Skipping path '{file_path_str}' from traceback as it is outside the project root or invalid.")
                        continue

                # If we found a relevant test file in the project...
                if project_test_file: # A project-owned test file was found in the traceback
                    target_file_to_fix = None
                    error_message_lower = error_record.message.lower()
                    test_file_path = Path(project_test_file)
                    app_dir = test_file_path.parent.parent if test_file_path.parent.name.lower() in ['test', 'tests'] else test_file_path.parent

                    # --- NEW: More intelligent redirection based on error content ---
                    # Apply heuristics to guess the *actual* source of the bug, not just the test file.
                    # Heuristic 1: If it's an assertContains error for a static file, the problem is likely the template.
                    if 'assertcontains' in error_message_lower and ('stylesheet' in error_message_lower or 'script src' in error_message_lower):
                        # This is a strong hint the template is missing a static file link.
                        # We need to find the template rendered by the view associated with this test. # type: ignore
                        # --- FIX: More robustly find the template file ---
                        # Look for a file path ending in .html in the error message itself
                        template_match = re.search(r'File "([^"]+\.html)"', error_record.message)
                        if template_match:
                            template_path = Path(template_match.group(1))

                        # This is a complex inference. For now, we'll assume a conventional template path.
                        # A more advanced implementation would parse the view file to find the template name.
                        template_path = app_dir / 'templates' / app_dir.name / 'display.html' # Example heuristic path
                        target_file_to_fix = template_path.as_posix()
                        logger.info(f"Redirecting 'assertContains' static file failure to likely template: {target_file_to_fix}")

                    # Heuristic 2: If it's an assertion on a model's __str__, fix the model.
                    # --- FIX: Make regex more specific ---
                    elif (re.search(r"test_.*__str__", error_message_lower) or
                          re.search(r"test_.*str_representation", error_message_lower) or
                          'self.assertequal(str(state)' in error_message_lower):

                        target_file_to_fix = (app_dir / 'models.py').as_posix()
                        logger.info(f"Redirecting '__str__' test failure to model file: {target_file_to_fix}")

                    # Fallback Heuristic: Blame the view file if no other heuristic matches.
                    if not target_file_to_fix:
                        target_file_to_fix = (app_dir / "views.py").as_posix()
                        logger.info(f"Using fallback redirection for test failure: blaming view file {target_file_to_fix}")

                    view_file_path = target_file_to_fix
                    
                    # Group all errors that point to the same fix file.
                    if view_file_path not in view_file_to_errors:
                        view_file_to_errors[view_file_path] = []
                    # Update the error record's file_path to point to the *test file* we found,
                    # as this is more accurate than what the analyzer might have reported.
                    view_file_to_errors[view_file_path].append(error_record.model_copy(update={'file_path': project_test_file}))
                else:
                    logger.warning(f"Could not find a project-specific test file in the traceback for error: {error_record.summary}. Passing to fallback planner.")
                    unhandled_errors.append(error_record)
            else:
                unhandled_errors.append(error_record)

        plan_tasks: List[AnyRemediationTask] = []
        # Bundle all errors for a single file into one `FixLogicTask`.
        for view_path, error_list in view_file_to_errors.items():
            logger.info(f"Detected {len(error_list)} test failures pointing to view '{view_path}'. Bundling into a single FixLogicTask.")
                # --- FIX: Create a more readable combined message for the LLM ---
            combined_message = f"Multiple test failures occurred in '{error_list[0].file_path}'. All failures are listed below:\n\n"
            for i, e in enumerate(error_list):
                    combined_message += f"--- Failure {i+1}: {e.summary} ---\n{e.message}\n\n"

            primary_error = error_list[0].model_copy(update={"message": combined_message, "file_path": view_path})
            description = (
                f"Multiple tests in `{error_list[0].file_path}` failed, pointing to logical errors in the view file `{view_path}`. The tests are the specification for the correct behavior. "
                f"Analyze the full error log below, which contains all related failures. Modify the view logic in `{view_path}` to produce the correct output that will satisfy all the assertions in the tests. "
                "DO NOT modify the test file."
            )
            # Ensure files_to_fix are posix-style for consistency
            # The fix might be in the view or the test, so provide both for context.
            files_to_fix = sorted(list({view_path, error_list[0].file_path or ""}))
            task = FixLogicTask(original_error=primary_error, description=description, files_to_fix=files_to_fix)
            plan_tasks.append(task)

        return plan_tasks, unhandled_errors


    def _apply_assertion_error_strategy(self, errors: List[ErrorRecord], project_state: ProjectState) -> Tuple[List[AnyRemediationTask], List[ErrorRecord]]:
        """
        A strategy for generic `AssertionError` in test files.

        It creates a plan that includes BOTH the test file and the likely application
        code file (e.g., `views.py`). This gives the LLM permission to fix the test
        itself if it's faulty, which is a common scenario.
        """
        plan_tasks: List[AnyRemediationTask] = []
        unhandled_errors: List[ErrorRecord] = []

        for error in errors:
            is_assertion_error_in_test = (
                error.error_type == ErrorType.TestFailure and
                "AssertionError" in error.message and
                error.file_path and "test" in error.file_path
            )

            if is_assertion_error_in_test:
                logger.info(f"Applying 'AssertionError' strategy for error in '{error.file_path}'.")
                test_path = Path(error.file_path)

                # Infer the application file that corresponds to the test file.
                # --- FIX: Make the inference more robust by analyzing the test file's imports ---
                # This is a conceptual improvement. A full implementation would use CodeIntelligenceService.
                app_file_to_fix = None
                app_dir = test_path.parent.parent if test_path.parent.name == 'test' else test_path.parent

                # Heuristic 1: Look for a corresponding file in the parent app directory.
                # e.g., 'products/test/test_views.py' -> 'products/views.py'
                app_file_stem = test_path.stem.replace('test_', '') # e.g., 'views'
                potential_app_file = (app_dir / f"{app_file_stem}.py")
                if potential_app_file.exists(): # A real implementation would check the file system manager
                    app_file_to_fix = potential_app_file.as_posix()
                else:
                    # Fallback: If no direct match, just blame the app's views.py as a likely candidate.
                    app_file_to_fix = (app_dir / "views.py").as_posix()
                    logger.warning(f"Could not find direct match for test '{test_path}'. Falling back to default app file: '{app_file_to_fix}'")

                # Create a description that explicitly allows the LLM to fix the test.
                new_description = (
                    f"An `AssertionError` occurred in the test file `{error.file_path}`. "
                    f"This could mean the application logic in `{app_file_to_fix}` is wrong, OR the test assertion itself is faulty.\n\n"
                    "Analyze both files. You have permission to modify the test file if you determine it is the source of the error. "
                    "For example, you can comment out or change a faulty `self.assertEqual` line. "
                    "Provide the complete, corrected content for the single file you choose to fix."
                )

                multi_context_task = FixLogicTask(original_error=error, description=new_description, files_to_fix=sorted([app_file_to_fix, error.file_path]))
                plan_tasks.append(multi_context_task)
            else:
                unhandled_errors.append(error)

        return plan_tasks, unhandled_errors

    def _apply_template_does_not_exist_strategy(self, errors: List[ErrorRecord], project_state: ProjectState) -> Tuple[List[AnyRemediationTask], List[ErrorRecord]]:
        """
        Handles `TemplateDoesNotExist` errors.

        This is a high-priority strategy that creates a plan to either create the
        missing template file or fix the reference to it in the corresponding view.
        """
        plan_tasks: List[AnyRemediationTask] = []
        unhandled_errors = list(errors)
        consumed_errors: List[ErrorRecord] = []

        for error in errors:
            if error.error_type == ErrorType.TemplateError and "TemplateDoesNotExist" in error.message:
                logger.info(f"Applying 'TemplateDoesNotExist' strategy for error: {error.summary}")

                # Extract the missing template path from the error message
                match = re.search(r"TemplateDoesNotExist: ([\w\/\.\-]+)", error.message)
                if not match:
                    continue # This is inside a loop, it's fine.

                missing_template_path = match.group(1)
                # The file_path in the error record is the view that tried to render the template
                view_file_path = error.file_path

                # Give the LLM two possible solutions.
                description = (
                    f"A `TemplateDoesNotExist` error occurred in `{view_file_path}` because it tried to render a template at `{missing_template_path}` which does not exist. "
                    "You must fix this. There are two possible solutions:\n"
                    f"1. **Create the missing template file:** Create the complete HTML content for `{missing_template_path}`.\n"
                    f"2. **Correct the view:** Modify the `render()` call in `{view_file_path}` to point to an existing template.\n\n"
                    "Analyze the context and choose the most logical fix. Provide the complete, corrected content for the file you choose to modify."
                )

                task = FixLogicTask(original_error=error, description=description, files_to_fix=sorted([view_file_path, missing_template_path]))
                plan_tasks.append(task)
                consumed_errors.append(error)

        # Remove consumed errors from the list of unhandled errors
        for err in consumed_errors:
            if err in unhandled_errors:
                unhandled_errors.remove(err)

        return plan_tasks, unhandled_errors
    
    def create_plan(self, errors: List[ErrorRecord], project_state: ProjectState) -> Optional[List[AnyRemediationTask]]:
        """
        Creates a strategic, multi-task remediation plan from a list of errors.

        This is the main entry point for the planner. It orchestrates the process by:
        1. Running a series of high-priority "strategic planners" for common, well-defined errors.
        2. Bundling any remaining errors that affect the same file into a single `FixBundleTask`.
        3. Creating generic, single-error tasks for any leftovers.
        """
        if not errors:
            return None

        plan_tasks: List[AnyRemediationTask] = []
        unhandled_errors = list(errors)

        # --- Run strategic planners in order of priority ---
        # NEW: Check for conflicting model errors and NoReverseMatch errors together
        conflicting_model_error = next((e for e in unhandled_errors if "Conflicting" in e.message and "models" in e.message), None)
        no_reverse_match_errors = [e for e in unhandled_errors if "NoReverseMatch" in e.message]
        # This is a new, more holistic strategy that could be added

        # Iterate over the class attribute instead of a hardcoded list.
        for planner_func in self.STRATEGIC_PLANNERS:
            new_tasks, unhandled_errors = planner_func(self, unhandled_errors, project_state)
            if new_tasks:
                plan_tasks.extend(new_tasks)

        # --- Bundle remaining unhandled errors by file path ---
        # This is an efficiency measure to reduce the number of LLM calls.
        file_to_errors_map: Dict[str, List[ErrorRecord]] = {}
        errors_without_paths: List[ErrorRecord] = []

        for error in unhandled_errors:
            if error.file_path and error.file_path != "Unknown":
                target_file = error.file_path
                if target_file not in file_to_errors_map:
                    file_to_errors_map[target_file] = []
                file_to_errors_map[target_file].append(error)
            else:
                errors_without_paths.append(error)

        for file_path, error_list in file_to_errors_map.items():
            # If multiple errors point to the same file, bundle them.
            if len(error_list) > 1:
                logger.info(f"Bundling {len(error_list)} errors into a single FixBundleTask for file: {file_path}")
                combined_message = "\n\n---\n\n".join(
                    [f"--- Error {i+1}: {e.error_type.value} in {e.file_path} ---\n{e.message}" for i, e in enumerate(error_list)]
                )
                bundle_primary_error = error_list[0].model_copy(update={"message": combined_message, "file_path": file_path})
                bundle_task = FixBundleTask(original_error=bundle_primary_error, bundled_errors=error_list)
                plan_tasks.append(bundle_task)
            # If only one error for a file, create a standard single task for it.
            elif len(error_list) == 1:
                tasks = self._create_single_task_plan(error_list, project_state)
                if tasks:
                    plan_tasks.extend(tasks)
        
        # Handle any errors that couldn't be associated with a specific file.
        if errors_without_paths:
            logger.info(f"Applying general fallback planning for {len(errors_without_paths)} error(s) without file paths.")
            general_tasks = self._create_single_task_plan(errors_without_paths, project_state)
            if general_tasks:
                plan_tasks.extend(general_tasks)

        return plan_tasks if plan_tasks else None

    # --- Specialist Planner Implementations ---

    def _apply_no_reverse_match_strategy(self, errors: List[ErrorRecord], project_state: ProjectState) -> Tuple[List[AnyRemediationTask], List[ErrorRecord]]:
        """If NoReverseMatch is a dominant error, create a plan and consume all related errors."""
        no_reverse_match_errors = [e for e in errors if "NoReverseMatch" in e.message]
        if no_reverse_match_errors:
            logger.info("Prioritizing NoReverseMatch error with a strategic multi-step configuration fix.")
            # Create a single, comprehensive task for the first NoReverseMatch error found.
            # Instantiate FileSystemManager here to pass to the plan creator.
            fsm = FileSystemManager(project_state.root_path)
            no_reverse_match_task = self._create_no_reverse_match_plan(no_reverse_match_errors[0], project_state, fsm)
            if no_reverse_match_task:
                # Consume all NoReverseMatch errors
                remaining_errors = [e for e in errors if "NoReverseMatch" not in e.message]
                return [no_reverse_match_task], remaining_errors
        return [], errors

    def _apply_attribute_error_strategy(self, errors: List[ErrorRecord], project_state: ProjectState) -> Tuple[List[AnyRemediationTask], List[ErrorRecord]]:
        """If AttributeError on a module is found, create a targeted plan and consume the error."""
        attr_error_record = next((e for e in errors if "AttributeError: module" in e.message), None)
        
        if attr_error_record:
            logger.info("Prioritizing AttributeError on a module with a targeted fix strategy.")
            attr_error_plan = self._create_attribute_error_plan(attr_error_record, project_state)
            if attr_error_plan:
                # Consume the error that was handled
                remaining_errors = [e for e in errors if e is not attr_error_record]
                return attr_error_plan, remaining_errors
        
        return [], errors

    def _create_attribute_error_plan(
        self, error_record: ErrorRecord, project_state: ProjectState
    ) -> Optional[List[AnyRemediationTask]]:
        """
        Creates a high-confidence, multi-step plan for AttributeError on a Django view module.
        This plan not only fixes the missing view function but also proactively ensures
        the URL configuration and namespacing are correct to prevent subsequent NoReverseMatch errors.
        """
        # Example: "AttributeError: module 'calculate.views' has no attribute 'index'"
        match = re.search(
            r"AttributeError: module '([^']*)' has no attribute '([^']*)'",
            error_record.message
        )
        if not match or not match.group(1).endswith('.views'):
            # This strategy is specifically for Django views.
            return None

        module_name, attribute_name = match.groups()
        app_name = module_name.split('.')[0]
        logger.info(f"Detected Django view AttributeError for '{attribute_name}' in module '{module_name}'. Creating strategic multi-step fix plan.")

        # --- Task 1: Fix the missing view function in views.py ---
        view_file_path_str = module_name.replace('.', '/') + '.py'
        importing_file = error_record.file_path if error_record.file_path and error_record.file_path != "Unknown" else "an unknown file"

        view_fix_error_record = ErrorRecord(
            error_type=ErrorType.LogicError, file_path=view_file_path_str, line_number=None,
            message=f"The file '{importing_file}' raised an AttributeError for '{attribute_name}' in module '{module_name}'.",
            command=error_record.command,
        )
        view_fix_description = (
            f"An `AttributeError` occurred because `{importing_file}` tried to access the view `{attribute_name}` from `{module_name}`, but it was not defined.\n"
            f"The root cause is in `{view_file_path_str}`. Please modify this file to correctly define the `{attribute_name}` function. It should accept a `request` argument and return an `HttpResponse` or `JsonResponse`."
        )
        view_fix_task = FixLogicTask(original_error=view_fix_error_record, description=view_fix_description, files_to_fix=[view_file_path_str])

        # --- Task 2: Proactively fix the app's urls.py for namespacing ---
        app_urls_path_str = f"{app_name}/urls.py"
        app_urls_error_record = ErrorRecord(
            error_type=ErrorType.LogicError, file_path=app_urls_path_str, line_number=None,
            message=f"A `NoReverseMatch` error is likely to occur if the 'app_name' variable is missing in the URL configuration for the '{app_name}' app.",
            command=error_record.command,
        )
        app_urls_fix_description = (
            f"To prevent a `NoReverseMatch` error, the URL configuration for the '{app_name}' app needs to be namespaced. "
            f"In `{app_urls_path_str}`, ensure the `app_name = '{app_name}'` variable is defined at the top level (outside of `urlpatterns`). This is required for Django's URL reversing to work correctly with namespaces (e.g., `reverse('{app_name}:index')`)."
        )
        app_urls_fix_task = FixLogicTask(original_error=app_urls_error_record, description=app_urls_fix_description, files_to_fix=[app_urls_path_str])

        # --- Task 3: Proactively include the app's URLs in the project's urls.py ---
        project_config_dir = project_state.project_name
        if not project_config_dir:
            logger.warning("Cannot create project-level URL fix: project_name is missing from project_state.")
            # Return the two-step plan if we can't determine the project urls.py path
            return [view_fix_task, app_urls_fix_task]

        project_urls_path_str = f"{project_config_dir}/urls.py"
        project_urls_error_record = ErrorRecord(
            error_type=ErrorType.LogicError, file_path=project_urls_path_str, line_number=None,
            message=f"A `NoReverseMatch` error is likely to occur if the URLs for the '{app_name}' app are not included in the main project's URL configuration.",
            command=error_record.command,
        )
        project_urls_fix_description = (
            f"To prevent a `NoReverseMatch` error, the URLs for the '{app_name}' app must be included in the project's main URL configuration. "
            f"In `{project_urls_path_str}`, ensure that `path('{app_name}/', include('{app_name}.urls'))` is present in the `urlpatterns` list. "
            f"Also ensure `from django.urls import include` is present at the top of the file."
        )
        project_urls_fix_task = FixLogicTask(original_error=project_urls_error_record, description=project_urls_fix_description, files_to_fix=[project_urls_path_str])

        # The order is important: define the view, then configure app URLs, then include in project URLs.
        plan = [view_fix_task, app_urls_fix_task, project_urls_fix_task]
        return plan

    def _apply_import_error_strategy(self, errors: List[ErrorRecord], project_state: ProjectState) -> Tuple[List[AnyRemediationTask], List[ErrorRecord]]:
        """If ImportError is found, create a targeted plan and consume the error."""
        # Find the first matching ImportError
        import_error_record = next((e for e in errors if "ImportError: cannot import name" in e.message), None)
        
        if import_error_record:
            logger.info("Prioritizing ImportError with a targeted fix strategy.")
            import_error_plan = self._create_import_error_plan(import_error_record)
            if import_error_plan:
                # Consume the error that was handled
                remaining_errors = [e for e in errors if e is not import_error_record]
                return import_error_plan, remaining_errors
        
        return [], errors
    def _create_import_error_plan(
        self, error_record: ErrorRecord
    ) -> Optional[List[AnyRemediationTask]]:
        """
        Creates a high-confidence plan for ImportError, redirecting the fix
        to the file that is failing to provide the import.
        """
        # Regex to capture the imported name and the source module.
        # Example: "ImportError: cannot import name 'CalculatorStateAdmin' from 'calculator.admin' (...)"
        match = re.search(
            r"cannot import name '([^']*)' from '([^']*)'",
            error_record.message
        )
        if not match or not error_record.file_path or error_record.file_path == "Unknown":
            return None

        imported_name, source_module = match.groups()
        original_file = Path(error_record.file_path)

        logger.info(f"Detected ImportError for '{imported_name}' in '{original_file}'. Creating targeted fix.")

        # --- FIX: Correctly determine the target file from the source module path ---
        # Convert module path like 'calculator.admin' to a file path 'calculator/admin.py'
        target_file_path_str = source_module.replace('.', '/') + '.py'
        logger.info(f"Redirecting ImportError fix to source file: '{target_file_path_str}'")
        # --- END FIX ---

        # Create a new, clean ErrorRecord targeting the correct file.
        targeted_error_record = ErrorRecord(
            error_type=ErrorType.LogicError,
            file_path=target_file_path_str,
            line_number=None,
            message=f"The file '{error_record.file_path}' failed to import '{imported_name}' from '{source_module}'. The definition is likely missing or incorrect in '{target_file_path_str}'.",
            command=error_record.command,
        )

        # Create a specific description for the LLM.
        description = (
            f"An `ImportError` occurred because `{error_record.file_path}` tried to import `{imported_name}` from `{source_module}`, but it was not defined or exported in `{target_file_path_str}`. "
            f"Your task is to MODIFY the file `{target_file_path_str}` to correctly define and export `{imported_name}`."
        )
        
        usage_match = re.search(rf"{re.escape(imported_name)}\.([a-zA-Z_][a-zA-Z0-9_]*)", error_record.message)
        if usage_match:
            used_attribute = usage_match.group(1)
            description += f" The importing file (`{error_record.file_path}`) references `{imported_name}.{used_attribute}`, so you likely need to define the `{used_attribute}` function or class within `{target_file_path_str}`."

        plan = [FixLogicTask(original_error=targeted_error_record, description=description, files_to_fix=[target_file_path_str])]
        return plan

    def _apply_str_representation_strategy(self, errors: List[ErrorRecord], project_state: ProjectState) -> Tuple[List[AnyRemediationTask], List[ErrorRecord]]:
        """Creates tasks for __str__ representation errors and consumes them."""
        tasks, remaining_errors = self._create_str_representation_fixes(errors)
        return tasks, remaining_errors

    # --- Fallback Task Creation ---

    def _create_single_task_plan(
        self, error_records: List[ErrorRecord], project_state: ProjectState
    ) -> List[AnyRemediationTask]:
        """
        The fallback planner. It creates a single, simple task for each error
        that wasn't handled by a more advanced strategy.
        """
        tasks: List[AnyRemediationTask] = []
        for record in error_records:
            try:
                path_to_fix = record.file_path
                if path_to_fix == "PROJECT_SETTINGS_FILE":
                    if project_state and project_state.project_name:
                        settings_file_path = f"{project_state.project_name}/settings.py"
                        logger.info(f"Resolved 'PROJECT_SETTINGS_FILE' to '{settings_file_path}'.")
                        path_to_fix = settings_file_path
                    else:
                        logger.error("Cannot resolve 'PROJECT_SETTINGS_FILE': project_name is missing from project_state.")
                        tasks.append(FixCommandTask(original_error=record))
                        continue

                # If the error analyzer provided hints (like candidate files), use them.
                # --- NEW: Use hints from the analyzer to create a multi-file task if available ---
                files_for_task = [path_to_fix] if path_to_fix and path_to_fix != "Unknown" else []
                description = (
                    f"A {record.error_type.value} occurred. "
                    f"Analyze the full error log provided below and apply a logical fix to resolve the issue. "
                    f"The error was triggered by the command: `{record.command}`."
                )

                if record.hints:
                    logger.info(f"Found hints in error record for '{record.summary}'. Expanding task context.")
                    if 'candidate_files' in record.hints and record.hints['candidate_files']:
                        # The planner resolves placeholders like PROJECT_SETTINGS_FILE
                        resolved_candidates = [self._resolve_path_placeholder(p, project_state) for p in record.hints['candidate_files']]
                        files_for_task.extend(filter(None, resolved_candidates))
                        files_for_task = sorted(list(set(files_for_task))) # Make unique and sort

                    if 'diagnosis' in record.hints:
                        description = record.hints['diagnosis'] + "\n\n" + description
                # --- END NEW ---

                # Create the most appropriate task type based on the error.
                if record.error_type in [ErrorType.FileNotFound, ErrorType.TemplateError] and path_to_fix and not files_for_task:
                    new_record = record.model_copy(update={"file_path": path_to_fix})
                    tasks.append(CreateFileTask(original_error=new_record))
                elif record.error_type == ErrorType.SyntaxError and path_to_fix and not files_for_task:
                    new_record = record.model_copy(update={"file_path": path_to_fix})
                    tasks.append(FixSyntaxTask(original_error=new_record))
                elif files_for_task:
                    primary_file = path_to_fix if path_to_fix in files_for_task else files_for_task[0]
                    new_record = record.model_copy(update={"file_path": primary_file})
                    tasks.append(FixLogicTask(original_error=new_record, description=description, files_to_fix=files_for_task))
                else:
                    tasks.append(FixCommandTask(original_error=record))
            except ValidationError as e:
                logger.error(f"Validation error creating fallback task for error: {record}. Error: {e}")
        return tasks

    def _resolve_path_placeholder(self, path: str, project_state: ProjectState) -> Optional[str]:
        """
        Resolves special path placeholders like 'PROJECT_SETTINGS_FILE' into
        their actual file paths based on the current project state.
        """
        if path == "PROJECT_SETTINGS_FILE":
            if project_state and project_state.project_name:
                return f"{project_state.project_name}/settings.py"
            else:
                logger.error("Cannot resolve 'PROJECT_SETTINGS_FILE': project_name is missing from project_state.")
                return None
        return path