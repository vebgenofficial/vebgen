# backend/src/core/validators/frontend_validator.py
import logging
from typing import List, Set, Generator, Tuple, Any

from ..project_models import (
    ProjectStructureMap, FrontendValidationIssue, FrontendValidationReport
)
from .js_html_validator import JSHtmlValidator
# --- NEW: Import the specialized analyzers ---
from ..analyzers.performance_analyzer import PerformanceAnalyzer
from ..analyzers.accessibility_analyzer import AccessibilityAnalyzer

logger = logging.getLogger(__name__)

class FrontendValidator:
    """
    Orchestrates all HTML, CSS, and JS validators and performs cross-cutting
    validation to generate a single, comprehensive report.
    """
    def __init__(self, project_structure_map: ProjectStructureMap):
        self.project_map = project_structure_map
        self.report = FrontendValidationReport()

    def validate(self) -> FrontendValidationReport:
        """
        Runs all frontend validation checks and returns a unified report.
        """
        logger.info("Starting unified frontend validation...")

        # 1. Aggregate issues from individual file parsers
        self._aggregate_parser_issues()

        # 2. Run JS-HTML cross-file validation for functionality issues
        js_html_validator = JSHtmlValidator(self.project_map)
        # This now returns FrontendValidationIssue objects directly, which include the file_path.
        self.report.issues.extend(js_html_validator.validate())

        # 3. Run specialized analyzers
        performance_analyzer = PerformanceAnalyzer(self.project_map)
        self.report.issues.extend(performance_analyzer.analyze())

        accessibility_analyzer = AccessibilityAnalyzer(self.project_map)
        self.report.issues.extend(accessibility_analyzer.analyze())

        # 4. Prioritize and sort the final report
        self._prioritize_and_sort_issues()
        self.report.total_issues = len(self.report.issues)

        logger.info(f"Unified frontend validation complete. Found {self.report.total_issues} issues.")
        return self.report

    def _aggregate_parser_issues(self):
        """Collects validation issues from all parsed HTML, CSS, and JS files."""
        for file_path, file_info in self._iter_all_files():
            # HTML issues
            if file_info.html_details and file_info.html_details.validation:
                validation = file_info.html_details.validation
                for issue in validation.structure_issues: self.report.issues.append(FrontendValidationIssue(severity=issue.severity, category=issue.category, message=issue.message, file_path=file_path, element_preview=issue.element_preview))
                for issue in validation.seo_issues: self.report.issues.append(FrontendValidationIssue(severity=issue.severity, category=issue.category, message=issue.message, file_path=file_path, element_preview=issue.element_preview))
                for issue in validation.forms_issues: self.report.issues.append(FrontendValidationIssue(severity=issue.severity, category=issue.category, message=issue.message, file_path=file_path, element_preview=issue.element_preview))
                # Accessibility issues are handled by the AccessibilityAnalyzer, which is called separately.

            # CSS issues
            if file_info.css_details and file_info.css_details.validation:
                for issue in file_info.css_details.validation.architecture_issues: self.report.issues.append(FrontendValidationIssue(severity=issue.severity, category=issue.category, message=issue.message, file_path=file_path, line=issue.line, element_preview=issue.element_preview))
                for issue in file_info.css_details.validation.naming_issues: self.report.issues.append(FrontendValidationIssue(severity=issue.severity, category=issue.category, message=issue.message, file_path=file_path, line=issue.line, element_preview=issue.element_preview))
                for issue in file_info.css_details.validation.responsive_issues: self.report.issues.append(FrontendValidationIssue(severity=issue.severity, category=issue.category, message=issue.message, file_path=file_path, line=issue.line, element_preview=issue.element_preview))
                for issue in file_info.css_details.validation.compatibility_issues: self.report.issues.append(FrontendValidationIssue(severity=issue.severity, category=issue.category, message=issue.message, file_path=file_path, line=issue.line, element_preview=issue.element_preview))
                # Note: Performance and Accessibility issues are handled by their respective analyzers

            # JS issues
            if file_info.js_details and file_info.js_details.validation:
                for issue in file_info.js_details.validation.modernjs_issues: self.report.issues.append(FrontendValidationIssue(severity=issue.severity, category=issue.category, message=issue.message, file_path=file_path, line=issue.line, element_preview=issue.element_preview))
                for issue in file_info.js_details.validation.organization_issues: self.report.issues.append(FrontendValidationIssue(severity=issue.severity, category=issue.category, message=issue.message, file_path=file_path, line=issue.line, element_preview=issue.element_preview))
                for issue in file_info.js_details.validation.security_issues: self.report.issues.append(FrontendValidationIssue(severity=issue.severity, category=issue.category, message=issue.message, file_path=file_path, line=issue.line, element_preview=issue.element_preview))
                for issue in file_info.js_details.validation.compatibility_issues: self.report.issues.append(FrontendValidationIssue(severity=issue.severity, category=issue.category, message=issue.message, file_path=file_path, line=issue.line, element_preview=issue.element_preview))
                # Note: Performance, DOM, API, and Forms issues are handled by other analyzers/validators

    def _iter_all_files(self) -> Generator[Tuple[str, Any], None, None]:
        """Generator to iterate over all files in the project map."""
        for file_path, file_info in self.project_map.global_files.items():
            yield file_path, file_info
        for app_info in self.project_map.apps.values():
            for file_path, file_info in app_info.files.items():
                yield file_path, file_info

    def _prioritize_and_sort_issues(self):
        """Sorts all collected issues by severity."""
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        self.report.issues.sort(key=lambda issue: severity_order.get(issue.severity, 99))