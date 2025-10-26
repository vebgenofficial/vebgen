# 📘 adaptive_agent.py - Complete Documentation

## 🎯 Overview

**File**: `backend/src/core/adaptive_agent.py`  
**Purpose**: The core execution engine for VebGen's autonomous development system

> **📌 Documentation Version**: v0.3.0  
> **🆕 Major Changes**: Frontend validation suite, Patch escalation strategy, 6 state persistence bug fixes, Enhanced file tracking

---

This file implements the **dual-agent architecture** that powers VebGen:
1. **TARS** (The Architect & QA Lead) - Plans features and verifies quality
2. **CASE** (The Developer) - Implements features step-by-step autonomously

Think of this as the "brain" of VebGen—where AI agents make decisions, write code, fix errors, and ensure quality without human intervention.

---

## 🧠 For Users: What This File Does

### The Two AI Agents

#### **TARS (Planning Agent)** 🏗️
**Role**: Senior architect and quality inspector

**What TARS Does**:
- Reads your project request (e.g., "Build a blog with user authentication")
- Breaks it down into 2-50+ specific features depending on complexity
- After CASE builds each feature, TARS reviews the work
- Assigns a **completion score** (0-100%) to each feature
- If incomplete, creates a **correction plan** with specific fix instructions

**Example**:
User Request: "Add user authentication to my Django app"

TARS Creates:
- Create User model with email/password fields
- Set up Django authentication middleware
- Create login/logout views
- Add registration form with validation
- Write tests for auth flow

---

#### **CASE (Execution Agent)** 👨‍💻
**Role**: Hands-on developer that implements features

**What CASE Does**:
- Takes one feature from TARS's list
- Works step-by-step (max 15 actions per feature)
- Has 9 actions available (write files, patch code, run commands, etc.)
- **Automatically fixes mistakes** using rollback and retry
- Asks TARS for help when stuck (TARS_CHECKPOINT)
- Asks you for input when needed (API keys, design choices)

**Example Workflow**:
Feature: "Create User model"

CASE Actions:
1.  `GET_FULL_FILE_CONTENT(models.py)` - Load existing code
2.  `PATCH_FILE(models.py)` - Add User model class
3.  `RUN_COMMAND(python manage.py makemigrations)`
4.  `RUN_COMMAND(python manage.py migrate)`
5.  `FINISH_FEATURE`

---

## 🆕 What's New in v0.3.0

### **1. Frontend Validation Suite** (Game-Changer)

**Before v0.3.0**: CASE could finish features with broken/inaccessible frontend code  
**After v0.3.0**: Automatic quality enforcement with 100+ validation rules

```python
Automatically runs before FINISH_FEATURE
from .frontend_validator import FrontendValidator

validator = FrontendValidator(project_structure_map)
report = validator.validate()

if report.has_critical_issues():
# Blocks feature completion until fixed
raise ValidationError(f"Found {len(report.critical_issues)} issues")
```

**What Gets Validated**:
- 🔴 **Critical**: Missing alt text, CSRF tokens, focus outlines (blocks completion)
- 🟡 **Warning**: Non-optimal patterns, console.log statements (logged only)
- 🔵 **Info**: Suggestions for improvement (BEM naming, arrow functions)

**Impact**: Production-ready code from day one, WCAG 2.1 compliance built-in

---

### **2. Patch Escalation Strategy** (92% Success Rate)

**Before v0.3.0**: Could get stuck in endless PATCH retry loops  
**After v0.3.0**: Intelligent escalation to full rewrites

```python
After 3 consecutive PATCH_FILE failures on same file
if patch_failure_count >= 3:
correction = (
"⚠️ PATCH failed 3 times. Switch strategy: "
"Use GET_FULL_FILE_CONTENT + WRITE_FILE to rewrite entire file."
)
```

**Success Pattern**:
Attempt 1: PATCH (exact match) → ❌ Failed
Attempt 2: PATCH (fuzzy match) → ❌ Failed
Attempt 3: PATCH (manual retry) → ❌ Failed
Attempt 4: WRITE_FILE (full rewrite) → ✅ Success

**Impact**: Prevents wasted tokens, achieves 92% patch success rate

---

### **3. Enhanced File Tracking** (Bug Fixes)

**Before v0.3.0**: `GET_FULL_FILE_CONTENT` and `RUN_COMMAND` didn't track modified files  
**After v0.3.0**: All actions properly populate `newly_modified_files`

```python
GET_FULL_FILE_CONTENT now tracks
newly_modified_files.add(filepath)

RUN_COMMAND parses output for new files
if 'created' in command_output.lower():
newly_modified_files.add(extract_filename(line))
```

**Impact**: TARS verification sees complete file list, better remediation decisions

---

### **4. State Persistence Improvements** (6 Bugs Fixed)

**Before v0.3.0**: Several tracking functions failed to save data  
**After v0.3.0**: Comprehensive state tracking

| Bug # | Issue | Fix |
|-------|-------|-----|
| #2 | Registered apps not saved | Added `_track_registered_apps()` call |
| #3 | Defined models not saved | Added `_track_defined_models()` call |
| #5 | Historical notes not saved | Fixed save timing |
| #6 | Work history not persisted | Added explicit flush |
| #7 | File checksums missing | Added hash calculation |
| #12 | Artifact registry empty | Fixed population logic |

