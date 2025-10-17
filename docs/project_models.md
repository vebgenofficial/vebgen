# 📋 project_models.py - Complete Documentation

## 🎯 Overview

**File**: `backend/src/core/project_models.py`  
**Size**: 35,371 characters (35 KB)  
**Purpose**: The **type-safe data schema** for VebGen's entire project state using **Pydantic**

This file is VebGen's **data architecture blueprint**—it defines 60+ Pydantic models that represent every aspect of a Django project, from high-level features down to individual function parameters. Think of it as the **DNA sequence** of VebGen:
- **Type-safe** (Pydantic validation ensures data integrity)
- **Self-documenting** (field names and descriptions explain structure)
- **Serializable** (converts to JSON for persistence via MemoryManager)
- **Extensible** (easy to add new fields without breaking old code)
- **Framework-agnostic base** (Python, Django, DRF, Wagtail, django-cms, Celery, Channels, GraphQL all supported)

**Think of it as**: A detailed blueprint that defines the "shape" of every piece of data VebGen stores—from a feature request to a single function parameter.

---

## 🧠 For Users: What This File Does

### The Type System

**The Problem**: Python is dynamically typed—easy to store wrong data types, breaking code

**VebGen's Solution**: Pydantic models enforce structure at runtime

**Example**:
Without Pydantic (dangerous):
```python
feature = {
    "id": "user_auth",
    "status": "completedd", # Typo! But Python allows it
    "tasks": "some string" # Should be list! But Python allows it
}
```
Result: Runtime errors later when code expects list 💀

With Pydantic (safe):
```python
feature = ProjectFeature(
    id="user_auth",
    status="completedd", # ❌ Validation fails immediately!
    tasks="some string" # ❌ Validation fails immediately!
)
```
Result: `ValidationError` raised with helpful message ✅

### What Gets Modeled

**60+ Pydantic Models** organized into categories:

**1. High-Level Project Structure** (5 models):
- `ProjectState` - Entire project (features, apps, models, file checksums)
- `ProjectFeature` - Single feature (e.g., "User Authentication")
- `FeatureTask` - Single atomic task (e.g., "Create User model")
- `ProjectStructureMap` - AST-parsed code map
- `APIContract` - API endpoint specifications

**2. Django-Specific Models** (25+ models):
- `DjangoModel` - Model class with fields and Meta
- `DjangoModelField` - Single field (CharField, ForeignKey, etc.)
- `DjangoView` - FBV or CBV with templates, context, ORM queries
- `DjangoURLPattern` - URL routing configuration
- `DjangoForm` - Form or ModelForm
- `DjangoSerializer` - DRF serializer
- `DjangoAdmin` - ModelAdmin configuration
- `DjangoTest` - Test class
- `DjangoSignal` - Signal receiver
- `CeleryTask` - Background task
- `DjangoChannelsConsumer` - WebSocket consumer
- `GraphQLType` - GraphQL schema (Graphene)
- `DjangoMigration` - Migration file operations

**3. Generic Python Models** (10 models):
- `PythonFileImport` - Import statement
- `PythonFunction` - Function with parameters, decorators
- `PythonClass` - Class with methods, attributes
- `PythonFunctionParam` - Function parameter with type hints

**4. Frontend Models** (5 models):
- `TemplateFileDetails` - Django template (extends, includes, context vars)
- `JSFileDetails` - JavaScript file structure
- `CSSFileDetails` - CSS file structure

**5. Third-Party Framework Models** (5 models):
- `WagtailPage` - Wagtail CMS page model
- `DjangoCMSPlugin` - django-cms plugin
- `MPTTModel` - Tree structure models

---

## 👨‍💻 For Developers: Technical Architecture

### File Structure

