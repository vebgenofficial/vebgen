# 🎨 css_parser.py — VebGen CSS Analysis Engine

## 🎯 Overview

**Location:** `backend/src/core/parsers/css_parser.py`  
**Size:** 11KB (203 lines)  
**Purpose:** Parses CSS content using tinycss2 to extract structured data and perform comprehensive validation covering rules, media queries, animations, imports, and enterprise-level checks.

> **📌 Documentation Version**: v0.3.0  
> **🆕 Major Features**: CSS Grid/Flexbox detection, custom properties extraction, performance optimization, responsive design validation

This is VebGen's **CSS intelligence engine**—the parser that understands CSS structure, validates performance patterns, detects accessibility issues, and ensures modern CSS best practices.

---

## 🧠 What This File Does

### Core Functionality
- **Extracts CSS structure** (rules, media queries, animations, imports)
- **Calculates specificity** for selector optimization
- **Detects modern CSS** (Grid, Flexbox, custom properties)
- **Validates performance** (will-change usage, render optimization)
- **Responsive design analysis** (mobile-first patterns, unit usage)
- **Accessibility validation** (focus indicators, reduced motion)

### Integration Points
- Used by `CodeIntelligenceService` for project scanning
- Feeds data to `AccessibilityAnalyzer` for WCAG compliance
- Provides structured data to `PerformanceAnalyzer` for optimization
- Integrates with `FrontendValidator` for quality gates

---

## 🗂️ File Structure

```text
css_parser.py (203 lines)
├── CSSParser (Main Class)
│   ├── __init__() - Initialize with tinycss2
│   ├── parse() - Main entry point
│   │
│   ├── Parsing Methods (3 methods)
│   │   ├── _handle_at_rule() - @import, @media, @keyframes, @font-face
│   │   ├── _handle_qualified_rule() - Standard CSS rules
│   │   └── _parse_css_rule() - Rule parsing with specificity
│   │
│   ├── Detection Methods (2 methods)
│   │   ├── _detect_grid_and_flexbox() - Modern layout detection
│   │   └── _parse_declaration_block() - Property extraction
│   │
│   ├── Validation Methods (5 methods)
│   │   ├── _validate_architecture() - @import usage
│   │   ├── _validate_naming_and_specificity() - BEM patterns, specificity
│   │   ├── _validate_performance() - will-change optimization
│   │   ├── _validate_responsive() - Mobile-first, unit usage
│   │   └── _validate_accessibility() - Focus indicators, reduced motion
│   │
│   └── Helper Methods
│       └── _add_validation_issue() - Unified issue creation
│
└── Data Models (from project_models.py)
    ├── CSSFileDetails - Main output structure
    ├── CSSRule, CSSMediaQuery, CSSAnimation - CSS structure
    └── CSSValidationIssue, CSSValidationResults - Validation output
```

---

## 🔧 Key Methods Deep Dive

### 1. Main Entry Point

```python
def parse(self) -> CSSFileDetails:
    """Main entry point to parse the CSS and return structured details."""
    logger.debug(f"Starting CSS parsing for '{self.file_path}'.")
    
    stylesheet_tokens = tinycss2.parse_stylesheet(self.content, skip_comments=True)

    for rule in stylesheet_tokens:
        if isinstance(rule, tinycss2.ast.ParseError):
            self._add_validation_issue("error", "Architecture", 
                f"CSS parsing error: {rule.message}", rule.source_line)
            continue

        if rule.type == 'at-rule':
            self._handle_at_rule(rule)
        elif rule.type == 'qualified-rule':
            self._handle_qualified_rule(rule)

    self._detect_grid_and_flexbox()
    self._validate_all()

    self.details.validation = self.validation_results
    return self.details
```

### 2. At-Rule Handling (Advanced)

```python
def _handle_at_rule(self, rule):
    """Handles different types of at-rules like @import, @media, @keyframes."""
    at_keyword = rule.at_keyword.lower()
    
    if at_keyword == 'import':
        # Extract URL from @import
        prelude_str = tinycss2.serialize(rule.prelude)
        match = re.search(r"""url\((['"]?)(.*?)\1\)|(['"])(.*?)\3""", prelude_str)
        if match:
            url = match.group(2) or match.group(4)
            self.details.imports.append(url.strip())
    
    elif at_keyword == 'media':
        # Parse media queries with nested rules
        media_query = CSSMediaQuery(condition=tinycss2.serialize(rule.prelude).strip())
        if rule.content:
            for child_rule in tinycss2.parse_rule_list(rule.content, skip_comments=True):
                if child_rule.type == 'qualified-rule':
                    parsed_rule = self._parse_css_rule(child_rule)
                    if parsed_rule:
                        media_query.rules.append(parsed_rule)
        self.details.media_queries.append(media_query)
    
    elif at_keyword == 'keyframes':
        # Parse animations with keyframe steps
        animation = CSSAnimation(name=tinycss2.serialize(rule.prelude).strip())
        if rule.content:
            for keyframe_rule in tinycss2.parse_rule_list(rule.content, skip_comments=True):
                if hasattr(keyframe_rule, 'prelude'):
                    stop = tinycss2.serialize(keyframe_rule.prelude).strip()
                    properties = self._parse_declaration_block(keyframe_rule.content)
                    animation.steps[stop] = properties
        self.details.animations.append(animation)
```

