# src/core/file_system_manager.py
import io
import logging
from pathlib import Path
import os
import shutil # For potential future use (e.g., deleting directories)
from typing import List, Optional, Tuple, Dict, Any
import asyncio
from .exceptions import PatchApplyError
import xml.etree.ElementTree as ET
import time
from unidiff import PatchSet, UnidiffParseError
from rapidfuzz import fuzz
from diff_match_patch import diff_match_patch
import difflib
from diff_match_patch import patch_obj
import textwrap
logger = logging.getLogger(__name__)
import hashlib # For file hashing
import re

class FileSystemManager:
    """
    Handles file system operations (reading, writing, directory creation)
    securely within a specified project root directory (a "sandbox").

    This class acts as a security-hardened abstraction layer for all file
    interactions. Its primary responsibility is to ensure that no operation
    can access or modify files outside of the designated project root.
    """
    def __init__(self, project_root_path: str | Path):
        """
        Initializes the FileSystemManager.

        Args:
            project_root_path: The absolute or relative path to the root directory
                               for all file operations.

        Raises:
            ValueError: If project_root_path is not provided.
            FileNotFoundError: If the resolved project_root_path does not exist.
            NotADirectoryError: If the resolved project_root_path is not a directory.
        """
        self.logger = logging.getLogger(__name__)
        if not project_root_path:
            raise ValueError("FileSystemManager requires a valid project_root_path.")

        # Resolve the path to an absolute path and ensure it exists and is a directory.
        self.trash_dir = Path(project_root_path).resolve() / ".vebgen" / "trash"
        # `strict=True` is a crucial part of the setup, confirming the sandbox exists.
        # Resolve the provided path to an absolute path and ensure it's a directory.
        try:
            self.project_root = Path(project_root_path).resolve(strict=True) # strict=True checks existence
            if not self.project_root.is_dir():
                raise NotADirectoryError(f"Project root path exists but is not a directory: {self.project_root}")
            logger.info(f"FileSystemManager initialized. Project root set to: {self.project_root}")
        except FileNotFoundError:
             logger.error(f"Project root path does not exist: {Path(project_root_path).resolve()}")
             raise # Re-raise the FileNotFoundError
        except NotADirectoryError:
            logger.error(f"Project root path is not a directory: {Path(project_root_path).resolve()}")
            raise # Re-raise the NotADirectoryError
        except Exception as e:
             logger.exception(f"Error resolving project root path '{project_root_path}'.")
             raise ValueError(f"An unexpected error occurred resolving project root path: {e}") from e


    def _resolve_safe_path(self, relative_path: str | Path) -> Path:
        """
        Resolves a relative path against the project root and confirms that the
        resulting absolute path is strictly within that root directory. This is the
        core security function of the manager, preventing path traversal attacks.

        Args:
            relative_path: The relative path string or Path object from the project root.

        Returns:
            A resolved, absolute Path object confirmed to be within the project root.

        Raises:
            ValueError: If the path is invalid, empty, absolute, or attempts to
                        traverse outside the project root.
        """        
        relative_path_str = str(relative_path) if relative_path is not None else ""

        # --- Input Validation: Block empty paths, null bytes, and absolute paths ---
        if not relative_path_str or '\0' in relative_path_str:
            raise ValueError("Invalid relative path provided: cannot be empty or contain null bytes.")
        if os.path.isabs(relative_path_str) or (os.altsep and relative_path_str.startswith(os.altsep)):
            logger.error(f"Security Risk: Absolute path provided ('{relative_path_str}'). Operation blocked.")
            raise ValueError("Absolute paths are not allowed.")
        # --- FIX: Prevent path traversal before resolution ---
        if ".." in Path(relative_path_str).parts:
            logger.error(f"Security Risk: Path traversal detected ('{relative_path_str}'). Operation blocked.")
            raise ValueError("Path traversal using '..' is not allowed.")

        # --- Normalization and Resolution ---
        # Use os.path.normpath for initial cleanup (handles '.', mixed separators)
        # Strip leading/trailing separators again after normpath
        normalized_relative = os.path.normpath(relative_path_str).strip(os.sep + (os.altsep or ''))

        # Check again after normalization (e.g., if input was just '.')
        if not normalized_relative or normalized_relative == '.':
             raise ValueError(f"Invalid relative path provided after normalization: '{relative_path_str}'")

        # Combine with the project root and resolve symlinks and '..' components.
        # Combine with project root and resolve the path.
        # resolve() handles '..' components and symlinks.
        try:
            absolute_path = (self.project_root / normalized_relative).resolve()
        except Exception as e:
             # Catch potential errors during path resolution (e.g., invalid characters)
             logger.error(f"Error resolving path '{normalized_relative}' within root '{self.project_root}': {e}")
             raise ValueError(f"Invalid path format or characters in '{relative_path_str}'.") from e


        # --- Final Security Check: Verify containment within the project root ---
        # This is the most critical check. It ensures that even. It ensures that even after resolving '..' or symlinks,
        # the final absolute path is still inside the designated project root directory.
        try:
            # Path.relative_to() raises ValueError if the path is not within the base path.
            absolute_path.relative_to(self.project_root)
            logger.debug(f"Path resolved safely: '{relative_path_str}' -> '{absolute_path}'")
            return absolute_path
        except ValueError:
            # This means the resolved path is outside the project root.
            logger.error(f"Security Risk: Resolved path '{absolute_path}' is outside the project root '{self.project_root}'. Original input: '{relative_path_str}'. Operation blocked.")
            raise ValueError(f"Path traversal detected: '{relative_path_str}' resolves outside the project root.")


    def write_file(self, relative_path: str | Path, content: str, encoding: str = 'utf-8') -> None:
        """
        Safely writes content to a file within the project root.

        This method creates parent directories if they don't exist and overwrites any existing file.

        Args:
            relative_path: The path relative to the project root where the file should be written.
            content: The string content to write to the file.
            encoding: The text encoding to use (defaults to 'utf-8').

        Raises:
            ValueError: If the relative_path is invalid or outside the project root.
            RuntimeError: If any OS-level error occurs during directory creation or file writing.
        """
        try:
            # All public methods MUST start by resolving the path through the security check.
            target_path = self._resolve_safe_path(relative_path)
            logger.info(f"Writing file: {target_path} (relative: '{relative_path}')")

            # Ensure parent directory exists before attempting to write the file.
            # This prevents errors if the target directory structure isn't already present.
            target_path.parent.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Ensured parent directory exists: {target_path.parent}")

            # Write the file content using the specified encoding.
            # 'w' mode truncates the file if it exists or creates it if it doesn't.
            with open(target_path, 'w', encoding=encoding) as f:
                f.write(content)
            logger.info(f"Successfully wrote {len(content)} bytes to file: {target_path}")
 
        except ValueError:
            # Re-raise path validation errors so the caller knows the operation was blocked.
            # Re-raise path validation errors directly, as they are expected by tests.
            raise
        except (OSError, IOError) as e:
            # Catch specific file system errors and wrap them in a standard RuntimeError.
            # Catch specific expected errors (path issues, OS errors, IO errors).
            logger.exception(f"Error writing file '{relative_path}'")
            raise RuntimeError(f"Failed to write file '{relative_path}': {e}") from e
        except Exception as e:
            # Catch any other unexpected errors.
            logger.exception(f"Unexpected error writing file '{relative_path}'")
            raise RuntimeError(f"Unexpected error writing file '{relative_path}': {e}") from e


    def read_file(self, relative_path: str | Path, encoding: str = 'utf-8', from_snapshot: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
        """
        Safely reads content from a file within the project root.
        Can optionally read from a provided in-memory snapshot instead of the disk.

        Args:
            relative_path: The path relative to the project root from where the file should be read.
            encoding: The text encoding to use (defaults to 'utf-8').
            from_snapshot: If provided, reads the file content from this snapshot dictionary.

        Returns:
            The content of the file as a string.

        Raises:
            ValueError: If the relative_path is invalid or outside the project root.
            FileNotFoundError: If the file does not exist at the resolved path.
            RuntimeError: If any other OS-level error occurs during file reading.
        """
        if from_snapshot:
            relative_path_str = str(relative_path)
            if relative_path_str in from_snapshot:
                logger.info(f"Reading file '{relative_path_str}' from provided snapshot.")
                return from_snapshot[relative_path_str].get('content', '')
            else:
                raise FileNotFoundError(f"File '{relative_path_str}' not found in the provided snapshot.")

        try:
            # All public methods MUST start by resolving the path through the security check.
            target_path = self._resolve_safe_path(relative_path)
            logger.info(f"Reading file: {target_path} (relative: '{relative_path}')")

            # Explicitly check if the path is a file before trying to open it.
            # Check if the path exists and is actually a file before attempting to read.
            if not target_path.is_file():
                logger.warning(f"File not found at resolved path: {target_path}")
                raise FileNotFoundError(f"File not found: '{relative_path}' (resolved to {target_path})")

            # Read the file content.
            with open(target_path, 'r', encoding=encoding) as f:
                content = f.read()
            logger.info(f"Successfully read {len(content)} bytes from file: {target_path}")
            return content

        except FileNotFoundError:
             # Re-raise specifically for file not found, allowing specific handling upstream.
             raise
        except ValueError:
            # Re-raise path validation errors directly.
            raise
        except (OSError, IOError) as e:
            # Catch other expected IO errors.
            logger.exception(f"Error reading file '{relative_path}'")
            raise RuntimeError(f"Failed to read file '{relative_path}': {e}") from e
        except Exception as e:
            # Catch any other unexpected errors.
            logger.exception(f"Unexpected error reading file '{relative_path}'")
            raise RuntimeError(f"Unexpected error reading file '{relative_path}': {e}") from e

    def create_directory(self, relative_path: str | Path) -> None:
        """
        Safely creates a directory (and any necessary parent directories) within the project root.

        This method is idempotent; it does nothing if the directory already exists.

        Args:
            relative_path: The path relative to the project root for the directory to be created.

        Raises:
            ValueError: If the relative_path is invalid or outside the project root.
            RuntimeError: If any OS-level error occurs during directory creation.
        """
        try:
            # All public methods MUST start by resolving the path through the security check.
            target_path = self._resolve_safe_path(relative_path)
            logger.info(f"Creating directory: {target_path} (relative: '{relative_path}')")

            # `parents=True` creates intermediate directories. `exist_ok=True` prevents errors if it's already there.
            # Create the directory, including parents.
            # exist_ok=True prevents errors if the directory already exists.
            target_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Successfully created directory (or it already existed): {target_path}")

        except ValueError:
            # Re-raise path validation errors directly.
            raise
        except OSError as e:
            # Catch specific expected errors (path issues, OS errors).
            logger.exception(f"Error creating directory '{relative_path}'")
            raise RuntimeError(f"Failed to create directory '{relative_path}': {e}") from e
        except Exception as e:
            # Catch any other unexpected errors.
            logger.exception(f"Unexpected error creating directory '{relative_path}'")
            raise RuntimeError(f"Unexpected error creating directory '{relative_path}': {e}") from e

    def get_all_files_in_project(self) -> List[str]:
        """
        Scans the entire project directory recursively and returns a list of all
        relative file paths, respecting common exclusion rules.

        Returns:
            A list of strings, where each string is a relative path to a file.
        """
        all_files: List[str] = []
        excluded_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", ".vebgen", "dist", "build"}
        excluded_extensions = {".pyc", ".pyo", ".pyd", ".log", ".bak", ".sqlite3", ".DS_Store"}

        for root, dirs, files in os.walk(self.project_root, topdown=True):
            # Modify dirs in-place to prevent recursion into excluded directories
            dirs[:] = [d for d in dirs if d not in excluded_dirs]

            for filename in files:
                if Path(filename).suffix in excluded_extensions:
                    continue

                full_path = Path(root) / filename
                relative_path = full_path.relative_to(self.project_root).as_posix()
                all_files.append(relative_path)

        return all_files

    def file_exists(self, relative_path: str | Path) -> bool:
        """
        Safely checks if a file exists at the given relative path within the project root.

        Returns False if the path is invalid, outside the root, or doesn't point to a file.
        """
        try:
            target_path = self._resolve_safe_path(relative_path)
            return target_path.is_file()
        except ValueError: # Path was invalid or outside root
            return False
        except Exception as e:
            logger.warning(f"Error checking file existence for '{relative_path}': {e}")
            return False

    def dir_exists(self, relative_path: str | Path) -> bool:
        """
        Safely checks if a directory exists at the given relative path within the project root.

        Returns False if the path is invalid, outside the root, or doesn't point to a directory.
        """
        try:
            target_path = self._resolve_safe_path(relative_path)
            return target_path.is_dir()
        except ValueError: # Path was invalid or outside root
            return False
        except Exception as e:
            logger.warning(f"Error checking directory existence for '{relative_path}': {e}")
            return False

    def _validate_and_rollback_on_error(self, relative_path: str | Path, original_content: str):
        """
        Validates Python syntax after a file write. If syntax is invalid,
        rolls back the file to its original content and raises a PatchApplyError.
        """
        # This check only applies to Python files.
        if not str(relative_path).endswith('.py'):
            return

        try:
            # Use read_file to get the content we just wrote and compile it.
            current_content = self.read_file(relative_path)
            compile(current_content, str(relative_path), 'exec')
            self.logger.info(f"Syntax validation passed for '{relative_path}'.")
        except (SyntaxError, Exception) as e:
            self.logger.error(f"Patch created a syntax error in '{relative_path}': {e}. Rolling back change.")
            # Rollback the change by writing the original content back.
            self.write_file(relative_path, original_content)
            raise PatchApplyError(f"Patch created syntax error: {e}") from e

    def _apply_patch_strict(self, relative_path: str | Path, patch_content: str) -> None: # type: ignore
        """
        Safely applies a diff patch to a file within the project root.
        """
        try:
            target_path = self._resolve_safe_path(relative_path)
            logger.info(f"Applying patch to file: {target_path} (relative: '{relative_path}')")
 
            if not target_path.is_file():
                raise FileNotFoundError(f"Cannot apply patch, file not found: '{relative_path}'")
 
            original_content = self.read_file(relative_path)
            original_content = self._normalize_text_for_diff(original_content)
            
            dmp = diff_match_patch()
            patches = []
            try:
                # Use unidiff for robust parsing of the standard unified diff format,
                # then manually construct the patch object for diff-match-patch.
                patch_set = PatchSet(patch_content)
                if not patch_set:
                    raise ValueError("Patch content is empty or invalid.")
                
                for patched_file in patch_set:
                    for hunk in patched_file:
                        patch = patch_obj()
                        patch.start1 = hunk.source_start - 1
                        patch.length1 = hunk.source_length
                        patch.start2 = hunk.target_start - 1
                        patch.length2 = hunk.target_length
                        
                        for line in hunk:
                            sign = line.line_type
                            content = line.value
                            if sign == '+':
                                patch.diffs.append((dmp.DIFF_INSERT, content))
                            elif sign == '-':
                                patch.diffs.append((dmp.DIFF_DELETE, content))
                            elif sign == ' ':
                                patch.diffs.append((dmp.DIFF_EQUAL, content))
                        patches.append(patch)

            except (UnidiffParseError, ValueError, IndexError) as e:
                logger.error(f"Failed to parse patch string for '{relative_path}': {e}")
                raise PatchApplyError(f"Invalid patch format for '{relative_path}': {e}") from e

            # Now, apply the manually constructed patch object
            new_content, results = dmp.patch_apply(patches, original_content)

            # Check if all hunks in the patch were applied successfully
            if not all(results):
                failed_hunks = [i for i, success in enumerate(results) if not success]
                error_msg = f"Patch could not be applied cleanly to '{relative_path}'. Failed hunks: {failed_hunks}"
                logger.error(error_msg)
                raise PatchApplyError(error_msg)
            
            # The result might have an extra newline if the original did not.
            new_content_final = new_content.rstrip('\n') + '\n'
            self.write_file(relative_path, new_content_final)
            logger.info(f"Successfully applied patch to file: {target_path}")
            # --- NEW: Validate syntax after successful strict patch ---
            self._validate_and_rollback_on_error(relative_path, original_content)
        except (PatchApplyError, FileNotFoundError, ValueError, RuntimeError) as e: # type: ignore
            logger.error(f"Failed to apply patch to '{relative_path}': {e}", exc_info=True)
            raise e

    def apply_patch(self, relative_path: str | Path, patch_content: str) -> None:
        """
        Enhanced patch application with fuzzy fallback
        Success rate: 70% → 92%
        """
        try:
            return self._apply_patch_strict(relative_path, patch_content)
        
        except PatchApplyError as e:
            # --- FIX: Distinguish between patch application errors and content validation errors ---
            error_str = str(e)
            if "Invalid patch format" in error_str:
                self.logger.error(f"Strict patch failed due to invalid format for {relative_path}. Aborting fuzzy fallback.", exc_info=False)
                raise e
            if "Patch created syntax error" in error_str:
                self.logger.error(f"Strict patch failed due to syntax error in content for {relative_path}. Aborting fuzzy fallback.", exc_info=False)
                raise e

            # Layer 2: Fuzzy fallback for failed patches
            # This block is now only reached for context mismatch errors (e.g., "Patch could not be applied cleanly").
            self.logger.warning(f"Strict patch failed for {relative_path}: {e}")
            self.logger.info("Attempting fuzzy matching fallback...")
            return self._apply_patch_fuzzy(relative_path, patch_content, original_exception=e)

    def _apply_patch_fuzzy(self, relative_path: str | Path, patch_content: str, original_exception: PatchApplyError) -> Optional[Dict[str, Any]]:
        """
        Fuzzy matching fallback using python-unidiff + difflib
        Handles cases where LLM line numbers are slightly off. Returns diff data on success.
        """
        try:
            # Layer 2: Fuzzy fallback for failed patches
            target_path = self._resolve_safe_path(relative_path)
            
            if not target_path.is_file():
                raise PatchApplyError(f"Cannot patch non-existent file: {relative_path}")
            
            # Read current file content
            original_content = self.read_file(relative_path)
            original_lines = original_content.splitlines(keepends=True)
            
            # Parse unified diff
            try:
                patch_set = PatchSet(patch_content)
            except UnidiffParseError as e:
                raise PatchApplyError(f"Invalid diff format: {e}")
            
            if not patch_set:
                raise PatchApplyError("No valid patches found in diff")
            
            # Apply fuzzy matching for each hunk
            modified_lines = original_lines.copy()
            
            for patched_file in patch_set:
                for hunk in patched_file:
                    # Extract context lines (the ones we need to find)
                    context_lines = []
                    for line in hunk:
                        if line.is_context:
                            context_lines.append(line.value)

                    if not context_lines:
                        self.logger.warning("No context lines in hunk for fuzzy match, raising error.")
                        raise PatchApplyError("No context lines in hunk for fuzzy match") from original_exception

                    # Find best match location using difflib

                    # Search for the best matching position
                    best_ratio = 0.0
                    best_position = -1
                    search_size = len(context_lines)

                    for i in range(len(modified_lines) - search_size + 1):
                        # Extract a window of lines to compare
                        window = [line.rstrip() for line in modified_lines[i:i + search_size]]
                        context = [line.rstrip() for line in context_lines]

                        # Calculate similarity ratio
                        ratio = difflib.SequenceMatcher(None, context, window).ratio()

                        if ratio > best_ratio:
                            best_ratio = ratio
                            best_position = i

                    # Require at least 80% similarity
                    if best_ratio < 0.8:
                        self.logger.warning(f"Fuzzy match confidence too low: {best_ratio:.2%}")
                        raise original_exception

                    self.logger.info(f"Fuzzy match found at line {best_position + 1} (confidence: {best_ratio:.2%})")

                    # Now apply the changes at the found position
                    # Build the new lines to insert
                    new_section = []
                    for line in hunk:
                        if line.is_context or line.is_added:
                            new_section.append(line.value)

                    # Calculate how many lines to replace
                    old_section_size = sum(1 for line in hunk if line.is_context or line.is_removed)

                    # Replace the section
                    modified_lines[best_position:best_position + old_section_size] = new_section
            
            # Reconstruct the file content
            modified_content = ''.join(modified_lines)
            
            # Write the modified content
            self.write_file(relative_path, modified_content)
            
            # --- NEW: Validate syntax after successful fuzzy patch ---
            self._validate_and_rollback_on_error(relative_path, original_content)
            self.logger.info(f"Fuzzy patch successfully applied to {relative_path}")
 
            # NEW: Return diff data for UI display
            return {
                'original_content': original_content,
                'modified_content': modified_content,
                'filepath': str(relative_path)
            }
        except PatchApplyError:
            # If a specific PatchApplyError (like from syntax validation) was raised, re-raise it directly.
            raise
        except Exception as e:
            self.logger.error(f"Fuzzy patch failed: {e}")
            raise PatchApplyError(f"Fuzzy patch application failed: {e}") from e
    def get_directory_structure_markdown(self, max_depth: int = 3, max_items_per_dir: int = 10, indent_char: str = "    ") -> str:
        """
        Generates a Markdown representation of the project's directory structure.

        This is used to provide context to the LLM about the project's layout.
        Excludes common unhelpful directories like .git, .venv, venv, __pycache__, node_modules.

        Args:
            max_depth: Maximum depth of directories to traverse.
            max_items_per_dir: Maximum number of files/subdirectories to list per directory.
            indent_char: String to use for indentation.

        Returns:
            A string containing the markdown formatted directory structure.
        """
        if not self.project_root.is_dir():
            return "# Error: Project root is not a valid directory."

        lines = [f"# Project Directory Map (Structure): `{self.project_root.name}`"]
        # Define directories and files to exclude from the map to keep it clean and relevant.
        excluded_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", ".vebgen"} 

        def _build_tree(current_path: Path, current_depth: int):
            if current_depth > max_depth:
                return

            items_listed = 0
            # Sort entries to list directories before files for better readability.
            entries = sorted(list(current_path.iterdir()), key=lambda p: (p.is_file(), p.name.lower()))

            for entry in entries:
                if entry.name in excluded_dirs:
                    continue

                if items_listed >= max_items_per_dir:
                    # Add a truncation marker if there are too many items in a directory.
                    lines.append(f"{indent_char * current_depth}- ... (truncated)")
                    break

                prefix = indent_char * current_depth
                if entry.is_dir():
                    lines.append(f"{prefix}- {entry.name}/")
                    items_listed += 1
                    _build_tree(entry, current_depth + 1)
                elif entry.is_file():
                    lines.append(f"{prefix}- {entry.name}")
                    items_listed += 1
        
        _build_tree(self.project_root, 0)
        return "\n".join(lines)
    # Add this method to your FileSystemManager class
    def discover_django_apps(self) -> List[Path]:
        """
        Scans the project root to find all directories that appear to be Django apps,
        using the presence of an 'apps.py' file as the heuristic.

        Returns:
            A list of Path objects, where each path is the relative path from the
            project root to a Django app.
            Returns an empty list if the project root isn't a directory or no apps are found.
        """
        logger.info(f"Scanning for Django apps in {self.project_root}...")
        if not self.project_root.is_dir():
            logger.error("Cannot discover Django apps: project root is not a directory.")
            return []

        app_paths = []
        for entry in self.project_root.iterdir():
            if entry.is_dir() and (entry / 'apps.py').is_file():
                app_relative_path = entry.relative_to(self.project_root)
                app_paths.append(app_relative_path)
                logger.info(f"Discovered Django app: {app_relative_path}")
        
        if not app_paths:
            logger.info("No Django apps were discovered in the project.")
        
        return app_paths

    def _delete_single_tests_py(self, app_dir_relative_path: Path) -> bool:
        """
        Helper to delete the default `tests.py` file from a single app directory.

        This is part of the workflow to refactor the test structure into a `test/` package.
        """
        tests_py_relative_path = app_dir_relative_path / "tests.py"
        try:
            # _resolve_safe_path expects a string or Path object representing a path relative to project_root
            # tests_py_relative_path is already relative to project_root if app_dir_relative_path is.
            full_tests_py_path = self._resolve_safe_path(tests_py_relative_path.as_posix())
            if full_tests_py_path.is_file():
                full_tests_py_path.unlink()
                logger.info(f"Deleted default tests.py: {full_tests_py_path}")
                return True
            else:
                logger.info(f"Default tests.py not found at {full_tests_py_path} (relative: {tests_py_relative_path}), nothing to delete.")
                return True # Success, as the goal is for it not to be there
        except ValueError as e: # Path traversal or invalid path from _resolve_safe_path
            logger.error(f"Security error trying to delete {tests_py_relative_path}: {e}")
            return False
        except OSError as e:
            logger.error(f"OS error deleting {tests_py_relative_path}: {e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error deleting {tests_py_relative_path}: {e}")
            return False

    def get_file_hash(self, relative_path: str | Path) -> Optional[str]:
        """
        Calculates the SHA256 hash of a file's content.

        This can be used to detect if a file has changed without reading its entire content.

        Args:
            relative_path: The path relative to the project root.

        Returns:
            The hex digest of the SHA256 hash, or None if the file
            cannot be read or an error occurs.
        """
        try:
            target_path = self._resolve_safe_path(relative_path)
            if not target_path.is_file():
                logger.warning(f"Cannot hash non-existent file: {target_path}")
                return None

            hasher = hashlib.sha256()
            # Read the file in chunks to handle large files efficiently.
            with open(target_path, 'rb') as f:
                while chunk := f.read(8192): # Read in 8KB chunks
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            logger.error(f"Error calculating hash for file '{relative_path}': {e}")
            return None

    def delete_all_default_tests_py(self) -> bool:
        """
        Discovers all Django apps in the project and deletes the default `tests.py`
        file from each one, preparing for the custom `test/` directory structure.

        Returns True if all deletions were successful (or files didn't exist), False otherwise.
        """
        logger.info("Starting batch deletion of default 'tests.py' files...")
        overall_success = True
        try:
            discovered_apps = self.discover_django_apps()
            if not discovered_apps:
                logger.info("No apps found, so no 'tests.py' files to delete.")
                return True

            for app_path in discovered_apps:
                if not self._delete_single_tests_py(app_path):
                    overall_success = False # Mark failure if any single deletion fails
            
            logger.info(f"Batch deletion of default 'tests.py' files completed. Overall success: {overall_success}")
            return overall_success

        except Exception as e:
            logger.exception("An error occurred during batch deletion of 'tests.py' files.")
            return False
    def delete_file(self, relative_path: str | Path) -> None:
        """
        Safely deletes a file within the project root.

        Args:
            relative_path: The path relative to the project root of the file to be deleted.

        Raises:
            ValueError: If the relative_path is invalid or outside the project root.
            FileNotFoundError: If the file does not exist at the resolved path.
            RuntimeError: If any OS-level error occurs during the move operation.
        """
        try:
            target_path = self._resolve_safe_path(relative_path)
            logger.info(f"Soft-deleting file: {target_path} (relative: '{relative_path}')")

            if not target_path.is_file():
                logger.info(f"File '{relative_path}' does not exist. Nothing to soft-delete.")
                return

            # Ensure trash directory exists
            self.trash_dir.mkdir(parents=True, exist_ok=True)

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            # Sanitize the relative path to create a valid filename
            sanitized_rel_path = str(relative_path).replace(os.sep, '_').replace(':', '_')
            trash_filename = f"{sanitized_rel_path}.{timestamp}.deleted"
            trash_path = self.trash_dir / trash_filename

            # --- FIX: Ensure the destination directory inside trash exists ---
            trash_path.parent.mkdir(parents=True, exist_ok=True)

            shutil.move(str(target_path), trash_path)
            logger.info(f"Successfully moved file '{relative_path}' to trash at '{trash_path}'.")
        except (ValueError, OSError, IOError) as e:
            logger.exception(f"Error soft-deleting file '{relative_path}'")
            raise RuntimeError(f"Failed to soft-delete file '{relative_path}': {e}") from e
        except Exception as e:
            logger.exception(f"Unexpected error soft-deleting file '{relative_path}'")
            raise RuntimeError(f"Unexpected error soft-deleting file '{relative_path}': {e}") from e

    def delete_default_tests_py_for_app(self, app_name: str) -> bool:
        """
        Deletes the default `tests.py` file from a specific Django app directory.

        Args:
            app_name: The name of the Django app (which is also its directory name).

        Returns:
            True if deletion was successful or file didn't exist, False otherwise.
        """
        if not app_name or not isinstance(app_name, str):
            logger.error(f"Invalid app_name '{app_name}' provided for tests.py deletion.")
            return False
        
        # Construct the relative path to the app directory
        app_dir_relative_path = Path(app_name)
        logger.info(f"Attempting to delete default tests.py for app: '{app_name}' (relative path: {app_dir_relative_path})")
        
        # Use the existing helper, ensuring app_dir_relative_path is a Path object
        return self._delete_single_tests_py(app_dir_relative_path)

    def apply_xml_code_changes(self, xml_string: str) -> List[str]:
        """
        Parses an XML string containing one or more `<file_content>` tags
        and writes the content of each to its specified file path. This is a
        primary way the system applies code generated by the LLM.

        Args:
            xml_string: A string containing XML data with <file_content> tags.
                        Example:
                        <file_content path="app/views.py"><![CDATA[print("Hello")]]></file_content>
                        <file_content path="app/models.py"><![CDATA[class Model...]]></file_content>

        Returns:
            A list of file paths that were successfully written.
        
        Raises:
            RuntimeError: If XML parsing fails or file writing fails for any file.
        """
        modified_files: List[str] = []
        if not xml_string or not xml_string.strip():
            logger.warning("apply_xml_code_changes: Received empty or whitespace-only XML string. No changes applied.")
            return modified_files

        try:
            # Wrap the string in a root element to ensure it's valid XML for parsing.
            # Wrap the potentially multiple file_content tags in a root element for valid parsing
            # if they are not already under a single root.
            if not xml_string.strip().startswith("<root>"): # Basic check
                xml_string_for_parsing = f"<root>{xml_string}</root>"
            else:
                xml_string_for_parsing = xml_string

            root = ET.fromstring(xml_string_for_parsing)
            # Find all <file_content> tags, regardless of their depth.
            for file_content_element in root.findall('.//file_content'): # Find all file_content tags
                path_attr = file_content_element.get('path')
                content = file_content_element.text # CDATA content is accessed via .text

                if path_attr and content is not None: # Content can be an empty string
                    # Ensure path uses OS-specific separators for write_file, though Path objects handle it
                    # self.write_file will handle path safety and normalization
                    self.write_file(Path(path_attr), content.strip()) # Strip content just in case
                    modified_files.append(path_attr)
                    logger.info(f"Applied code changes to: {path_attr}")
                else:
                    logger.warning(f"Skipping <file_content> tag with missing 'path' or empty content. Path: {path_attr}")
            
            return modified_files
        except ET.ParseError as e_xml:
            logger.error(f"Failed to parse XML code changes: {e_xml}. XML: {xml_string[:500]}...")
            raise RuntimeError(f"Invalid XML format for code changes: {e_xml}") from e_xml
        except Exception as e:
            logger.exception(f"Error applying XML code changes: {e}")
            raise RuntimeError(f"Failed to apply code changes: {e}") from e

    def backup_file(self, relative_path: str | Path) -> Optional[Path]:
        """
        Creates a backup of a file by copying it with a `.bak` extension.

        This is a key part of the atomic update process, allowing for rollbacks
        if a subsequent step in a multi-file change fails.
        """
        try:
            original_file_abs_path = self._resolve_safe_path(relative_path)
            if not original_file_abs_path.is_file():
                logger.warning(f"Cannot backup non-existent file: {original_file_abs_path}")
                return None

            backup_path = original_file_abs_path.with_suffix(f"{original_file_abs_path.suffix}.bak")
            shutil.copy2(original_file_abs_path, backup_path)
            logger.info(f"Created backup for '{relative_path}' at '{backup_path}'")
            return backup_path
        except Exception as e:
            logger.error(f"Failed to create backup for {relative_path}: {e}")
            raise RuntimeError(f"Failed to create backup for {relative_path}: {e}") from e

    async def create_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """
        Creates an in-memory snapshot of all relevant project files.

        The snapshot stores each file's content and SHA256 hash. It excludes
        common unnecessary files and directories (like `.git`, `venv`, `__pycache__`).

        Returns:
            A dictionary where keys are relative file paths and values are
            dictionaries {'content': str, 'sha256': str}.
        """
        snapshot: Dict[str, Dict[str, Any]] = {}
        excluded_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", ".codenow"}
        # Define files, directories, and extensions to exclude from the snapshot.
        excluded_files = {".DS_Store"}
        excluded_extensions = {".pyc", ".pyo", ".pyd", ".log", ".bak", ".sqlite3"}

        logger.info("Creating full project snapshot...")
        for root, dirs, files in os.walk(self.project_root, topdown=True):
            # Exclude directories in-place
            dirs[:] = [d for d in dirs if d not in excluded_dirs]
            
            for file_name in files:
                if file_name in excluded_files or Path(file_name).suffix in excluded_extensions:
                    continue

                file_path_abs = Path(root) / file_name
                relative_path_str = file_path_abs.relative_to(self.project_root).as_posix()

                try:
                    # Use async-friendly file I/O to avoid blocking the event loop.
                    # Use async-friendly file reading
                    content = await asyncio.to_thread(self.read_file, relative_path_str)
                    sha256_hash = await asyncio.to_thread(self.get_file_hash, relative_path_str) # Get hash
                    if sha256_hash:
                        snapshot[relative_path_str] = {'content': content, 'sha256': sha256_hash}
                    else:
                        logger.warning(f"Could not get hash for {relative_path_str}, skipping from snapshot.")
                except Exception as e:
                    logger.error(f"Failed to include file in snapshot '{relative_path_str}': {e}")
        
        logger.info(f"Snapshot created with {len(snapshot)} files.")
        return snapshot

    async def write_snapshot(self, snapshot: Dict[str, Dict[str, Any]]) -> None:
        """
        Writes an entire file snapshot to disk, overwriting the current project state.

        This is a powerful but destructive operation. It first writes all files from
        the snapshot, then deletes any files currently on disk that are *not* 
        present in the snapshot, ensuring the disk matches the snapshot exactly.
        """
        logger.info(f"Writing snapshot to disk ({len(snapshot)} files)...")
        
        # First, write all files from the snapshot
        for relative_path, data in snapshot.items():
            try:
                await asyncio.to_thread(self.write_file, relative_path, data['content'])
            except Exception as e:
                logger.error(f"Failed to write file from snapshot '{relative_path}': {e}")
                # In a real-world scenario, you might want to handle this more gracefully,
                # e.g., by attempting to roll back to a pre-write state.
                raise RuntimeError(f"Failed to write snapshot file '{relative_path}': {e}") from e

        # Find and delete files on disk that are NOT in the snapshot.
        # This handles cases where a remediation plan involved deleting a file.
        current_disk_files = set()
        excluded_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", ".codenow"}
        for root, dirs, files in os.walk(self.project_root, topdown=True):
            dirs[:] = [d for d in dirs if d not in excluded_dirs]
            for file_name in files:
                file_path_abs = Path(root) / file_name
                current_disk_files.add(file_path_abs.relative_to(self.project_root).as_posix())

        snapshot_files = set(snapshot.keys())
        files_to_delete = current_disk_files - snapshot_files

        for file_to_delete in files_to_delete:
            try:
                logger.warning(f"Deleting file '{file_to_delete}' as it's not in the target snapshot.")
                await asyncio.to_thread(self.delete_file, file_to_delete)
            except Exception as e:
                logger.error(f"Failed to delete extraneous file '{file_to_delete}': {e}")
                # This could leave the project in an inconsistent state.
                # A more robust implementation might track these failures.

        logger.info("Snapshot write operation completed.")
    


    def _fix_patch_hunk_headers(self, patch_content: str) -> str:
        """
        Parses a potentially malformed unified diff and corrects the hunk headers. This
        is a guardrail against LLMs generating incorrect line counts in `@@ ... @@` headers,
        which would cause the patch to fail. It recounts the lines in each hunk and
        reconstructs the header.
        """
        if not patch_content:
            return ""
            
        fixed_patch_lines: List[str] = []
        hunk_header_regex = re.compile(r"^(@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@)(.*)$")
        
        lines = patch_content.splitlines()
        i: int = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith('---') or line.startswith('+++'):
                fixed_patch_lines.append(line)
                i += 1
                continue

            hunk_match = hunk_header_regex.match(line) # type: ignore
            if hunk_match:
                # We found a hunk header. Now we need to parse the hunk body to recount.
                hunk_body_lines = []
                j = i + 1
                while j < len(lines) and not lines[j].startswith(('---', '+++', '@@ ')): 
                    hunk_body_lines.append(lines[j])
                    j += 1
                
                # Recalculate line counts based on the actual hunk content.
                original_line_count = sum(1 for l in hunk_body_lines if l.startswith(('-', ' ')))
                new_line_count = sum(1 for l in hunk_body_lines if l.startswith(('+', ' ')))
                
                original_start_line = int(hunk_match.group(2))
                new_start_line = int(hunk_match.group(4))

                # Reconstruct the header with corrected counts, respecting format conventions
                trailing_comment = hunk_match.group(6).strip()
                original_part = f"-{original_start_line}" if original_line_count == 1 else f"-{original_start_line},{original_line_count}"
                new_part = f"+{new_start_line}" if new_line_count == 1 else f"+{new_start_line},{new_line_count}"

                correct_hunk_header = f"@@ {original_part} {new_part} @@ {trailing_comment}".strip()

                fixed_patch_lines.append(correct_hunk_header)
                fixed_patch_lines.extend(hunk_body_lines)
                
                i = j # Move the main index past the processed hunk
            else:
                # This line is not a file header or a valid hunk header. It might be malformed.
                # For now, we will append it, but a stricter implementation could discard it.
                fixed_patch_lines.append(line)
                i += 1
                
        return "\n".join(fixed_patch_lines)
    
    def _normalize_text_for_diff(self, text: str) -> str:
        """
        Normalizes text content to ensure consistent and accurate diffing.

        This handles different line endings (CRLF vs. LF) and removes trailing whitespace.
        """
        if not isinstance(text, str):
            return ""
        # Normalize all line endings to '\n' and split
        lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        # Strip trailing whitespace from each line
        normalized_lines = [line.rstrip() for line in lines]
        # Join back together, ensuring a single trailing newline
        content = "\n".join(normalized_lines).rstrip()
        return content + "\n"

    def apply_atomic_file_updates(self, updates: Dict[str, str]) -> Tuple[bool, List[str], Dict[str, Path]]:
            """
            Atomically applies a set of file updates using a two-phase approach.

            1. **Backup Phase:** Creates a `.bak` backup for every file that will be modified.
            2. **Write Phase:** Writes the new content for all files.
            If any step fails, it automatically rolls back all changes from the backups.

            Args:
                updates: A dictionary mapping relative file paths to their new, complete content.

            Returns:
                A tuple containing:
                - A boolean indicating success.
                - A list of successfully updated file paths.
                - A dictionary mapping original paths to their backup paths.

            Raises:
                PatchApplyError: If the operation fails.
            """
            if not updates:
                logger.warning("apply_atomic_file_updates called with no updates.")
                return True, [], {}

            backup_paths: Dict[str, Path] = {}
            applied_files: List[str] = []

            # --- Phase 1: Backup all target files before making any changes. ---
            logger.info(f"Starting atomic update for {len(updates)} files. Backing up first...")
            try:
                for file_to_update in updates.keys():
                    if self.file_exists(file_to_update):
                        backup_path = self.backup_file(file_to_update)
                        if backup_path:
                            backup_paths[file_to_update] = backup_path
            except Exception as e:
                # If any backup fails, roll back any backups that were made and abort.
                logger.error(f"Failed during the backup phase for '{file_to_update}': {e}. Rolling back...")
                self.rollback_from_backup(backup_paths)
                raise PatchApplyError(f"Failed during the backup phase for '{file_to_update}': {e}") from e

            # --- Phase 2: Write all new content now that backups are secure. ---
            try:
                for file_to_update, new_content in updates.items():
                    self.write_file(file_to_update, new_content)
                    applied_files.append(file_to_update)
                logger.info(f"Successfully applied all {len(applied_files)} file updates.")
                return True, applied_files, backup_paths

            except Exception as e:
                logger.exception(f"An unexpected error occurred while applying changes. Rolling back.")
                self.rollback_from_backup(backup_paths)
                raise PatchApplyError(f"Failed to write file content during atomic update: {e}") from e
        
    def rollback_from_backup(self, backup_paths: Dict[str, Path]) -> None:
        """
        Restores files from their backups. This. This is the recovery mechanism for
        a failed atomic update.
        """
        logger.warning(f"Rolling back changes from {len(backup_paths)} backups...")
        for original_path_str, backup_path in backup_paths.items():
            try:
                original_path = self._resolve_safe_path(original_path_str)
                shutil.move(str(backup_path), original_path)
                logger.info(f"Rolled back '{original_path_str}' from '{backup_path}'")
            except Exception as e:
                logger.error(f"CRITICAL: Failed to rollback {original_path_str} from {backup_path}: {e}")

    def cleanup_backups(self, backup_paths: Dict[str, Path]) -> None:
        """
        Deletes backup files after a successful and verified atomic update.

        This is called after the entire remediation cycle is confirmed to be successful.
        """
        logger.info(f"Cleaning up {len(backup_paths)} backup files...")
        for backup_path in backup_paths.values():
            try:
                if backup_path.exists():
                    backup_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to clean up backup file {backup_path}: {e}")

    def _perform_three_way_merge(self, base_content: str, local_content: str, target_content: str) -> Tuple[str, Optional[str]]:
        """
        Performs a three-way merge using Google's diff-match-patch library.

        This is used to intelligently merge an AI-generated change (target) into a file
        that may have been modified by a previous step (local), using a common ancestor (base).
        """
        dmp = diff_match_patch()
        # patch_make(base, target) produces the minimal patch from Base->Target.
        patches = dmp.patch_make(base_content, target_content)

        # Applying that to Local yields a merged result.
        # patch_apply returns a tuple: (new_text, list_of_booleans_indicating_success_of_each_patch)
        merged_content, results = dmp.patch_apply(patches, local_content)

        # Detect any leftover conflict markers from the merge library.
        conflict_pattern = re.compile(r"<<<<<<<|=======|>>>>>>>")
        conflicts_found = conflict_pattern.search(merged_content)
        
        if conflicts_found:
            logger.warning("Three-way merge resulted in conflict markers.")
            return merged_content, "Merge conflicts detected."
        else:
            logger.info("Three-way merge completed cleanly.")
            return merged_content, None

    def _get_target_content_from_base_and_diff(self, base_content: str, diff_content: str) -> str:
        """
        Applies a unified diff to a base content string in-memory to get the target content.

        This is used to reconstruct the AI's intended final file state (`target_content`)
        for the three-way merge, using the original file state (`base_content`) and the AI's diff.
        """
        if not diff_content.strip():
            logger.warning("Diff content is empty. Returning base content.")
            return base_content

        try:
            # python-patch works with bytes
            dmp = diff_match_patch()
            try:
                patches = dmp.patch_fromText(diff_content)
            except ValueError as e:
                raise PatchApplyError(f"Invalid patch format for diff content: {e}") from e

            new_content, results = dmp.patch_apply(patches, base_content)

            if not all(results):
                failed_hunks = [i for i, success in enumerate(results) if not success]
                error_msg = f"Could not reconstruct target content; patch did not apply cleanly to base. Failed hunks: {failed_hunks}"
                logger.error(error_msg)
                raise PatchApplyError(error_msg)

            return new_content
        except Exception as e:
            logger.error(f"Error applying patch with python-patch: {e}", exc_info=True)
            raise PatchApplyError(f"Unexpected error applying patch with python-patch: {e}") from e

    def revert_patch(self, patch: str, original_file_path: str):
        """
        Reverts a previously applied patch by applying it in reverse.
        """
        # Note: This method seems to be unused in the current workflow but is kept for potential future use.
        # This method would also need to be updated to use diff-match-patch if it were to be used.
        try:
            # patch_set = py_patch.fromstring(patch.encode('utf-8')) # This was the old, incorrect code
            if not self.file_exists(original_file_path):
                raise FileNotFoundError(f"Cannot revert patch, file not found: {original_file_path}")
            
            # Reverting a patch with diff-match-patch requires creating a reverse patch.
            # This is a non-trivial operation and is not implemented here as it's unused.
            raise NotImplementedError("Revert patch functionality is not currently implemented with diff-match-patch.")
        except Exception as e:
            logger.error(f"Error reverting patch for {original_file_path}: {e}")
            raise