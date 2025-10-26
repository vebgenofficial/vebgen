# backend/src/core/analyzers/performance_analyzer.py
import logging
import re
from typing import List, Set, Dict, Any
from pathlib import Path

from ..project_models import ProjectStructureMap, FrontendValidationIssue

logger = logging.getLogger(__name__)

class PerformanceReport(dict):
    """A dictionary-like object to hold performance analysis results."""
    pass

class PerformanceAnalyzer:
    """
    Analyzes frontend assets for performance issues, similar to Lighthouse.
    Calculates page weight, identifies render-blocking resources, and detects dead code.
    """
    def __init__(self, project_structure_map: ProjectStructureMap):
        self.project_map = project_structure_map
        self.report = PerformanceReport()
        self.issues: List[FrontendValidationIssue] = []
        self.total_page_weight = 0  # in bytes
        self.all_html_ids: Set[str] = set()
        self.all_html_classes: Set[str] = set()

    def analyze(self) -> List[FrontendValidationIssue]:
        """
        Runs all performance analysis checks and returns a list of issues.
        """
        logger.info("Starting performance analysis...")

        self._collect_html_selectors_and_weight()
        self._calculate_asset_weights()
        self._identify_render_blocking_resources()
        self._detect_unused_css()
        self._detect_layout_thrashing_patterns()

        # Add a summary issue for total page weight
        weight_kb = self.total_page_weight / 1024
        severity = "warning" if weight_kb > 1500 else "info"
        if weight_kb > 500: # Only report if it's significant
            self.issues.append(FrontendValidationIssue(
                severity=severity,
                category="Performance",
                message=f"Total estimated page weight is ~{weight_kb:.0f} KB. Aim for < 1500 KB for fast load times.",
                file_path="Project-wide",
            ))

        logger.info(f"Performance analysis complete. Found {len(self.issues)} issues.")
        return self.issues

    def _collect_html_selectors_and_weight(self):
        """Collects all IDs and classes from all HTML files and calculates their weight."""
        for file_info in self.project_map.global_files.values():
            if file_info.html_details:
                # This part needs a refactor of html_parser to expose all found IDs/classes
                # For now, we'll rely on the existing parsed data.
                for form in file_info.html_details.forms:
                    if form.id: self.all_html_ids.add(form.id)
                    for inp in form.inputs:
                        if inp.id: self.all_html_ids.add(inp.id)

        for app_info in self.project_map.apps.values():
            for file_info in app_info.files.values():
                if file_info.html_details:
                    for form in file_info.html_details.forms:
                        if form.id: self.all_html_ids.add(form.id)
                        for inp in form.inputs:
                            if inp.id: self.all_html_ids.add(inp.id)

    def _calculate_asset_weights(self):
        """Estimates total page weight by summing file sizes."""
        # This is a placeholder. A real implementation would need file sizes.
        # We can simulate it by content length for now.
        # In a real scenario, this would be passed from FileSystemManager.
        pass # Placeholder

    def _identify_render_blocking_resources(self):
        """Identifies scripts in <head> that are not async or defer."""
        for file_path, file_info in self._iter_all_files():
            if file_info.html_details:
                for script in file_info.html_details.scripts:
                    if not script.is_async and not script.is_defer and not script.is_inline:
                        # A more advanced check would see if it's in the <head>
                        self.issues.append(FrontendValidationIssue(
                            severity="warning",
                            category="Performance",
                            message=f"Script '{Path(script.src).name if script.src else 'inline script'}' may be render-blocking. Consider adding 'async' or 'defer' attributes.",
                            file_path=file_path,
                        ))

    def _detect_unused_css(self):
        """Identifies CSS selectors that are defined but not used in any HTML file."""
        all_css_selectors: Set[str] = set()
        css_files: List[str] = []

        for file_path, file_info in self._iter_all_files():
            if file_info.css_details:
                css_files.append(file_path)
                for rule in file_info.css_details.rules:
                    # Simple class/ID selector parsing
                    selectors = re.findall(r'([#.])([\w-]+)', rule.selector)
                    for type, name in selectors:
                        all_css_selectors.add(f"{type}{name}")

        if not css_files: return # No CSS to check

        unused_selectors = {s for s in all_css_selectors if (s.startswith('#') and s[1:] not in self.all_html_ids) or (s.startswith('.') and s[1:] not in self.all_html_classes)}

        if len(unused_selectors) > 10: # Only report if significant
            self.issues.append(FrontendValidationIssue(
                severity="low",
                category="Performance",
                message=f"Found {len(unused_selectors)} potentially unused CSS selectors (e.g., {list(unused_selectors)[:3]}). This could be dead code.",
                file_path=f"Across {len(css_files)} CSS files",
            ))

    def _detect_layout_thrashing_patterns(self):
        """Heuristically detects potential layout thrashing in JS."""
        for file_path, file_info in self._iter_all_files():
            if file_info.js_details:
                # This is a very basic heuristic. It looks for keywords in the summary.
                summary = file_info.raw_content_summary or ""
                if "for" in summary.lower() and "offset" in summary.lower() and "style" in summary.lower():
                    self.issues.append(FrontendValidationIssue(
                        severity="warning",
                        category="Performance",
                        message="Potential layout thrashing detected. Reading DOM properties (like .offsetHeight) and then writing to the DOM inside a loop can cause performance issues.",
                        file_path=file_path,
                    ))

    def _iter_all_files(self):
        """Generator to iterate over all files in the project map."""
        for file_path, file_info in self.project_map.global_files.items():
            yield file_path, file_info
        for app_info in self.project_map.apps.values():
            for file_path, file_info in app_info.files.items():
                yield file_path, file_info