**Impact**: State survives restarts, better project continuity

---

### **5. Smart Auto-Fetch Enhancements** (Performance)

**Before v0.3.0**: Could load wrong files from venv, no limit on matches  
**After v0.3.0**: Intelligent filtering and safety limits

```python
def _find_project_files(self, filename: str):
# ✅ NEW: Filter out virtual environments
if 'venv' in file.parts or 'env' in file.parts:
continue
```
```python
# ✅ NEW: Skip ambiguous matches
if len(matches) > 5:
    logger.warning(f"Too many matches for {filename}")
    return []
```

**Impact**: Faster context loading, no accidental venv file reads

---

## 👨‍💻 For Developers: Technical Architecture

### File Structure

```text
adaptive_agent.py (67,225 characters)
└── +6,540 characters added in v0.3.0 (frontend validation + bug fixes)
├── TarsPlanner (Class)
│   ├── break_down_feature() - Feature breakdown logic
│   └── verify_feature_completion() - QA verification logic
│
└── AdaptiveAgent (Class - CASE)
    ├── execute_feature() - Main entry point
    ├── _execute_feature_steps() - Core execution loop
    ├── _execute_action() - Action handlers (9 types)
    ├── Error Recovery Methods
    ├── Security Validation Methods
    └── Project State Update Methods
```

---

### Key Classes

#### **1. TarsPlanner**
```python
class TarsPlanner:
    def __init__(self, agent_manager: AgentManager, tech_stack: str):
        ...
```
---

**Methods**:

**`break_down_feature(user_request: str) -&gt; List[str]`**
- Takes high-level user request
- Uses LLM with `TARS_FEATURE_BREAKDOWN_PROMPT`
- Returns list of actionable features
- Adaptive complexity: 2-5 features (simple) to 50+ (complex)

**`verify_feature_completion(feature_description, work_log, project_structure) -&gt; Tuple[int, List[str]]`**
- Reviews CASE's work log and modified code
- Uses `TARS_VERIFICATION_PROMPT` for LLM analysis
- Returns `(completion_percentage: 0-100, issues: List[str])`
- JSON response parsing with regex fallback for robustness

---

#### **2. AdaptiveAgent (CASE)**
```python
class AdaptiveAgent:
    def __init__(
        self,
        agent_manager: AgentManager,
        tech_stack: str,
        framework_rules: str,
        project_state: ProjectState,
        file_system_manager: FileSystemManager,
        command_executor: CommandExecutor,
        memory_manager: MemoryManager,
        code_intelligence_service: CodeIntelligenceService,
        show_input_prompt_cb: ShowInputPromptCallable,
        progress_callback: Callable,
        show_file_picker_cb: ShowFilePickerCallable,
        stop_event: asyncio.Event,
        request_command_execution_cb: Optional[RequestCommandExecutionCallable]
    ):
        ...
```

---

**Core Responsibilities**:
1. **Feature execution** (step-by-step loop)
2. **Action decision-making** (LLM-driven)
3. **Error recovery** (rollback, retry, circuit breaker)
4. **Context management** (token optimization)
5. **Security enforcement** (validation, sanitization)
6. **State persistence** (project tracking)

---

### Main Execution Flow

#### **Entry Point: `execute_feature()`**
```python
async def execute_feature(
    self,
    feature_description: str,
    correction_instructions: Optional[str] = None
) -> tuple[list[str], list[str]]:
```
---

**What Happens**:
1. **Smart Auto-Fetch**: Pre-loads common config files if feature needs them
   - Detects keywords: `install`, `setup`, `configure`, `add`, `middleware`, etc.
   - Pre-loads: `settings.py`, `urls.py`, `wsgi.py`, `asgi.py`
   - Skips if 5+ files with same name found (avoids context bloat)

2. **Calls `_execute_feature_steps()`**: The core execution loop

**Returns**: `(modified_files: List[str], work_history: List[str])`

---

#### **Core Loop: `_execute_feature_steps()`**
```python
async def _execute_feature_steps(
    self,
    feature_description: str,
    correction_instructions: Optional[str] = None
) -> tuple[list[str], list[str]]:
```
---

**Loop Structure** (max 15 steps):
1.  **Check Stop Signal**: Abort if the user has clicked "Stop".
2.  **Create Snapshot**: Save the current project state for potential rollback.
3.  **Build Context**: Assemble the prompt with project structure, file summaries, and work history.
4.  **Invoke Agent**: Ask CASE, "What is the single next best action?"
5.  **Parse Response**: Decode the JSON response (`{"thought": "...", "action": "..."}`).
6.  **Validate Action**: Pre-flight check to ensure the action is valid before execution (e.g., cannot `PATCH_FILE` without `FULL_CONTENT`).
7.  **Execute Action**: Run the validated action (e.g., write a file, run a command).
8.  **Update State**: Add the result to the work history and update the project state (e.g., file checksums, AST map).
9.  **Error Handling**: Check for failures and apply circuit breaker logic to prevent loops.

---

### The 9 Available Actions

#### **1. WRITE_FILE**
```json
{
    "action": "WRITE_FILE",
    "parameters": {
        "file_path": "blog/models.py",
        "content": "from django.db import models\\n\\nclass Post(models.Model):\\n title = models.CharField(max_length=200)"
    }
}
```