```text
project_models.py (35,371 characters)
├── Enums
│   ├── FeatureStatusEnum (13 states)
│   └── FeatureStatus (Literal - legacy compatibility)
│
├── High-Level Models
│   ├── FeatureTask (atomic task with 20+ fields)
│   ├── ProjectFeature (feature with tasks, logs, status)
│   ├── ProjectState (entire project state)
│   └── APIContract (API specification)
│
├── Generic Python Models (10 models)
│   ├── PythonFileImport
│   ├── PythonFunction
│   ├── PythonFunctionParam
│   ├── PythonClass
│   ├── PythonClassAttribute
│   └── PythonFileDetails
│
├── Django Core Models (25+ models)
│   ├── DjangoModel (extends PythonClass)
│   ├── DjangoModelField (field definition)
│   ├── DjangoView (extends PythonFunction)
│   ├── DjangoForm
│   ├── DjangoSerializer
│   ├── DjangoURLPattern
│   ├── DjangoAdmin
│   ├── DjangoTest
│   ├── DjangoSignal
│   ├── CeleryTask
│   ├── DjangoChannelsConsumer
│   ├── DjangoMigration
│   └── DjangoSettings
│
├── Django File Details (aggregates)
│   ├── DjangoModelFileDetails (models.py)
│   ├── DjangoViewFileDetails (views.py)
│   ├── DjangoURLConfDetails (urls.py)
│   ├── DjangoFormFileDetails (forms.py)
│   ├── DjangoAdminFileDetails (admin.py)
│   ├── DjangoTestFileDetails (tests.py)
│   ├── DjangoSerializerFileDetails (serializers.py)
│   └── DjangoSettingsDetails (settings.py)
│
├── Third-Party Models
│   ├── WagtailPage (Wagtail CMS)
│   ├── DjangoCMSPlugin (django-cms)
│   └── GraphQLType (Graphene-Django)
│
├── Frontend Models
│   ├── TemplateFileDetails (HTML)
│   ├── JSFileDetails (JavaScript)
│   └── CSSFileDetails (CSS)
│
├── Project Structure
│   ├── FileStructureInfo (parsed file)
│   ├── AppStructureInfo (app files)
│   └── ProjectStructureMap (entire project)
│
└── Utility Models
    ├── CommandResult
    ├── CommandOutput
    └── TaskExecutionResult
```

---

## 📚 Key Models Deep Dive

### 1. `ProjectState` (The Root)

**Purpose**: Represents the entire project state (persisted to disk)

```python
class ProjectState(BaseModel):
    """The main Pydantic model holding entire project state."""

    # Basic Info
    schema_version: int = 1  # For migration support
    project_name: str
    framework: str  # "django", "flask", etc.
    root_path: str

    # Features & API Contracts
    api_contracts: List[APIContract] = Field(default_factory=list)
    features: List[ProjectFeature] = Field(default_factory=list)
    current_feature_id: Optional[str] = None

    # File & Code Tracking
    file_checksums: Dict[str, str] = Field(default_factory=dict)
    code_summaries: Dict[str, str] = Field(default_factory=dict)
    project_structure_map: ProjectStructureMap = Field(default_factory=ProjectStructureMap)

    # Django State (NEW)
    registered_apps: Set[str] = Field(default_factory=set)
    defined_models: Dict[str, List[str]] = Field(default_factory=dict)

    # Artifact Registry
    artifact_registry: Dict[str, Any] = Field(default_factory=dict)

    # Historical Data
    historical_notes: List[str] = Field(default_factory=list)
    security_feedback_history: List[Dict[str, str]] = Field(default_factory=list)

    # Git Integration
    active_git_branch: Optional[str] = None
    git_status_summary: Optional[str] = None

    # Placeholders (for secrets)
    placeholders: Dict[str, str] = Field(default_factory=dict)

    # Helper Methods
    def get_feature_by_id(self, feature_id: str) -> Optional[ProjectFeature]:
        """Retrieves feature by ID."""
        for feature in self.features:
            if feature.id == feature_id:
                return feature
        return None
```

**Example Usage**:
```python
state = ProjectState(
    project_name="my_blog",
    framework="django",
    root_path="/home/user/my_blog",
    registered_apps={"blog", "accounts"},
    defined_models={
        "blog": ["Post", "Comment"],
        "accounts": ["User"]
    }
)

# Save to JSON (via MemoryManager)
state_dict = state.model_dump(mode='json')
json.dump(state_dict, file)

# Load from JSON
loaded_state = ProjectState.model_validate(state_dict)
```

---

### 2. `ProjectFeature` (High-Level Feature)

**Purpose**: Represents a single feature (e.g., "User Authentication")

```python
class ProjectFeature(BaseModel):
    """Represents a high-level feature to be implemented."""

    # Identity
    id: str  # Unique ID (e.g., "user_auth")
    name: str  # Human-readable (e.g., "User Authentication")
    description: str  # Feature description

    # Lifecycle Status (13 states)
    status: FeatureStatusEnum = Field(default=FeatureStatusEnum.IDENTIFIED)
    # IDENTIFIED → PLANNED → IMPLEMENTING → TASKS_IMPLEMENTED → 
    # FEATURE_TESTING → FEATURE_TESTING_PASSED → MERGED

    # Implementation Plan
    plan_markdown: Optional[str] = None  # TARS-generated Markdown plan
    tasks: List[FeatureTask] = Field(default_factory=list)  # Parsed tasks

    # Work Tracking
    work_log: List[str] = Field(default_factory=list)  # Action history
    remediation_attempts_for_feature_tests: int = Field(default=0)

    # API Contracts
    related_api_contract_ids: List[str] = Field(default_factory=list)

    # Git Integration
    branch_name: Optional[str] = None  # e.g., "feature/user_auth"

    # Dependencies
    dependencies: List[str] = Field(default_factory=list)  # Other feature IDs
```

