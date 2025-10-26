# backend/src/core/parsers/vanilla_js_parser.py
import logging
import re
from typing import List, Optional

from ..project_models import (
    VanillaJSFileDetails, JSFunction, JSVariable, JSEventListener, JSAPICall,
    JSValidationIssue, JSValidationResults
)

logger = logging.getLogger(__name__)

class VanillaJSParser:
    """
    Parses JavaScript content using regular expressions to extract structured data and perform validation.
    Covers functions, variables, DOM manipulation, API calls, and enterprise-level checks.
    """
    def __init__(self, js_content: str, file_path: str):
        self.content = js_content
        self.file_path = file_path
        self.lines = js_content.splitlines()
        self.details = VanillaJSFileDetails()
        self.validation_results = JSValidationResults()

    def parse(self) -> VanillaJSFileDetails:
        """Main entry point to parse the JS and return structured details."""
        logger.debug(f"Starting JS parsing for '{self.file_path}'.")

        self._extract_imports_exports()
        self._extract_functions()
        self._extract_variables()
        self._extract_dom_manipulation()
        self._extract_event_listeners()
        self._extract_api_calls()
        self._extract_storage_usage()

        self._validate_all()

        self.details.validation = self.validation_results
        logger.debug(f"Finished JS parsing for '{self.file_path}'.")
        return self.details

    def _add_validation_issue(self, severity, category, message, line_num=None, element=None):
        """Helper to add a validation issue."""
        issue = JSValidationIssue(
            severity=severity,
            category=category,
            message=message,
            line=line_num,
            element_preview=element
        )
        # Pydantic uses alias for validation, so we access it via the alias
        getattr(self.validation_results, f"{category.lower()}_issues").append(issue)

    # --- Extraction Methods ---

    def _extract_imports_exports(self):
        self.details.imports = re.findall(r"import\s+.*\s+from\s+['\"](.*?)['\"]", self.content)
        self.details.exports = re.findall(r"export\s+(?:const|let|var|function|class)\s+(\w+)", self.content)

    def _extract_functions(self):
        # Matches: function name(p1, p2), const name = (p1) =>, async function ...
        pattern = re.compile(r"(async\s+)?function\s+(\w+)\s*\((.*?)\)|(?:const|let|var)\s+(\w+)\s*=\s*(async\s*)?\((.*?)\)\s*=>")
        for match in pattern.finditer(self.content):
            is_async = bool(match.group(1) or match.group(5))
            if match.group(2): # Standard function
                name, params_str = match.group(2), match.group(3)
            else: # Arrow function
                name, params_str = match.group(4), match.group(6)

            # Safely handle cases where params_str might be None (e.g., function with no params)
            params = [p.strip() for p in (params_str or "").split(',') if p.strip()]
            self.details.functions.append(JSFunction(name=name, is_async=is_async, params=params))

    def _extract_variables(self):
        # This regex now uses a negative lookahead `(?!\s*=.*=>)` to exclude arrow function declarations.
        # It finds `const name = value` but not `const name = () => {}`
        pattern = re.compile(r"\b(const|let|var)\s+([\w\d_]+)\s*=\s*(?!.*=>)")
        for match in pattern.finditer(self.content):
            self.details.variables.append(JSVariable(name=match.group(2), type=match.group(1)))

    def _extract_dom_manipulation(self):
        self.details.dom_manipulations = re.findall(r"document\.(getElementById|querySelector|querySelectorAll)\(['\"](.*?)['\"]\)", self.content)

    def _extract_event_listeners(self):
        # Matches: element.addEventListener('click', handler)
        # This regex now correctly captures the target, event type, and handler.
        pattern = re.compile(
            r"(.*?)\.addEventListener\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(function\s*\(.*?\)|.*?=>|\w+)"
        )
        for match in pattern.finditer(self.content):
            self.details.event_listeners.append(JSEventListener(
                target_selector=match.group(1).strip(),
                event_type=match.group(2).strip(),
                handler_name=match.group(3).strip()
            ))

    def _extract_api_calls(self):
        # Matches: fetch('/api/data'), axios.get('/api/users')
        # This improved regex handles single quotes, double quotes, and backticks for the URL,
        # and correctly captures the method from an options object if it exists.
        # Example: fetch('/api/data') or fetch('/api/data', { method: 'POST' })
        
        # ========================================================================
        # FINAL CORRECTED REGEX
        # This version captures the full quoted string in group 1 to match the test case.
        # ========================================================================
        fetch_pattern = re.compile(
            r"fetch\s*\(\s*(([`'\"]).*?\2)(?:[^)]*?\bmethod\s*:\s*['\"](\w+)['\"])?",
            re.IGNORECASE | re.DOTALL
        )
        for match in fetch_pattern.finditer(self.content):
            # The full url string with quotes is now in group 1
            url = match.group(1) 
            # The method is now in group 3
            method = (match.group(3) or 'GET').upper()
            self.details.api_calls.append(JSAPICall(method=method, url=url))

        # Match axios calls where the method is part of the function name, e.g., axios.get(...)
        axios_pattern = re.compile(r"axios\.(get|post|put|delete|patch)\s*\(\s*([`'\"])(.*?)\2", re.IGNORECASE)
        for match in axios_pattern.finditer(self.content):
            method = match.group(1).upper()
            url = match.group(3)
            self.details.api_calls.append(JSAPICall(method=method, url=url))

    def _extract_storage_usage(self):
        # This improved regex now correctly captures method calls like .setItem(...)
        self.details.local_storage_usage = re.findall(r"((?:localStorage|sessionStorage)\.\w+\(.*\))", self.content)

    # --- Validation Methods ---

    def _validate_all(self):
        self._validate_modern_js()
        self._validate_organization()
        self._validate_dom()
        self._validate_api()
        self._validate_performance()
        self._validate_enterprise_checks()
        self._validate_security()

    def _validate_modern_js(self):
        for i, line in enumerate(self.lines):
            if re.search(r"\bvar\s+\w+", line):
                self._add_validation_issue("warning", "ModernJS", "Usage of 'var' is discouraged. Use 'const' or 'let' instead.", i + 1, line.strip())
            # More general check for `function` keyword not part of a class method definition.
            if re.search(r"\bfunction\b", line) and "=>" not in line and not line.strip().startswith("async function"):
                 if "(" in line and ")" in line: # Basic check to ensure it's a function definition/expression
                    self._add_validation_issue("info", "ModernJS", "Consider using arrow functions for callbacks.", i + 1, line.strip())
            if re.search(r"fetch\(.*\)\.then\(", self.content):
                self._add_validation_issue("info", "ModernJS", "Detected .then() chain for fetch. Consider using async/await for cleaner code.", element="fetch(...).then(...)")

    def _validate_organization(self):
        # This is a heuristic. A true check for global variables is complex with regex.
        # We check for variables declared outside of any function scope.
        if re.search(r"^(const|let|var)\s+\w+", self.content, re.MULTILINE):
            self._add_validation_issue("info", "Organization", "Global variables detected. Consider using modules or an IIFE to avoid polluting the global scope.", element=re.search(r"^(const|let|var)\s+\w+", self.content, re.MULTILINE).group(0))

    def _validate_dom(self):
        for i, line in enumerate(self.lines):
            if "getElementById" in line:
                self._add_validation_issue("info", "DOM", "Usage of 'getElementById' found. 'querySelector' is often more flexible.", i + 1, line.strip())
            if ".innerHTML" in line:
                self._add_validation_issue("warning", "DOM", "Usage of '.innerHTML' can be a security risk (XSS) if used with user input. Prefer '.textContent'.", i + 1, line.strip())

    def _validate_api(self):
        if "XMLHttpRequest" in self.content:
            self._add_validation_issue("warning", "API", "'XMLHttpRequest' is used. The 'fetch' API is a more modern and powerful alternative.", element="XMLHttpRequest")

        for api_call in self.details.api_calls:
            # Heuristic: check if a try/catch block surrounds the fetch call
            # or if the fetch call is awaited.
            call_line_index = -1
            for i, line in enumerate(self.lines):
                # We need to check for the URL content, not the quoted string
                url_content = api_call.url.strip('`"\'')
                if url_content in line:
                    call_line_index = i
                    break

            if call_line_index != -1 and 'await fetch' not in self.lines[call_line_index]:
                # Simple check: is 'try' on the line before or 'catch' on the line after?
                # This is a very basic heuristic.
                surrounding_lines = "".join(self.lines[max(0, call_line_index-2):min(len(self.lines), call_line_index+3)])
                if "try" not in surrounding_lines or "catch" not in surrounding_lines:
                    self._add_validation_issue("warning", "API", f"API call to '{api_call.url}' may be missing try/catch error handling.", call_line_index + 1)

    def _validate_security(self):
        for i, line in enumerate(self.lines):
            if "eval(" in line:
                self._add_validation_issue("error", "Security", "Use of 'eval()' is a major security risk and is strongly discouraged.", i + 1, line.strip())
            if "new Function(" in line:
                self._add_validation_issue("error", "Security", "Use of 'new Function()' is a security risk, similar to 'eval()'.", i + 1, line.strip())

    def _validate_performance(self):
        """Validates against common performance anti-patterns."""
        if "new XMLHttpRequest()" in self.content and "async: false" in self.content:
            self._add_validation_issue("error", "Performance", "Synchronous XMLHttpRequest found. This blocks the main thread and should be avoided.", element="new XMLHttpRequest()")

    def _validate_enterprise_checks(self):
        """Performs enterprise-level validation checks."""
        for i, line in enumerate(self.lines):
            if "console.log(" in line:
                self._add_validation_issue("info", "Organization", "Found 'console.log'. Ensure this is for debugging and not present in production code.", i + 1, line.strip())
            if "debugger;" in line:
                self._add_validation_issue("warning", "Organization", "Found 'debugger' statement. This should be removed from production code.", i + 1, line.strip())

        # Heuristic for hardcoded credentials
        # Looks for long strings assigned to variables with names like KEY, SECRET, TOKEN
        credential_pattern = re.compile(r"(?:const|let)\s+(?:[A-Z_]*_)?(?:API_KEY|SECRET|TOKEN|PASSWORD)(?:_[A-Z_]*)?\s*=\s*['\"]([a-zA-Z0-9\-_/.]{20,})['\"]", re.IGNORECASE)
        for match in credential_pattern.finditer(self.content):
            self._add_validation_issue("error", "Security", "Potential hardcoded credential found. Use environment variables or a secure secret management system.", element=match.group(0))