---
**What Happens**:
1. Security validation (checks for `eval()`, hardcoded secrets, raw SQL)
2. Placeholder replacement (e.g., `{{ API_KEY }}` → actual value)
3. Write file to disk
4. Update project state (if `models.py` or `settings.py`)
5. Update project structure map (AST parsing)

---

#### **2. PATCH_FILE**
```json
{
    "action": "PATCH_FILE",
    "parameters": {
        "file_path": "blog/views.py",
        "patch": "--- blog/views.py\\n+++ blog/views.py\\n@@ -5,0 +6,3 @@\\n+def post_detail(request, pk):\\n+ post = get_object_or_404(Post, pk=pk)\\n+ return render(request, 'blog/post_detail.html', {'post': post})"
    }
}
```

---
**What Happens**:
1. **Validation**: Checks file exists, CASE has FULL_CONTENT in context
2. Security validation on patch content
3. Apply patch (strict → fuzzy fallback if needed)
4. **UI diff view**: Sends before/after content to UI for visualization
5. Update project state if `settings.py` modified

**Validation Logic**:
```python
def _validate_patch_action(self, parameters: dict) -> tuple[bool, Optional[str]]:
    # 1. File must exist
    if not file_exists(filepath):
        return False, "Cannot PATCH non-existent file. Use WRITE_FILE first."

    # 2. Must have FULL_CONTENT (not just SUMMARY_ONLY)
    if content_type != 'FULL_CONTENT':
        return False, "Cannot PATCH - only have SUMMARY. Use GET_FULL_FILE_CONTENT first."

    return True, None
```
---

#### **3. GET_FULL_FILE_CONTENT**
```json
{
    "action": "GET_FULL_FILE_CONTENT",
    "parameters": {
        "file_path": "blog/models.py"
    }
}
```

---
**What Happens**:
1. Read file content with security validation
2. **Add line numbers** (for files ≤500 lines):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📄 FULL CONTENT: blog/models.py (42 lines)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ Line numbers (before │) are for REFERENCE ONLY

Use these in your @@ -X,Y +X,Z @@ headers

Do NOT include line numbers in diff content

1 │from django.db import models
2 │
3 │class Post(models.Model):
4 │ title = models.CharField(max_length=200)
...

---
3. Store in `context_manager` for next step
4. Mark file as `FULL_CONTENT` in availability tracking
5. Add to `modified_files` set (for TARS verification)
6. **Continue loop immediately** with new context

**Why Line Numbers?**
- Helps LLM generate accurate `@@ -X,Y +X,Z @@` headers for patches
- Reference only—not included in actual diff content

---

#### **4. RUN_COMMAND**
```json
{
    "action": "RUN_COMMAND",
    "parameters": {
        "command": "python",
        "args": ["manage.py", "makemigrations", "blog"]
    }
}
```

---
**What Happens**:
1. Reconstruct full command: `python manage.py makemigrations blog`
2. Placeholder replacement (for API keys in commands)
3. **Snapshot file system** (detect new files created by command)
4. **UI callback** (if available): Request user approval
   - Shows command preview
   - User can approve/deny
5. Execute command (via `CommandExecutor` with security validation)
6. **Detect new files**:
   ```python
   files_before = get_project_files()

   # Execute command
   files_after = get_project_files()
   new_files = files_after - files_before
   ```
---
7. Analyze new files (AST parsing, update structure map)
8. Update checksums for all new files

**Example**: `python manage.py startapp blog` creates 7 new files—all analyzed automatically

---

#### **5. REQUEST_USER_INPUT**
```json
{
    "action": "REQUEST_USER_INPUT",
    "parameters": {
        "prompt": "What should the default blog post category be?"
    }
}
```

---
**What Happens**:
1. Pause execution
2. Show UI prompt to user
3. Wait for user response
4. Sanitize and validate input
5. Return response to LLM for next step

**Use Cases**:
- Design choices (color schemes, default values)
- Missing information (API endpoints, third-party service names)
- Ambiguous requirements

---

#### **6. TARS_CHECKPOINT**
```json
{
    "action": "TARS_CHECKPOINT",
    "parameters": {
        "reason": "Stuck trying to integrate Celery. Need architectural guidance."
    }
}
```

---
**What Happens**:
1. CASE admits it's stuck
2. Sends work log + reason to **TARS**
3. TARS analyzes situation, provides guidance:
"Based on your work log, you're missing the Celery configuration in settings.py.
First, install celery with pip. Then add CELERY_BROKER_URL and CELERY_RESULT_BACKEND
to settings.py. Create a celery.py file in the project root with the Celery app instance."

---
4. Inject guidance as `correction_instructions` for next step
5. **Continue loop** with TARS's advice

**This is unique**: Other AI coding tools don't have mid-execution checkpoints

---

#### **7. ROLLBACK**
```json
{
    "action": "ROLLBACK",
    "parameters": {
        "reason": "Patch introduced syntax error. Reverting to try different approach."
    }
}
```

---
**What Happens**:
1. Increment `rollback_count`
2. **Check limit**: If `rollback_count &gt;= 3`, abort with error
3. Restore project state from `last_known_good_snapshot`
4. Inject reason as correction for next step
5. **Continue loop** from restored state

**Rollback Triggers**:
- Syntax errors after PATCH_FILE (automatic)
- Failed patch application (automatic)
- Command execution failure (manual by LLM)
- LLM decides strategy was wrong (manual)

