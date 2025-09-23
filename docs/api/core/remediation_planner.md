<a id="core.remediation_planner"></a>

# core.remediation\_planner

<a id="core.remediation_planner.RemediationPlanner"></a>

## RemediationPlanner Objects

```python
class RemediationPlanner()
```

Analyzes a list of structured errors and creates a strategic, prioritized plan
of remediation tasks to fix them.

This class acts as the "brain" of the self-healing mechanism. It uses a series
of specialized "strategic planners" to diagnose common, high-confidence error
patterns (like Django's NoReverseMatch). For errors that don't match a specific
strategy, it falls back to creating more generic fix tasks.

<a id="core.remediation_planner.RemediationPlanner.create_plan"></a>

#### create\_plan

```python
def create_plan(
        errors: List[ErrorRecord],
        project_state: ProjectState) -> Optional[List[AnyRemediationTask]]
```

Creates a strategic, multi-task remediation plan from a list of errors.

This is the main entry point for the planner. It orchestrates the process by:
1. Running a series of high-priority "strategic planners" for common, well-defined errors.
2. Bundling any remaining errors that affect the same file into a single `FixBundleTask`.
3. Creating generic, single-error tasks for any leftovers.

