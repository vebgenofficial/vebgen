import difflib
import os


class PatchGenerator:
    """
    Generates a diff patch using Python's standard difflib library, ensuring
    compatibility with the patch application logic.
    """

    @staticmethod
    def _normalize_text_for_diff(text: str) -> str:
        """
        Normalizes text content for diffing.
        Handles line endings and strips trailing whitespace from each line.
        """
        if not isinstance(text, str):
            # Return an empty string for non-string inputs to avoid errors.
            if text is not None:
                text = str(text)
            return ""
        # Standardize all line endings (CRLF, CR) to LF for consistent processing.
        lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')

        # Remove any trailing whitespace from each line to prevent meaningless diffs.
        normalized_lines = [line.rstrip() for line in lines]
        # Re-join the lines and ensure the text ends with a single newline, a POSIX standard.
        return "\n".join(normalized_lines) + "\n"

    @staticmethod
    def create_diff(original_content: str, new_content: str, file_path: str) -> str:
        """
        Compares the original and new content and returns a patch string
        in the standard unified diff format.
        """
        # First, normalize both original and new content to ensure a clean comparison.
        normalized_original = PatchGenerator._normalize_text_for_diff(original_content)
        normalized_new = PatchGenerator._normalize_text_for_diff(new_content)

        if normalized_original == normalized_new:
            return ""

        from_file = to_file = os.path.normpath(file_path).replace('\\', '/')

        diff = difflib.unified_diff(
            normalized_original.splitlines(keepends=True),
            normalized_new.splitlines(keepends=True),
            fromfile=from_file,
            tofile=to_file,
        )

        return "".join(diff)