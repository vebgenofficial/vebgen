# src/core/project_models.py
import logging
import traceback # For detailed validation errors
from enum import Enum
from typing import List, Dict, Any, Optional, Literal, Union, ForwardRef # Keep Literal, Add Union, ForwardRef
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator # Import Pydantic components
import re # Added to resolve "re is not defined"
from typing import Tuple
# Import ChatMessage for potential use if history is stored within state (currently separate)
# from .llm_client import ChatMessage # Keep commented if not used directly in state

logger = logging.getLogger(__name__)
import time # For default contract_id

# --- Feature Status Enum ---
class FeatureStatusEnum(str, Enum):
    """
    Defines the possible lifecycle statuses for a development feature.
    """
    IDENTIFIED = "identified"
    PLANNED = "planned"
    IMPLEMENTING = "implementing"
    TASKS_IMPLEMENTED = "tasks_implemented"
    GENERATING_FEATURE_TESTS = "generating_feature_tests"
    FEATURE_TESTING = "feature_testing"
    FEATURE_TESTING_FAILED = "feature_testing_failed"
    FEATURE_TESTING_PASSED = "feature_testing_passed"
    REVIEWING = "reviewing"
    MERGED = "merged"
    PLANNING_FAILED = "planning_failed"
    IMPLEMENTATION_FAILED = "implementation_failed"
    CANCELLED = "cancelled"

# --- Feature Status Literal (kept for compatibility if direct str assignment is used elsewhere, but Enum is preferred) ---
FeatureStatus = Literal[
    # NOTE: This Literal is kept for compatibility but FeatureStatusEnum is preferred.
    # It represents the different stages a feature can be in, from initial idea to completion.
    "identified",       # Feature listed based on prompt, but not planned yet.
    "planned",          # Detailed Markdown plan exists, tasks defined.
    "implementing",     # Individual task code generation/modification is in progress.
    "tasks_implemented", # All individual tasks for the feature are completed (their own test_steps passed).
    "generating_feature_tests", # LLM is generating the feature-level test file.
    "feature_testing",  # Feature-level tests (e.g., test_feature_name.py) are being executed.
    "feature_testing_failed", # Feature-level tests failed.
    "feature_testing_passed", # Feature-level tests passed.
    "reviewing",        # Simulated code review phase (placeholder for now).
    "merged",           # Feature completed, integrated, and considered done.
    "planning_failed",  # Feature planning failed.
    "implementation_failed", # Feature implementation failed permanently.
    "cancelled"         # Feature cancelled by user or process.
]

# --- Task Status ---
# Represents the status of an individual task within a feature's plan.
# Each task is a single step, like creating a file or running a command.
TaskStatus = Literal[
    "pending",          # Task is waiting for dependencies or its turn.
    "waiting_dependency",# Task is blocked because its dependencies are not met.
    "in_progress",      # Task execution (code gen, command run) is active.
    "completed",        # Task execution and its test step passed successfully.
    "failed",           # Task execution or its test step failed, even after remediation attempts.
    "skipped",          # Task was intentionally skipped (e.g., condition not met).
]

