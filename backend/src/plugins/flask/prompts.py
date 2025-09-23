# src/plugins/flask/prompts.py
# Contains system prompts specifically tailored for the Flask framework.
import logging
from src.core.config_manager import FrameworkPrompts, ChatMessage

logger = logging.getLogger(__name__)

# --- Create the FrameworkPrompts instance ---
# This framework is not yet supported. The prompts below are placeholders.

unsupported_message = "The Flask framework is not yet supported by this version of Vebgen."

# Create placeholder ChatMessage objects
placeholder_prompt = ChatMessage(role="system", content=unsupported_message)

# --- FrameworkPrompts Instance for Flask ---
try:
    flask_prompts = FrameworkPrompts(
        system_tars_markdown_planner=placeholder_prompt,
        system_case_executor=placeholder_prompt,
        system_tars_validator=placeholder_prompt,
        system_tars_error_analyzer=placeholder_prompt,
        system_tars_feature_identifier=None,
        system_tars_debugger=None,
        system_tars_triage_engineer=None,
        system_case_code_fixer=None,
        system_tars_deep_analyzer=None,
        system_test_agent_feature_tester=None,
        system_case_remediation=None,
        system_tars_remediation_planner=None,
        system_tars_remediation_differ=None,
    )
    logger.info("Flask prompts defined as placeholders (framework not supported).")
except Exception as e:
    logger.error(f"Error creating placeholder Flask prompts: {e}")
    raise ImportError(f"Could not create placeholder Flask prompts: {e}") from e