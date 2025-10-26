# 🔍 html_parser.py — VebGen HTML Analysis Engine

## 🎯 Overview

**Location:** `backend/src/core/parsers/html_parser.py`  
**Size:** 13KB (253 lines)  
**Purpose:** Parses HTML content using BeautifulSoup to extract structured data and perform comprehensive validation covering semantic structure, forms, SEO, accessibility, and enterprise-level checks.

> **📌 Documentation Version**: v0.3.0  
> **🆕 Major Features**: Django template tag extraction, enterprise validation, comprehensive accessibility checks, SEO optimization

This is VebGen's **HTML intelligence engine**—the parser that understands HTML structure, validates accessibility compliance, detects SEO issues, and ensures enterprise-grade code quality.

---

## 🧠 What This File Does

### Core Functionality
- **Extracts structured data** from HTML (forms, meta tags, scripts, links)
- **Validates accessibility** against WCAG 2.1 guidelines
- **Detects SEO issues** (missing meta tags, title optimization)
- **Analyzes form structure** (CSRF tokens, labels, input types)
- **Enterprise validation** (deprecated tags, inline styles, security issues)
- **Django template integration** (extracts template tags and variables)

### Integration Points
- Used by `CodeIntelligenceService` for project scanning
- Feeds data to `AccessibilityAnalyzer` for WCAG compliance
- Provides structured data to `FrontendValidator` for quality gates

---

## 🗂️ File Structure

```text
html_parser.py (253 lines)
├── HTMLParser (Main Class)
│   ├── __init__() - Initialize with BeautifulSoup
│   ├── parse() - Main entry point
│   │
│   ├── Extraction Methods (7 methods)
│   │   ├── _extract_doctype_and_lang() - DOCTYPE and language detection
│   │   ├── _extract_title() - Page title extraction
│   │   ├── _extract_meta_tags() - Meta tags parsing
│   │   ├── _extract_links() - Link elements (canonical, stylesheets)
│   │   ├── _extract_scripts() - Script tags with async/defer detection
│   │   ├── _extract_forms() - Form structure and input analysis
│   │   └── _extract_django_template_tags() - Django template integration
│   │
│   ├── Validation Methods (5 methods)
│   │   ├── _validate_structure() - DOCTYPE, heading hierarchy, semantic structure
│   │   ├── _validate_accessibility() - Alt text, labels, focus indicators
│   │   ├── _validate_seo() - Meta descriptions, Open Graph, canonical links
│   │   ├── _validate_forms() - CSRF tokens, input labels, form security
│   │   └── _validate_enterprise() - Deprecated tags, inline styles, security
│   │
│   └── Helper Methods
│       └── _add_validation_issue() - Unified issue creation
│
└── Data Models (from project_models.py)
    ├── HTMLFileDetails - Main output structure
    ├── HTMLForm, HTMLFormInput - Form analysis
    ├── HTMLLink, HTMLMeta, HTMLScript - Element extraction
    └── HTMLValidationIssue, HTMLValidationResults - Validation output
```

---

## 🔧 Key Methods Deep Dive

### 1. Main Entry Point

```python
def parse(self) -> HTMLFileDetails:
    """Main entry point to parse the HTML and return structured details."""
    logger.debug("Starting HTML parsing and validation.")
    
    # Extraction
    self._extract_doctype_and_lang()
    self._extract_title()
    self._extract_meta_tags()
    self._extract_links()
    self._extract_scripts()
    self._extract_forms()
    self._extract_django_template_tags()

    # Validation
    self._validate_structure()
    self._validate_accessibility()
    self._validate_seo()
    self._validate_forms()
    self._validate_enterprise()

    self.details.validation = self.validation_results
    return self.details
```

### 2. Form Extraction (Advanced)

```python
def _extract_forms(self):
    for form_tag in self.soup.find_all('form'):
        form_model = HTMLForm(
            id=form_tag.get('id'),
            action=form_tag.get('action'),
            method=form_tag.get('method', 'GET').upper(),
            has_csrf_token='{% csrf_token %}' in str(form_tag)
        )
        for input_tag in form_tag.find_all(['input', 'textarea', 'select']):
            label_text = None
            input_id = input_tag.get('id')
            if input_id:
                label_tag = form_tag.find('label', {'for': input_id})
                if label_tag:
                    label_text = label_tag.get_text(strip=True)
            
            form_model.inputs.append(HTMLFormInput(
                tag=input_tag.name,
                type=input_tag.get('type'),
                name=input_tag.get('name'),
                id=input_id,
                label=label_text,
                is_required='required' in input_tag.attrs
            ))
        self.details.forms.append(form_model)
```

