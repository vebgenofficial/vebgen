# ⚡ vanilla_js_parser.py — VebGen JavaScript Analysis Engine

## 🎯 Overview

**Location:** `backend/src/core/parsers/vanilla_js_parser.py`  
**Size:** 12KB (211 lines)  
**Purpose:** Parses JavaScript content using regular expressions to extract structured data and perform comprehensive validation covering functions, variables, DOM manipulation, API calls, and enterprise-level security checks.

> **📌 Documentation Version**: v0.3.0  
> **🆕 Major Features**: Modern JS pattern detection, security vulnerability scanning, API call analysis, performance optimization, enterprise-grade validation

This is VebGen's **JavaScript intelligence engine**—the parser that understands JS structure, detects security vulnerabilities, validates modern patterns, and ensures enterprise-grade code quality.

---

## 🧠 What This File Does

### Core Functionality
- **Extracts JS structure** (functions, variables, imports, exports)
- **Detects security vulnerabilities** (eval usage, XSS risks, hardcoded credentials)
- **Validates modern patterns** (async/await, arrow functions, const/let)
- **Analyzes DOM manipulation** (querySelector vs getElementById, innerHTML risks)
- **API call analysis** (error handling, method detection, URL extraction)
- **Performance optimization** (layout thrashing, synchronous operations)

### Integration Points
- Used by `CodeIntelligenceService` for project scanning
- Feeds data to `PerformanceAnalyzer` for optimization analysis
- Provides structured data to `FrontendValidator` for quality gates
- Integrates with security validation for enterprise compliance

---

## 🗂️ File Structure

```text
vanilla_js_parser.py (211 lines)
├── VanillaJSParser (Main Class)
│   ├── __init__() - Initialize with content and file path
│   ├── parse() - Main entry point
│   │
│   ├── Extraction Methods (7 methods)
│   │   ├── _extract_imports_exports() - ES6 module analysis
│   │   ├── _extract_functions() - Function declarations and expressions
│   │   ├── _extract_variables() - Variable declarations (const/let/var)
│   │   ├── _extract_dom_manipulation() - DOM query methods
│   │   ├── _extract_event_listeners() - Event listener patterns
│   │   ├── _extract_api_calls() - Fetch/axios API calls
│   │   └── _extract_storage_usage() - localStorage/sessionStorage
│   │
│   ├── Validation Methods (7 methods)
│   │   ├── _validate_modern_js() - Modern JS patterns
│   │   ├── _validate_organization() - Code organization
│   │   ├── _validate_dom() - DOM manipulation best practices
│   │   ├── _validate_api() - API call error handling
│   │   ├── _validate_performance() - Performance anti-patterns
│   │   ├── _validate_enterprise_checks() - Production readiness
│   │   └── _validate_security() - Security vulnerability detection
│   │
│   └── Helper Methods
│       └── _add_validation_issue() - Unified issue creation
│
└── Data Models (from project_models.py)
    ├── VanillaJSFileDetails - Main output structure
    ├── JSFunction, JSVariable, JSEventListener - JS structure
    └── JSValidationIssue, JSValidationResults - Validation output
```

---

## 🔧 Key Methods Deep Dive

### 1. Main Entry Point

```python
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
    return self.details
```

### 2. Function Extraction (Advanced)

```python
def _extract_functions(self):
    # Matches: function name(p1, p2), const name = (p1) =>, async function ...
    pattern = re.compile(r"(async\s+)?function\s+(\w+)\s*\((.*?)\)|(?:const|let|var)\s+(\w+)\s*=\s*(async\s*)?\((.*?)\)\s*=>")
    for match in pattern.finditer(self.content):
        is_async = bool(match.group(1) or match.group(5))
        if match.group(2): # Standard function
            name, params_str = match.group(2), match.group(3)
        else: # Arrow function
            name, params_str = match.group(4), match.group(6)

        # Safely handle cases where params_str might be None
        params = [p.strip() for p in (params_str or "").split(',') if p.strip()]
        self.details.functions.append(JSFunction(name=name, is_async=is_async, params=params))
```

### 3. API Call Analysis

```python
def _extract_api_calls(self):
    # Matches: fetch('/api/data'), axios.get('/api/users')
    fetch_pattern = re.compile(
        r"fetch\s*\(\s*(([`'\"]).*?\2)(?:[^)]*?\bmethod\s*:\s*['\"](\w+)['\"])?",
        re.IGNORECASE | re.DOTALL
    )
    for match in fetch_pattern.finditer(self.content):
        url = match.group(1)  # Full quoted string
        method = (match.group(3) or 'GET').upper()
        self.details.api_calls.append(JSAPICall(method=method, url=url))

    # Match axios calls
    axios_pattern = re.compile(r"axios\.(get|post|put|delete|patch)\s*\(\s*([`'\"])(.*?)\2", re.IGNORECASE)
    for match in axios_pattern.finditer(self.content):
        method = match.group(1).upper()
        url = match.group(3)
        self.details.api_calls.append(JSAPICall(method=method, url=url))
