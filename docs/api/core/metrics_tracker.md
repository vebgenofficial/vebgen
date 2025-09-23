<a id="core.metrics_tracker"></a>

# core.metrics\_tracker

<a id="core.metrics_tracker.MetricsTracker"></a>

## MetricsTracker Objects

```python
class MetricsTracker()
```

Provides a structured way to log key events during the self-healing process.

This class is designed to record remediation metrics to a JSONL (JSON Lines)
file. Each log entry is a self-contained JSON object on a new line, making
it easy to parse and analyze the agent's performance over time.

<a id="core.metrics_tracker.MetricsTracker.__init__"></a>

#### \_\_init\_\_

```python
def __init__(log_file_path: str)
```

Initializes the MetricsTracker with a path to the log file.

**Arguments**:

- `log_file_path` - The path to the file where remediation metrics
  will be logged (e.g., 'remediation_metrics.jsonl').

<a id="core.metrics_tracker.MetricsTracker.log_remediation_event"></a>

#### log\_remediation\_event

```python
def log_remediation_event(event_data: dict)
```

Logs a remediation event to the specified log file.

This method takes a dictionary of event data, adds a standardized UTC
timestamp, and appends the resulting JSON object as a new line to the
log file.

**Arguments**:

- `event_data` - A dictionary containing the data for the remediation
  event (e.g., error details, proposed patch, outcome).

