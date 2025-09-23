import re
from typing import Dict
import logging

logger = logging.getLogger(__name__)


def extract_file_contents_from_llm_output(raw_output: str) -> Dict[str, str]:
    """
    Robustly extracts one or more file contents from a raw LLM output string.

    This function is designed to parse a string that may contain conversational
    text or markdown surrounding one or more XML-like `<file_content>` tags.
    It specifically looks for tags with a 'path' attribute and a CDATA block
    containing the file's code, making it resilient to messy LLM responses.

    Args:
        raw_output: The potentially messy string response from the LLM, which
                    may contain code blocks wrapped in <file_content> tags.

    Returns:
        A dictionary mapping each file path to its corresponding string content.
        Returns an empty dictionary if no valid tags are found.
    """
    # This regex is the core of the parser. It looks for:
    # - `<file_content\s+path="([^"]+)">`: The opening tag with a captured path attribute.
    # - `\s*<!\[CDATA\[(.*?)]]>\s*`: A CDATA block, capturing the content inside.
    #   The `(.*?)` is non-greedy to handle multiple tags correctly.
    # - `</file_content>`: The closing tag.
    # `re.DOTALL` is crucial as it allows `.` to match newline characters, which is
    # essential for capturing multi-line code within the CDATA block.
    pattern = re.compile(
        r'<file_content\s+path="([^"]+)">\s*<!\[CDATA\[(.*?)]]>\s*</file_content>',
        re.DOTALL
    )

    files: Dict[str, str] = {}
    # `finditer` is used to find all non-overlapping matches in the string.
    for match in pattern.finditer(raw_output):
        # The match object's groups correspond to the captured parts of the regex.
        path, content = match.groups()
        logger.debug(f"Extracted file from LLM output: '{path}'")
        # Strip leading/trailing whitespace from the content to clean up any
        # formatting inconsistencies from the LLM inside the CDATA block.
        files[path] = content.strip()

    return files