### 3. Specificity Calculation

```python
def _parse_css_rule(self, rule) -> Optional[CSSRule]:
    """Parses a tinycss2 qualified-rule into a CSSRule with specificity calculation."""
    if not rule.content:
        return None
    
    selector = tinycss2.serialize(rule.prelude).strip()
    properties = self._parse_declaration_block(rule.content)
    
    # Calculate specificity: (IDs, classes/attributes, elements)
    ids = selector.count('#')
    classes_attrs = selector.count('.') + selector.count('[')
    elements = len([s for s in selector.replace('>', ' ').replace('+', ' ').replace('~', ' ').split() 
                   if s not in ('*', '+', '>', '~') and not s.startswith(('.', '#', '['))])

    return CSSRule(selector=selector, properties=properties, specificity=(ids, classes_attrs, elements))
```

### 4. Modern CSS Detection

```python
def _detect_grid_and_flexbox(self):
    """Scans all parsed rules to detect usage of CSS Grid and Flexbox."""
    for rule in self.details.rules:
        for prop, value in rule.properties.items():
            if prop == 'display':
                if 'grid' in value:
                    self.details.uses_grid = True
                if 'flex' in value:
                    self.details.uses_flexbox = True
        if self.details.uses_grid and self.details.uses_flexbox:
            return # Stop if both are found
```

---

## 📊 Validation Categories

### 1. Architecture Validation
- **@import usage** (warning) - Recommends build-time concatenation
- **CSS parsing errors** (error) - Malformed CSS detection

### 2. Naming & Specificity Validation
- **Overly specific selectors** (warning) - ID + multiple classes
- **Deep nesting detection** (info) - BEM methodology recommendations
- **Specificity calculation** - (IDs, classes/attributes, elements)

### 3. Performance Validation
- **will-change usage** (info) - Memory usage warnings
- **Render optimization** - Property usage analysis

### 4. Responsive Validation
- **Mobile-first approach** (warning) - min-width vs max-width patterns
- **Unit usage analysis** (info) - px vs rem/em recommendations
- **Media query patterns** - Responsive design validation

### 5. Accessibility Validation
- **Focus indicators** (error) - Missing outline alternatives
- **Reduced motion support** (warning) - Animation accessibility
- **Pseudo-element content** (warning) - Screen reader accessibility

---

## 🧪 Test Coverage & Examples

### Test Data Examples

**CSS with Import:**
```css
@import url('theme.css'); 
.body { color: blue; }
```

**CSS with Media Query:**
```css
@media (min-width: 600px) {
    .container {
        display: flex;
    }
}
```

**CSS with Keyframes:**
```css
@keyframes slide-in {
    from {
        transform: translateX(-100%);
    }
    to {
        transform: translateX(0);
    }
}
```

**CSS with Font Face:**
```css
@font-face {
    font-family: 'MyFont';
    src: url('myfont.woff2');
}
```

**CSS with Root Variables:**
```css
:root {
    --main-bg-color: #f0f0f0;
    --main-text-color: #333;
}
.card { color: var(--main-text-color); }
```

**CSS for Validation Testing:**
```css
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
```

### Test Results

**Import Detection:**
- ✅ `theme.css` detected in imports
- ⚠️ Architecture warning: "@import rules found. For production, it's better to concatenate files during a build step."

**Media Query Parsing:**
- ✅ Media query condition: `(min-width: 600px)`
- ✅ Nested rule: `.container { display: flex; }`
- ✅ Flexbox detection: `uses_flexbox = True`

**Keyframes Animation:**
- ✅ Animation name: `slide-in`
- ✅ Keyframe steps: `from` and `to`
- ✅ Transform properties: `translateX(-100%)` → `translateX(0)`

**Font Face Detection:**
- ✅ Font family: `MyFont`
- ✅ Source URL: `myfont.woff2`

**Custom Properties:**
- ✅ Root variables: `--main-bg-color: #f0f0f0`, `--main-text-color: #333`
- ✅ Usage detection: `.card` rule with `var(--main-text-color)`

**Specificity Calculation:**
- ✅ Complex selector: `#main .nav > li.active`
- ✅ Specificity: `(1, 2, 1)` - 1 ID, 2 classes, 1 element