### 3. Django Template Integration

```python
def _extract_django_template_tags(self):
    # Find Django template tags {% tag %}
    tags_found = re.findall(r'{[%#]\s*(\w+)', self.content)
    # Find template variables {{ variable }}
    variables_found = re.findall(r'{{\s*([\w\.]+)', self.content)
    tags_found.extend(f"var:{v}" for v in variables_found)
    self.details.django_template_tags = sorted(list(set(tags_found)))
```

### 4. Accessibility Validation

```python
def _validate_accessibility(self):
    # Image alt text validation
    for img in self.soup.find_all('img'):
        if not img.has_attr('alt'):
            self._add_validation_issue("critical", "Accessibility", 
                "Image is missing an 'alt' attribute.", img)
        elif not img['alt'].strip():
            self._add_validation_issue("warning", "Accessibility", 
                "Image 'alt' attribute is empty.", img)

    # Link text validation
    for a in self.soup.find_all('a'):
        if not a.get_text(strip=True) and not a.find('img'):
            self._add_validation_issue("critical", "Accessibility", 
                "Link has no descriptive text.", a)

    # Button accessibility
    for button in self.soup.find_all('button'):
        if not button.get_text(strip=True) and not button.get('aria-label'):
            self._add_validation_issue("error", "Accessibility", 
                "Button has no text or 'aria-label'.", button)
```

---

## 📊 Validation Categories

### 1. Structure Validation
- **DOCTYPE presence** (critical)
- **Language attribute** (warning)
- **Meta charset** (critical)
- **Heading hierarchy** (warning)
- **Multiple H1 tags** (warning)
- **Semantic structure** (info)

### 2. Accessibility Validation
- **Missing alt attributes** (critical)
- **Empty alt attributes** (warning)
- **Link descriptive text** (critical)
- **Button accessibility** (error)
- **Lazy loading optimization** (info)

### 3. SEO Validation
- **Title tag presence** (high)
- **Title length optimization** (warning)
- **Meta description** (error)
- **Open Graph tags** (info)
- **Canonical links** (warning)

### 4. Form Validation
- **CSRF token presence** (critical)
- **Input label associations** (warning)
- **Input type validation** (warning)

### 5. Enterprise Validation
- **Deprecated tags** (high)
- **Inline styles** (warning)
- **Inline event handlers** (warning)
- **Unclosed Django tags** (critical)

---

## 🧪 Test Coverage & Examples

### Test Data Examples

**Valid HTML:**
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Valid Page</title>
    <meta name="description" content="A valid test page.">
    <link rel="canonical" href="https://example.com">
    <meta property="og:title" content="Valid Page">
</head>
<body>
    <h1>Welcome</h1>
    <main>
        <form action="/submit" method="post" id="main-form">
            {% csrf_token %}
            <label for="username">Username</label>
            <input type="text" id="username" name="username" required>
            <button type="submit">Submit</button>
        </form>
        <img src="image.png" alt="A descriptive alt text." loading="lazy">
    </main>
</body>
</html>
```

**HTML with Issues:**
```html
<html>
<head>
    <title>Page with Issues</title>
</head>
<body>
    <h1>First H1</h1>
    <h1>Second H1</h1>
    <h3>Sub-heading skipping H2</h3>
    <img src="image.png">
    <a href="#"></a>
    <button></button>
    <form method="post" action="/submit">
        <input type="text" name="data">
    </form>
    <font>Deprecated tag</font>
    <p style="color: red;">Inline style</p>
    <button onclick="alert('hi')">Click me</button>
