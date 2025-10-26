# backend/src/core/tests/test_vanilla_js_parser.py
import pytest
from src.core.parsers.vanilla_js_parser import VanillaJSParser

# --- Test Data ---

VALID_JS = """
import { helper } from './utils.js';

const API_ENDPOINT = '/api/v1/data';

/**
 * Fetches data from the API.
 */
async function fetchData(id) {
    try {
        const response = await fetch(`${API_ENDPOINT}/${id}`);
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Fetch error:', error);
    }
}

document.querySelector('#submit-btn').addEventListener('click', () => {
    const inputElement = document.querySelector('#data-input');
    localStorage.setItem('lastInput', inputElement.value);
});

export const utilityFunction = () => {
    // A simple utility
    return true;
};
"""

JS_WITH_ISSUES = """
var globalVar = "should not be used";

function oldStyleFunction(cb) {
    cb();
}

eval("alert('pwned')");

function updateContent() {
    var element = document.getElementById('content');
    element.innerHTML = '<p>User controlled content</p>'; // XSS risk
}

fetch('/api/no-error-handling').then(res => res.json());

console.log("This should not be in production");
debugger;

const API_KEY = "ak_this_is_a_very_long_and_insecure_hardcoded_api_key";
"""


class TestVanillaJSParser:
    """Tests for the VanillaJSParser class."""

    def test_parse_valid_js(self):
        """Tests that a valid JS file is parsed with minimal validation issues."""
        parser = VanillaJSParser(VALID_JS, "script.js")
        details = parser.parse()

        # Extraction assertions
        assert './utils.js' in details.imports
        assert 'utilityFunction' in details.exports
        assert any(f.name == 'fetchData' and f.is_async for f in details.functions)
        assert any(v.name == 'API_ENDPOINT' and v.type == 'const' for v in details.variables)
        assert any(d[1] == '#submit-btn' for d in details.dom_manipulations)
        assert any(e.event_type == 'click' for e in details.event_listeners)
        assert any('localStorage.setItem' in usage for usage in details.local_storage_usage)
        # Note: We need to check for the URL with its quotes to match what the parser now extracts
        assert any(a.url == '`${API_ENDPOINT}/${id}`' for a in details.api_calls)

        # Validation assertions (expecting only info-level issues for a valid file)
        validation = details.validation
        assert not validation.security_issues
        assert not validation.performance_issues
        
        # ========================================================================
        # THIS IS THE CORRECTED ASSERTION
        # This correctly asserts that NO issue messages contain the forbidden string.
        # It passes correctly if the list of issues is empty.
        # ========================================================================
        assert not any("Usage of 'getElementById' found" in issue.message for issue in validation.dom_issues)
        
        # May find console.error, which is acceptable for error handling.
        assert len(validation.organization_issues) <= 1

    def test_extract_all_elements(self):
        """Tests that all types of JS elements are extracted correctly."""
        parser = VanillaJSParser(VALID_JS, "script.js")
        details = parser.parse()

        assert len(details.imports) == 1
        assert len(details.exports) == 1
        assert len(details.functions) == 2  # fetchData and the arrow function
        assert len(details.variables) == 4  # API_ENDPOINT, response, data, inputElement
        assert len(details.dom_manipulations) == 2
        assert len(details.event_listeners) == 1
        assert len(details.api_calls) == 1
        assert len(details.local_storage_usage) == 1

    def test_validate_modern_js_issues(self):
        """Tests detection of outdated JavaScript patterns."""
        parser = VanillaJSParser(JS_WITH_ISSUES, "issues.js")
        details = parser.parse()
        issues = details.validation.modernjs_issues

        assert any("Usage of 'var' is discouraged" in issue.message for issue in issues)
        assert any("Consider using arrow functions" in issue.message for issue in issues)
        assert any("Consider using async/await" in issue.message for issue in issues)

    def test_validate_dom_issues(self):
        """Tests detection of problematic DOM interactions."""
        parser = VanillaJSParser(JS_WITH_ISSUES, "issues.js")
        details = parser.parse()
        issues = details.validation.dom_issues

        assert any("'getElementById' found" in issue.message for issue in issues)
        assert any("Usage of '.innerHTML' can be a security risk" in issue.message for issue in issues)

    def test_validate_api_issues(self):
        """Tests detection of API call issues like missing error handling."""
        parser = VanillaJSParser(JS_WITH_ISSUES, "issues.js")
        details = parser.parse()
        issues = details.validation.api_issues

        assert any("may be missing try/catch error handling" in issue.message for issue in issues)

    def test_validate_security_issues(self):
        """Tests detection of major security vulnerabilities."""
        parser = VanillaJSParser(JS_WITH_ISSUES, "issues.js")
        details = parser.parse()
        issues = details.validation.security_issues

        assert any("Use of 'eval()' is a major security risk" in issue.message for issue in issues)
        assert any("Potential hardcoded credential found" in issue.message for issue in issues)

    def test_validate_organization_issues(self):
        """Tests detection of code organization and style issues."""
        parser = VanillaJSParser(JS_WITH_ISSUES, "issues.js")
        details = parser.parse()
        issues = details.validation.organization_issues

        assert any("Global variables detected" in issue.message for issue in issues)
        assert any("Found 'console.log'" in issue.message for issue in issues)
        assert any("Found 'debugger' statement" in issue.message for issue in issues)

    def test_function_extraction_types(self):
        """Tests extraction of various function declaration styles."""
        js_code = """
        function standardFunc(a, b) {}
        async function asyncStandardFunc() {}
        const arrowFunc = (c, d) => {};
        let asyncArrowFunc = async (e) => {};
        """
        parser = VanillaJSParser(js_code, "funcs.js")
        details = parser.parse()

        assert len(details.functions) == 4
        
        std_func = next(f for f in details.functions if f.name == 'standardFunc')
        async_std_func = next(f for f in details.functions if f.name == 'asyncStandardFunc')
        arrow_func = next(f for f in details.functions if f.name == 'arrowFunc')
        async_arrow_func = next(f for f in details.functions if f.name == 'asyncArrowFunc')

        assert not std_func.is_async
        assert std_func.params == ['a', 'b']

        assert async_std_func.is_async
        assert not async_std_func.params

        assert not arrow_func.is_async
        assert arrow_func.params == ['c', 'd']

        assert async_arrow_func.is_async
        assert async_arrow_func.params == ['e']