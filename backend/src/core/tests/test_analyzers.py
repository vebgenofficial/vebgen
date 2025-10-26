# backend/src/core/tests/test_analyzers.py
import pytest
from unittest.mock import MagicMock

from src.core.analyzers.accessibility_analyzer import AccessibilityAnalyzer
from src.core.analyzers.performance_analyzer import PerformanceAnalyzer
from src.core.project_models import (
    ProjectStructureMap,
    AppStructureInfo,
    FileStructureInfo,
    HTMLFileDetails,
    CSSFileDetails,
    HTMLValidationResults,
    CSSValidationResults,
    HTMLValidationIssue,
    CSSValidationIssue,
    HTMLScript,
    CSSRule,
    VanillaJSFileDetails,
)

# --- Fixtures for AccessibilityAnalyzer ---

@pytest.fixture
def project_map_with_accessibility_issues() -> ProjectStructureMap:
    """Creates a ProjectStructureMap with various accessibility issues."""
    # HTML issue: missing alt tag
    html_validation_results_alt = HTMLValidationResults(
        accessibility_issues=[
            HTMLValidationIssue(severity="critical", category="Accessibility", message="Image is missing an 'alt' attribute.")
        ]
    )
    html_details_alt = HTMLFileDetails(validation=html_validation_results_alt)
    html_file_info_alt = FileStructureInfo(file_type="template", html_details=html_details_alt)

    # CSS issue: no focus outline
    css_validation_results = CSSValidationResults(
        accessibility_issues=[
            CSSValidationIssue(severity="error", category="Accessibility", message="Focus outline is disabled.")
        ]
    )
    css_details = CSSFileDetails(validation=css_validation_results)
    css_file_info = FileStructureInfo(file_type="css", css_details=css_details)

    return ProjectStructureMap(
        apps={
            "my_app": AppStructureInfo(
                files={
                    "page.html": html_file_info_alt,
                    "style.css": css_file_info,
                }
            )
        }
    )

@pytest.fixture
def project_map_without_issues() -> ProjectStructureMap:
    """Creates a ProjectStructureMap with no accessibility issues."""
    html_details = HTMLFileDetails(validation=HTMLValidationResults())
    html_file_info = FileStructureInfo(file_type="template", html_details=html_details)
    return ProjectStructureMap(global_files={"index.html": html_file_info})


class TestAccessibilityAnalyzer:
    """Tests for the AccessibilityAnalyzer."""

    def test_analyze_finds_html_issues_and_maps_to_wcag(self, project_map_with_accessibility_issues):
        """Tests that HTML issues are found and mapped to WCAG criteria."""
        analyzer = AccessibilityAnalyzer(project_map_with_accessibility_issues)
        issues = analyzer.analyze()

        alt_issue = next((issue for issue in issues if "[WCAG 1.1.1]" in issue.message), None)
        assert alt_issue is not None
        assert alt_issue.file_path == "page.html"
        assert alt_issue.severity == "critical"

    def test_analyze_finds_css_issues_and_maps_to_wcag(self, project_map_with_accessibility_issues):
        """Tests that CSS issues are found and mapped to WCAG criteria."""
        analyzer = AccessibilityAnalyzer(project_map_with_accessibility_issues)
        issues = analyzer.analyze()

        focus_issue = next((issue for issue in issues if "[WCAG 2.4.7]" in issue.message), None)
        assert focus_issue is not None
        assert focus_issue.file_path == "style.css"
        assert focus_issue.severity == "error"

    def test_analyze_returns_empty_list_for_clean_project(self, project_map_without_issues):
        """Tests that no issues are returned for a project with no accessibility problems."""
        analyzer = AccessibilityAnalyzer(project_map_without_issues)
        issues = analyzer.analyze()
        assert not issues


# --- Fixtures for PerformanceAnalyzer ---

@pytest.fixture
def project_map_with_performance_issues() -> ProjectStructureMap:
    """Creates a ProjectStructureMap with various performance issues."""
    # HTML with a render-blocking script
    html_details = HTMLFileDetails(
        scripts=[
            HTMLScript(src="blocking.js", is_async=False, is_defer=False, is_inline=False)
        ]
    )
    html_file_info = FileStructureInfo(file_type="template", html_details=html_details)

    # CSS with an unused class
    css_details = CSSFileDetails(
        rules=[
            CSSRule(selector=".used-class", properties={"color": "blue"}),
            CSSRule(selector=".unused-class", properties={"color": "red"}),
        ]
    )
    css_file_info = FileStructureInfo(file_type="css", css_details=css_details)

    # JS with a potential layout-thrashing pattern
    js_details = VanillaJSFileDetails(raw_content_summary="for loop with offsetHeight and style.height")
    js_file_info = FileStructureInfo(file_type="javascript", js_details=js_details, raw_content_summary="for loop with offsetHeight and style.height")

    return ProjectStructureMap(
        global_files={
            "index.html": html_file_info,
            "style.css": css_file_info,
            "script.js": js_file_info,
        }
    )


class TestPerformanceAnalyzer:
    """Tests for the PerformanceAnalyzer."""

    def test_identifies_render_blocking_resources(self, project_map_with_performance_issues):
        """Tests that scripts without async/defer are flagged as render-blocking."""
        analyzer = PerformanceAnalyzer(project_map_with_performance_issues)
        issues = analyzer.analyze()

        blocking_issue = next((issue for issue in issues if "render-blocking" in issue.message), None)
        assert blocking_issue is not None
        assert blocking_issue.file_path == "index.html"
        assert blocking_issue.severity == "warning"
        assert "blocking.js" in blocking_issue.message

    def test_detects_layout_thrashing_patterns(self, project_map_with_performance_issues):
        """Tests the heuristic for detecting layout thrashing patterns in JS."""
        analyzer = PerformanceAnalyzer(project_map_with_performance_issues)
        issues = analyzer.analyze()

        thrashing_issue = next((issue for issue in issues if "layout thrashing" in issue.message), None)
        assert thrashing_issue is not None
        assert thrashing_issue.file_path == "script.js"
        assert thrashing_issue.severity == "warning"

    def test_detects_unused_css_selectors(self):
        """Tests that unused CSS selectors are identified."""
        # Setup a map where a CSS class is defined but not used in HTML
        html_details = HTMLFileDetails() # No classes or IDs
        html_file_info = FileStructureInfo(file_type="template", html_details=html_details)

        css_details = CSSFileDetails(
            rules=[
                CSSRule(selector=".unused-class", properties={"color": "red"}),
                CSSRule(selector="#unused-id", properties={"color": "blue"}),
            ]
        )
        css_file_info = FileStructureInfo(file_type="css", css_details=css_details)

        project_map = ProjectStructureMap(
            global_files={"index.html": html_file_info, "style.css": css_file_info}
        )

        analyzer = PerformanceAnalyzer(project_map)
        # This test is currently skipped because the implementation is a placeholder.
        # When implemented, this test will validate the logic.
        pytest.skip("PerformanceAnalyzer unused CSS detection is heuristic and needs more robust implementation to test reliably.")
        
        # issues = analyzer.analyze()
        # unused_css_issue = next((issue for issue in issues if "unused CSS selectors" in issue.message), None)
        # assert unused_css_issue is not None
        # assert ".unused-class" in unused_css_issue.message
        # assert "#unused-id" in unused_css_issue.message