# --- Task within a Feature Plan ---
# Defines the structure for a single, atomic task derived from the Markdown plan.
class FeatureTask(BaseModel):
    """
    Represents a single, atomic step in a feature's implementation plan.
    """
    # Metadata parsed from Markdown plan
    task_id_str: str            # Hierarchical ID (e.g., "1.1", "3.2.1") from the plan.
    action: Literal[            # The specific type of action this task performs.
        "Create file",
        "Modify file",
        "Run command",
        "Create directory", # Keep Create directory
        "delete_all_default_tests_py", # Add new action
        "delete_app_tests_py", # New action for specific app
        "Prompt user input",
        "Delete file" # Added new action
    ]
    target: str                 # The target of the action (e.g., a file path or a command).
    description: str = Field(default="") # Default to empty string if missing
    requirements: Optional[str] = None # Detailed requirements (from plan).
    dependencies: List[str] = Field(default_factory=list) # List of other task IDs this task depends on.
    test_step: Optional[str] = None    # Command string to run for validating this task (from plan).
    doc_update: Optional[str] = None   # Brief note on documentation impact (from plan).

    resources_defined: Optional[str] = None # A unique ID for a resource this task creates (e.g., a model class).
    api_contract_references: List[str] = Field(default_factory=list) # Links to API contracts relevant to this task.
    ui_component_name: Optional[str] = None # Name of the UI component, if applicable.
    styling_details: Optional[str] = None # Description of visual styles for CSS tasks.
    # Runtime state information managed by the WorkflowManager
    status: TaskStatus = Field(default="pending") # Current status of the task execution.
    result: Optional[str] = None       # Stores the output from execution, an error message, or other feedback.
    execution_history: List[Dict[str, Any]] = Field(default_factory=list) # Stores history of command executions for this task # Add this line
    remediation_attempts: int = Field(default=0)   # Counter for remediation attempts.
    llm_interactions: List[Dict[str, Any]] = Field(default_factory=list) # Stores key LLM prompts/responses for this task

    # --- Pydantic Validators ---

    @field_validator('dependencies', mode='before')
    @classmethod
    def validate_deps_list(cls, v):
        """
        Cleans and validates the dependency list.
        It can parse dependencies from a raw string (e.g., "depends_on: 1.1, 1.2") or a list.
        """
        if v is None:
            return []
        if isinstance(v, str):
            # Handle comma-separated string input if needed
            dep_ids_str = v.replace("depends_on:", "").strip()
            if dep_ids_str.lower() == 'none':
                return []
            # Split, strip whitespace from each potential ID
            deps = [re.sub(r'\s*\(.*\)\s*$', '', dep).strip() for dep in dep_ids_str.split(',') if dep.strip()] # Strip text in parentheses
        elif isinstance(v, list):
            # Ensure all items in the list are strings and strip whitespace
            deps = [str(dep).strip() for dep in v if dep and isinstance(dep, (str, int, float))] # Ensure dep is not None
        else:
            raise ValueError("Dependencies must be a list or comma-separated string")

        # Basic check for hierarchical ID format (must contain '.')
        valid_deps = [dep for dep in deps if dep and '.' in dep and re.match(r'^[0-9\.]+$', dep)] # Added invalid_deps
        invalid_deps = [dep for dep in deps if dep and '.' not in dep]
        if invalid_deps:
            logger.warning(f"Ignoring invalid dependency IDs {invalid_deps} during validation (not in 'X.Y' format).")
        return valid_deps

    @model_validator(mode='after')
    def set_default_test_step(self) -> 'FeatureTask':
        """Assigns a default test step if none is provided and action is not 'Prompt user input'."""
        # If a task is planned without a test step, we add a default one
        # to remind the user or system that manual verification is needed.
        if self.test_step is None and self.action != "Prompt user input": # Check for None explicitly
            logger.warning(f"Task '{self.task_id_str}' missing 'Test step'. Assigning default.")
            self.test_step = 'echo "Default test step - Check manually"'
        if self.test_step and "echo" in self.test_step and self.action != "Prompt user input":
            logger.warning(f"Task '{self.task_id_str}' the test step is an echo command, not desirable")
            #raise ValueError("Test step in taks shouldn't be echo")
        return self

# --- Feature Representation ---
# Defines the structure for a single feature within the project.
class ProjectFeature(BaseModel):
    """
    Represents a high-level feature to be implemented in the project.
    """
    id: str                     # Unique identifier for the feature (e.g., "auth", "user-profile-view").
    name: str                   # Human-readable name (e.g., "Authentication", "User Profile Display").
    description: str            # Brief description of the feature's purpose (often from the user prompt).
    status: FeatureStatusEnum = Field(default=FeatureStatusEnum.IDENTIFIED) # Current lifecycle status of the feature.
    plan_markdown: Optional[str] = None # The raw Markdown plan generated by Tars for this feature.
    related_api_contract_ids: List[str] = Field(default_factory=list) # List of APIContract.contract_id
    tasks: List[FeatureTask] = Field(default_factory=list) # List of parsed tasks required to implement this feature.
    branch_name: Optional[str] = None # Simulated Git branch name (e.g., "feature/auth"). (Optional field)
    dependencies: List[str] = Field(default_factory=list) # IDs of other *features* this feature depends on.
    remediation_attempts_for_feature_tests: int = Field(default=0) # New field to track attempts for feature-level tests
# --- Detailed File Structure Models ---

class PythonFileImport(BaseModel):
    """Represents a single Python import statement (e.g., `from .models import User`)."""
    module: str
    names: List[Dict[str, Optional[str]]] = Field(default_factory=list) # [{"name": "actual_name", "as_name": "alias_name_or_null"}]
    level: int = 0 # For relative imports
    type: Literal["stdlib", "third_party", "local_app", "project_app", "unknown"] = "unknown"