```

### 4. Security Validation

```python
def _validate_security(self):
    for i, line in enumerate(self.lines):
        if "eval(" in line:
            self._add_validation_issue("error", "Security", 
                "Use of 'eval()' is a major security risk and is strongly discouraged.", 
                i + 1, line.strip())
        if "new Function(" in line:
            self._add_validation_issue("error", "Security", 
                "Use of 'new Function()' is a security risk, similar to 'eval()'.", 
                i + 1, line.strip())

    # Heuristic for hardcoded credentials
    credential_pattern = re.compile(r"(?:const|let)\s+(?:[A-Z_]*_)?(?:API_KEY|SECRET|TOKEN|PASSWORD)(?:_[A-Z_]*)?\s*=\s*['\"]([a-zA-Z0-9\-_/.]{20,})['\"]", re.IGNORECASE)
    for match in credential_pattern.finditer(self.content):
        self._add_validation_issue("error", "Security", 
            "Potential hardcoded credential found. Use environment variables or a secure secret management system.", 
            element=match.group(0))
```

### 5. Modern JS Validation

```python
def _validate_modern_js(self):
    for i, line in enumerate(self.lines):
        if re.search(r"\bvar\s+\w+", line):
            self._add_validation_issue("warning", "ModernJS", 
                "Usage of 'var' is discouraged. Use 'const' or 'let' instead.", 
                i + 1, line.strip())
        
        if re.search(r"\bfunction\b", line) and "=>" not in line and not line.strip().startswith("async function"):
            if "(" in line and ")" in line:
                self._add_validation_issue("info", "ModernJS", 
                    "Consider using arrow functions for callbacks.", 
                    i + 1, line.strip())
        
        if re.search(r"fetch\(.*\)\.then\(", self.content):
            self._add_validation_issue("info", "ModernJS", 
                "Detected .then() chain for fetch. Consider using async/await for cleaner code.", 
                element="fetch(...).then(...)")
```

---

## 📊 Validation Categories

### 1. Modern JS Validation
- **var usage** (warning) - Recommends const/let
- **Function declarations** (info) - Suggests arrow functions
- **Promise chains** (info) - Recommends async/await

### 2. Organization Validation
- **Global variables** (info) - Module scope recommendations
- **Code structure** - Organization best practices

### 3. DOM Validation
- **getElementById usage** (info) - Recommends querySelector
- **innerHTML usage** (warning) - XSS security risk
- **DOM manipulation patterns** - Best practice recommendations

### 4. API Validation
- **XMLHttpRequest usage** (warning) - Recommends fetch API
- **Error handling** (warning) - Missing try/catch blocks
- **API call patterns** - Modern fetch usage

### 5. Performance Validation
- **Synchronous operations** (error) - Blocking main thread
- **Layout thrashing** - Performance anti-patterns

### 6. Security Validation
- **eval() usage** (error) - Major security risk
- **new Function()** (error) - Security vulnerability
- **Hardcoded credentials** (error) - Secret management
- **XSS risks** (warning) - innerHTML security

### 7. Enterprise Validation
- **console.log usage** (info) - Production readiness
- **debugger statements** (warning) - Production cleanup
- **Code organization** - Enterprise standards

---

## 🧪 Test Coverage & Examples

### Test Data Examples

**Valid JavaScript:**
```javascript
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
```

**JavaScript with Issues:**
```javascript
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
```

**Function Extraction Examples:**
```javascript
function standardFunc(a, b) {}
async function asyncStandardFunc() {}
const arrowFunc = (c, d) => {};
let asyncArrowFunc = async (e) => {};
```

### Test Results

**Valid JavaScript Results:**
- ✅ **Imports**: `['./utils.js']`
- ✅ **Exports**: `['utilityFunction']`
- ✅ **Functions**: 2 functions (fetchData, arrow function)
- ✅ **Variables**: 4 variables (API_ENDPOINT, response, data, inputElement)
- ✅ **DOM Manipulations**: 2 queries (`#submit-btn`, `#data-input`)
- ✅ **Event Listeners**: 1 listener (click event)
- ✅ **API Calls**: 1 call (`${API_ENDPOINT}/${id}`)
- ✅ **Storage Usage**: 1 usage (`localStorage.setItem`)
- ✅ **No security issues**
- ✅ **No performance issues**

**JavaScript with Issues Results:**
- ❌ **ModernJS**: var usage warning, function declaration info, .then() chain info
- ❌ **DOM**: getElementById usage info, innerHTML XSS warning
- ❌ **API**: Missing error handling warning
- ❌ **Security**: eval() error, hardcoded credential error
- ❌ **Organization**: Global variables info, console.log info, debugger warning

