# backend/src/core/validators/js_html_validator.py
import logging
from typing import List, Dict, Set

from ..project_models import ( # type: ignore
    ProjectStructureMap, HTMLFileDetails, VanillaJSFileDetails, # type: ignore
    FrontendValidationIssue, JSValidationIssue # Import FrontendValidationIssue
) # type: ignore

logger = logging.getLogger(__name__)

class JSHtmlValidator:
    """
    Performs cross-file validation between JavaScript and HTML files.
    - Validates that JS selectors (IDs, classes) exist in HTML.
    - Validates that form IDs referenced in JS exist.
    - Validates that API endpoints in fetch calls match Django URLs.
    """
    def __init__(self, project_structure_map: ProjectStructureMap):
        self.project_map = project_structure_map
        self.all_html_ids: Set[str] = set()
        self.all_html_classes: Set[str] = set()
        self.all_django_urls: Set[str] = set()
        self._collect_all_html_and_url_definitions()

    def _collect_all_html_and_url_definitions(self):
        """Iterates through the project map once to collect all defined IDs, classes, and URLs."""
        for app_info in self.project_map.apps.values():
            for file_info in app_info.files.values():
                if file_info.html_details:
                    # Collect IDs from forms and inputs
                    for form in file_info.html_details.forms:
                        if form.id:
                            self.all_html_ids.add(form.id)
                        for form_input in form.inputs:
                            if form_input.id:
                                self.all_html_ids.add(form_input.id)
                
                if file_info.django_urls_details:
                    for url_pattern in file_info.django_urls_details.url_patterns:
                        if url_pattern.name:
                            self.all_django_urls.add(url_pattern.name)

        logger.debug(f"Collected {len(self.all_html_ids)} HTML IDs and {len(self.all_django_urls)} Django URL names for cross-validation.")

    def validate(self) -> List[JSValidationIssue]:
        """
        Runs all JS-HTML cross-validation checks and returns a list of issues.
        """
        all_issues: List[FrontendValidationIssue] = [] # type: ignore
        for app_info in self.project_map.apps.values():
            for file_path, file_info in app_info.files.items():
                if file_info.js_details:
                    logger.debug(f"Cross-validating JS file: {file_path}")
                    all_issues.extend(self._validate_js_file(file_info.js_details, file_path)) # type: ignore
        return all_issues

    def _validate_js_file(self, js_details: VanillaJSFileDetails, file_path: str) -> List[FrontendValidationIssue]: # type: ignore
        """Validates a single parsed JavaScript file against the collected HTML/URL definitions."""
        issues: List[FrontendValidationIssue] = [] # type: ignore

        # Validate DOM selectors
        for method, selector in js_details.dom_manipulations: # type: ignore
            clean_selector = selector.strip("'\"")
            if method == "getElementById":
                if clean_selector not in self.all_html_ids:
                    issues.append(FrontendValidationIssue( # type: ignore
                        severity="medium", # type: ignore
                        category="Functionality",
                        message=f"Orphaned JS selector: `getElementById` targets non-existent ID '#{clean_selector}'.",
                        file_path=file_path,
                        element_preview=f"document.getElementById('{clean_selector}')"
                    ))

        # Validate API endpoints
        for api_call in js_details.api_calls:
            # This is a heuristic. It checks if the URL looks like a Django URL name.
            # A more robust check would involve resolving the URL pattern.
            url = api_call.url
            if url and not url.startswith(('/', 'http')) and url not in self.all_django_urls:
                 issues.append(FrontendValidationIssue( # type: ignore
                        severity="medium", # type: ignore
                        category="Functionality",
                        message=f"API call to '{url}' does not seem to match any defined Django URL name.",
                        file_path=file_path,
                        element_preview=f"fetch('{url}')"
                    ))

        return issues