class PythonFunctionParam(BaseModel):
    """Represents a single parameter in a Python function definition."""
    name: str
    annotation: Optional[str] = None # Store type hint as string
    default: Optional[str] = None # Store as string representation

class PythonFunction(BaseModel):
    """Represents a Python function, including its parameters and decorators."""
    name: str
    params: List[PythonFunctionParam] = Field(default_factory=list)
    decorators: List[str] = Field(default_factory=list)
    return_type_hint: Optional[str] = None
    is_async: bool = False

class PythonClassAttribute(BaseModel):
    """Represents a class-level attribute."""
    name: str
    value_preview: Optional[str] = None # String representation of the assigned value (truncated)
    type_hint: Optional[str] = None
    is_static: bool = False # Placeholder for future analysis

class PythonClass(BaseModel):
    """Represents a Python class, including its methods and attributes."""
    name: str
    bases: List[str] = Field(default_factory=list) # List of base class names as strings
    methods: List[PythonFunction] = Field(default_factory=list)
    attributes: List[PythonClassAttribute] = Field(default_factory=list) # Statically defined class attributes
    decorators: List[str] = Field(default_factory=list)

class PythonFileDetails(BaseModel):
    """Structured representation of a Python file's contents."""
    imports: List[PythonFileImport] = Field(default_factory=list)
    functions: List[PythonFunction] = Field(default_factory=list)
    classes: List[PythonClass] = Field(default_factory=list)

class DjangoModelField(BaseModel):
    """Represents a single field within a Django model class."""
    name: str
    field_type: str  # e.g., "CharField", "ForeignKey"
    args: Dict[str, Any] = Field(default_factory=dict) # e.g., {"max_length": 50, "to": "OtherModel"}
    # Explicitly store common and important field arguments
    related_model_name: Optional[str] = None # Explicitly store the 'to' model for ForeignKey, OneToOneField, ManyToManyField
    related_name: Optional[str] = None # For ForeignKey, OneToOneField, ManyToManyField
    on_delete: Optional[str] = None # For ForeignKey, OneToOneField (e.g., "models.CASCADE")
    null: Optional[bool] = None
    blank: Optional[bool] = None
    default: Optional[Any] = None
    max_length: Optional[int] = None
    unique: Optional[bool] = None
    db_index: Optional[bool] = None
    choices: Optional[List[Tuple[Any, str]]] = None # Store as list of (value, display_name) tuples

class DjangoModel(PythonClass): # Inherits name, bases, methods, attributes
    """Represents a Django model, extending a Python class with Django-specific fields."""
    django_fields: List[DjangoModelField] = Field(default_factory=list)
    meta_options: Dict[str, Any] = Field(default_factory=dict) # e.g., {"ordering": ["-created_at"]}

class DjangoModelFileDetails(PythonFileDetails):
    """Structured representation of a Django models.py file."""
    models: List[DjangoModel] = Field(default_factory=list)

class DjangoView(PythonFunction): # Inherits name, params, decorators, return_type_hint
    """Represents a Django view, extending a Python function with view-specific details."""
    rendered_templates: List[str] = Field(default_factory=list)
    models_queried: List[str] = Field(default_factory=list)
    uses_forms: List[str] = Field(default_factory=list)
    redirects_to_url_name: Optional[str] = None
    allowed_http_methods: List[str] = Field(default_factory=list) # e.g., ['GET', 'POST']
    context_data_keys: List[str] = Field(default_factory=list) # Keys passed in the context to a template

class DjangoViewFileDetails(PythonFileDetails):
    """Structured representation of a Django views.py file."""
    views: List[DjangoView] = Field(default_factory=list)

class DjangoURLPattern(BaseModel):
    """Represents a single `path()` or `re_path()` in a urls.py file."""
    pattern: str
    view_reference: str # String reference to the view (e.g., "views.my_view", "MyClassView.as_view()")
    http_methods: List[str] = Field(default_factory=list) # e.g., ['GET', 'POST']
    name: Optional[str] = None

class DjangoURLInclude(BaseModel):
    """Represents an `include()` in a urls.py file."""
    pattern: str
    included_urlconf: str # String reference to the included module (e.g., "other_app.urls")

class DjangoURLConfDetails(PythonFileDetails):
    """Structured representation of a Django urls.py file."""
    app_name: Optional[str] = None
    url_patterns: List[DjangoURLPattern] = Field(default_factory=list)
    includes: List[DjangoURLInclude] = Field(default_factory=list)