**Example**:
```python
feature = ProjectFeature(
    id="user_auth",
    name="User Authentication",
    description="Add login and registration functionality",
    status=FeatureStatusEnum.IMPLEMENTING,
    tasks=[
        FeatureTask(task_id_str="1.1", action="Create file", target="accounts/models.py"),
        FeatureTask(task_id_str="1.2", action="Run command", target="python manage.py migrate")
    ]
)
```

---

### 3. `FeatureTask` (Atomic Task)

**Purpose**: Represents a single, atomic step in feature implementation

```python
class FeatureTask(BaseModel):
    """Represents a single atomic step in a feature's implementation."""

    # Task Identity
    task_id_str: str  # Hierarchical ID (e.g., "1.1", "3.2.1")

    # Action Type (8 types)
    action: Literal[
        "Create file",
        "Modify file",
        "Run command",
        "Create directory",
        "Delete file",
        "delete_all_default_tests_py",
        "delete_app_tests_py",
        "Prompt user input"
    ]

    # Target & Description
    target: str  # File path or command string
    description: str = Field(default="")
    requirements: Optional[str] = None  # Detailed requirements

    # Dependencies & Testing
    dependencies: List[str] = Field(default_factory=list)  # Task IDs this depends on
    test_step: Optional[str] = None  # Validation command

    # Documentation
    doc_update: Optional[str] = None

    # Resource Tracking
    resources_defined: Optional[str] = None  # e.g., "User:model"
    api_contract_references: List[str] = Field(default_factory=list)

    # UI-Specific (for frontend tasks)
    ui_component_name: Optional[str] = None
    styling_details: Optional[str] = None

    # Runtime State
    status: TaskStatus = Field(default="pending")
    result: Optional[str] = None
    execution_history: List[Dict[str, Any]] = Field(default_factory=list)
    remediation_attempts: int = Field(default=0)
    llm_interactions: List[Dict[str, Any]] = Field(default_factory=list)

    # Validators
    @field_validator('dependencies', mode='before')
    @classmethod
    def validate_deps_list(cls, v):
        """Parses dependencies from string or list."""
        # Converts "depends_on: 1.1, 1.2" → ["1.1", "1.2"]
        # ...
```

**Example**:
```python
task = FeatureTask(
    task_id_str="1.1",
    action="Create file",
    target="accounts/models.py",
    description="Create User model with email and password fields",
    requirements="Inherit from AbstractBaseUser, use email as USERNAME_FIELD",
    test_step="python manage.py check",
    dependencies=[] # No dependencies
)
```

---

### 4. `DjangoModel` (Django Model Representation)

**Purpose**: Represents a Django model class with all fields and Meta options

```python
class DjangoModelField(BaseModel):
    """Represents a single field within a Django model."""
    name: str
    field_type: str # e.g., "CharField", "ForeignKey"
    args: Dict[str, Any] = Field(default_factory=dict)

    # Commonly used arguments (extracted for easy access)
    related_model_name: Optional[str] = None  # For ForeignKey
    related_name: Optional[str] = None
    on_delete: Optional[str] = None  # e.g., "models.CASCADE"
    null: Optional[bool] = None
    blank: Optional[bool] = None
    default: Optional[Any] = None
    max_length: Optional[int] = None
    unique: Optional[bool] = None
    db_index: Optional[bool] = None
    choices: Optional[List[Tuple[Any, str]]] = None

class DjangoModel(PythonClass): # Inherits name, bases, methods, attributes
    """Represents a Django model, extending PythonClass."""
    django_fields: List[DjangoModelField] = Field(default_factory=list)
    meta_options: Dict[str, Any] = Field(default_factory=dict)
    is_mptt_model: bool = Field(default=False)
```

**Example**:
```python
user_model = DjangoModel(
    name="User",
    bases=["AbstractBaseUser"],
    django_fields=[
        DjangoModelField(
            name="email",
            field_type="EmailField",
            unique=True,
            max_length=255
        ),
        DjangoModelField(
            name="is_active",
            field_type="BooleanField",
            default=True
        )
    ],
    meta_options={
        "ordering": ["-date_joined"],
        "verbose_name_plural": "Users"
    }
)
```

---

### 5. `DjangoView` (View Representation)

**Purpose**: Represents a Django view with all metadata

```python
class DjangoView(PythonFunction): # Inherits name, params, decorators
    """Represents a Django view (FBV or CBV)."""

    # Template & Context
    rendered_templates: List[str] = Field(default_factory=list)
    context_data_keys: List[str] = Field(default_factory=list)

    # ORM Queries
    models_queried: List[str] = Field(default_factory=list)
    queryset_optimizations: List[str] = Field(default_factory=list)
    uses_raw_sql: bool = Field(default=False)
    aggregations_annotations: List[str] = Field(default_factory=list)

    # Forms & Redirects
    uses_forms: List[str] = Field(default_factory=list)
    redirects_to_url_name: Optional[str] = None

    # HTTP
    allowed_http_methods: List[str] = Field(default_factory=list)

    # DRF (if applicable)
    authentication_classes: List[str] = Field(default_factory=list)
    permission_classes: List[str] = Field(default_factory=list)
```

