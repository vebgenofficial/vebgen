<a id="core.workflow_manager"></a>

# core.workflow\_manager

<a id="core.workflow_manager.ProgressCallback"></a>

#### ProgressCallback

func(progress_data: Dict)

<a id="core.workflow_manager.ShowInputPromptCallable"></a>

#### ShowInputPromptCallable

func(title, is_password, prompt) -> user_input | None

<a id="core.workflow_manager.ShowFilePickerCallable"></a>

#### ShowFilePickerCallable

func(title) -> file_path | None

<a id="core.workflow_manager.ShowConfirmationDialogCallable"></a>

#### ShowConfirmationDialogCallable

func(prompt) -> True | False

<a id="core.workflow_manager.ShowUserActionPromptCallable"></a>

#### ShowUserActionPromptCallable

func(title, instructions, command) -> True | False

<a id="core.workflow_manager.RequestNetworkRetryCallable"></a>

#### RequestNetworkRetryCallable

agent_desc, error_message -> should_retry

<a id="core.workflow_manager.RequestRemediationRetryCallable"></a>

#### RequestRemediationRetryCallable

task_id, failure_reason -> should_retry

<a id="core.workflow_manager.RequestCommandExecutionCallable"></a>

#### RequestCommandExecutionCallable

async func(task_id, command, description) -> (success, output/error)

<a id="core.workflow_manager.RETRY_DELAY_SECONDS"></a>

#### RETRY\_DELAY\_SECONDS

Default delay for retries (seconds)

<a id="core.workflow_manager.MAX_PLANNING_ATTEMPTS"></a>

#### MAX\_PLANNING\_ATTEMPTS

Max attempts for Tars to generate a valid plan (including initial)

<a id="core.workflow_manager.MAX_IMPLEMENTATION_ATTEMPTS"></a>

#### MAX\_IMPLEMENTATION\_ATTEMPTS

Max attempts for Case to generate code for a single task

<a id="core.workflow_manager.MAX_REMEDIATION_ATTEMPTS_FOR_TASK"></a>

#### MAX\_REMEDIATION\_ATTEMPTS\_FOR\_TASK

Max attempts for a task to be remediated (blueprint: "Max 2 attempts")

<a id="core.workflow_manager.MAX_VALIDATION_ATTEMPTS"></a>

#### MAX\_VALIDATION\_ATTEMPTS

Max attempts to validate a task (usually test step) before failing

<a id="core.workflow_manager.LOG_PROMPT_SUMMARY_LENGTH"></a>

#### LOG\_PROMPT\_SUMMARY\_LENGTH

Max length for logging prompt summaries

<a id="core.workflow_manager.MAX_FEATURE_TEST_ATTEMPTS"></a>

#### MAX\_FEATURE\_TEST\_ATTEMPTS

Max attempts to generate and pass feature-level tests

<a id="core.workflow_manager.InterruptedError"></a>

## InterruptedError Objects

```python
class InterruptedError(Exception)
```

Custom exception for user cancellation.

<a id="core.workflow_manager.WorkflowManager"></a>

## WorkflowManager Objects

```python
class WorkflowManager()
```

Orchestrates the entire AI-driven development lifecycle from prompt to completion.

This is the central nervous system of the application. It manages the state of the
project, directs the flow of work between different AI agents (Tars for planning,
Case for coding), and handles the execution and validation of each step. It is
responsible for the main feature cycle, including planning, implementation, and remediation.
Orchestrates the AI-driven development workflow based on features, plans, and tasks.

Handles:
- Project initialization and setup.
- Feature identification and planning using Tars.
- Task execution using Case (code generation) and CommandExecutor (commands).
- Dependency management between tasks.
- Validation of tasks using test steps.
- Self-correction/remediation of failed tasks using Tars Analyzer.
- Interaction with the UI via callbacks for input, confirmation, and command execution.
- **Note:** While Hugging Face models can be added to the UI, the underlying
`AgentManager` and `LlmClient` currently only support the OpenRouter API structure
and authentication. Significant changes in `AgentManager` are required to fully
integrate direct calls to Hugging Face APIs (Inference API or local models).
- Saving and loading project state.

<a id="core.workflow_manager.WorkflowManager.initialize_project"></a>

#### initialize\_project

```python
async def initialize_project(project_root: str, framework: str,
                             initial_prompt: str, is_new_project: bool)
```

Initializes the project state for the WorkflowManager.

This involves:
1. Loading framework-specific prompts.
2. Loading existing project state from disk, if available and matching the framework.
3. If no state exists or framework mismatches:
- Creating a new project state structure.
- Performing initial framework setup (venv, requirements, startproject/npm init).
- Identifying initial features based on the user's first prompt.
- **Triggering the main feature cycle to start processing.**
4. Saving the initialized or loaded state.

**Arguments**:

- `project_root` - The absolute path to the project's root directory.
- `framework` - The name of the selected framework (e.g., "django").
- `initial_prompt` - The user's first prompt describing the project goal.
- `is_new_project` - Flag from the UI indicating if initial framework setup should run.
  

**Raises**:

- `RuntimeError` - If prompt loading or initial setup fails critically.
- `ValueError` - If required prompts are missing for the framework.

<a id="core.workflow_manager.WorkflowManager.handle_new_prompt"></a>

#### handle\_new\_prompt

```python
async def handle_new_prompt(prompt: str)
```

Handles a new user prompt received after the project has been initialized.

This typically involves:
1. Identifying new features based on the prompt.
2. Adding these features to the project state.
3. Triggering the main feature development cycle (`run_feature_cycle`).

**Arguments**:

- `prompt` - The new user prompt describing desired changes or features.
  

**Raises**:

- `RuntimeError` - If the project state is not initialized.

<a id="core.workflow_manager.WorkflowManager.sort_tasks"></a>

#### sort\_tasks

```python
def sort_tasks(feature: ProjectFeature)
```

Sorts the project's task list based on the framework-specific priority logic.

<a id="core.workflow_manager.WorkflowManager.run_feature_cycle"></a>

#### run\_feature\_cycle

```python
async def run_feature_cycle()
```

Runs the main development cycle, processing all eligible features sequentially.

This is the primary loop of the application. It selects the next feature,
plans it, implements its tasks, and handles testing and merging.