---

#### **8. FINISH_FEATURE**
```json
{
    "action": "FINISH_FEATURE",
    "parameters": {}
}
```

---
**What Happens**:
1. **Frontend Validation** (v0.3.0 🆕):
   - Runs `FrontendValidator` to check HTML/CSS/JS quality.
   - Checks for missing alt text, CSRF tokens, and focus outlines.
   - **Blocks completion** if critical issues are found.
2. **Break out of loop** (feature complete).
3. **Return** `(modified_files, work_history)` to the workflow manager.
4. The workflow manager then calls **TARS for verification**.

---

#### **9. ABORT**
```json
{
    "action": "ABORT",
    "parameters": {
        "reason": "User requirements are contradictory. Cannot proceed."
    }
}
```

---
**What Happens**:
1. Raise `RuntimeError` with detailed reason
2. Escalate to workflow manager
3. Stop feature execution

**Use Cases**:
- Impossible requirements detected
- Security violation detected
- Project state corrupted

---

### Error Recovery System

#### **1. Circuit Breaker (Anti-Loop Protection)**

**Problem**: LLM gets stuck doing A → B → A → B forever

**Solution**: Detect repetitive action patterns

```python
# Create action signature (action + target)
if action == "PATCH_FILE":
    signature = f"PATCH_FILE:blog/models.py"

# Store last 3 signatures
recent_signatures = ["WRITE_FILE:blog/views.py", "ROLLBACK:blog/views.py"]

# Detect A -> B -> A pattern
if signature == recent_signatures[-2] and signature != recent_signatures[-1]:
    raise RuntimeError("Repetitive cycle detected!")
```

---

**Triggers**:
- Same file patched 3+ times with rollbacks in between
- A → B → A cycles detected
- 3+ consecutive failures on same action

**Result**: Abort feature with detailed failure analysis

#### **Escalation #4: Patch Exhaustion** (v0.3.0 🆕)

**Trigger**: 3 consecutive `PATCH_FILE` failures on same file

Example: Trying to patch blog/models.py
Action 1: PATCH_FILE on blog/models.py → ❌ Search block not found
Action 2: PATCH_FILE on blog/models.py → ❌ Fuzzy match failed
Action 3: PATCH_FILE on blog/models.py → ❌ Still can't apply

Circuit breaker activates
if self._should_escalate_patch_to_write('blog/models.py'):
correction = "Switch to WRITE_FILE strategy - rewrite entire file"

**Result**: 
- LLM abandons surgical edits
- Uses `GET_FULL_FILE_CONTENT` to load current state
- Writes complete corrected file with `WRITE_FILE`
- Success rate: 92%

---

#### **2. Automatic Syntax Validation**

**Problem**: LLM introduces syntax errors

**Solution**: Compile Python files after every modification

```python
# In FileSystemManager (called by PATCH_FILE)
def apply_patch(filepath, patch_content):
    # 1. Create .bak snapshot
    backup_content = read_file(filepath)

    # 2. Apply patch
    new_content = apply_unified_diff(patch_content)
    write_file(filepath, new_content)

    # 3. Validate syntax
    try:
        compile(new_content, filepath, 'exec')
    except SyntaxError:
        # 4. Automatic rollback
        write_file(filepath, backup_content)
        raise PatchApplyError("Syntax error detected. Rolled back.")
```

**This prevents broken code from ever being committed**

---

#### **3. Remediation Loop (3 Attempts)**

**Problem**: Feature fails TARS verification

**Solution**: Up to 3 retry attempts with increasingly specific corrections

```python
# In WorkflowManager
for attempt in range(1, 4):
    modified_files, work_log = await case.execute_feature(
        feature_description,
        correction_instructions=correction_from_tars
    )

    completion, issues = tars.verify_feature_completion(
        feature_description, work_log, modified_files
    )

    if completion >= 100:
        break  # Success!

    if attempt == 3:
        raise RuntimeError(f"Feature failed after 3 attempts. Issues: {issues}")

    # TARS creates more specific correction plan for retry
    correction_from_tars = f"Previous attempt was {completion}% complete. Issues: {issues}. Fix these specific problems."
```

**Each retry gets smarter** because TARS identifies exact problems

---

#### **4. Consecutive Failure Tracking**

**Problem**: Same action fails repeatedly

**Solution**: Track consecutive failures per action signature

```python
# Create unique signature for current action
current_sig = f"{action}:{params.get('file_path')}"

# Compare to last failed action
if current_sig == last_error_signature:
    consecutive_error_count += 1
else:
    consecutive_error_count = 1
    last_error_signature = current_sig

# Circuit breaker at 3 consecutive failures
if consecutive_error_count >= 3:
    raise RuntimeError(f"Action '{action}' failed 3 times in a row. Aborting.")
```

**This prevents wasting API tokens on hopeless operations**

---

### Security Features

#### **1. Pre-Execution Validation**

**All actions validated BEFORE execution**:
```python
is_valid, error = _validate_action(action, parameters)
if not is_valid:
    # Don't execute. Feed error back to LLM as correction
    correction_instructions = f"Invalid action: {error}. Choose a valid action."
    continue
```

---

#### **2. Content Security Validation**