**Example**:
```python
post_detail_view = DjangoView(
    name="post_detail",
    params=[
        PythonFunctionParam(name="request"),
        PythonFunctionParam(name="pk", annotation="int")
    ],
    rendered_templates=["blog/post_detail.html"],
    context_data_keys=["post", "comments", "comment_count"],
    models_queried=["Post", "Comment"],
    queryset_optimizations=["select_related"],
    allowed_http_methods=["GET"]
)
```

---

### 6. `FileStructureInfo` (Parsed File Representation)

**Purpose**: Container for all parsed details of a single file

```python
class FileStructureInfo(BaseModel):
    """Structured details of a single file, parsed by CodeIntelligenceService."""

    file_type: Literal[
        "python", "django_model", "django_view", "django_urls", 
        "django_test", "django_migration", "django_serializer",
        "django_signal", "celery_task", "django_form", "django_admin",
        "django_settings", "django_apps_config", "django_graphql_schema",
        "django_channels_consumer", "django_channels_routing",
        "django_templatetag", "template", "javascript", "css",
        "json_data", "text", "unknown"
    ] = "unknown"

    # Generic Python (always available for .py files)
    python_details: Optional[PythonFileDetails] = None

    # Django-specific (only if detected)
    django_model_details: Optional[DjangoModelFileDetails] = None
    django_view_details: Optional[DjangoViewFileDetails] = None
    django_urls_details: Optional[DjangoURLConfDetails] = None
    django_form_details: Optional[DjangoFormFileDetails] = None
    django_admin_details: Optional[DjangoAdminFileDetails] = None
    django_settings_details: Optional[DjangoSettingsDetails] = None
    django_test_details: Optional[DjangoTestFileDetails] = None
    django_serializer_details: Optional[DjangoSerializerFileDetails] = None
    # ... (15+ Django-specific detail types)

    # Frontend
    template_details: Optional[TemplateFileDetails] = None
    js_details: Optional[JSFileDetails] = None
    css_details: Optional[CSSFileDetails] = None

    # Fallback
    raw_content_summary: Optional[str] = None
```

**Usage**:
After `CodeIntelligenceService` parses `blog/models.py`:
```python
file_info = FileStructureInfo(
    file_type="django_model",
    python_details=PythonFileDetails(
        imports=[...],
        functions=[],
        classes=[...]
    ),
    django_model_details=DjangoModelFileDetails(
        models=[user_model, post_model, comment_model],
        wagtail_pages=[],
        cms_plugins=[]
    )
)

# Access models:
for model in file_info.django_model_details.models:
    print(f"Model: {model.name}")
    for field in model.django_fields:
        print(f" - {field.name}: {field.field_type}")
```

---

## 🎓 Advanced Features

### 1. Pydantic Validators

**Purpose**: Enforce business logic during model creation

**Example 1: Dependency Validation**
```python
@field_validator('dependencies', mode='before')
@classmethod
def validate_deps_list(cls, v):
    """Converts various dependency formats to standardized list."""
    if v is None:
        return []

    if isinstance(v, str):
        # Handle: "depends_on: 1.1, 1.2 (task name)"
        dep_ids_str = v.replace("depends_on:", "").strip()
        if dep_ids_str.lower() == 'none':
            return []
        # Extract IDs, strip parenthetical descriptions
        deps = [re.sub(r'\s*\(.*\)\s*$', '', dep).strip() 
                for dep in dep_ids_str.split(',') if dep.strip()]
    elif isinstance(v, list):
        deps = [str(dep).strip() for dep in v if dep]
    else:
        raise ValueError("Dependencies must be list or comma-separated string")

    # Validate hierarchical format (must contain '.')
    valid_deps = [dep for dep in deps if dep and '.' in dep]
    invalid_deps = [dep for dep in deps if dep and '.' not in dep]

    if invalid_deps:
        logger.warning(f"Ignoring invalid dependency IDs: {invalid_deps}")

    return valid_deps
```

**Example 2: Default Test Step**
```python
@model_validator(mode='after')
def set_default_test_step(self) -> 'FeatureTask':
    """Assigns default test step if missing."""
    if self.test_step is None and self.action != "Prompt user input":
        logger.warning(f"Task '{self.task_id_str}' missing test step. Assigning default.")
        self.test_step = 'echo "Default test step - Check manually"'
    return self
```

---