class DjangoForm(PythonClass): # Inherits name, bases, methods, attributes
    """Represents a Django Form or ModelForm."""
    meta_model: Optional[str] = None # For ModelForms
    meta_fields: List[str] = Field(default_factory=list) # For ModelForm fields
    form_fields: List[DjangoModelField] = Field(default_factory=list) # For explicitly defined fields

class DjangoFormFileDetails(PythonFileDetails):
    """Structured representation of a Django forms.py file."""
    forms: List[DjangoForm] = Field(default_factory=list)

class DjangoAdminRegisteredModel(BaseModel):
    """Represents a model registered with the Django admin site."""
    model: str # Name of the model class
    admin_class: Optional[str] = None # Name of the ModelAdmin class, if used

class DjangoAdminClass(PythonClass): # Inherits name, bases, methods, attributes
    """Represents a ModelAdmin class in an admin.py file."""
    model: Optional[str] = None # Model this admin class is for
    list_display: List[str] = Field(default_factory=list)
    list_filter: List[str] = Field(default_factory=list)
    search_fields: List[str] = Field(default_factory=list)

class DjangoAdminFileDetails(PythonFileDetails):
    """Structured representation of a Django admin.py file."""
    registered_models: List[DjangoAdminRegisteredModel] = Field(default_factory=list)
    admin_classes: List[DjangoAdminClass] = Field(default_factory=list)

class DjangoTestFileDetails(PythonFileDetails): # New model for tests.py
    """Structured representation of a Django test file."""
    # Reuses PythonFileDetails which has 'classes' and 'functions'
    # Test classes would be PythonClass where name starts with Test or inherits TestCase
    # Test methods would be PythonFunction where name starts with test_
    pass

class DjangoSettingsDetails(PythonFileDetails):
    """Structured representation of a Django settings.py file."""
    key_settings: Dict[str, Any] = Field(default_factory=dict) # e.g., {"INSTALLED_APPS": [...]}

class TemplateFileDetails(BaseModel):
    """Structured representation of an HTML/Jinja2 template file."""
    extends_template: Optional[str] = None
    includes_templates: List[str] = Field(default_factory=list)
    extends_base_html_unresolved: bool = False # New flag for planner
    static_files_used: List[str] = Field(default_factory=list)
    url_references: List[str] = Field(default_factory=list) # Names or paths used in {% url %}
    key_dom_ids: List[str] = Field(default_factory=list) # IDs of significant DOM elements
    # context_variables_used: List[str] = Field(default_factory=list) # Already exists
    context_variables_used: List[str] = Field(default_factory=list)
    form_targets: List[str] = Field(default_factory=list) # URLs that forms post to

class JSFileDetails(BaseModel):
    """Structured representation of a JavaScript file."""
    imports_from: List[str] = Field(default_factory=list)
    ajax_calls_to_urls: List[str] = Field(default_factory=list)
    accesses_dom_ids: List[str] = Field(default_factory=list)
    global_functions: List[str] = Field(default_factory=list) # Top-level functions

class CSSFileDetails(BaseModel):
    """Structured representation of a CSS file."""
    imports_css: List[str] = Field(default_factory=list)
    defines_selectors: List[str] = Field(default_factory=list) # Key IDs and classes

# --- API Contract Models ---
APIContractFieldRef = ForwardRef('APIContractField')

class APIContractField(BaseModel):
    """Defines a single field within an API request or response body."""
    name: str
    type: str # e.g., "string", "integer", "boolean", "object", "array"
    required: bool = True
    description: Optional[str] = None
    example: Optional[Any] = None
    properties: Optional[Dict[str, APIContractFieldRef]] = None # For nested objects
    items: Optional[APIContractFieldRef] = None # For arrays

APIContractField.model_rebuild()

class APIContractRequestResponse(BaseModel):
    """Defines the structure of an API request or response body."""
    description: Optional[str] = None
    content_type: str = "application/json"
    schema_description: Optional[str] = None # General description of the schema
    fields: Dict[str, APIContractField] = Field(default_factory=dict) # Key: field name

class APIContractEndpoint(BaseModel):
    """Defines a single API endpoint (e.g., GET /api/users)."""
    path: str
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"]
    summary: Optional[str] = None
    description: Optional[str] = None
    request_body: Optional[APIContractRequestResponse] = None
    responses: Dict[str, APIContractRequestResponse] = Field(default_factory=dict) # Key: status code (e.g., "200", "400")
    authentication_required: bool = False
    permissions_needed: List[str] = Field(default_factory=list)