**Checks for dangerous patterns**:
def _perform_security_validation(code_content, file_path) -&gt; tuple[bool, str]:
```python
def _perform_security_validation(code_content, file_path) -> tuple[bool, str]:
    # 1. eval() usage (code injection)
    if re.search(r'\beval\s*\(', code_content):
        return False, "Dangerous: eval() detected. Use json.loads instead."

    # 2. Hardcoded secrets
    if re.search(r'(SECRET_KEY|API_KEY).*=.*["\'].{20,}', code_content):
        return False, "Hardcoded secret detected. Use {{ PLACEHOLDER }} instead."

    # 3. Raw SQL (Django)
    if re.search(r'\.(raw|extra)\s*\(', code_content):
        return False, "SQL injection risk. Use Django ORM instead."

    # 4. XSS (templates)
    if file_path.endswith('.html') and re.search(r'\{\{.*?\|safe\}\}', code_content):
        return False, "XSS risk: |safe filter detected. Ensure proper escaping."

    return True, None
```

**This runs on EVERY file write and patch**

---

#### **3. Path Traversal Prevention**

```python
def validate_file_access(filepath: str) -> bool:
    # Block directory traversal
    if '..' in filepath or filepath.startswith('/'):
        return False

    # All file operations go through FileSystemManager's sandbox
    return True
```

**Combined with FileSystemManager's multi-layer sandbox enforcement**

---

#### **4. Input Sanitization**

```python
# User input from REQUEST_USER_INPUT
user_input = show_input_prompt("Enter value")
sanitized = sanitize_and_validate_input(user_input) # From security_utils
```

**Prevents injection attacks via user-provided values**

---

### Context Management

#### **The Content Availability System**