### 2. Model Inheritance

**Purpose**: Reuse common fields via inheritance

**Example**:
```python
class PythonFunction(BaseModel):
    """Generic Python function."""
    name: str
    params: List[PythonFunctionParam]
    decorators: List[str]
    return_type_hint: Optional[str]
    is_async: bool = False

class DjangoView(PythonFunction):
    """Django view - extends PythonFunction with view-specific fields."""
    rendered_templates: List[str]
    context_data_keys: List[str]
    models_queried: List[str]
    # Inherits: name, params, decorators, return_type_hint, is_async

class CeleryTask(PythonFunction):
    """Celery task - extends PythonFunction with task-specific fields."""
    task_options: Dict[str, Any]
    uses_retry: bool
    # Inherits: name, params, decorators, return_type_hint, is_async
```

**Benefits**:
- **DRY**: Common fields defined once
- **Type consistency**: All function-like models have same base structure
- **Extensibility**: Easy to add new function subtypes

---

### 3. `ForwardRef` Resolution

**Purpose**: Handle circular dependencies between models

**Example**:
Problem: `APIContractField` can contain nested `APIContractField` (circular!)
```python
APIContractFieldRef = ForwardRef('APIContractField')

class APIContractField(BaseModel):
    name: str
    type: str
    # Self-reference for nested objects
    properties: Optional[Dict[str, APIContractFieldRef]] = None
    items: Optional[APIContractFieldRef] = None # For arrays

# CRITICAL: Must rebuild after definition
APIContractField.model_rebuild()
```

**Without `model_rebuild()`**: Pydantic doesn't know what `APIContractFieldRef` points to → validation fails

---

### 4. Enum-Based State Management

**Purpose**: Prevent typos in feature status strings

**Without Enum**:
```python
feature.status = "completedd" # Typo! But valid string
if feature.status == "completed":
    # Never triggers! 💀
```

**With Enum**:
```python
class FeatureStatusEnum(str, Enum):
    IDENTIFIED = "identified"
    PLANNED = "planned"
    IMPLEMENTING = "implementing"
    MERGED = "merged"

feature.status = FeatureStatusEnum.COMPLETEDD # ❌ AttributeError!
feature.status = "completedd" # ❌ ValidationError!
feature.status = FeatureStatusEnum.MERGED # ✅ Valid

if feature.status == FeatureStatusEnum.MERGED:
    # Works! ✅
```

---

### 5. JSON Serialization

**Purpose**: Convert Pydantic models to JSON for storage

**Example**:
```python
# Create model
state = ProjectState(
    project_name="my_blog",
    framework="django",
    root_path="/home/user/project",
    registered_apps={"blog", "accounts"}, # Set (not JSON-serializable!)
    features=[...]
)

# Serialize to dict (handles sets, dates, Enums)
state_dict = state.model_dump(mode='json')
# registered_apps: {"blog", "accounts"} → ["blog", "accounts"]

# Save to JSON
with open("project_state.json", "w") as f:
    json.dump(state_dict, f, indent=2)

# Load from JSON
with open("project_state.json", "r") as f:
    state_dict = json.load(f)

# Deserialize back to model
loaded_state = ProjectState.model_validate(state_dict)
# registered_apps: ["blog", "accounts"] → {"blog", "accounts"} (set)
```

---

## 📊 Model Statistics

| Category | Model Count | Purpose |
|----------|-------------|---------|
| **High-Level** | 5 | ProjectState, ProjectFeature, FeatureTask, ProjectStructureMap, APIContract |
| **Generic Python** | 10 | PythonFunction, PythonClass, PythonFileImport, etc. |
| **Django Core** | 25+ | DjangoModel, DjangoView, DjangoForm, DjangoSerializer, etc. |
| **Django File Aggregates** | 10+ | DjangoModelFileDetails, DjangoViewFileDetails, etc. |
| **Third-Party** | 5 | WagtailPage, DjangoCMSPlugin, GraphQLType, etc. |
| **Frontend** | 5 | TemplateFileDetails, JSFileDetails, CSSFileDetails |
| **Utility** | 5 | CommandResult, TaskExecutionResult, etc. |
| **Total** | 60+ | Complete type system for Django projects |

---

## 🧪 Testing

VebGen includes **15 comprehensive tests** for Project Models covering Pydantic validation, dependency parsing, serialization/deserialization, recursive models, and Django-specific structures.

### Run Tests

```bash
pytest src/core/tests/test_project_models.py -v
```

**Expected output:**

