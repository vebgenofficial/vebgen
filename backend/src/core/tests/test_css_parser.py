# backend/src/core/tests/test_css_parser.py
import pytest
from src.core.parsers.css_parser import CSSParser

# --- Test Data ---

CSS_WITH_IMPORT = "@import url('theme.css'); .body { color: blue; }"
CSS_WITH_MEDIA_QUERY = """
@media (min-width: 600px) {
    .container {
        display: flex;
    }
}
"""
CSS_WITH_KEYFRAMES = """
@keyframes slide-in {
    from {
        transform: translateX(-100%);
    }
    to {
        transform: translateX(0);
    }
}
"""
CSS_WITH_FONT_FACE = """
@font-face {
    font-family: 'MyFont';
    src: url('myfont.woff2');
}
_"""
CSS_WITH_ROOT_VARS = """
:root {
    --main-bg-color: #f0f0f0;
    --main-text-color: #333;
}
.card { color: var(--main-text-color); }
"""
CSS_FOR_SPECIFICITY = "#main .nav > li.active"
CSS_WITH_GRID_FLEX = ".grid { display: grid; } .flex { display: flex; }"

CSS_FOR_VALIDATION = """
@import 'legacy.css'; /* Architecture warning */

#main .container .content .sidebar .card { /* Naming/Specificity warning */
    color: red;
}

.element {
    will-change: transform; /* Performance info */
    font-size: 16px; /* Responsive info */
}

a:focus {
    outline: none; /* Accessibility error */
}

@media (max-width: 500px) { /* Responsive warning */
    body { font-size: 14px; }
}

div::before {
    content: 'Important: '; /* Accessibility warning */
}
"""

class TestCSSParser:
    """Comprehensive tests for the CSSParser."""

    def test_parse_import(self):
        """Tests that @import rules are correctly extracted."""
        parser = CSSParser(CSS_WITH_IMPORT, "style.css")
        details = parser.parse()
        assert "theme.css" in details.imports

    def test_parse_media_query(self):
        """Tests that @media queries and their nested rules are parsed."""
        parser = CSSParser(CSS_WITH_MEDIA_QUERY, "style.css")
        details = parser.parse()
        assert len(details.media_queries) == 1
        media_query = details.media_queries[0]
        assert media_query.condition == "(min-width: 600px)"
        assert len(media_query.rules) == 1
        assert media_query.rules[0].selector == ".container"
        assert media_query.rules[0].properties["display"] == "flex"

    def test_parse_keyframes(self):
        """Tests that @keyframes animations and their steps are parsed."""
        parser = CSSParser(CSS_WITH_KEYFRAMES, "style.css")
        details = parser.parse()
        assert len(details.animations) == 1
        animation = details.animations[0]
        assert animation.name == "slide-in"
        assert "from" in animation.steps
        assert "to" in animation.steps
        assert animation.steps["from"]["transform"] == "translateX(-100%)"

    def test_parse_font_face(self):
        """Tests that @font-face rules are parsed."""
        parser = CSSParser(CSS_WITH_FONT_FACE, "style.css")
        details = parser.parse()
        assert len(details.font_faces) == 1
        font_face = details.font_faces[0]
        assert font_face["font-family"].strip("'\"") == "MyFont"
        assert "myfont.woff2" in font_face["src"]

    def test_parse_root_variables(self):
        """Tests that custom properties defined in :root are extracted."""
        parser = CSSParser(CSS_WITH_ROOT_VARS, "style.css")
        details = parser.parse()
        assert details.custom_properties["--main-bg-color"] == "#f0f0f0"
        assert details.custom_properties["--main-text-color"] == "#333"
        # Ensure the .card rule is also parsed
        assert len(details.rules) == 1
        assert details.rules[0].selector == ".card"

    def test_calculate_specificity(self):
        """Tests the specificity calculation for a complex selector."""
        parser = CSSParser(f"{CSS_FOR_SPECIFICITY} {{ color: blue; }}", "style.css")
        details = parser.parse()
        rule = details.rules[0]
        # Specificity: (IDs, classes/attributes, elements)
        # #main -> 1 ID
        # .nav, .active -> 2 classes
        # li -> 1 element
        assert rule.specificity == (1, 2, 1)

    def test_detect_grid_and_flexbox(self):
        """Tests the detection of `display: grid` and `display: flex`."""
        parser = CSSParser(CSS_WITH_GRID_FLEX, "style.css")
        details = parser.parse()
        assert details.uses_grid is True
        assert details.uses_flexbox is True

    def test_validation_finds_all_issues(self):
        """
        Tests that the validation methods correctly identify various issues
        and add them to the validation results.
        """
        parser = CSSParser(CSS_FOR_VALIDATION, "style.css")
        details = parser.parse()
        validation = details.validation

        # Architecture
        assert any("@import rules found" in issue.message for issue in validation.architecture_issues)
        
        # Naming/Specificity
        assert any("seems deeply nested" in issue.message for issue in validation.naming_issues)

        # Performance
        assert any("'will-change' property is used" in issue.message for issue in validation.performance_issues)

        # Responsive
        assert any("desktop-first instead of a mobile-first" in issue.message for issue in validation.responsive_issues)
        assert any("Fixed unit 'px' used" in issue.message for issue in validation.responsive_issues)

        # Accessibility
        assert any("Focus outline is disabled" in issue.message for issue in validation.accessibility_issues)
        assert any("Content added via ::before or ::after" in issue.message for issue in validation.accessibility_issues)
        # The prefers-reduced-motion check is in the analyzer, not the parser, so we don't test it here.

    def test_parsing_error_handling(self):
        """Tests that a parsing error is gracefully handled and logged as a validation issue."""
        malformed_css = ".my-class { color: blue; background: " # Missing value and closing brace
        parser = CSSParser(malformed_css, "malformed.css")
        details = parser.parse()
        assert any("CSS parsing error" in issue.message for issue in details.validation.architecture_issues)