**Three-tier tracking**:
```python
content_availability = {
    'blog/models.py': 'FULL_CONTENT', # Has complete source with line numbers
    'blog/views.py': 'SUMMARY_ONLY', # Has AST-parsed structure only
    'blog/urls.py': 'NOT_AVAILABLE' # Not accessed yet
}
```
---
**Why This Matters**:
- Prevents LLM from hallucinating code it hasn't seen
- Optimizes token usage (don't load files until needed)
- **Enforces workflow**: Must GET_FULL_FILE_CONTENT before PATCH_FILE

#### **Smart Auto-Fetch**

**Preloads config files if feature needs them**:
```python
def _feature_needs_configuration(feature_description: str) -> bool:
    keywords = ['install', 'setup', 'configure', 'add', 'app',
                'middleware', 'database', 'url', 'route']
    return any(kw in feature_description.lower() for kw in keywords)

async def _preload_config_files(self):
    for filename in ['settings.py', 'urls.py', 'wsgi.py', 'asgi.py']:
        files = find_project_files(filename)
        for filepath in files[:5]: # Max 5 to avoid bloat
            if not already_loaded(filepath):
                content = read_file(filepath)
                context_manager.mark_full_content_loaded(filepath)
```

**This reduces the number of GET_FULL_FILE_CONTENT steps needed**

---

### Project State Tracking

#### **Real-Time State Updates**

**After every action, the system updates**:

**1. File Checksums**:
```python
file_hash = hashlib.sha256(content.encode()).hexdigest()
project_state.file_checksums[filepath] = file_hash
```
---
**Used for incremental caching—only re-parse changed files**

**2. Django Models**:
```python
async def _update_defined_models_from_content(filepath, content):
    app_name = Path(filepath).parent.name
    model_names = _extract_django_models(content) # AST parsing
    project_state.defined_models[app_name] = model_names

    # Artifact registry
    for model in model_names:
        artifact_key = f"django_model:{app_name}.{model}"
        project_state.artifact_registry[artifact_key] = {
            "type": "django_model",
            "app": app_name,
            "class_name": model,
            "defined_in": filepath
        }
```

**3. Registered Apps**:
```python
async def _update_registered_apps_from_content(filepath, content):
    # Parse settings.py for INSTALLED_APPS
    tree = ast.parse(content)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(t.id == 'INSTALLED_APPS' for t in node.targets if isinstance(t, ast.Name)):
            if isinstance(node.value, ast.List):
                for app_string_node in node.value.elts:
                    if isinstance(app_string_node, ast.Constant):
                        app_name = app_string_node.value.split('.')[0] # blog.apps.BlogConfig -> blog
                        project_state.registered_apps.add(app_name)
```

**4. Project Structure Map**:
```python
async def _update_project_structure_map(filepath):
    content = read_file(filepath)
    parsed_info = code_intelligence_service.parse_file(filepath, content)

    # Determine app vs global file
    if is_global_file(filepath):
        project_state.structure_map.global_files[filename] = parsed_info
    else:
        app_name = get_app_name(filepath)
        project_state.structure_map.apps[app_name].files[filename] = parsed_info
```
---
**This AST-parsed structure map is used for zero-token codebase reading**

**5. Historical Notes**:
```python
async def _add_historical_note(note: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_note = f"[{timestamp}] {note}"
    project_state.historical_notes.append(full_note)
    memory_manager.save_project_state(project_state)
```

**Provides audit trail for debugging**

---

### Placeholder System

#### **Secure Secret Management**

**Problem**: LLM needs API keys but shouldn't see them

**Solution**: Use placeholders that get replaced at runtime

**In Code**:
```python
# LLM writes this
OPENAI_API_KEY = "{{ OPENAI_API_KEY }}"
```

---
**At Runtime**:
```python
async def handle_placeholders_in_code(code: str) -> str:
    # Find all {{ PLACEHOLDER_NAME }}
    placeholders = re.findall(r'{{\s*([A-Z0-9_]+)\s*}}', code)

    for name in placeholders:
        # Check if it's a secret
        is_secret = "KEY" in name or "SECRET" in name or "TOKEN" in name

        # Try to retrieve from secure storage
        if is_secret:
            value = retrieve_credential(name)  # From OS keyring
        else:
            value = project_state.placeholders.get(name)

        # If not found, prompt user
        if value is None:
            value = await show_input_prompt(
                prompt=f"Enter value for {name}",
                is_password=is_secret
            )

            # Store securely
            if is_secret:
                store_credential(name, value)  # OS keyring
            else:
                project_state.placeholders[name] = value

        # Replace in code
        code = code.replace(f"{{{{ {name} }}}}", value)

    return code
```

**This prevents secrets from appearing in logs or project state files**

---

## 🔍 Advanced Features

### 1. Repeated Failure Detection

**Tracks action failures to detect patterns**:
```python
def _is_repeated_failure(new_failure: Dict) -> bool:
    recent_failures = action_failures[-6:-1] # Last 5
    target_file = new_failure['parameters'].get('file_path')

    count = 0
    for old_failure in recent_failures:
        if (old_failure['action'] == new_failure['action'] and
            old_failure['parameters'].get('file_path') == target_file):
            count += 1

    return count >= 1  # Seen before = repeated
```

**If repeated failure detected**:
```python
correction_instructions = (
    f"You have repeatedly failed action '{action}' on file '{filepath}'. "
    f"Last error: {error}. Re-evaluate your strategy. "
    f"If stuck, use TARS_CHECKPOINT to ask for help."
)
```

**This nudges the LLM to try a different approach or ask for help**

---

### 2. New File Detection After Commands

**Problem**: Commands like `startapp` create multiple files—need to analyze them

**Solution**: Diff file system before/after
```python
def get_project_files():
    excluded = {"venv", ".venv", "node_modules", ".git", "__pycache__", ".vebgen"}
    files = set()
    for path in project_root.rglob("*"):
        if path.is_file() and not any(part in excluded for part in path.parts):
            files.add(path.relative_to(project_root).as_posix())
    return files

files_before = get_project_files()

# Execute: python manage.py startapp blog
files_after = get_project_files()

new_files = files_after - files_before

# ['blog/__init__.py', 'blog/models.py', 'blog/views.py', ...]
for filepath in new_files:
    # Analyze with AST parser
    await _update_project_structure_map(filepath)
```

**All new files automatically indexed for future operations**

---

### 3. JSON Response Parsing with Fallback

**Problem**: LLM sometimes returns malformed JSON

**Solution**: Robust parsing with multiple strategies
```python
def _parse_json_response(response_text: str) -> dict | None:
    try:
        # Strategy 1: Look for JSON in markdown fence
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            # Strategy 2: Assume entire response is JSON
            json_str = response_text

        # Strategy 3: Fix common malformations (missing opening brace)
        if json_str.strip().startswith('"') and not json_str.strip().startswith('{'):
            json_str = "{" + json_str

        return json.loads(json_str)
    except json.JSONDecodeError:
        # Feed error back to LLM as correction
        return None
```

**If parsing fails, LLM gets correction instruction to fix JSON format**

---

### 4. Django Model Extraction

**Extracts model names by checking inheritance**:
```python
def _extract_django_models(file_content: str) -> List[str]:
    tree = ast.parse(file_content)
    models = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                # Check: class Post(models.Model)
                if isinstance(base, ast.Attribute) and base.attr == 'Model':
                    models.append(node.name)
                # Check: class Post(Model) [imported directly]
                elif isinstance(base, ast.Name) and base.id == 'Model':
                    models.append(node.name)

    return models
```

**Only extracts actual Django models, not helper classes**

---

## 🔧 v0.3.0 Improvements Summary

| Category | Improvement | Impact |
|----------|-------------|--------|
| **Frontend** | Added 7-validator frontend quality enforcement | WCAG 2.1 compliance, production-ready code |
| **Patching** | 5-layer SEARCH/REPLACE + escalation strategy | 92% success rate (up from ~60%) |
| **Tracking** | Fixed 6 state persistence bugs | Better project continuity across sessions |
| **Performance** | Smart auto-fetch with venv filtering | Faster context loading, no false positives |
| **Reliability** | Enhanced file tracking for all actions | Complete visibility for TARS verification |
| **Testing** | +2 tests (32 → 34), focused on new features | Comprehensive coverage of v0.3.0 additions |

**Lines of Code**: 60,685 → 67,225 characters (+10.7%)  
**Test Coverage**: Maintained at 100% for critical paths  
**Backwards Compatibility**: ✅ Full compatibility with v0.2.0 projects

---

## � Key Metrics & Limits

| Metric | Value | Reason |
|--------|-------|--------|
| **Max steps per feature** | 15 | Safety limit to prevent infinite loops |
| **Max rollbacks** | 3 | Prevents wasting tokens on hopeless features |
| **Circuit breaker threshold** | 3 consecutive failures | Detects stuck patterns early |
| **Preload file limit** | 5 per filename | Avoids excessive context bloat |
| **Line number cutoff** | 500 lines | Larger files skip line numbers to save tokens |
| **Repeated failure lookback** | Last 5 failures | Detects patterns without excessive memory |
| **Rollback count escalation** | 3 rollbacks = abort | Strategic error indicator |
| **Patch escalation threshold** | 3 failures | Auto-switches to WRITE_FILE after 3 consecutive PATCH failures |
| **Patch success rate** | 92% | 5-layer matching strategy (v0.3.0 improvement from ~60%) |
| **Frontend validation rules** | 100+ checks | Covers HTML, CSS, JS, accessibility, performance, cross-file integrity |
| **State persistence bugs fixed** | 6 (v0.3.0) | Bugs #2, #3, #5, #6, #7, #12 - all related to data tracking |

---

## 🔗 Dependencies

**External Modules**:
```python
from .agent_manager import AgentManager # LLM API communication
from .file_system_manager import FileSystemManager # File operations + patching
from .command_executor import CommandExecutor # Secure command execution
from .memory_manager import MemoryManager # State persistence
from .code_intelligence_service import CodeIntelligenceService # AST parsing
from .context_manager import ContextManager # Token optimization
from .project_models import ProjectState, FeatureTask, CommandOutput
from .secure_storage import retrieve_credential, store_credential
from .security_utils import sanitize_and_validate_input
from .exceptions import InterruptedError
from .adaptive_prompts import (
TARS_FEATURE_BREAKDOWN_PROMPT,
TARS_VERIFICATION_PROMPT,
CASE_NEXT_STEP_PROMPT,
TARS_CHECKPOINT_PROMPT,
CONTENT_AVAILABILITY_INSTRUCTIONS
)

**New in v0.3.0**:
- `FrontendValidator` - Orchestrates 7 frontend quality validators (HTML, CSS, JS, accessibility, performance, cross-file)
- `json_repair` - Library for repairing malformed JSON from LLM responses

```

**UI Callbacks** (for desktop app integration):
```python
ShowInputPromptCallable = Callable[[str, bool, Optional[str]], Optional[str]]
ShowFilePickerCallable = Callable[[str], Optional[str]]
RequestCommandExecutionCallable = Callable[[str, str, str], Awaitable[Tuple[bool, str]]]
```

---

## 🚀 Usage Example

```python
# Initialize components
agent_manager = AgentManager(api_key="...", model="gpt-4")
file_system_manager = FileSystemManager(project_root="/path/to/project")
command_executor = CommandExecutor(project_root="/path/to/project")
memory_manager = MemoryManager(project_root="/path/to/project")
code_intelligence = CodeIntelligenceService()
stop_event = asyncio.Event()

# Create TARS (planner)
tars = TarsPlanner(
    agent_manager=agent_manager,
    tech_stack="django"
)

# Create CASE (executor)
case = AdaptiveAgent(
    agent_manager=agent_manager,
    tech_stack="django",
    framework_rules="Django best practices...",
    project_state=project_state,
    file_system_manager=file_system_manager,
    command_executor=command_executor,
    memory_manager=memory_manager,
    code_intelligence_service=code_intelligence,
    show_input_prompt_cb=ui_callbacks.show_input,
    progress_callback=ui_callbacks.update_progress,
    show_file_picker_cb=ui_callbacks.show_file_picker,
    stop_event=stop_event,
    request_command_execution_cb=ui_callbacks.execute_command
)

# Break down user request
user_request = "Add user authentication with email/password to my Django blog"
features = tars.break_down_feature(user_request)

# Returns: [
#     "Create User model extending AbstractBaseUser",
#     "Set up authentication backends in settings.py",
#     "Create login/logout views with forms",
#     "Add registration view with email validation",
#     "Write authentication tests"
# ]

# Execute each feature
for feature_desc in features:
    # CASE implements the feature
    modified_files, work_log = await case.execute_feature(feature_desc)

    # TARS verifies the work
    completion, issues = tars.verify_feature_completion(
        feature_desc, work_log, modified_files
    )

    if completion < 100:
        # Retry with corrections (up to 3 attempts)
        correction = f"Issues found: {issues}"
        modified_files, work_log = await case.execute_feature(
            feature_desc,
            correction_instructions=correction
        )
```
---

## 🐛 Error Handling

### Common Errors

**1. `InterruptedError`**
```python
raise InterruptedError("Workflow stopped by user.")
```
**Cause**: User clicked Stop button  
**Handling**: Graceful shutdown, state saved

**2. `RuntimeError` (Circuit Breaker)**
```python
raise RuntimeError("Repetitive action cycle detected: PATCH_FILE -> ROLLBACK -> PATCH_FILE")
```
**Cause**: Agent stuck in loop  
**Handling**: Feature aborted, detailed failure report generated

**3. `RuntimeError` (Rollback Limit)**
```python
raise RuntimeError("Feature failed after 3 rollbacks")
```
**Cause**: Persistent strategic error  
**Handling**: Escalate to user, request manual intervention

**4. `ValueError` (Invalid Action)**
```python
raise ValueError("Cannot PATCH non-existent file: blog/models.py")
```
**Cause**: Action validation failed  
**Handling**: Error fed back to LLM as correction instruction

**5. `RuntimeError` (Command Failure)**
```python
raise RuntimeError("Command 'python manage.py migrate' failed with exit code 1")
```
**Cause**: Command execution error  
**Handling**: Stdout/stderr logged, LLM decides next action (retry or ROLLBACK)

---

## 📝 Logging

**Log Levels Used**:
- `DEBUG`: File operations, cache hits, validation details
- `INFO`: Action execution, state updates, feature progress
- `WARNING`: Recoverable errors, fallback strategies, repeated failures
- `ERROR`: Action failures, security violations, parsing errors
- `CRITICAL`: Circuit breaker triggers, escalation events

**Example Log Output**:
```log
INFO: CASE Agent: Step 3/15 for feature 'Create User model'
DEBUG: Created pre-action snapshot for potential rollback
INFO: Agent decided action: PATCH_FILE on blog/models.py
DEBUG: Security validation passed for 'blog/models.py'
INFO: Successfully patched file blog/models.py
INFO: Updated project structure map for app 'blog', file 'models.py'
DEBUG: Updated checksum for file: blog/models.py
INFO: Added historical note: [2025-10-12 16:45:23] Action: PATCH_FILE, Target: blog/models.py, Result: Successfully patched...
```
---

## 🎓 Learning Resources

**For Users**:
1. Read the main README.md for high-level overview
2. Check adaptive_prompts.py to see how TARS/CASE are instructed
3. Try simple features first (e.g., "Add a Contact page") before complex ones

**For Developers**:
1. Study `_execute_feature_steps()` to understand the core loop
2. Read workflow_manager.py to see how TARS/CASE interact
3. Check file_system_manager.py for patching logic
4. Review context_manager.py for token optimization
5. Test with `tests/test_adaptive_agent.py` (34 tests covering all scenarios)

---

## 🔬 Testing

**Run Tests**:
```sh
pytest src/core/tests/test_adaptive_agent.py -v
```
---
**Key Test Cases** (32 total):
- `test_write_file_action` - Basic file writing
- `test_patch_file_validation` - Patch pre-flight checks
- `test_get_full_file_content_action` - Context loading
- `test_rollback_action` - State restoration
- `test_circuit_breaker_repetitive_action_cycle` - Loop detection
- `test_escalation_on_three_rollbacks` - Retry limit
- `test_consecutive_failures_circuit_breaker` - Failure threshold
- `test_security_validation_eval` - Dangerous code detection
- `test_security_validation_hardcoded_secret` - Secret detection
- `test_placeholder_replacement_secret` - Secure credential handling
- `test_django_model_extraction` - AST parsing accuracy
- `test_repeated_failure_detection` - Pattern recognition

**New in v0.3.0** 🆕:
- `test_finish_feature_is_blocked_by_frontend_validation` - Validates critical frontend issues block completion
- `test_find_project_files_filters_venv` - Ensures venv directories are excluded from file searches
- `test_preload_config_files_skips_on_too_many_matches` - Safety limit for ambiguous file patterns

---

## ✅ Best Practices

**For Users**:
1. **Be specific** in feature requests (helps TARS break down accurately)
2. **Use descriptive names** (helps CASE write better code)
3. **Provide API keys upfront** (avoids mid-execution interruptions)
4. **Review TARS verification results** (catch issues early)

**For Developers**:
1. **Always validate before execution** (prevents wasting LLM calls)
2. **Log at appropriate levels** (DEBUG for details, INFO for progress)
3. **Use async/await consistently** (prevents blocking operations)
4. **Update project state immediately** (keeps context synchronized)
5. **Test error paths thoroughly** (error recovery is critical)
6. **Add security checks for new actions** (prevent vulnerabilities)

---

## 🆘 Troubleshooting

**Issue**: "Cannot PATCH non-existent file"  
**Fix**: CASE tried to patch before WRITE_FILE. This is caught by validation. LLM will receive correction instruction.

**Issue**: "Repetitive action cycle detected"  
**Fix**: Circuit breaker triggered. Check logs for A → B → A pattern. May need to adjust prompts or add TARS checkpoint.

**Issue**: "Feature failed after 3 rollbacks"  
**Fix**: Strategic error—CASE can't figure out the feature. Manual intervention needed. Check TARS verification issues for clues.

**Issue**: "Security validation failed: eval() detected"  
**Fix**: LLM wrote dangerous code. System blocked it. LLM will receive correction to use safer alternatives.

**Issue**: Agent reaches 15 steps without finishing  
**Fix**: Feature too complex—should be broken into smaller features by TARS. Check feature breakdown prompt.

---

## 🌟 Summary

**adaptive_agent.py** is the **heart** of VebGen's autonomous development system:

✅ **Dual-agent architecture** (TARS plans, CASE executes, TARS verifies)  
✅ **9 powerful actions** (write, patch, inspect, command, input, checkpoint, rollback, finish, abort)  
✅ **Multi-layer error recovery** (rollback, retry, circuit breaker)  
✅ **Production-grade security** (validation, sanitization, secrets management)  
✅ **Zero-token codebase reading** (AST-based state tracking)  
✅ **Real-time state persistence** (never lose progress)  
✅ **Intelligent context management** (content availability tracking)

**This file enables VebGen to build complete applications autonomously—from first line to deployment—without human intervention.**

---

<div align="center">

**Questions?** Check the main README or open an issue on GitHub.

**Contributing?** See CONTRIBUTING.md for guidelines.

</div>