# --- Project Structure Map ---
# Defines the structure for the project's code map.
class FileStructureInfo(BaseModel):
    """
    A container for the structured details of a single file, parsed by CodeIntelligenceService.
    """
    file_type: Literal[
        # ... (keep existing types)
        "python", "django_model", "django_view", "django_urls", "django_test",
        "django_form", "django_admin", "django_settings", "django_apps_config",
        "template", "javascript", "css", "json_data", "text", "unknown"
    ] = "unknown"
    python_details: Optional[PythonFileDetails] = None
    django_model_details: Optional[DjangoModelFileDetails] = None
    django_view_details: Optional[DjangoViewFileDetails] = None
    django_urls_details: Optional[DjangoURLConfDetails] = None
    django_form_details: Optional[DjangoFormFileDetails] = None
    django_admin_details: Optional[DjangoAdminFileDetails] = None
    django_settings_details: Optional[DjangoSettingsDetails] = None
    django_test_details: Optional[DjangoTestFileDetails] = None # New field
    django_apps_config_details: Optional[PythonFileDetails] = None # For apps.py
    template_details: Optional[TemplateFileDetails] = None
    js_details: Optional[JSFileDetails] = None
    css_details: Optional[CSSFileDetails] = None
    raw_content_summary: Optional[str] = None # For unknown or simple text files

class AppStructureInfo(BaseModel):
    """Represents the collection of parsed files within a single Django app."""
    files: Dict[str, FileStructureInfo] = Field(default_factory=dict) # file_name: FileStructureInfo

class GlobalURLRegistryEntry(BaseModel):
    """Represents a single named URL pattern found anywhere in the project."""
    name: str # The 'name' attribute from path()
    file_path: str # Relative path to the urls.py file defining it
    app_name: Optional[str] = None # The app_name if defined in that urls.py
class ProjectStructureMap(BaseModel):
    """
    The top-level map of the entire project's code structure, organized by app.
    This is a key input for providing context to the AI agents.
    """
    apps: Dict[str, AppStructureInfo] = Field(default_factory=dict) # app_name: AppStructureInfo
    global_url_registry: Dict[str, GlobalURLRegistryEntry] = Field(default_factory=dict) # url_name: GlobalURLRegistryEntry

# --- Overall Project State ---
# Defines the top-level structure for the entire project's state, saved by MemoryManager.

class ProjectState(BaseModel):
    """
    The main Pydantic model that holds the entire state of the development project.
    This object is serialized to disk by the MemoryManager to persist state across sessions.
    """
    project_name: str
    framework: str
    root_path: str
    api_contracts: List['APIContract'] = Field(default_factory=list)
    features: List[ProjectFeature] = Field(default_factory=list)
    current_feature_id: Optional[str] = None
    cumulative_docs: str = Field(default="")
    placeholders: Dict[str, str] = Field(default_factory=dict)
    file_checksums: Dict[str, str] = Field(default_factory=dict)
    venv_path: Optional[str] = None
    active_git_branch: Optional[str] = None
    git_status_summary: Optional[str] = None # Added field to store summary of git status
    detailed_dependency_info: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    open_files_context: Dict[str, str] = Field(default_factory=dict) # path: partial content/summary
    last_error_context: Optional[Dict[str, Any]] = None
    code_summaries: Dict[str, str] = Field(default_factory=dict) # Stores file_path: latest_summary
    security_feedback_history: List[Dict[str, str]] = Field(default_factory=list) # Stores feedback about blocked commands
    historical_notes: List[str] = Field(default_factory=list) # Stores high-level decisions/notes
    artifact_registry: Dict[str, Any] = Field(default_factory=dict) # Central registry for defined resources
    project_structure_map: ProjectStructureMap = Field(default_factory=ProjectStructureMap) # New field for code map
    remediation_config: Optional[Dict[str, bool]] = None

    def get_feature_by_id(self, feature_id: str) -> Optional[ProjectFeature]:
        """
        Retrieves a feature from the features list by its ID.

        Args:
            feature_id: The ID of the feature to retrieve.

        Returns:
            The ProjectFeature instance if found, otherwise None.
        """
        for feature in self.features:
            if feature.id == feature_id:
                return feature
        return None

    def get_api_contract_by_id(self, contract_id: str) -> Optional['APIContract']:
        """
        Retrieves an API contract from the api_contracts list by its ID.

        Args:
            contract_id: The ID of the API contract to retrieve.

        Returns:
            The APIContract instance if found, otherwise None.
        """
        for contract in self.api_contracts:
            if contract.contract_id == contract_id:
                return contract
        return None
