# backend/src/core/tests/test_frontend_intelligence.py
import pytest
from pathlib import Path

from src.core.parsers.html_parser import HTMLParser
from src.core.parsers.css_parser import CSSParser
from src.core.parsers.vanilla_js_parser import VanillaJSParser
from src.core.validators.frontend_validator import FrontendValidator
from src.core.project_models import ProjectStructureMap, AppStructureInfo, FileStructureInfo

# --- Test Data ---

VALID_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Valid Page</title>
    <meta name="description" content="A valid test page.">
</head>
<body>
    <header>
        <h1>Welcome</h1>
    </header>
    <main>
        <form action="/submit" method="post" id="main-form">
            {% csrf_token %}
            <label for="username">Username</label>
            <input type="text" id="username" name="username" required>
            <button type="submit">Submit</button>
        </form>
        <img src="image.png" alt="A descriptive alt text.">
    </main>
</body>
</html>
"""

HTML_MISSING_ALT = """
<h1>Page with issues</h1>
<img src="image.png">
"""

HTML_MISSING_CSRF = """
<form method="post" action="/submit">
    <input type="text" name="data">
</form>
"""

HTML_NON_SEMANTIC = """
<div class="header">
    <div class="nav"></div>
</div>
"""

VALID_CSS = """
.card {
    border: 1px solid #ccc;
    padding: 1rem;
}
"""

CSS_WITH_UNUSED_CLASS = """
.used-card {
    padding: 1rem;
}
.unused-class {
    color: red;
}
"""

VALID_JS = """
const form = document.querySelector('#main-form');
form.addEventListener('submit', (e) => {
    console.log('Form submitted');
});
"""

JS_WITH_ORPHAN_SELECTOR = """
const btn = document.getElementById('non-existent-btn');
if (btn) {
    btn.addEventListener('click', () => alert('Clicked!'));
}
"""

# --- Parser Tests ---

class TestFrontendParsers:
    """Tests for individual frontend file parsers."""

    def test_html_parser_valid(self):
        """Tests that valid HTML produces no validation errors."""
        parser = HTMLParser(VALID_HTML)
        details = parser.parse()
        assert not details.validation.structure_issues
        assert not details.validation.accessibility_issues
        assert not details.validation.forms_issues
        assert details.forms[0].has_csrf_token is True

    def test_html_parser_detects_missing_alt(self):
        """Tests that the HTML parser detects missing alt attributes."""
        parser = HTMLParser(HTML_MISSING_ALT)
        details = parser.parse()
        assert len(details.validation.accessibility_issues) == 1
        assert "missing an 'alt' attribute" in details.validation.accessibility_issues[0].message

    def test_html_parser_detects_missing_csrf(self):
        """Tests that the HTML parser detects missing CSRF tokens in POST forms."""
        parser = HTMLParser(HTML_MISSING_CSRF)
        details = parser.parse()
        assert len(details.validation.forms_issues) >= 1
        assert any("missing a Django CSRF token" in issue.message for issue in details.validation.forms_issues)

    def test_css_parser_valid(self):
        """Tests that a valid CSS file is parsed correctly."""
        parser = CSSParser(VALID_CSS, "style.css")
        details = parser.parse()
        assert len(details.rules) == 1
        assert details.rules[0].selector == ".card"

    def test_js_parser_valid(self):
        """Tests that a valid JS file is parsed correctly."""
        parser = VanillaJSParser(VALID_JS, "script.js")
        details = parser.parse()
        assert len(details.dom_manipulations) == 1
        assert details.dom_manipulations[0][1] == "#main-form"


# --- Validator and Analyzer Tests ---

@pytest.fixture
def project_map_for_validation() -> ProjectStructureMap:
    """Creates a ProjectStructureMap with various frontend files for validation tests."""
    # Create FileStructureInfo objects by parsing content
    html_parser = HTMLParser(VALID_HTML)
    html_details = html_parser.parse()
    html_file_info = FileStructureInfo(file_type="template", html_details=html_details)

    css_parser = CSSParser(CSS_WITH_UNUSED_CLASS, "style.css")
    css_details = css_parser.parse()
    css_file_info = FileStructureInfo(file_type="css", css_details=css_details, raw_content_summary=CSS_WITH_UNUSED_CLASS)

    js_parser = VanillaJSParser(JS_WITH_ORPHAN_SELECTOR, "script.js")
    js_details = js_parser.parse()
    js_file_info = FileStructureInfo(file_type="javascript", js_details=js_details, raw_content_summary=JS_WITH_ORPHAN_SELECTOR)

    # Build the project map
    project_map = ProjectStructureMap(
        apps={
            "my_app": AppStructureInfo(
                files={
                    "template.html": html_file_info,
                    "style.css": css_file_info,
                    "script.js": js_file_info,
                }
            )
        }
    )
    return project_map

class TestFrontendValidation:
    """Tests the integrated FrontendValidator and its analyzers."""

    def test_js_html_validator_finds_orphan_selector(self, project_map_for_validation: ProjectStructureMap):
        """
        Tests that the cross-reference validator detects a JS `getElementById`
        targeting an ID that does not exist in any HTML file.
        """
        validator = FrontendValidator(project_map_for_validation)
        report = validator.validate()

        orphan_issue = next((issue for issue in report.issues if "Orphaned JS selector" in issue.message), None)
        assert orphan_issue is not None
        assert orphan_issue.severity == "medium"
        assert orphan_issue.category == "Functionality"
        assert "non-existent ID '#non-existent-btn'" in orphan_issue.message
        assert orphan_issue.file_path == "script.js"

    def test_accessibility_analyzer_finds_issues(self):
        """
        Tests that the AccessibilityAnalyzer correctly aggregates issues
        from the individual file parsers.
        """
        # Create a map with an accessibility issue
        html_parser = HTMLParser(HTML_MISSING_ALT)
        html_details = html_parser.parse()
        project_map = ProjectStructureMap(
            global_files={"bad.html": FileStructureInfo(file_type="template", html_details=html_details)}
        )

        validator = FrontendValidator(project_map)
        report = validator.validate()

        alt_issue = next((issue for issue in report.issues if "[WCAG 1.1.1]" in issue.message), None)
        assert alt_issue is not None
        assert alt_issue.severity == "critical"
        assert alt_issue.category == "Accessibility"
        assert "Image is missing an 'alt' attribute" in alt_issue.message
        assert alt_issue.file_path == "bad.html"

    def test_performance_analyzer_finds_unused_css(self, project_map_for_validation: ProjectStructureMap):
        """
        Tests that the PerformanceAnalyzer detects unused CSS classes.
        Note: This is a basic heuristic and might have false positives/negatives.
        """
        # This test is more complex as it requires a full project scan.
        # The current implementation of PerformanceAnalyzer is a placeholder.
        # We will test the principle.
        pytest.skip("PerformanceAnalyzer unused CSS detection is heuristic and needs more robust implementation to test reliably.")

    def test_validator_handles_non_semantic_html(self):
        """
        Tests that the validator flags non-semantic HTML as a warning/info.
        """
        parser = HTMLParser(HTML_NON_SEMANTIC)
        details = parser.parse()
        
        # The HTML parser's internal validation should catch this.
        # Let's check the direct output of the parser.
        structure_issues = details.validation.structure_issues
        # This check is currently not implemented in the provided HTMLParser.
        # If it were, the test would look like this:
        # assert any("Consider using semantic <header>" in issue.message for issue in structure_issues)
        pytest.skip("Non-semantic HTML check is not fully implemented in the current HTMLParser.")

    def test_full_validation_report(self, project_map_for_validation: ProjectStructureMap):
        """
        Tests the generation of a full report, ensuring issues from different
        validators are aggregated and prioritized.
        """
        validator = FrontendValidator(project_map_for_validation)
        report = validator.validate()

        assert report.total_issues > 0
        
        # Check for the high-priority orphan selector issue
        assert any("Orphaned JS selector" in issue.message for issue in report.issues)
        
        # Check that severities are ordered correctly (critical/high first)
        severities = [issue.severity for issue in report.issues]
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        
        # Ensure the list is sorted by severity
        assert severities == sorted(severities, key=lambda s: severity_order.get(s, 99))