**Grid/Flexbox Detection:**
- ✅ Grid detection: `display: grid`
- ✅ Flexbox detection: `display: flex`

**Validation Results:**
- ❌ **Architecture**: @import usage warning
- ❌ **Naming**: Overly specific selector warning
- ❌ **Performance**: will-change usage info
- ❌ **Responsive**: Desktop-first approach warning, px unit usage info
- ❌ **Accessibility**: Focus outline disabled error, pseudo-element content warning

---

## 🔗 Integration & Data Models

### Input/Output Flow
```
CSS Content → CSSParser → CSSFileDetails → AccessibilityAnalyzer + PerformanceAnalyzer → FrontendValidator
```

### Key Data Models

**CSSFileDetails:**
```python
class CSSFileDetails:
    imports: List[str]
    rules: List[CSSRule]
    media_queries: List[CSSMediaQuery]
    animations: List[CSSAnimation]
    font_faces: List[Dict[str, str]]
    custom_properties: Dict[str, str]
    uses_grid: bool
    uses_flexbox: bool
    validation: CSSValidationResults
```

**CSSRule:**
```python
class CSSRule:
    selector: str
    properties: Dict[str, str]
    specificity: Tuple[int, int, int]  # (IDs, classes/attributes, elements)
```

**CSSMediaQuery:**
```python
class CSSMediaQuery:
    condition: str
    rules: List[CSSRule]
```

**CSSAnimation:**
```python
class CSSAnimation:
    name: str
    steps: Dict[str, Dict[str, str]]  # {step: {property: value}}
```

---

## ⚙️ Configuration & Extension

### Adding New Validation Rules

```python
def _validate_custom_checks(self):
    """Add your custom validation logic here."""
    # Example: Check for specific patterns
    for rule in self.details.rules:
        if 'custom-property' in rule.selector:
            self._add_validation_issue("info", "Custom", 
                "Custom property usage detected.", rule.selector)
```

### Modifying Severity Levels

```python
# In validation methods, adjust severity as needed:
self._add_validation_issue("error", "Accessibility", message, element)    # Blocks completion
self._add_validation_issue("warning", "Performance", message, element)  # Logs but continues
self._add_validation_issue("info", "Responsive", message, element)      # Informational only
```

### Custom Property Detection

```python
# The parser automatically detects custom properties in :root
:root {
    --primary-color: #007bff;
    --secondary-color: #6c757d;
}

.button {
    color: var(--primary-color);  # Usage detected
}
```

---

## 📝 Changelog (v0.3.0)

### 🆕 New Features:
- **CSS Grid/Flexbox detection** - Modern layout pattern recognition
- **Custom properties extraction** - CSS variable detection and usage
- **Performance optimization** - will-change usage analysis
- **Responsive design validation** - Mobile-first pattern detection
- **Accessibility compliance** - Focus indicators, reduced motion support

### 🔧 Technical Improvements:
- **tinycss2 integration** - Robust CSS parsing with error handling
- **Specificity calculation** - Selector optimization analysis
- **Media query parsing** - Nested rule extraction
- **Animation analysis** - Keyframe step detection
- **Enterprise-grade validation** - Production-ready quality checks

### 🧪 Testing:
- **7 comprehensive test scenarios** covering all parsing and validation categories
- **Real-world CSS examples** with expected validation results
- **Modern CSS pattern testing** - Grid, Flexbox, custom properties
- **Performance optimization validation** - will-change, unit usage

---

## 🎉 Summary

**CSSParser** is VebGen's **CSS intelligence engine**:

✅ **Comprehensive parsing** (rules, media queries, animations, imports)  
✅ **Modern CSS detection** (Grid, Flexbox, custom properties)  
✅ **Performance optimization** (will-change, render optimization)  
✅ **Responsive validation** (mobile-first, unit usage)  
✅ **Accessibility compliance** (focus indicators, reduced motion)  
✅ **Specificity analysis** (selector optimization)  
✅ **Enterprise-grade quality gates** (blocks completion until issues fixed)  

**This parser ensures every CSS file follows modern best practices for performance, accessibility, and maintainability before features are marked complete.**

---

## 🔗 Related Documentation

For more on VebGen's frontend analysis suite, see:

- **[html_parser.md](html_parser.md)** - HTML parsing and validation
- **[vanilla_js_parser.md](vanilla_js_parser.md)** - JavaScript analysis
- **[analyzers.md](analyzers.md)** - Frontend quality analyzers
- **[frontend_validator.md](frontend_validator.md)** - Main validation orchestrator

---

<div align="center">

**Questions?** Check the main README or workflow_manager.md for integration details!

**Want to extend CSS validation?** See the "Configuration & Extension" section above.

</div>
