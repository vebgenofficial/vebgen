# backend/src/core/tests/test_js_html_validator.py
import pytest
from src.core.validators.js_html_validator import JSHtmlValidator
from src.core.project_models import (
    ProjectStructureMap,
    AppStructureInfo,
    FileStructureInfo,
    HTMLFileDetails,
    HTMLForm,
    HTMLFormInput,
    VanillaJSFileDetails,
    JSAPICall,
    DjangoURLConfDetails,
    DjangoURLPattern,
)

@pytest.fixture
def project_map_for_js_validation() -> ProjectStructureMap:
    """
    Creates a ProjectStructureMap with HTML, JS, and Django URL files
    to test cross-file validation scenarios.
    """
    # 1. Define HTML details with some IDs
    html_details = HTMLFileDetails(
        forms=[
            HTMLForm(
                id="main-form",
                inputs=[
                    HTMLFormInput(tag="input", id="username-input"),
                    HTMLFormInput(tag="input", id="password-input"),
                ]
            )
        ]
    )
    html_file_info = FileStructureInfo(file_type="template", html_details=html_details)

    # 2. Define JS details with both valid and orphaned selectors and API calls
    js_details = VanillaJSFileDetails(
        dom_manipulations=[
            ("getElementById", "username-input"),
            ("getElementById", "non-existent-id"),
            ("querySelector", "#main-form"),
        ],
        api_calls=[
            JSAPICall(method="GET", url="api-data-list"), # Valid Django URL name
            JSAPICall(method="POST", url="non-existent-api-name"), # Invalid Django URL name
            JSAPICall(method="GET", url="/api/v1/users"), # Ignored (starts with /)
            JSAPICall(method="GET", url="https://example.com/api/data"), # Ignored (starts with http)
        ]
    )
    js_file_info = FileStructureInfo(file_type="javascript", js_details=js_details)

    # 3. Define Django URL details
    django_urls_details = DjangoURLConfDetails(
        url_patterns=[
            DjangoURLPattern(pattern="api/data/", view_reference="views.data_list", name="api-data-list")
        ]
    )
    django_urls_file_info = FileStructureInfo(file_type="django_urls", django_urls_details=django_urls_details)

    # 4. Assemble the project map
    project_map = ProjectStructureMap(
        apps={
            "my_app": AppStructureInfo(
                files={
                    "templates/my_app/index.html": html_file_info,
                    "static/my_app/js/script.js": js_file_info,
                    "urls.py": django_urls_file_info,
                }
            )
        }
    )
    return project_map


class TestJSHtmlValidator:
    """Tests for the JSHtmlValidator."""

    def test_finds_orphaned_getelementbyid_selector(self, project_map_for_js_validation: ProjectStructureMap):
        """
        Tests that the validator correctly identifies a `getElementById` call
        targeting an ID that does not exist in any HTML file.
        """
        validator = JSHtmlValidator(project_map_for_js_validation)
        issues = validator.validate()

        assert len(issues) > 0
        orphan_issue = next((issue for issue in issues if "Orphaned JS selector" in issue.message), None)
        
        assert orphan_issue is not None
        assert orphan_issue.severity == "medium"
        assert "targets non-existent ID '#non-existent-id'" in orphan_issue.message
        assert orphan_issue.file_path == "static/my_app/js/script.js"

    def test_finds_api_call_with_no_matching_django_url_name(self, project_map_for_js_validation: ProjectStructureMap):
        """
        Tests that the validator flags an API call where the URL string does not
        match any named Django URL pattern.
        """
        validator = JSHtmlValidator(project_map_for_js_validation)
        issues = validator.validate()

        assert len(issues) > 0
        api_issue = next((issue for issue in issues if "does not seem to match" in issue.message), None)

        assert api_issue is not None
        assert api_issue.severity == "medium"
        assert "API call to 'non-existent-api-name' does not seem to match" in api_issue.message
        assert api_issue.file_path == "static/my_app/js/script.js"