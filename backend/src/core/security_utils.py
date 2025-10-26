# backend/src/core/security_utils.py
import re
import logging

logger = logging.getLogger(__name__)

# --- Prompt Injection Detection Patterns ---
# A list of regex patterns to detect common prompt injection/jailbreaking attempts.
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore all previous instructions", re.IGNORECASE),
    re.compile(r"you are now in developer mode", re.IGNORECASE),
    re.compile(r"act as an unfiltered model", re.IGNORECASE),
    re.compile(r"ignore the above", re.IGNORECASE),
    re.compile(r"print the instructions", re.IGNORECASE),
    re.compile(r"reveal your prompts", re.IGNORECASE),
    re.compile(r"system prompt", re.IGNORECASE),
]


def sanitize_and_validate_input(input_string: str, max_length: int = 4096) -> str:
    """
    Sanitizes and validates user-provided input to prevent prompt injection and other security risks.

    Args:
        input_string: The raw input string from the user.
        max_length: The maximum allowed length for the input string.

    Returns:
        The sanitized and validated string.

    Raises:
        ValueError: If the input is invalid, too long, or contains a potential prompt injection attempt.
    """
    if not isinstance(input_string, str):
        raise ValueError("Input must be a string.")

    # 1. Length Validation
    if len(input_string) > max_length:
        raise ValueError(f"Input length exceeds the maximum allowed limit of {max_length} characters.")

    # 2. Prompt Injection Detection
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(input_string):
            logger.warning(f"Potential prompt injection attempt detected: '{input_string[:100]}...'")
            raise ValueError("Input contains a potential prompt injection pattern and has been blocked.")

    # 3. Sanitize by removing characters that could manipulate prompt structure.
    # This removes markdown headers, list markers, and code fences.
    sanitized_string = re.sub(r"[`*#\-=\[\]{}<>!]", "", input_string)

    # 4. Normalize whitespace to prevent obfuscation
    sanitized_string = " ".join(sanitized_string.split())

    logger.debug(f"Sanitized input: '{input_string[:100]}...' -> '{sanitized_string[:100]}...'")
    return sanitized_string