</body>
</html>
```

**Django Template Integration:**
```html
{% load static %}
<p>Hello, {{ user.name }}!</p>
<img src="{% static 'images/logo.png' %}">
{# This is a template comment #}
```

### Test Results

**Valid HTML Results:**
- ✅ No structure issues
- ✅ No accessibility issues  
- ✅ No SEO issues
- ✅ No form issues
- ✅ Django template tags detected: `["load", "static", "var:user.name"]`

**HTML with Issues Results:**
- ❌ **Structure**: Missing DOCTYPE, missing lang attribute, missing meta charset, multiple H1 tags, heading level skip
- ❌ **Accessibility**: Missing alt attribute, link with no text, button with no text
- ❌ **SEO**: Missing meta description, missing Open Graph tags, missing canonical link
- ❌ **Forms**: Missing CSRF token, missing input labels
- ❌ **Enterprise**: Deprecated font tag, inline styles, inline event handlers

---

## 🔗 Integration & Data Models

### Input/Output Flow
```
HTML Content → HTMLParser → HTMLFileDetails → AccessibilityAnalyzer → FrontendValidator
```

### Key Data Models

**HTMLFileDetails:**
```python
class HTMLFileDetails:
    doctype_present: bool
    lang: Optional[str]
    title: Optional[str]
    meta_tags: List[HTMLMeta]
    links: List[HTMLLink]
    scripts: List[HTMLScript]
    forms: List[HTMLForm]
    django_template_tags: List[str]
    validation: HTMLValidationResults
```

**HTMLForm:**
```python
class HTMLForm:
    id: Optional[str]
    action: Optional[str]
    method: str
    has_csrf_token: bool
    inputs: List[HTMLFormInput]
```

**HTMLValidationResults:**
```python
class HTMLValidationResults:
    structure_issues: List[HTMLValidationIssue]
    accessibility_issues: List[HTMLValidationIssue]
    seo_issues: List[HTMLValidationIssue]
    forms_issues: List[HTMLValidationIssue]
```

---

## ⚙️ Configuration & Extension

### Adding New Validation Rules

```python
def _validate_custom_checks(self):
    """Add your custom validation logic here."""
    # Example: Check for specific patterns
    for tag in self.soup.find_all('div', class_='custom-class'):
        if not tag.get('data-required'):
            self._add_validation_issue("warning", "Custom", 
                "Custom div missing required data attribute.", tag)
```

### Modifying Severity Levels

```python
# In validation methods, adjust severity as needed:
self._add_validation_issue("critical", "Accessibility", message, element)  # Blocks completion
self._add_validation_issue("warning", "SEO", message, element)               # Logs but continues
self._add_validation_issue("info", "Performance", message, element)         # Informational only
```

---

## 📝 Changelog (v0.3.0)

### 🆕 New Features:
- **Django template tag extraction** - Detects `{% %}` tags and `{{ }}` variables
- **Enterprise validation** - Deprecated tags, inline styles, security checks
- **Enhanced form analysis** - CSRF token detection, input type validation
- **Advanced accessibility checks** - Lazy loading optimization, button accessibility

### 🔧 Technical Improvements:
- **BeautifulSoup html5lib parser** - More accurate, browser-like parsing
- **Comprehensive form extraction** - Labels, input types, validation attributes
- **Django integration** - Template tag and variable detection
- **Enterprise-grade validation** - Production-ready quality checks

### 🧪 Testing:
- **7 comprehensive test scenarios** covering all validation categories
- **Real-world HTML examples** with expected validation results
- **Django template integration testing** - Template tag extraction validation

---

## 🎉 Summary

**HTMLParser** is VebGen's **HTML intelligence engine**:

✅ **Comprehensive extraction** (forms, meta tags, scripts, Django templates)  
✅ **Accessibility validation** (WCAG 2.1 compliance)  
✅ **SEO optimization** (meta tags, Open Graph, canonical links)  
✅ **Enterprise validation** (deprecated tags, inline styles, security)  
✅ **Django integration** (template tag and variable detection)  
✅ **Form analysis** (CSRF tokens, labels, input validation)  
✅ **Production-ready quality gates** (blocks completion until issues fixed)  

**This parser ensures every HTML file meets enterprise standards for accessibility, SEO, and code quality before features are marked complete.**

---

## 🔗 Related Documentation

For more on VebGen's frontend analysis suite, see:

- **[css_parser.md](css_parser.md)** - CSS parsing and validation
- **[vanilla_js_parser.md](vanilla_js_parser.md)** - JavaScript analysis
- **[analyzers.md](analyzers.md)** - Frontend quality analyzers
- **[frontend_validator.md](frontend_validator.md)** - Main validation orchestrator

---

<div align="center">

**Questions?** Check the main README or workflow_manager.md for integration details!

**Want to extend HTML validation?** See the "Configuration & Extension" section above.

</div>
