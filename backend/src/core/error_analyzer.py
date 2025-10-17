# backend/src/core/error_analyzer.py
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict

from .file_system_manager import FileSystemManager
from .project_models import ErrorType, ErrorRecord

logger = logging.getLogger(__name__)


class ErrorAnalyzer:
    """
    DEPRECATED: This class is no longer used in the primary adaptive workflow.
    Error analysis is now handled by the TARS agent (LLM) in the WorkflowManager.
    This file is kept as a placeholder to prevent import errors from other
    deprecated modules (e.g., RemediationManager).
    """
    def __init__(self, project_root: Path, file_system_manager: FileSystemManager):
        logger.warning("ErrorAnalyzer is deprecated and should not be used.")
        pass

    def analyze_logs(self, command: str, stdout: str, stderr: str, exit_code: int) -> Tuple[List[ErrorRecord], Optional[Dict[str, int]]]:
        """DEPRECATED: Returns an empty result."""
        return [], None