```text
TestFeatureTask::test_task_creation_success ✓
TestFeatureTask::test_task_creation_missing_required_fields ✓
TestFeatureTask::test_invalid_action_fails ✓
TestFeatureTask::test_dependency_validator[1.1, 1.2] ✓
TestFeatureTask::test_dependency_validator[depends_on: 2.1, 2.2] ✓
TestFeatureTask::test_dependency_validator[3.1 (Create model), 3.2] ✓
TestFeatureTask::test_dependency_validator[None] ✓
TestFeatureTask::test_dependency_validator[None-None] ✓
TestFeatureTask::test_dependency_validator[4.1, 4.2] ✓
TestFeatureTask::test_dependency_validator[5.1, invalid_id, 5.2] ✓
TestFeatureTask::test_default_test_step_validator ✓
TestProjectState::test_project_state_creation_and_get_feature ✓
TestProjectState::test_serialization_and_deserialization ✓
TestRecursiveModels::test_recursive_api_contract_field ✓
TestDjangoModels::test_django_model_creation ✓

15 passed in 0.3s
```

### Test Coverage Breakdown

| Test Class | Tests | Description |
|---|---|---|
| **TestFeatureTask** | 11 tests | Pydantic validation, dependency parsing (7 parametrized), default test steps |
| **TestProjectState** | 2 tests | State management, JSON serialization with sets |
| **TestRecursiveModels** | 1 test | ForwardRef resolution, nested APIContractField |
| **TestDjangoModels** | 1 test | Django model/field creation |
| **Total:** | **15 tests** | with 100% pass rate |

### Test Categories

#### 1. FeatureTask Validation (11 tests)

**Test: `test_task_creation_success`**
```python
def test_task_creation_success(self):
    """Verify valid FeatureTask creation"""
    task_data = {
        "task_id_str": "1.1",
        "action": "Create file",
        "target": "app/models.py",
        "description": "Create the user model.",
        "dependencies": ["1.0"]
    }
    
    task = FeatureTask(**task_data)
    
    assert task.task_id_str == "1.1"
    assert task.action == "Create file"
    assert task.dependencies == ["1.0"]
```

**Test: `test_task_creation_missing_required_fields`**
```python
def test_task_creation_missing_required_fields(self):
    """Verify Pydantic raises ValidationError for missing fields"""
    # Missing task_id_str
    with pytest.raises(ValidationError, match="task_id_str"):
        FeatureTask(action="Create file", target="a.txt")
    
    # Missing action
    with pytest.raises(ValidationError, match="action"):
        FeatureTask(task_id_str="1.1", target="a.txt")
    
    # Missing target
    with pytest.raises(ValidationError, match="target"):
        FeatureTask(task_id_str="1.1", action="Create file")
```

**Test: `test_invalid_action_fails`**
```python
def test_invalid_action_fails(self):
    """Verify actions not in Literal type raise ValidationError"""
    with pytest.raises(ValidationError, match="Input should be .* 'Delete file'"):
        FeatureTask(
            task_id_str="1.1",
            action="Invalid Action",  # Not in allowed actions
            target="a.txt"
        )
```
**Valid actions (from `Literal`):**
```python
"Create file"
"Update file"
"Delete file"
"Run command"
"Prompt user input"
"Wait for confirmation"
```

**Test: `test_dependency_validator` (7 parametrized variations)**
```python
@pytest.mark.parametrize("dep_input, expected_output", [
    ("1.1, 1.2", ["1.1", "1.2"]),                           # Comma-separated string
    ("depends_on: 2.1, 2.2", ["2.1", "2.2"]),              # With prefix
    ("3.1 (Create model), 3.2", ["3.1", "3.2"]),           # With descriptions
    ("None", []),                                           # String "None"
    (None, []),                                             # Actual None
    ([4.1, "4.2"], ["4.1", "4.2"]),                        # Mixed list
    (["5.1", "invalid_id", "5.2"], ["5.1", "5.2"]),       # Filters invalid IDs
])
def test_dependency_validator(self, dep_input, expected_output):
    """Verify dependency parser handles multiple formats"""
    task = FeatureTask(
        task_id_str="10.1",
        action="Create file",
        target="a.txt",
        dependencies=dep_input
    )
    
    assert task.dependencies == expected_output
```
**Dependency parsing logic:**
- String input → Split by commas, extract IDs
- List input → Validate each ID format
- `None` input → Empty list
- Invalid IDs → Filtered out (must match pattern `\d+\.\d+`)

**Test: `test_default_test_step_validator`**
```python
def test_default_test_step_validator(self):
    """Verify automatic default test step injection"""
    # No test_step provided → Default added
    task1 = FeatureTask(task_id_str="1.1", action="Create file", target="a.txt")
    assert task1.test_step == 'echo "Default test step - Check manually"'
    
    # Explicit test_step → Kept as-is
    task2 = FeatureTask(
        task_id_str="1.2",
        action="Run command",
        target="python manage.py check",
        test_step="python manage.py check"
    )
    assert task2.test_step == "python manage.py check"
    
    # 'Prompt user input' action → No default test_step
    task3 = FeatureTask(task_id_str="1.3", action="Prompt user input", target="API_KEY")
    assert task3.test_step is None
```
**Default test step logic:**
- Most actions → `'echo "Default test step - Check manually"'`
- `"Prompt user input"` → `None` (no test step)
- Explicit `test_step` → Use provided value

