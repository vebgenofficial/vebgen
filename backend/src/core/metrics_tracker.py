

import json
from datetime import datetime, timezone

class MetricsTracker:
    """
    Provides a structured way to log key events during the self-healing process.

    This class is designed to record remediation metrics to a JSONL (JSON Lines)
    file. Each log entry is a self-contained JSON object on a new line, making
    it easy to parse and analyze the agent's performance over time.
    """

    def __init__(self, log_file_path: str):
        """
        Initializes the MetricsTracker with a path to the log file.

        Args:
            log_file_path: The path to the file where remediation metrics
                           will be logged (e.g., 'remediation_metrics.jsonl').
        """
        self.log_file_path = log_file_path

    def log_remediation_event(self, event_data: dict):
        """
        Logs a remediation event to the specified log file.

        This method takes a dictionary of event data, adds a standardized UTC
        timestamp, and appends the resulting JSON object as a new line to the
        log file.

        Args:
            event_data: A dictionary containing the data for the remediation
                        event (e.g., error details, proposed patch, outcome).
        """
        # Add a UTC timestamp in ISO 8601 format. Using UTC is crucial to avoid
        # timezone ambiguity when analyzing logs from different systems.
        event_data['timestamp'] = datetime.now(timezone.utc).isoformat()

        # Serialize the dictionary to a JSON string.
        log_entry = json.dumps(event_data)

        # Append the JSON string as a new line. The 'a' mode opens the file for
        # appending, so existing content is not overwritten. This creates a
        # JSONL (JSON Lines) file, where each line is a valid JSON object,
        # which is efficient to read and parse line-by-line.
        with open(self.log_file_path, 'a') as f:
            f.write(log_entry + '\n')