**Function Extraction Results:**
- ✅ **Standard Function**: `standardFunc(a, b)` - not async, params: `['a', 'b']`
- ✅ **Async Function**: `asyncStandardFunc()` - async, no params
- ✅ **Arrow Function**: `arrowFunc(c, d)` - not async, params: `['c', 'd']`
- ✅ **Async Arrow**: `asyncArrowFunc(e)` - async, params: `['e']`

---

## 🔗 Integration & Data Models

### Input/Output Flow
```
JavaScript Content → VanillaJSParser → VanillaJSFileDetails → PerformanceAnalyzer + SecurityValidation → FrontendValidator
```

### Key Data Models

**VanillaJSFileDetails:**
```python
class VanillaJSFileDetails:
    imports: List[str]
    exports: List[str]
    functions: List[JSFunction]
    variables: List[JSVariable]
    dom_manipulations: List[Tuple[str, str]]  # (method, selector)
    event_listeners: List[JSEventListener]
    api_calls: List[JSAPICall]
    local_storage_usage: List[str]
    validation: JSValidationResults
```

**JSFunction:**
```python
class JSFunction:
    name: str
    is_async: bool
    params: List[str]
```

**JSVariable:**
```python
class JSVariable:
    name: str
    type: str  # 'const', 'let', 'var'
```

**JSEventListener:**
```python
class JSEventListener:
    target_selector: str
    event_type: str
    handler_name: str
```

**JSAPICall:**
```python
class JSAPICall:
    method: str
    url: str
```

---

## ⚙️ Configuration & Extension

### Adding New Validation Rules

```python
def _validate_custom_checks(self):
    """Add your custom validation logic here."""
    # Example: Check for specific patterns
    for i, line in enumerate(self.lines):
        if 'customPattern' in line:
            self._add_validation_issue("warning", "Custom", 
                "Custom pattern detected.", i + 1, line.strip())
```

### Modifying Severity Levels

```python
# In validation methods, adjust severity as needed:
self._add_validation_issue("error", "Security", message, line, element)     # Blocks completion
self._add_validation_issue("warning", "ModernJS", message, line, element)   # Logs but continues
self._add_validation_issue("info", "Performance", message, line, element)   # Informational only
```

### Custom Security Patterns

```python
# Add custom security pattern detection
def _validate_custom_security(self):
    # Example: Check for specific security anti-patterns
    dangerous_patterns = [
        (r'document\.write\s*\(', "document.write() usage detected"),
        (r'window\.location\s*=', "Direct window.location assignment"),
    ]
    
    for pattern, message in dangerous_patterns:
        if re.search(pattern, self.content):
            self._add_validation_issue("warning", "Security", message)
```

---

## 📝 Changelog (v0.3.0)

### 🆕 New Features:
- **Modern JS pattern detection** - async/await, arrow functions, const/let
- **Security vulnerability scanning** - eval(), XSS risks, credential detection
- **API call analysis** - Error handling, method detection, URL extraction
- **Performance optimization** - Layout thrashing, synchronous operations
- **Enterprise validation** - Production readiness, code organization

### 🔧 Technical Improvements:
- **Advanced regex patterns** - Function extraction, API call detection
- **Security heuristics** - Credential detection, XSS risk analysis
- **Performance analysis** - Anti-pattern detection, optimization recommendations
- **Enterprise-grade validation** - Production-ready quality checks

### 🧪 Testing:
- **7 comprehensive test scenarios** covering all parsing and validation categories
- **Real-world JavaScript examples** with expected validation results
- **Security vulnerability testing** - eval(), XSS, credential detection
- **Modern JS pattern validation** - async/await, arrow functions, const/let

---

## 🎉 Summary

**VanillaJSParser** is VebGen's **JavaScript intelligence engine**:

✅ **Comprehensive extraction** (functions, variables, imports, API calls)  
✅ **Security vulnerability detection** (eval, XSS, credential scanning)  
✅ **Modern JS validation** (async/await, arrow functions, const/let)  
✅ **Performance optimization** (layout thrashing, synchronous operations)  
✅ **API call analysis** (error handling, method detection)  
✅ **Enterprise validation** (production readiness, code organization)  
✅ **Production-ready quality gates** (blocks completion until issues fixed)  

**This parser ensures every JavaScript file follows modern best practices for security, performance, and maintainability before features are marked complete.**

---

## 🔗 Related Documentation

For more on VebGen's frontend analysis suite, see:

- **[html_parser.md](html_parser.md)** - HTML parsing and validation
- **[css_parser.md](css_parser.md)** - CSS parsing and validation
- **[analyzers.md](analyzers.md)** - Frontend quality analyzers
- **[frontend_validator.md](frontend_validator.md)** - Main validation orchestrator

---

<div align="center">

**Questions?** Check the main README or workflow_manager.md for integration details!

**Want to extend JavaScript validation?** See the "Configuration & Extension" section above.

</div>