#### 2. ProjectState Management (2 tests)

**Test: `test_project_state_creation_and_get_feature`**
```python
def test_project_state_creation_and_get_feature(self):
    """Verify ProjectState helper method for feature lookup"""
    feature1 = ProjectFeature(id="feat_1", name="Feature One", description="First feature")
    feature2 = ProjectFeature(id="feat_2", name="Feature Two", description="Second feature")
    
    state = ProjectState(
        project_name="test_proj",
        framework="django",
        root_path="/fake/path",
        features=[feature1, feature2],
        current_feature_id="feat_1"
    )
    
    # Test get_feature_by_id helper
    assert state.get_feature_by_id("feat_1") == feature1
    assert state.get_feature_by_id("feat_2") is not None
    assert state.get_feature_by_id("non_existent") is None
```

**Test: `test_serialization_and_deserialization`**
```python
def test_serialization_and_deserialization(self):
    """Verify JSON serialization handles sets correctly"""
    state = ProjectState(
        project_name="test_proj",
        framework="django",
        root_path="/fake/path",
        registered_apps={"app1", "app2"}  # Python set
    )
    
    # Serialize: set → list (JSON compatible)
    state_dict = state.model_dump(mode='json')
    assert isinstance(state_dict["registered_apps"], list)
    
    # Simulate JSON round-trip
    json_str = json.dumps(state_dict)
    loaded_dict = json.loads(json_str)
    
    # Deserialize: list → set (Pydantic validation)
    loaded_state = ProjectState.model_validate(loaded_dict)
    assert isinstance(loaded_state.registered_apps, set)
    assert loaded_state.registered_apps == {"app1", "app2"}
```
**Set handling workflow:**
```text
Python set → model_dump(mode='json') → JSON list
JSON list → model_validate() → Python set
```

#### 3. Recursive Models (1 test)

**Test: `test_recursive_api_contract_field`**
```python
def test_recursive_api_contract_field(self):
    """Verify ForwardRef resolution for nested APIContractField"""
    nested_field_data = {
        "name": "user",
        "type": "object",
        "properties": {
            "id": {"name": "id", "type": "integer"},
            "name": {"name": "name", "type": "string"}
        }
    }
    
    field = APIContractField(**nested_field_data)
    
    # Verify nested structure
    assert isinstance(field.properties, dict)
    assert isinstance(field.properties["id"], APIContractField)
    assert field.properties["id"].type == "integer"
```
**Nested field structure:**
```json
{
  "name": "user",
  "type": "object",
  "properties": {
    "id": {"name": "id", "type": "integer"},
    "name": {"name": "name", "type": "string"}
  }
}
```
**`ForwardRef` usage:**
```python
class APIContractField(BaseModel):
    name: str
    type: str
    properties: Optional[Dict[str, 'APIContractField']] = None  # Self-reference
```

#### 4. Django-Specific Models (1 test)

**Test: `test_django_model_creation`**
```python
def test_django_model_creation(self):
    """Verify Django model/field instantiation"""
    field = DjangoModelField(
        name="title",
        field_type="CharField",
        max_length=200
    )
    
    model = DjangoModel(
        name="Post",
        bases=["models.Model"],
        django_fields=[field],
        meta_options={"ordering": ["-created_at"]}
    )
    
    assert model.name == "Post"
    assert model.django_fields[0].name == "title"
    assert model.meta_options["ordering"] == ["-created_at"]
```
**Django model structure:**
```python
DjangoModel(
    name="Post",
    bases=["models.Model"],
    django_fields=[
        DjangoModelField(name="title", field_type="CharField", max_length=200),
        DjangoModelField(name="created_at", field_type="DateTimeField", auto_now_add=True)
    ],
    meta_options={"ordering": ["-created_at"]}
)
```

### Example: Complete FeatureTask Validation

```python
# ✅ Valid task
task = FeatureTask(
    task_id_str="1.1",
    action="Create file",
    target="blog/models.py",
    dependencies=["1.0"]  # Valid hierarchical ID
)
assert task.dependencies == ["1.0"]

# ❌ Invalid task (action not in Literal)
with pytest.raises(ValidationError):
    FeatureTask(
        task_id_str="1.1",
        action="Invalid action",  # Not in allowed actions
        target="blog/models.py"
    )
```

### Example: Django Model Field with Relations

