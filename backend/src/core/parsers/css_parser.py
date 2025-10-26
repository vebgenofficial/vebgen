# backend/src/core/parsers/css_parser.py
import logging
import tinycss2
from typing import List, Dict, Optional, Tuple

from ..project_models import (
    CSSFileDetails, CSSRule, CSSMediaQuery, CSSAnimation,
    CSSValidationIssue, CSSValidationResults
)

logger = logging.getLogger(__name__)

class CSSParser:
    """
    Parses CSS content using tinycss2 to extract structured data and perform validation.
    Covers rules, media queries, animations, imports, and enterprise-level checks.
    """
    def __init__(self, css_content: str, file_path: str):
        self.content = css_content
        self.file_path = file_path
        self.tokens = tinycss2.parse_stylesheet(self.content, skip_comments=True, skip_whitespace=True)
        self.details = CSSFileDetails()
        self.validation_results = CSSValidationResults()

    def parse(self) -> CSSFileDetails:
        """Main entry point to parse the CSS and return structured details."""
        logger.debug(f"Starting CSS parsing for '{self.file_path}'.")
        
        # Use parse_stylesheet which is more robust for full files and error handling.
        stylesheet_tokens = tinycss2.parse_stylesheet(self.content, skip_comments=True)

        for rule in stylesheet_tokens:
            if isinstance(rule, tinycss2.ast.ParseError):
                self._add_validation_issue("error", "Architecture", f"CSS parsing error: {rule.message}", rule.source_line)
                continue

            if rule.type == 'at-rule':
                self._handle_at_rule(rule)
            elif rule.type == 'qualified-rule':
                self._handle_qualified_rule(rule)

        self._detect_grid_and_flexbox()
        self._validate_all()

        self.details.validation = self.validation_results
        logger.debug(f"Finished CSS parsing for '{self.file_path}'.")
        return self.details

    def _add_validation_issue(self, severity, category, message, line=None, element=None):
        """Helper to add a validation issue."""
        issue = CSSValidationIssue(
            severity=severity,
            category=category,
            message=message,
            line=line,
            element_preview=element
        )
        getattr(self.validation_results, f"{category.lower()}_issues").append(issue)

    def _handle_at_rule(self, rule):
        """Handles different types of at-rules like @import, @media, @keyframes."""
        at_keyword = rule.at_keyword.lower()
        # Move imports to the top of the method to be available for all branches.
        import tinycss2.ast
        import re
        if at_keyword == 'import':
            # Serialize the prelude and use regex to robustly find the URL
            # This handles url('path'), url("path"), and "path"
            prelude_str = tinycss2.serialize(rule.prelude)
            match = re.search(r"""url\((['"]?)(.*?)\1\)|(['"])(.*?)\3""", prelude_str)
            if match:
                # group(2) is for url(), group(4) is for string literal
                url = match.group(2) or match.group(4)
                self.details.imports.append(url.strip())
        elif at_keyword == 'media':
            media_query = CSSMediaQuery(condition=tinycss2.serialize(rule.prelude).strip())
            if rule.content:
                for child_rule in tinycss2.parse_rule_list(rule.content, skip_comments=True):
                    if child_rule.type == 'qualified-rule':
                        parsed_rule = self._parse_css_rule(child_rule)
                        if parsed_rule:
                            media_query.rules.append(parsed_rule)
            self.details.media_queries.append(media_query)
        elif at_keyword == 'keyframes':
            animation = CSSAnimation(name=tinycss2.serialize(rule.prelude).strip())
            if rule.content:
                for keyframe_rule in tinycss2.parse_rule_list(rule.content, skip_comments=True):
                    if hasattr(keyframe_rule, 'prelude'):
                        stop = tinycss2.serialize(keyframe_rule.prelude).strip()
                        properties = self._parse_declaration_block(keyframe_rule.content)
                        animation.steps[stop] = properties
            self.details.animations.append(animation)
        elif at_keyword == 'font-face':
            if rule.content:
                properties = self._parse_declaration_block(rule.content)
                self.details.font_faces.append(properties)

    def _handle_qualified_rule(self, rule):
        """Handles a standard CSS rule with a selector and declarations."""
        parsed_rule = self._parse_css_rule(rule)
        if parsed_rule:
            # Check for custom properties defined at the :root level
            if parsed_rule.selector == ':root':
                for prop, value in parsed_rule.properties.items():
                    if prop.startswith('--'):
                        self.details.custom_properties[prop] = value
            else:
                self.details.rules.append(parsed_rule)

    def _parse_css_rule(self, rule) -> Optional[CSSRule]:
        """Parses a tinycss2 qualified-rule into a CSSRule Pydantic model."""
        if not rule.content:
            return None
        
        selector = tinycss2.serialize(rule.prelude).strip()
        properties = self._parse_declaration_block(rule.content)
        
        # Calculate specificity
        ids = selector.count('#')
        classes_attrs = selector.count('.') + selector.count('[')
        elements = len([s for s in selector.replace('>', ' ').replace('+', ' ').replace('~', ' ').split() if s not in ('*', '+', '>', '~') and not s.startswith(('.', '#', '['))])

        return CSSRule(selector=selector, properties=properties, specificity=(ids, classes_attrs, elements))

    def _parse_declaration_block(self, tokens) -> Dict[str, str]:
        """Parses a block of CSS declarations into a dictionary."""
        properties = {}
        declarations = tinycss2.parse_declaration_list(tokens, skip_comments=True)
        for decl in declarations:
            if decl.type == 'declaration':
                if not decl.value or all(token.type in ['whitespace', 'comment'] for token in decl.value): # Check for empty or whitespace-only value
                    self._add_validation_issue("error", "Architecture", f"CSS parsing error: Incomplete declaration for property '{decl.name}'.", decl.source_line)
                    continue
                prop_name = decl.name
                prop_value = tinycss2.serialize(decl.value).strip()
                properties[prop_name] = prop_value
        return properties

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

    def _validate_all(self):
        """Runs all validation checks."""
        self._validate_architecture()
        self._validate_naming_and_specificity()
        self._validate_performance()
        self._validate_responsive()
        self._validate_accessibility()

    def _validate_architecture(self):
        if self.details.imports:
            self._add_validation_issue("warning", "Architecture", "@import rules found. For production, it's better to concatenate files during a build step.", element=f"@import '{self.details.imports[0]}';")

    def _validate_naming_and_specificity(self):
        for rule in self.details.rules:
            # Check for overly specific selectors
            if rule.specificity[0] > 0 and rule.specificity[1] > 2:
                self._add_validation_issue("warning", "Naming", f"Overly specific selector found (ID with multiple classes/attributes). Consider simplifying.", element=rule.selector)
            
            # Check for BEM-like naming convention (heuristic)
            if '.' in rule.selector and '__' not in rule.selector and '--' not in rule.selector:
                if len(rule.selector.split()) > 2 and not any(c in rule.selector for c in ['>', '+', '~']):
                     self._add_validation_issue("info", "Naming", f"Selector '{rule.selector}' seems deeply nested. Consider using a methodology like BEM to flatten structure.", element=rule.selector)

    def _validate_performance(self):
        for rule in self.details.rules:
            if 'will-change' in rule.properties:
                self._add_validation_issue("info", "Performance", "The 'will-change' property is used. Ensure it is applied sparingly and only when necessary to avoid excessive memory usage.", element=rule.selector)

    def _validate_responsive(self):
        has_min_width_queries = any('min-width' in mq.condition for mq in self.details.media_queries)
        if self.details.media_queries and not has_min_width_queries:
            self._add_validation_issue("warning", "Responsive", "Media queries are used, but none use 'min-width'. This might indicate a desktop-first instead of a mobile-first approach.")
        
        for rule in self.details.rules:
            for prop, value in rule.properties.items():
                if 'px' in value and prop not in ['border', 'border-width', 'box-shadow']:
                    self._add_validation_issue("info", "Responsive", f"Fixed unit 'px' used for '{prop}'. Consider using relative units like 'rem', 'em', or '%' for better scalability.", element=f"{prop}: {value};")
                    break # Only flag once per rule

    def _validate_accessibility(self):
        for rule in self.details.rules:
            # Check for focus indicators
            if ':focus' in rule.selector and ('outline' not in rule.properties or rule.properties.get('outline') == 'none'):
                self._add_validation_issue("error", "Accessibility", "Focus outline is disabled. Ensure a visible focus indicator is provided for accessibility.", element=rule.selector)
            
            # Check for content in pseudo-elements
            if '::before' in rule.selector or '::after' in rule.selector:
                if 'content' in rule.properties and rule.properties['content'].strip("'\""):
                    self._add_validation_issue("warning", "Accessibility", "Content added via ::before or ::after is not accessible to screen readers. Use for decorative purposes only.", element=rule.selector)

        has_reduced_motion_query = any('prefers-reduced-motion' in mq.condition for mq in self.details.media_queries)
        if self.details.animations and not has_reduced_motion_query:
            self._add_validation_issue("warning", "Accessibility", "Animations are defined, but no '@media (prefers-reduced-motion: reduce)' query is present to disable them for users who prefer it.")