class TaskExecutionResult(BaseModel):
    success: bool
    is_fatal: bool = False
    output: Optional[str] = None
    error_details: Optional[str] = None # Detailed error message if success is False.

class CommandResult(BaseModel):
    """Standardized result object for command executions."""
    success: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    structured_error: Optional[Dict[str, Any]] = None
    command_str: str = ""

class APIContract(BaseModel): # Define APIContract after ProjectState or handle ForwardRef if it were nested
    """Represents a formal contract for an API, including its endpoints and data schemas."""
    contract_id: str = Field(default_factory=lambda: f"contract_{int(time.time() * 1000)}")
    feature_id: Optional[str] = None # Link to the feature this contract primarily serves
    title: str
    version: str = "1.0.0"
    description: Optional[str] = None
    endpoints: List[APIContractEndpoint] = Field(default_factory=list)

ProjectState.model_rebuild() # For ForwardRef resolution if APIContract was defined after

# --- Remediation System Models ---
class CommandOutput(BaseModel):
    """Structured output from a command execution."""
    command: str
    stdout: str
    stderr: str
    exit_code: int

class ErrorType(str, Enum):
    """
    Enumeration of the different types of errors the system can classify.
    """
    TestFailure = "TestFailure"
    FileNotFound = "FileNotFound"
    SyntaxError = "SyntaxError"
    CommandNotFound = "CommandNotFound"
    LogicError = "LogicError"
    TemplateError = "TemplateError"
    PermissionError = "PermissionError"
    Unknown = "Unknown"

class ErrorRecord(BaseModel):
    """
    A structured representation of a single error event, parsed from logs.
    """
    error_type: ErrorType = Field(..., description="The classified type of the error.")
    file_path: Optional[str] = Field(None, description="The file where the error occurred.")
    line_number: Optional[int] = Field(None, description="The line number of the error.")
    message: str = Field(..., description="The raw error message or a summary.")
    summary: Optional[str] = Field(None, description="A concise, one-line summary of the specific error (e.g., 'NameError: name 'x' is not defined').")
    command: Optional[str] = Field(None, description="The command that produced the error.")
    hints: Optional[Dict[str, Any]] = Field(None, description="Rich hints for the planner, like candidate files and diagnoses.")
    triggering_task: Optional['FeatureTask'] = Field(None, description="The original task that triggered this error.")

# Add this after the class definition to resolve the forward reference
ErrorRecord.model_rebuild()

class RemediationTaskType(str, Enum):
    """Enumeration of the different types of remediation tasks the planner can create."""
    CreateFile = "CreateFile"
    FixSyntax = "FixSyntax"
    FixCommand = "FixCommand"
    FixLogic = "FixLogic"

class RemediationTask(BaseModel):
    """
    Represents a single task within a remediation plan.
    (Note: This is a more generic model; the specific task types below are preferred).
    """
    task_type: RemediationTaskType
    file_path: Optional[str] = None
    command: Optional[str] = None
    errors: List[ErrorRecord] = []

class RemediationPlan(BaseModel):
    """Represents a full plan to remediate one or more errors, consisting of multiple tasks."""
    tasks: List[RemediationTask]


class FixLogicTask(BaseModel):
    """A remediation task to fix a logical error, often requiring context from multiple files."""
    type: Literal["FixLogicTask"] = "FixLogicTask"
    original_error: ErrorRecord
    description: str
    files_to_fix: List[str]

class FixBundleTask(BaseModel):
    """A remediation task that bundles multiple errors related to a single file into one fix."""
    type: Literal["FixBundleTask"] = "FixBundleTask"
    original_error: ErrorRecord
    bundled_errors: List[ErrorRecord]

class CreateFileTask(BaseModel):
    """A remediation task to create a file that was reported as missing."""
    type: Literal["CreateFileTask"] = "CreateFileTask"
    original_error: ErrorRecord

class FixSyntaxTask(BaseModel):
    """A remediation task to fix a syntax error in a specific file."""
    type: Literal["FixSyntaxTask"] = "FixSyntaxTask"
    original_error: ErrorRecord

class FixCommandTask(BaseModel):
    """A remediation task to correct a command that failed to execute."""
    type: Literal["FixCommandTask"] = "FixCommandTask"
    original_error: ErrorRecord 

AnyRemediationTask = Union[FixLogicTask, FixBundleTask, CreateFileTask, FixSyntaxTask, FixCommandTask]

logger.info("Project model definitions (Pydantic: ProjectState, ProjectFeature, FeatureTask) loaded.")
