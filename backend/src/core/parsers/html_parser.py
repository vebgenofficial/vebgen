# backend/src/core/parsers/html_parser.py
import logging
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup, Doctype, Comment
import re

from ..project_models import (
    HTMLFileDetails, HTMLForm, HTMLFormInput, HTMLLink, HTMLMeta, HTMLScript,
    HTMLValidationIssue, HTMLValidationResults
)

logger = logging.getLogger(__name__)

class HTMLParser:
    """
    Parses HTML content using BeautifulSoup to extract structured data and perform validation.
    Covers semantic structure, forms, SEO, accessibility, and structural validation.
    """
    def __init__(self, html_content: str):
        # Use html5lib for more accurate, browser-like parsing which is better for validation.
        # It handles malformed HTML more gracefully and correctly.
        self.soup = BeautifulSoup(html_content, 'html5lib')
        self.content = html_content
        self.details = HTMLFileDetails()
        self.validation_results = HTMLValidationResults()

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
        self._validate_enterprise() # NEW: Enterprise validation checks

        self.details.validation = self.validation_results
        logger.debug("Finished HTML parsing and validation.")
        return self.details

    def _add_validation_issue(self, severity, category, message, element=None):
        """Helper to add a validation issue."""
        preview = str(element)[:75] + '...' if element and len(str(element)) > 75 else str(element)
        issue = HTMLValidationIssue(
            severity=severity,
            category=category,
            message=message,
            element_preview=preview
        )
        getattr(self.validation_results, f"{category.lower()}_issues").append(issue) # type: ignore

    # --- Extraction Methods ---

    def _extract_doctype_and_lang(self):
        self.details.doctype_present = any(isinstance(item, Doctype) for item in self.soup.contents)
        html_tag = self.soup.find('html')
        if html_tag:
            self.details.lang = html_tag.get('lang')

    def _extract_title(self):
        title_tag = self.soup.find('title')
        if title_tag and title_tag.string:
            self.details.title = title_tag.string.strip()

    def _extract_meta_tags(self):
        for tag in self.soup.find_all('meta'):
            self.details.meta_tags.append(HTMLMeta(
                name=tag.get('name'),
                property=tag.get('property'),
                content=tag.get('content'),
                charset=tag.get('charset')
            ))

    def _extract_links(self):
        for tag in self.soup.find_all('link'):
            if tag.get('rel'):
                self.details.links.append(HTMLLink(
                    rel=",".join(tag['rel']),
                    href=tag.get('href', ''),
                    type=tag.get('type')
                ))

    def _extract_scripts(self):
        for tag in self.soup.find_all('script'):
            self.details.scripts.append(HTMLScript(
                src=tag.get('src'),
                is_inline=not tag.get('src') and bool(tag.string),
                is_async='async' in tag.attrs,
                is_defer='defer' in tag.attrs
            ))

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

    def _extract_django_template_tags(self):
        # Simple regex to find common Django template tags
        # This now also finds template comments {# ... #}
        tags_found = re.findall(r'{[%#]\s*(\w+)', self.content)
        # Also find template variables {{ ... }}
        variables_found = re.findall(r'{{\s*([\w\.]+)', self.content)
        tags_found.extend(f"var:{v}" for v in variables_found)
        self.details.django_template_tags = sorted(list(set(tags_found)))

    # --- Validation Methods ---

    def _validate_structure(self):
        if not self.details.doctype_present:
            self._add_validation_issue("critical", "Structure", "Missing DOCTYPE declaration.")
        if not self.details.lang:
            self._add_validation_issue("warning", "Structure", "<html> tag is missing the 'lang' attribute.")
        
        # Check for meta charset
        has_charset = any(m.charset is not None for m in self.details.meta_tags)
        if not has_charset:
            self._add_validation_issue("critical", "Structure", "Missing <meta charset> tag (e.g., <meta charset=\"UTF-8\">).")
        
        h1_tags = self.soup.find_all('h1')
        if len(h1_tags) > 1:
            self._add_validation_issue("warning", "Structure", f"Found {len(h1_tags)} <h1> tags. Only one is recommended for SEO.", h1_tags[1])
        
        # Check heading hierarchy
        headings = self.soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        last_level = 0
        for h in headings:
            current_level = int(h.name[1])
            if last_level != 0 and current_level > last_level + 1:
                self._add_validation_issue("warning", "Structure", f"Heading level skip detected: <h{last_level}> followed by <{h.name}>.", h)
            last_level = current_level
        
        # Semantic validation: nav should not be inside a header (common mistake)
        for header in self.soup.find_all('header'):
            if header.find('nav'):
                self._add_validation_issue("info", "Structure", "Semantic issue: <nav> element found inside a <header>. It's generally recommended to have them as siblings.", header)

    def _validate_accessibility(self):
        for img in self.soup.find_all('img'):
            if not img.has_attr('alt'):
                self._add_validation_issue("critical", "Accessibility", "Image is missing an 'alt' attribute.", img)
            elif not img['alt'].strip():
                self._add_validation_issue("warning", "Accessibility", "Image 'alt' attribute is empty. Provide descriptive text or leave it out entirely for decorative images.", img)

        for a in self.soup.find_all('a'):
            if not a.get_text(strip=True) and not a.find('img'):
                self._add_validation_issue("critical", "Accessibility", "Link has no descriptive text.", a)
            elif a.get_text(strip=True).lower() in ["click here", "read more", "learn more"]:
                self._add_validation_issue("warning", "Accessibility", "Link text is not descriptive.", a)

        for button in self.soup.find_all('button'):
            if not button.get_text(strip=True) and not button.get('aria-label'):
                self._add_validation_issue("error", "Accessibility", "Button has no text or 'aria-label'.", button)
        
        # Check for lazy loading on images that are not the first few on the page
        for i, img in enumerate(self.soup.find_all('img')):
            if i > 2 and 'loading' not in img.attrs: # Heuristic: check images after the 3rd one
                self._add_validation_issue("info", "Accessibility", "Consider adding loading=\"lazy\" to this image to improve performance.", img)

    def _validate_seo(self):
        if not self.details.title:
            self._add_validation_issue("high", "SEO", "Missing <title> tag.")
        elif len(self.details.title) > 60:
            self._add_validation_issue("warning", "SEO", f"Title tag is too long ({len(self.details.title)} chars). Recommended: 50-60.", self.soup.find('title'))
        
        meta_description = next((m.content for m in self.details.meta_tags if m.name == 'description' and m.content), None)
        if not meta_description:
            self._add_validation_issue("error", "SEO", "Missing meta description tag.")
        elif len(meta_description) > 160:
            self._add_validation_issue("warning", "SEO", f"Meta description is too long ({len(meta_description)} chars). Recommended: 150-160.")

        has_og_title = any(m.property == 'og:title' for m in self.details.meta_tags)
        if not has_og_title:
            self._add_validation_issue("info", "SEO", "Missing Open Graph (og:title) tag for social media sharing.")

        has_canonical = any(l.rel == 'canonical' for l in self.details.links)
        if not has_canonical:
            self._add_validation_issue("warning", "SEO", "Missing canonical link tag to prevent duplicate content issues.")

    def _validate_forms(self):
        for form in self.details.forms:
            if form.method == "POST" and not form.has_csrf_token:
                self._add_validation_issue("critical", "Forms", "POST form is missing a Django CSRF token ({% csrf_token %}).")
            
            for form_input in form.inputs:
                if not form_input.label:
                    self._add_validation_issue("warning", "Forms", f"Input '{form_input.name or form_input.id}' is missing an associated <label>.", f"<{form_input.tag} name='{form_input.name}'>")

                if form_input.tag == 'input':
                    valid_types = [
                        'text', 'password', 'email', 'number', 'tel', 'url', 'date', 
                        'time', 'datetime-local', 'month', 'week', 'search', 'color',
                        'checkbox', 'radio', 'file', 'hidden', 'submit', 'reset', 'button'
                    ]
                    if form_input.type and form_input.type not in valid_types:
                         self._add_validation_issue("warning", "Forms", f"Input '{form_input.name}' uses a non-standard or potentially incorrect type: '{form_input.type}'.", f"<{form_input.tag} name='{form_input.name}'>")

    def _validate_enterprise(self):
        """Performs enterprise-level validation checks."""
        
        # Check for deprecated tags
        deprecated_tags = ['center', 'font', 'marquee']
        for tag_name in deprecated_tags:
            for tag in self.soup.find_all(tag_name):
                self._add_validation_issue("high", "Structure", f"Deprecated <{tag_name}> tag found. Use CSS for styling.", tag)

        # Check for inline styles
        for tag in self.soup.find_all(style=True):
            self._add_validation_issue("warning", "Structure", "Inline 'style' attribute found. Use external CSS files for better maintainability.", tag)

        # Check for inline event handlers
        event_handlers = [attr for attr in self.soup.find_all(True) if any(key.startswith('on') for key in attr.attrs)]
        for tag in event_handlers:
            handler = [key for key in tag.attrs if key.startswith('on')][0]
            self._add_validation_issue("warning", "Structure", f"Inline event handler '{handler}' found. Use JavaScript event listeners for separation of concerns.", tag)

        # Check for unclosed Django template tags (basic check)
        # This regex looks for an opening tag that isn't properly closed on the same line or before the end of the file.
        # It's a heuristic and might have false positives with complex multiline tags.
        if re.search(r'({%[^%]*?)\n', self.content) and not re.search(r'.*?%}', self.content, re.DOTALL):
             self._add_validation_issue("critical", "Structure", "Potential unclosed Django template tag '{%' detected.")
        if re.search(r'({{[^}]*?)\n', self.content) and not re.search(r'.*?}}', self.content, re.DOTALL):
             self._add_validation_issue("critical", "Structure", "Potential unclosed Django template variable '{{' detected.")