```python
field = DjangoModelField(
    name="author",
    field_type="ForeignKey",
    related_model_name="auth.User",
    on_delete="models.CASCADE",
    related_name="posts"
)

assert field.related_model_name == "auth.User"
assert field.on_delete == "models.CASCADE"
```

### Running Specific Test Categories

Test `FeatureTask` only:
```bash
pytest src/core/tests/test_project_models.py::TestFeatureTask -v
```

Test dependency parsing:
```bash
pytest src/core/tests/test_project_models.py::TestFeatureTask::test_dependency_validator -v
```

Test serialization:
```bash
pytest src/core/tests/test_project_models.py::TestProjectState::test_serialization_and_deserialization -v
```

Test Django models:
```bash
pytest src/core/tests/test_project_models.py::TestDjangoModels -v
```

### Test Summary

| Test File | Tests | Pass Rate | Coverage |
|---|---|---|---|
| `test_project_models.py` | 15 | 100% | Pydantic validation, dependency parsing, serialization, recursive models, Django structures |

All 15 tests pass consistently, ensuring bulletproof data model validation! ✅

### Key Features Validated

✅ **Pydantic Validation** - Required fields, `Literal` types, `ValidationError` raising  
✅ **Dependency Parsing** - 7 input formats (strings, lists, `None`, mixed types)  
✅ **Default Test Steps** - Auto-injection logic, action-specific rules  
✅ **JSON Serialization** - `set` ↔ `list` conversion for JSON compatibility  
✅ **ForwardRef Resolution** - Self-referencing models (`APIContractField`)  
✅ **Django Models** - Field validation, meta options, relationships

---

## 🐛 Common Issues

### Issue 1: "ValidationError: Field required"

**Cause**: Missing required field when creating model

**Solution**: Check field definition in model
```python
class FeatureTask(BaseModel):
    task_id_str: str # Required!
    action: Literal[...] # Required!
    target: str # Required!

# ❌ Missing required fields
task = FeatureTask(description="Some task") # ValidationError!

# ✅ All required fields provided
task = FeatureTask(
    task_id_str="1.1",
    action="Create file",
    target="models.py"
)
```

---

### Issue 2: "TypeError: Object of type set is not JSON serializable"

**Cause**: Trying to JSON-serialize a set directly

**Solution**: Use `model_dump(mode='json')`
```python
# ❌ Wrong
json.dumps(state) # TypeError on registered_apps (set)

# ✅ Correct
json.dumps(state.model_dump(mode='json')) # Sets → lists
```

---

### Issue 3: "NameError: name 'APIContract' is not defined"

**Cause**: Forward reference not resolved

**Solution**: Call `model_rebuild()` after definition
```python
class ProjectState(BaseModel):
    api_contracts: List['APIContract'] # ForwardRef

# Define APIContract AFTER ProjectState
class APIContract(BaseModel):
    ...

# CRITICAL: Rebuild ProjectState to resolve ForwardRef
ProjectState.model_rebuild()
```

---

## ✅ Best Practices

### For Users

1. **No direct interaction** - Models used internally by VebGen
2. **Trust validation** - If Pydantic raises `ValidationError`, data is malformed

### For Developers

1. **Always use Pydantic models** - Never use raw dicts for project data
2. **Use `model_dump(mode='json')`** for serialization - Handles sets, Enums, dates
3. **Add validators for complex logic** - Enforce business rules at model level
4. **Inherit from existing models** - Reuse common fields (DRY)
5. **Use Enums for finite states** - Prevents typos (e.g., `FeatureStatusEnum`)
6. **Call `model_rebuild()`** after `ForwardRef` definitions
7. **Document new fields** - Use `Field(description="...")` for clarity
8. **Test validation logic** - Write unit tests for custom validators
9. **Keep models immutable** - Use `model_copy(update={...})` instead of direct modification
10. **Version schema** - Increment `schema_version` when making breaking changes

---

## 🌟 Summary

**`project_models.py`** is VebGen's **complete type system**:

✅ **35 KB of Pydantic schemas** (60+ models)  
✅ **Type-safe** (runtime validation prevents bad data)  
✅ **Self-documenting** (field names + descriptions = inline docs)  
✅ **Serializable** (converts to/from JSON seamlessly)  
✅ **Extensible** (easy to add new fields/models)  
✅ **Framework-complete** (Django, DRF, Wagtail, django-cms, Celery, Channels, GraphQL)  
✅ **Inheritance hierarchy** (DRY via model inheritance)  
✅ **Enum-based states** (prevents typos in feature status)  
✅ **Custom validators** (enforce business rules)  
✅ **ForwardRef support** (handles circular dependencies)  

**This is VebGen's data DNA—the blueprint for every piece of information the system stores and manipulates.**

---

<div align="center">

**Want to add a new model?** Inherit from `BaseModel` and add fields!

**Questions?** Check the main README or memory_manager.py documentation

</div>