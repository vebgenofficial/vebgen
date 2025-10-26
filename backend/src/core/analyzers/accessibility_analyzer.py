# backend/src/core/analyzers/accessibility_analyzer.py
import logging
from typing import List
from typing import List, Generator, Tuple, Any, Set
from ..project_models import ProjectStructureMap, FrontendValidationIssue

logger = logging.getLogger(__name__)

class AccessibilityAnalyzer:
    """
    Analyzes frontend assets for accessibility issues based on WCAG 2.1 guidelines.
    Aggregates findings from HTML and CSS parsers.
    """
    def __init__(self, project_structure_map: ProjectStructureMap):
        self.project_map = project_structure_map
        self.issues: List[FrontendValidationIssue] = []

    def analyze(self) -> List[FrontendValidationIssue]:
        """
        Runs all accessibility checks and returns a list of issues.
        """
        logger.info("Starting accessibility analysis...")

        for file_path, file_info in self._iter_all_files():
            # Aggregate issues from HTML parser
            if file_info.html_details:
                for issue in file_info.html_details.validation.accessibility_issues:
                    # Convert HTMLValidationIssue to FrontendValidationIssue and map to WCAG
                    frontend_issue = FrontendValidationIssue(
                        severity=issue.severity,
                        category="Accessibility",
                        message=self._map_html_issue_to_wcag_message(issue.message),
                        file_path=file_path,
                        element_preview=issue.element_preview,
                    )
                    self.issues.append(frontend_issue)

            # Aggregate issues from CSS parser
            if file_info.css_details:
                for issue in file_info.css_details.validation.accessibility_issues:
                    # Convert CSSValidationIssue to FrontendValidationIssue and map to WCAG
                    frontend_issue = FrontendValidationIssue(
                        severity=issue.severity,
                        category="Accessibility",
                        message=self._map_css_issue_to_wcag_message(issue.message),
                        file_path=file_path,
                        line=issue.line,
                        element_preview=issue.element_preview,
                    )
                    self.issues.append(frontend_issue)

        logger.info(f"Accessibility analysis complete. Found {len(self.issues)} issues.")
        return self.issues

    def _map_html_issue_to_wcag(self, issue: FrontendValidationIssue) -> FrontendValidationIssue:
        """Maps an HTML validation issue to a WCAG success criterion."""
        new_message = issue.message
        return self._map_html_issue_to_wcag_message(issue.message)

    def _map_html_issue_to_wcag_message(self, message: str) -> str:
        """Maps an HTML validation issue message to a WCAG success criterion."""
        if "'alt' attribute" in message:
            return f"[WCAG 1.1.1] {message}"
        elif "descriptive text" in message or "meaningful labels" in message:
            return f"[WCAG 2.4.6] {message}"
        elif "associated <label>" in message:
            return f"[WCAG 1.3.1, 4.1.2] {message}"
        return message

    def _map_css_issue_to_wcag_message(self, message: str) -> str:
        """Maps a CSS validation issue to a WCAG success criterion."""
        if "Focus outline" in message:
            return f"[WCAG 2.4.7] {message}"
        elif "prefers-reduced-motion" in message:
            return f"[WCAG 2.3.3] {message}"
        elif "Content added via ::before or ::after" in message:
            return f"[WCAG 1.3.1] {message}"
        return message

    def _iter_all_files(self):
        """Generator to iterate over all files in the project map."""
        for file_path, file_info in self.project_map.global_files.items():
            yield file_path, file_info
        for app_info in self.project_map.apps.values():
            for file_path, file_info in app_info.files.items():
                yield file_path, file_info