# src/core/code_intelligence_service.py
from __future__ import annotations
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Literal, Set
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import ast
from collections import defaultdict
import re
import sys # Import the sys module
import json# Placeholder for AST parsing libraries (e.g., ast, esprima, etc.)
from functools import lru_cache
import html # For unescaping HTML entities
from .patch_generator import PatchGenerator
# import ast
from .project_models import (
    ProjectState, FileStructureInfo, PythonFileImport, PythonFunctionParam, PythonFunction,
    PythonClassAttribute, PythonClass, PythonFileDetails, DjangoModelField, DjangoModel,
    DjangoModelFileDetails, DjangoView, DjangoViewFileDetails, DjangoTestFileDetails, WagtailPage, DjangoCMSPlugin,
    DjangoTestClass, # New Test Class model
    DjangoURLPattern, DjangoSerializer, DjangoSerializerField, DjangoSerializerFileDetails, # New Serializer models
    DjangoMigrationDetails, DjangoMigrationOperation, # New models for migrations
    DRFRouterRegistration, DRFViewSetDetails, # New models for DRF
    DjangoSignalReceiver, DjangoSignalFileDetails, CeleryTask, CeleryTaskFileDetails, # New Signal/Celery models
    DjangoChannelsConsumer, DjangoChannelsRouting, DjangoChannelsFileDetails, # New Channels models
    GlobalURLRegistryEntry, # New models for DRF,
    GraphQLSchemaDetails, GraphQLType, GraphQLField, # New GraphQL models
    APIContractEndpoint, # Added for API Contract parsing if needed in future
    DjangoURLInclude, DjangoTemplateTag, DjangoTemplateTagFileDetails, # New TemplateTag models
    DjangoURLConfDetails, DjangoForm, DjangoFormFileDetails, DjangoAdminRegisteredModel, DjangoAdminClass,
    DjangoAdminFileDetails, DjangoSettingsDetails, TemplateFileDetails, JSFileDetails, CSSFileDetails
) 
from .project_models import CeleryBeatSchedule
# --- NEW: Import performance monitoring decorator ---
from .performance_monitor import time_function

logger = logging.getLogger(__name__)

# --- Constants for Crash Prevention ---
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_LINE_COUNT = 50000  # 50,000 lines

# Common binary file extensions to skip parsing immediately
BINARY_FILE_EXTENSIONS = {
    '.pyc', '.pyo', '.pyd', '.so', '.dll', '.exe', '.o', '.a', '.lib',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.ico', '.webp',
    '.mp3', '.wav', '.ogg', '.flac',
    '.mp4', '.avi', '.mov', '.mkv', '.webm',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.zip', '.tar', '.gz', '.rar', '.7z',
    '.db', '.sqlite3', '.dat'
}

class CodeIntelligenceService:
    """
    Provides deep code analysis by parsing source files into structured data models.

    This service acts as the agent's "code understanding" layer. It uses Abstract
    Syntax Trees (AST) to analyze Python files, giving it a grammatical understanding
    of the code's structure (classes, functions, etc.), rather than just treating it
    as text. This enables highly precise and context-aware modifications. For other
    file types, it uses heuristics and regular expressions.
    """
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        logger.info(f"CodeIntelligenceService initialized for project root: {self.project_root}")
        # --- NEW: In-memory cache for incremental parsing ---
        # Maps file_path -> (content_hash, parsed_data)
        self.in_memory_cache: Dict[str, Tuple[str, Optional[FileStructureInfo]]] = {}

    def run_static_checks(self, file_paths: List[str]) -> Tuple[bool, str]:
        """
        (Placeholder) Runs static code analysis (linting, type checking, security)
        on a list of files.
        """
        logger.info(f"Running static checks on {len(file_paths)} files (placeholder).")
        # In a real implementation, this would invoke linters (e.g., flake8, eslint),
        # type checkers (e.g., mypy, tsc), or basic security scanners.
        return True, "Static checks passed (placeholder implementation)."

    def analyze_dependencies(self, file_path_str: str) -> Dict[str, Any]:
        """
        (Placeholder) Analyzes a file to identify its dependencies (e.g., imports).
        """
        logger.debug(f"Placeholder: Analyzing dependencies for {file_path_str}")
        # In a real implementation, this would parse the file (e.g., Python AST, package.json)
        # and return structured dependency information.
        return {"path": file_path_str, "imports": ["placeholder_import1", "placeholder_import2"]}

    def get_file_summary(self, file_path_str: str, max_lines: int = 20) -> str:
        """
        Generates a brief, high-level summary of a file by reading its first few lines.
        This is a fallback for providing context when a full AST parse is not needed or fails.

        Args:
            file_path_str: The relative path to the file.
            max_lines: The maximum number of lines to include in the summary.
        Returns:
            A string containing the first `max_lines` of the file, or an error message.
        """
        try:
            full_path = (self.project_root / file_path_str).resolve()
            if not full_path.is_file():
                return "[File not found for summary]"
            
            lines_read = []
            truncated = False
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                for i, line in enumerate(f):
                    if i >= max_lines:
                        truncated = True
                        break
                    lines_read.append(line)
            summary = "".join(lines_read).strip()
            if truncated:
                summary += "\n... [truncated]"
            return summary if summary else "[File is empty]"
        except Exception as e:
            logger.warning(f"Could not get summary for {file_path_str}: {e}")
            return f"[Error getting summary: {e}]"

    @lru_cache(maxsize=128)
    def _parse_env_file(self, file_path_str: str) -> Dict[str, str]:
        """
        Parses a `.env` file to extract key-value pairs.
        Uses an LRU cache to avoid re-parsing the same file.
        """
        env_vars: Dict[str, str] = {}
        try:
            full_path = (self.project_root / file_path_str).resolve(strict=True)
            if not full_path.is_file():
                return {}
            
            content = full_path.read_text(encoding='utf-8')
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip().strip("'\"")
        except Exception as e:
            logger.warning(f"Could not parse .env file '{file_path_str}': {e}")
        return env_vars

    def _extract_function_details(self, node: ast.FunctionDef) -> PythonFunction:
        """
        Extracts structured information from a Python AST `FunctionDef` node.

        Args:
            node: The AST node representing a function definition.
        Returns:
            A Pydantic `PythonFunction` model populated with details.
        """
        params = []
        num_defaults = len(node.args.defaults)
        # Combine posonlyargs and args for full parameter list
        all_args = node.args.posonlyargs + node.args.args
        num_args = len(all_args)
        for i, arg_node in enumerate(all_args):
            param_name = arg_node.arg
            annotation_str = ast.unparse(arg_node.annotation) if arg_node.annotation else None # type: ignore
            default_value_str = None
            default_idx = i - (num_args - num_defaults)
            if default_idx >= 0:
                try:
                    default_value_str = ast.unparse(node.args.defaults[default_idx]) # type: ignore
                except Exception:
                    default_value_str = "COMPLEX_DEFAULT"
            params.append(PythonFunctionParam(name=param_name, default=default_value_str, type_hint=annotation_str))
        
        # --- NEW: Analyze function body for specific calls ---
        channel_layer_invocations = []
        for body_item in ast.walk(node):
            if isinstance(body_item, ast.Call):
                func_to_check = None
                # Direct call: channel_layer.group_send(...)
                if isinstance(body_item.func, ast.Attribute):
                    func_to_check = body_item.func
                # Wrapped call: async_to_sync(channel_layer.group_send)(...)
                elif isinstance(body_item.func, ast.Call) and isinstance(body_item.func.func, ast.Name) and body_item.func.func.id == 'async_to_sync' and body_item.func.args:
                    if isinstance(body_item.func.args[0], ast.Attribute):
                        func_to_check = body_item.func.args[0]

                if func_to_check:
                    # The check now unparses the object on which the method is called and looks for 'channel_layer'.
                    if hasattr(func_to_check, 'value') and "channel_layer" in ast.unparse(func_to_check.value) and func_to_check.attr in ["group_send", "send"]:
                        channel_layer_invocations.append(ast.unparse(body_item))
        # --- END NEW ---

        # Ensure annotation_str and default_value_str are defined before use
        decorators = [ast.unparse(d) for d in node.decorator_list]
        return_type_hint = ast.unparse(node.returns) if node.returns else None

        return PythonFunction(
            name=node.name,
            params=params,
            decorators=decorators,
            return_type_hint=return_type_hint,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            channel_layer_invocations=channel_layer_invocations
        )

    @time_function
    def _extract_class_details(self, node: ast.ClassDef) -> PythonClass:
        """
        Extracts structured information from a Python AST `ClassDef` node.

        Args:
            node: The AST node representing a class definition.
        Returns:
            A Pydantic `PythonClass` model populated with details.
        """
        bases = [ast.unparse(b) for b in node.bases]
        methods = []
        attributes = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)): # Methods
                methods.append(self._extract_function_details(item))
            elif isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name): # Simple assignments
                # Only add as generic attribute if it's not a Django model field (handled by _parse_django_model_fields)
                # This is a heuristic; a more robust solution would be to pass model_aliases here.
                # Check if the assignment is a call to an attribute of an object (e.g., models.CharField)
                if isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Attribute) and isinstance(item.value.func.value, ast.Name):
                    # If the object's name is 'models' (or an alias), assume it's a Django field and skip it here.
                    # A more robust implementation would pass the learned model_aliases to this function.
                    if item.value.func.value.id != "models":
                        try:
                            value_preview = ast.unparse(item.value)[:50]
                        except Exception:
                            value_preview = "COMPLEX_VALUE"
                        attributes.append(PythonClassAttribute(name=item.targets[0].id, value_preview=value_preview, type_hint=None))
                else:
                    try:
                        value_preview = ast.unparse(item.value)[:50]
                    except Exception:
                        value_preview = "COMPLEX_VALUE"
                    attributes.append(PythonClassAttribute(name=item.targets[0].id, value_preview=value_preview, type_hint=None))
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name): # Type-hinted assignments
                value_preview = ast.unparse(item.value) if item.value else None
                type_hint_str = ast.unparse(item.annotation) if item.annotation else None
                attributes.append(PythonClassAttribute(name=item.target.id, value_preview=value_preview, type_hint=type_hint_str))

        class_decorators = [ast.unparse(d) for d in node.decorator_list]
        
        return PythonClass(
            name=node.name,
            bases=bases,
            methods=methods,
            attributes=attributes
        )

    def _get_import_aliases(self, imports: List[PythonFileImport], target_module: str) -> List[str]:
        """
        Finds all aliases used for a specific target module (e.g., 'django.db.models').

        Args:
            imports: A list of parsed `PythonFileImport` objects for the file.
            target_module: The full module path to find aliases for.
        Returns:
            A list of alias strings. For `import django.db.models`, it returns `['models']`.
            For `from django.db import models as db_models`, it returns ['db_models'].
        """
        aliases: List[str] = []
        for imp in imports:
            # Case 1: `import django.db.models` or `import django.db.models as a`
            if imp.module == target_module:
                for name_info in imp.names:
                    # This handles `import django.db.models as db_models` -> as_name is 'db_models'
                    # and `import django.db.models` -> as_name is None, name is 'django.db.models'
                    # We want the last part of the module name if there's no alias.
                    alias = name_info.get("as_name")
                    if not alias and name_info.get("name") == target_module:
                        alias = target_module.split('.')[-1]
                    if alias:
                        aliases.append(alias)
            # Case 2: `from django.db import models` or `from django.db import models as db_models`
            elif target_module.startswith(imp.module + '.'):
                imported_name = target_module.split(imp.module + '.')[-1]
                for name_info in imp.names:
                    if name_info.get("name") == imported_name:
                        aliases.append(name_info.get("as_name") or imported_name)
        # Filter out any empty strings that might have been added
        return [alias for alias in aliases if alias]
        
    def _determine_import_type(self, module_name: str, project_apps: Optional[List[str]] = None, level: int = 0) -> Literal["stdlib", "third_party", "local_app", "project_app", "unknown"]:
        """
        Classifies a Python import using heuristics (stdlib, third-party, local).

        Args:
            module_name: The name of the module being imported.
            project_apps: A list of known Django app names in the project.

        Returns:
            A literal string classifying the import type.
        """
        # If the import level is greater than 0, it's a relative import within the app.
        if level > 0:
            return "local_app"

        if not module_name:
            return "unknown"

        # Check if the module is part of Python's standard library.
        if module_name in sys.stdlib_module_names:
            return "stdlib"

        # Check for project apps (if provided)
        if project_apps:
            # Exact match for project app
            if module_name in project_apps:
                return "project_app"
            # Relative import within the same project app structure
        # Heuristic: If it's not stdlib and not a relative import, it's likely a third-party package.
        # This part is complex and often requires knowledge of the venv.
        # A simple heuristic: if it's not stdlib and doesn't start with '.', it might be third-party.
        if not module_name.startswith(".") and module_name not in sys.stdlib_module_names:
            return "third_party" # Tentative

        return "unknown"
    @time_function
    def _parse_python_ast(self, content: str, file_path_str: str) -> Tuple[List[PythonFileImport], List[PythonFunction], List[PythonClass]]:
        """
        Parses Python file content into its core components (imports, functions, classes) using AST.

        Args:
            content: The source code of the Python file.
            file_path_str: The path to the file (used for logging).

        Returns:
            A tuple containing lists of parsed imports, functions, and classes.
        """
        # Initialize lists to hold the parsed components.
        imports = []
        functions = []
        
        classes = []        
        
        try:
            # Ensure content is a string
            # The `ast` module parses the code into a tree of nodes.
            tree = ast.parse(content, filename=file_path_str)
            # We iterate through the top-level nodes in the file's body.
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(PythonFileImport(module=alias.name, names=[{"name": alias.name, "as_name": alias.asname}]))
                elif isinstance(node, ast.ImportFrom):
                    module_name = node.module if node.module else ""
                    # Handle relative imports (e.g., `from . import models`).
                    level = node.level
                    if level > 0:
                        module_name = "." * level + module_name
                    
                    names_data = []
                    for alias in node.names:
                        names_data.append({"name": alias.name, "as_name": alias.asname})
                    # Try to classify the import type (stdlib, third-party, local).
                    # Simplified project_apps list for this context; ideally, it's passed in or discovered
                    current_project_apps = [p.name for p in self.project_root.iterdir() if p.is_dir() and (p / '__init__.py').exists()]
                    import_type = self._determine_import_type(node.module if node.module else "", project_apps=current_project_apps, level=level)
                    imports.append(PythonFileImport(module=module_name, names=names_data, level=level, type=import_type))
                elif isinstance(node, ast.FunctionDef):
                    # If it's a function, use our helper to extract its details.
                    functions.append(self._extract_function_details(node))
                elif isinstance(node, ast.ClassDef):
                    # If it's a class, use our helper to extract its details.
                    classes.append(self._extract_class_details(node))
        except SyntaxError as e:
            logger.warning(f"Syntax error parsing Python file {file_path_str}: {e}") # Corrected indentation
        except Exception as e:
            logger.error(f"Error parsing Python AST for {file_path_str}: {e}") # Corrected indentation
        return imports, functions, classes
    @time_function
    def _parse_django_model_fields(self, class_node: ast.ClassDef, model_aliases: List[str], imports: List[PythonFileImport]) -> Tuple[List[DjangoModelField], Dict[str, Any]]:
        """
        Parses Django model fields and Meta class options from an AST ClassDef node.
        This captures field types, arguments (including relationships), and `Meta` options.
        Uses a list of learned aliases for 'models'.
        """
        # This function iterates through the body of a class AST node to find
        # assignments that look like Django model fields (e.g., `title = models.CharField(...)`).
        # It also looks for an inner class named `Meta` to extract model metadata.
        model_fields = []
        # --- NEW: Add aliases for third-party model fields ---
        geodjango_aliases = self._get_import_aliases(imports, 'django.contrib.gis.db.models')
        mptt_aliases = self._get_import_aliases(imports, 'mptt.models')
        all_model_aliases = model_aliases + geodjango_aliases + mptt_aliases
        # --- END NEW ---
        meta_options = {}
        for item in class_node.body:
            if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                field_name = item.targets[0].id
                if isinstance(item.value, ast.Call) and \
                   isinstance(item.value.func, ast.Attribute) and \
                   hasattr(item.value.func, 'value') and isinstance(item.value.func.value, ast.Name) and \
                   item.value.func.value.id in all_model_aliases:
                    field_type_str = item.value.func.attr
                    field_args_dict = {}
                    related_name_val = None
                    related_model_val = None
                    on_delete_val = None
                    unique_val = None
                    db_index_val = None
                    choices_val = None

                    null_val = None
                    blank_val = None
                    default_val = None
                    max_length_val = None
 
                    relationship_fields = {"ForeignKey", "OneToOneField", "ManyToManyField"}
                    if item.value.args:
                        first_arg = item.value.args[0]
                        # If it's a relationship field, the first arg is the related model.
                        if field_type_str in relationship_fields:
                            # The first positional argument for relationship fields is the related model.
                            # It can be a string literal ('app.Model' or 'Model') or a variable name (Model).
                            related_model_val = ast.unparse(first_arg)
                        # For other fields, it's often a verbose_name.
                        else:
                            try:
                                field_args_dict['verbose_name'] = ast.literal_eval(first_arg)
                            except (ValueError, SyntaxError):
                                field_args_dict['verbose_name'] = ast.unparse(first_arg)

                        if related_model_val:
                            # Store in the generic args dict as well for completeness, using 'to' as the canonical key
                            field_args_dict['to'] = related_model_val

                    for kw_node in item.value.keywords: # Renamed kw to kw_node
                        try:
                            # For 'to' argument in ForeignKey, store as string
                            if kw_node.arg == 'to' and isinstance(kw_node.value, ast.Constant) and isinstance(kw_node.value.value, str):
                                related_model_val = kw_node.value.value
                                field_args_dict[kw_node.arg] = related_model_val
                            elif kw_node.arg == 'related_name' and isinstance(kw_node.value, ast.Constant) and isinstance(kw_node.value.value, str):
                                related_name_val = kw_node.value.value
                                field_args_dict[kw_node.arg] = related_name_val
                            elif kw_node.arg == 'on_delete' and isinstance(kw_node.value, ast.Attribute) and \
                                 hasattr(kw_node.value, 'value') and isinstance(kw_node.value.value, ast.Name) and kw_node.value.value.id in model_aliases:
                                on_delete_val = f"{kw_node.value.value.id}.{kw_node.value.attr}"
                                field_args_dict[kw_node.arg] = on_delete_val
                            elif kw_node.arg == 'unique' and isinstance(kw_node.value, ast.Constant):
                                unique_val = bool(kw_node.value.value)
                                field_args_dict[kw_node.arg] = unique_val
                            elif kw_node.arg == 'db_index' and isinstance(kw_node.value, ast.Constant):
                                db_index_val = bool(kw_node.value.value)
                                field_args_dict[kw_node.arg] = db_index_val
                            elif kw_node.arg == 'choices' and isinstance(kw_node.value, (ast.List, ast.Tuple)):
                                # Simplistic choices parsing, assumes list/tuple of 2-tuples (value, display_name)
                                choices_val = [(ast.literal_eval(choice_item.elts[0]), ast.literal_eval(choice_item.elts[1])) for choice_item in kw_node.value.elts if isinstance(choice_item, ast.Tuple) and len(choice_item.elts) == 2]
                                field_args_dict[kw_node.arg] = choices_val
                            else:
                                # Try to evaluate, otherwise store as string representation
                                # FIX: Remove deprecated ast types (Num, Str) to resolve DeprecationWarning
                                evaluated_value = ast.literal_eval(kw_node.value) if isinstance(kw_node.value, (ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set)) else ast.unparse(kw_node.value)
                                field_args_dict[kw_node.arg] = evaluated_value
                                if kw_node.arg == 'null': null_val = bool(evaluated_value)
                                elif kw_node.arg == 'blank': blank_val = bool(evaluated_value)
                                elif kw_node.arg == 'default': default_val = evaluated_value # Keep as is, could be function
                                elif kw_node.arg == 'max_length': max_length_val = int(evaluated_value) if isinstance(evaluated_value, (int, str)) and str(evaluated_value).isdigit() else None
                        except (ValueError, TypeError): # Catch errors from ast.literal_eval or type conversion
                            field_args_dict[kw_node.arg] = ast.unparse(kw_node.value)
                    model_fields.append(DjangoModelField(
                        name=field_name, field_type=field_type_str, args=field_args_dict,
                        related_model_name=related_model_val, related_name=related_name_val, on_delete=on_delete_val,
                        unique=unique_val, db_index=db_index_val, choices=choices_val,
                        null=null_val, blank=blank_val, default=default_val, max_length=max_length_val
                    ))
            elif isinstance(item, ast.ClassDef) and item.name == "Meta":
                for meta_item in item.body:
                    if isinstance(meta_item, ast.Assign) and len(meta_item.targets) == 1 and isinstance(meta_item.targets[0], ast.Name):
                        meta_key = meta_item.targets[0].id
                        try:
                            meta_options[meta_key] = ast.literal_eval(meta_item.value)
                        except (ValueError, SyntaxError): # Added SyntaxError for safety
                            meta_options[meta_key] = ast.unparse(meta_item.value)
        return model_fields, meta_options

    def _parse_django_form_fields(self, class_node: ast.ClassDef, form_aliases: List[str]) -> List[DjangoModelField]:
        """
        Parses explicitly defined fields from a Django Form class.
        This captures field types and arguments.
        Uses a list of learned aliases for 'forms'.
        """
        form_fields = []
        # This is similar to the model field parser but looks for `forms.FieldType`.
        for item in class_node.body:
            if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                field_name = item.targets[0].id
                if isinstance(item.value, ast.Call) and \
                   isinstance(item.value.func, ast.Attribute) and \
                   hasattr(item.value.func, 'value') and isinstance(item.value.func.value, ast.Name) and \
                   item.value.func.value.id in form_aliases: # Check for 'forms.CharField' etc.
                    
                    field_type_str = item.value.func.attr
                    field_args_dict = {}
                    
                    # Simplified argument parsing for forms
                    for kw_node in item.value.keywords:
                        try:
                            evaluated_value = ast.literal_eval(kw_node.value) if isinstance(kw_node.value, (ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set)) else ast.unparse(kw_node.value)
                            field_args_dict[kw_node.arg] = evaluated_value
                        except (ValueError, TypeError):
                            field_args_dict[kw_node.arg] = ast.unparse(kw_node.value)
                    
                    form_fields.append(DjangoModelField(name=field_name, field_type=field_type_str, args=field_args_dict))
        return form_fields

    def _parse_django_form_meta(self, class_node: ast.ClassDef) -> Tuple[Optional[str], List[str]]:
        """
        Parses the Meta class of a Django Form or ModelForm.
        This extracts 'model' and 'fields' attributes.
        """
        meta_model = None
        meta_fields = []
        # Specifically looks for an inner class named "Meta".
        if not hasattr(class_node, 'body'): # Ensure class_node is an AST node with a body
            return meta_model, meta_fields
        for item in class_node.body:
            if isinstance(item, ast.ClassDef) and item.name == "Meta":
                for meta_item in item.body:
                    if isinstance(meta_item, ast.Assign) and len(meta_item.targets) == 1 and isinstance(meta_item.targets[0], ast.Name):
                        if meta_item.targets[0].id == "model": meta_model = ast.unparse(meta_item.value)
                        elif meta_item.targets[0].id == "fields":
                            # The value can be a list of strings. We need to evaluate it.
                            try:
                                # ast.literal_eval is safe for evaluating literals like lists of strings.
                                evaluated_fields = ast.literal_eval(meta_item.value)
                                meta_fields = evaluated_fields if isinstance(evaluated_fields, list) else []
                            except (ValueError, SyntaxError):
                                meta_fields = [] # Could not parse, default to empty
        return meta_model, meta_fields

    def _analyze_django_view_method_body(self, method_node: ast.FunctionDef | ast.AsyncFunctionDef, content: str, model_managers: List[str], form_aliases: List[str]) -> Dict[str, Any]:
        """
        Analyzes the body of a Django view method (e.g., `get()`, `post()`) to extract
        key details like rendered templates, models queried, forms used, and redirects.
        """
        rendered_templates_list: List[str] = []
        context_keys: List[str] = []
        models_q: List[str] = []
        forms_used_list: List[str] = []
        redirect_target_name: Optional[str] = None
        http_methods_allowed: List[str] = [] # Only for FBVs, CBVs infer from method name
        # --- NEW: ORM Query Intelligence ---
        queryset_opts: List[str] = []
        uses_raw: bool = False
        aggregations: List[str] = []

        for stmt in ast.walk(method_node):
            # Render calls
            if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Name) and stmt.func.id == 'render':
                if len(stmt.args) > 1 and isinstance(stmt.args[1], ast.Constant) and isinstance(stmt.args[1].value, str):
                    rendered_templates_list.append(stmt.args[1].value)
                for kw in stmt.keywords:
                    if kw.arg == 'template_name' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        rendered_templates_list.append(kw.value.value)
                if len(stmt.args) > 2 and isinstance(stmt.args[2], ast.Dict):
                    context_keys.extend([key.value for key in stmt.args[2].keys if isinstance(key, ast.Constant) and isinstance(key.value, str)])
            
            # Model queries (e.g., `Model.objects.get(...)`)
            elif isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Attribute) and hasattr(stmt.func, 'attr') and stmt.func.attr in model_managers:
                current_node = stmt.func
                while isinstance(current_node, ast.Attribute):
                        # New: Handle DRF ViewSet queryset attribute
                        if current_node.attr == 'queryset' and isinstance(current_node.value, ast.Name):
                            models_q.append(current_node.value.id)
                            break
                        current_node = current_node.value
                if isinstance(current_node, ast.Name) and current_node.id[0].isupper(): # Heuristic: Model names are typically PascalCase
                    models_q.append(current_node.id)

            # --- FIX: Traverse chained method calls for ORM intelligence ---
            # This block handles chains like Model.objects.select_related().prefetch_related().annotate()
            if isinstance(stmt, ast.Call):
                current_call_node = stmt
                # Walk backwards up the chain of calls (e.g., from .annotate() to .prefetch_related() to .select_related())
                while isinstance(current_call_node, ast.Call) and isinstance(current_call_node.func, ast.Attribute):
                    method_name = current_call_node.func.attr
                    if method_name in ['select_related', 'prefetch_related']:
                        queryset_opts.append(method_name)
                    elif method_name in ['raw', 'extra']:
                        uses_raw = True
                    elif method_name in ['annotate', 'aggregate']:
                        for arg in current_call_node.args: aggregations.append(ast.unparse(arg))
                        for kw in current_call_node.keywords: aggregations.append(kw.arg)
                    # Move to the next node in the chain (the object the method was called on)
                    current_call_node = current_call_node.func.value

            
            # Form usage (e.g., `MyForm(...)` or `forms.MyForm(...)`)
            elif isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Name) and (stmt.func.id.endswith('Form') or stmt.func.id.endswith('FormSet')):
                forms_used_list.append(stmt.func.id)
            elif isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Attribute) and \
                 isinstance(stmt.func.value, ast.Name) and stmt.func.value.id in form_aliases:
                forms_used_list.append(stmt.func.attr)

            # Redirects (e.g., `redirect('name')` or `redirect(reverse('name'))`)
            elif isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Name) and stmt.func.id == 'redirect':
                if stmt.args:
                    if isinstance(stmt.args[0], ast.Constant) and isinstance(stmt.args[0].value, str):
                        redirect_target_name = stmt.args[0].value
                    elif isinstance(stmt.args[0], ast.Call) and isinstance(stmt.args[0].func, ast.Name) and stmt.args[0].func.id == 'reverse':
                        if stmt.args[0].args and isinstance(stmt.args[0].args[0], ast.Constant) and isinstance(stmt.args[0].args[0].value, str):
                            redirect_target_name = stmt.args[0].args[0].value
            
            # HTTP methods from request.method checks (primarily for FBVs)
            elif isinstance(stmt, ast.Compare) and isinstance(stmt.left, ast.Attribute) and \
                 isinstance(stmt.left.value, ast.Name) and stmt.left.value.id == 'request' and \
                 stmt.left.attr == 'method':
                for op, val_node in zip(stmt.ops, stmt.comparators):
                    if isinstance(op, ast.Eq) and isinstance(val_node, ast.Constant) and isinstance(val_node.value, str):
                        http_methods_allowed.append(val_node.value.upper())
            
            # Decorators for @require_http_methods (primarily for FBVs)
            if isinstance(method_node, ast.FunctionDef) or isinstance(method_node, ast.AsyncFunctionDef):
                for decorator in method_node.decorator_list:
                    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name) and decorator.func.id == 'require_http_methods':
                        if decorator.args and isinstance(decorator.args[0], ast.List):
                            http_methods_allowed.extend([elt.value for elt in decorator.args[0].elts if isinstance(elt, ast.Constant)])

        return {
            "rendered_templates": list(set(rendered_templates_list)),
            "context_keys": list(set(context_keys)),
            "models_queried": list(set(models_q)),
            "forms_used": list(set(forms_used_list)),
            "redirect_target_name": redirect_target_name,
            "http_methods_allowed": list(set(http_methods_allowed)),
            # --- NEW: Return ORM intelligence ---
            "queryset_optimizations": list(set(queryset_opts)),
            "uses_raw_sql": uses_raw,
            "aggregations_annotations": list(set(aggregations)),
        }

    def _pre_parse_validation(self, file_path: Path, content: str) -> Optional[str]:
        """
        Performs validation checks (size, line count, binary content) before parsing.
        This is a critical crash-prevention step to avoid wasting resources on invalid files.

        Args:
            file_path: The Path object of the file.
            content: The string content of the file.
        Returns:
            An error message string if validation fails, otherwise None.
        """
        # 1. File Size Protection
        file_size = len(content.encode('utf-8', errors='ignore'))
        if file_size > MAX_FILE_SIZE_BYTES:
            return f"File size ({file_size / 1024:.1f} KB) exceeds maximum of {MAX_FILE_SIZE_BYTES / 1024:.1f} KB."

        # 2. Line Count Protection
        line_count = content.count('\n') + 1
        if line_count > MAX_LINE_COUNT:
            return f"File line count ({line_count}) exceeds maximum of {MAX_LINE_COUNT}."

        # 3. Binary File Detection (Layer 1: Extension)
        if file_path.suffix.lower() in BINARY_FILE_EXTENSIONS:
            return f"File has a binary extension ('{file_path.suffix}')."

        # 4. Binary File Detection (Layer 2: Content Heuristics)
        # Check the first 1024 bytes for a high percentage of non-printable or null characters.
        # This helps catch binary files that might not have a standard extension.
        try:
            # The content is already a string, so we check for null bytes which are
            # a strong indicator of a binary file being misread as text.
            if '\0' in content[:1024]:
                return "File content contains null bytes, indicating it is likely a binary file."
        except Exception:
            # If checking the content slice fails for any reason, treat it as a red flag.
            return "Could not analyze file content for binary heuristics."

        # All checks passed
        return None

    def _extract_summary_from_code(self, code_content: str) -> Optional[str]:
        """
        Extracts a special summary comment block from generated code.
        """
        summary_match = re.search(r"<!-- SUMMARY_START -->(.*?)<!-- SUMMARY_END -->", code_content, re.DOTALL)
        if summary_match:
            summary = summary_match.group(1).strip().replace("#", "").strip()
            logger.debug(f"Extracted code summary: {summary[:100]}...")
            return summary
        return None

    @time_function
    def _parse_django_migration_file(self, content: str, file_path_str: str) -> Optional[DjangoMigrationDetails]:
        """
        Parses a Django migration file to extract its dependencies and operations list.
        """
        try:
            tree = ast.parse(content, filename=file_path_str)
            dependencies: List[Tuple[str, str]] = []
            operations: List[DjangoMigrationOperation] = []

            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    # Extract migration dependencies
                    if any(isinstance(t, ast.Name) and t.id == 'dependencies' for t in node.targets):
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            for dep_tuple in node.value.elts:
                                if isinstance(dep_tuple, (ast.List, ast.Tuple)) and len(dep_tuple.elts) == 2:
                                    try:
                                        app_name = ast.literal_eval(dep_tuple.elts[0])
                                        migration_name = ast.literal_eval(dep_tuple.elts[1])
                                        dependencies.append((app_name, migration_name))
                                    except (ValueError, SyntaxError):
                                        continue
                    
                    # Extract migration operations
                    elif any(isinstance(t, ast.Name) and t.id == 'operations' for t in node.targets):
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            for op_call in node.value.elts:
                                if isinstance(op_call, ast.Call) and isinstance(op_call.func, ast.Attribute):
                                    op_type = op_call.func.attr # e.g., 'CreateModel', 'AddField'
                                    # For simplicity, we'll just store the type. A deeper parse could get args.
                                    operations.append(DjangoMigrationOperation(type=op_type))

            return DjangoMigrationDetails(dependencies=dependencies, operations=operations)
        except (SyntaxError, Exception) as e:
            logger.warning(f"Could not parse Django migration file {file_path_str}: {e}")
            return None

    @time_function
    def _parse_django_serializer_class(self, class_node: ast.ClassDef, serializer_aliases: List[str]) -> DjangoSerializer:
        """Parses a DRF Serializer class from an AST node."""
        meta_model: Optional[str] = None
        meta_fields: List[str] = []
        explicit_fields: List[DjangoSerializerField] = []

        # Parse Meta class for ModelSerializer
        for item in class_node.body:
            if isinstance(item, ast.ClassDef) and item.name == "Meta":
                for meta_item in item.body:
                    if isinstance(meta_item, ast.Assign) and len(meta_item.targets) == 1 and isinstance(meta_item.targets[0], ast.Name):
                        if meta_item.targets[0].id == "model":
                            meta_model = ast.unparse(meta_item.value)
                        elif meta_item.targets[0].id == "fields":
                            try:
                                meta_fields = ast.literal_eval(meta_item.value)
                            except (ValueError, SyntaxError, TypeError):
                                pass # Keep empty
        
        # Parse explicitly defined serializer fields
        for item in class_node.body:
            if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                field_name = item.targets[0].id
                if isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Attribute) and \
                   hasattr(item.value.func, 'value') and isinstance(item.value.func.value, ast.Name) and \
                   item.value.func.value.id in serializer_aliases:
                    
                    field_type = item.value.func.attr
                    source = None
                    read_only = False
                    for kw in item.value.keywords:
                        if kw.arg == 'source':
                            try: source = ast.literal_eval(kw.value) # type: ignore
                            except Exception: pass
                        elif kw.arg == 'read_only':
                            try: read_only = ast.literal_eval(kw.value) # type: ignore
                            except Exception: pass
                    
                    explicit_fields.append(DjangoSerializerField(name=field_name, field_type=field_type, source=source, read_only=read_only))

        # Extract general class details
        class_details = self._extract_class_details(class_node)
        
        return DjangoSerializer(
            name=class_details.name,
            bases=class_details.bases,
            methods=class_details.methods,
            attributes=class_details.attributes,
            decorators=class_details.decorators,
            meta_model=meta_model,
            meta_fields=meta_fields,
            serializer_fields=explicit_fields
        )

    @time_function
    def _parse_django_templatetag_file(self, content: str, file_path_str: str) -> Optional[DjangoTemplateTagFileDetails]:
        """Parses a Django templatetags file to find custom tags and filters."""
        try:
            tree = ast.parse(content, filename=file_path_str)
            tags_and_filters: List[DjangoTemplateTag] = []

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    for decorator in node.decorator_list:
                        # Looking for @register.simple_tag, @register.inclusion_tag, @register.filter
                        if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and \
                           decorator.func.attr in ["simple_tag", "inclusion_tag", "filter"]:
                            
                            tag_name = node.name
                            # Check for explicit name, e.g., @register.filter(name='cut')
                            if decorator.keywords:
                                name_kw = next((kw for kw in decorator.keywords if kw.arg == 'name'), None) # type: ignore
                                if name_kw:
                                    tag_name = ast.literal_eval(name_kw.value)
                            
                            template_path_for_tag: Optional[str] = None
                            if decorator.func.attr == "inclusion_tag":
                                # For @register.inclusion_tag('path/to/template.html')
                                if decorator.args:
                                    try: # type: ignore
                                        template_path_for_tag = ast.literal_eval(decorator.args[0])
                                    except (ValueError, SyntaxError):
                                        logger.warning(f"Could not parse template path from inclusion_tag in {file_path_str}")

                            takes_context = any(kw.arg == 'takes_context' and ast.literal_eval(kw.value) for kw in decorator.keywords) if hasattr(decorator, 'keywords') else False
                            tags_and_filters.append(DjangoTemplateTag(
                                name=tag_name, tag_type=decorator.func.attr, takes_context=takes_context, template_path=template_path_for_tag
                            ))
            return DjangoTemplateTagFileDetails(tags_and_filters=tags_and_filters)
        except (SyntaxError, Exception) as e:
            logger.warning(f"Could not parse Django templatetag file {file_path_str}: {e}")
            return None

    @time_function
    def _parse_django_signal_file(self, content: str, file_path_str: str, functions: List[PythonFunction]) -> Optional[DjangoSignalFileDetails]:
        """Parses a signals.py file to find @receiver decorators."""
        try:
            tree = ast.parse(content, filename=file_path_str)
            receivers: List[DjangoSignalReceiver] = []

            for func_def_node in ast.walk(tree):
                if isinstance(func_def_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for decorator in func_def_node.decorator_list:
                        if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name) and decorator.func.id == 'receiver':
                            if decorator.args:
                                signal_type = ast.unparse(decorator.args[0])
                                sender_model = None
                                dispatch_uid_val = None
                                for kw in decorator.keywords: # Renamed kw_node to kw
                                    if kw.arg == 'sender':
                                        sender_model = ast.unparse(kw.value)
                                    elif kw.arg == 'dispatch_uid': # type: ignore
                                        try:
                                            dispatch_uid_val = ast.literal_eval(kw.value)
                                        except (ValueError, SyntaxError):
                                            dispatch_uid_val = ast.unparse(kw.value)
                                
                                # Find the corresponding PythonFunction object
                                func_obj = next((f for f in functions if f.name == func_def_node.name), None)
                                if func_obj:
                                    receivers.append(DjangoSignalReceiver(
                                        signal=signal_type,
                                        sender=sender_model,
                                        dispatch_uid=dispatch_uid_val,
                                        **func_obj.model_dump()
                                    ))
            return DjangoSignalFileDetails(receivers=receivers)
        except (SyntaxError, Exception) as e:
            logger.warning(f"Could not parse Django signal file {file_path_str}: {e}")
            return None

    @time_function
    def _parse_celery_task_file(self, content: str, file_path_str: str, functions: List[PythonFunction]) -> Optional[CeleryTaskFileDetails]:
        """Parses a tasks.py file to find Celery tasks."""
        try:
            tree = ast.parse(content, filename=file_path_str)
            celery_tasks: List[CeleryTask] = []
            
            # --- NEW: Helper to check for self.retry() in a function body ---
            def has_retry_call(func_node: ast.FunctionDef) -> bool:
                return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'retry' and isinstance(n.func.value, ast.Name) and n.func.value.id == 'self' for n in ast.walk(func_node))
            # --- END NEW ---

            for func_def_node in ast.walk(tree):
                if isinstance(func_def_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for decorator in func_def_node.decorator_list:
                        # Look for @app.task or @shared_task
                        is_task = False
                        if isinstance(decorator, ast.Attribute) and decorator.attr == 'task':
                            is_task = True
                        elif isinstance(decorator, ast.Name) and decorator.id == 'shared_task':
                            is_task = True
                        elif isinstance(decorator, ast.Call) and hasattr(decorator.func, 'id') and decorator.func.id == 'shared_task':
                            is_task = True
                        
                        if is_task:
                            func_obj = next((f for f in functions if f.name == func_def_node.name), None)
                            if func_obj:
                                task_options = {}
                                if isinstance(decorator, ast.Call): # @app.task(bind=True)
                                    for kw in decorator.keywords:
                                        task_options[kw.arg] = ast.unparse(kw.value)
                                # --- NEW: Check for retry call ---
                                uses_retry_call = has_retry_call(func_def_node)
                                # --- END NEW ---

                                celery_tasks.append(CeleryTask(task_options=task_options, uses_retry=uses_retry_call, **func_obj.model_dump()))
                                break # Move to next function once a task decorator is found
            return CeleryTaskFileDetails(tasks=celery_tasks)
        except (SyntaxError, Exception) as e:
            logger.warning(f"Could not parse Celery task file {file_path_str}: {e}")
            return None

    @time_function
    def _parse_graphql_schema_file(self, content: str, file_path_str: str, classes: List[PythonClass]) -> Optional[GraphQLSchemaDetails]:
        """Parses a graphene-django schema.py file."""
        try:
            tree = ast.parse(content, filename=file_path_str)
            queries: List[GraphQLType] = []
            mutations: List[GraphQLType] = []
            object_types: List[GraphQLType] = []

            for cls_obj in classes:
                is_query = any("graphene.ObjectType" in b and "Query" in cls_obj.name for b in cls_obj.bases)
                is_mutation = any("graphene.Mutation" in b for b in cls_obj.bases)
                is_object_type = any("graphene_django.DjangoObjectType" in b for b in cls_obj.bases)

                if not (is_query or is_mutation or is_object_type):
                    continue # Not a Graphene class, skip

                class_ast_node = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == cls_obj.name), None)
                if not class_ast_node:
                    continue

                graphql_fields: List[GraphQLField] = []
                for item in class_ast_node.body:
                    if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                        field_name = item.targets[0].id
                        field_type = ast.unparse(item.value)
                        args = {}
                        if isinstance(item.value, ast.Call):
                            for kw in item.value.keywords:
                                if kw.arg:
                                    args[kw.arg] = ast.unparse(kw.value)
                        graphql_fields.append(GraphQLField(name=field_name, field_type=field_type, args=args))

                graphql_type = GraphQLType(graphql_fields=graphql_fields, **cls_obj.model_dump())

                if is_query:
                    queries.append(graphql_type)
                elif is_mutation:
                    mutations.append(graphql_type)
                elif is_object_type:
                    object_types.append(graphql_type)

            return GraphQLSchemaDetails(queries=queries, mutations=mutations, object_types=object_types)

        except (SyntaxError, Exception) as e:
            logger.warning(f"Could not parse GraphQL schema file {file_path_str}: {e}")
            return None

    @time_function
    def parse_file(self, file_path_str: str, content: str) -> Optional[FileStructureInfo]:
        """
        The main dispatcher method. It analyzes a file's content and routes it to the
        appropriate specialized parser based on its name and content, returning a
        structured `FileStructureInfo` object.
        """
        # --- NEW: Incremental Cache Logic ---
        try:
            content_hash = "" # Initialize to prevent UnboundLocalError
            # 1. Calculate the hash of the file content.
            content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()

            # 2. Check for a cache hit.
            if file_path_str in self.in_memory_cache:
                cached_hash, cached_data = self.in_memory_cache[file_path_str]
                if cached_hash == content_hash:
                    logger.debug(f"Cache hit for '{file_path_str}'. Skipping re-parsing.")
                    return cached_data
            logger.debug(f"Cache miss for '{file_path_str}'. Proceeding with full parse.")
        except Exception as e:
            logger.error(f"Error during cache check for '{file_path_str}': {e}. Parsing file directly.")
        # --- END: Incremental Cache Logic ---

        file_path = Path(file_path_str)

        # --- Crash Prevention: Pre-parsing validation ---
        validation_error = self._pre_parse_validation(file_path, content)
        if validation_error:
            logger.warning(f"Skipping parsing for '{file_path_str}': {validation_error}")
            # Create the info object and immediately return it, also caching the "skipped" result.
            skipped_info = FileStructureInfo(file_type="unknown", raw_content_summary=f"Skipped: {validation_error}")
            if content_hash: # Only cache if hash was calculated
                self.in_memory_cache[file_path_str] = (content_hash, skipped_info)
            return skipped_info

        # This is the main dispatcher method for the service.
        file_info = FileStructureInfo()
        filename = file_path.name.lower()
        app_name_from_path = file_path.parts[0] if len(file_path.parts) > 1 else None

        # --- .env File Parsing ---
        if filename == ".env": # type: ignore
            file_info.file_type = "text" # Treat as text
            env_vars = self._parse_env_file(file_path_str)
            file_info.raw_content_summary = f".env file with keys: {', '.join(env_vars.keys())}"

        # --- Python File Parsing Logic ---
        if filename.endswith(".py"): # type: ignore
            # First, perform a general AST parse for any Python file.
            imports, functions, classes = self._parse_python_ast(content, file_path_str)
            py_details = PythonFileDetails(imports=imports, functions=functions, classes=classes)
            file_info.python_details = py_details # Default to python
            file_info.file_type = "python"
            
            # --- NEW: Learn import aliases for key Django modules ---
            model_aliases = self._get_import_aliases(imports, 'django.db.models') # type: ignore
            view_aliases = self._get_import_aliases(imports, 'django.views')
            # --- NEW: Add aliases for third-party extensions ---
            mptt_model_aliases = self._get_import_aliases(imports, 'mptt.models')
            wagtail_aliases = self._get_import_aliases(imports, 'wagtail.models')
            cms_aliases = self._get_import_aliases(imports, 'cms.models')
            # --- END NEW ---
            form_aliases = self._get_import_aliases(imports, 'django.forms')
            admin_aliases = self._get_import_aliases(imports, 'django.contrib.admin')
            serializer_aliases = self._get_import_aliases(imports, 'rest_framework.serializers')
            drf_router_aliases: Set[str] = set(self._get_import_aliases(imports, 'rest_framework.routers'))

            # --- Django Migration File Parsing ---
            if "migrations" in file_path.parts and not filename.startswith("__init__"): # type: ignore
                file_info.file_type = "django_migration"
                file_info.django_migration_details = self._parse_django_migration_file(content, file_path_str)
                # Continue to parse Python details as well
            
            # --- Django Template Tag File Parsing ---
            if "templatetags" in file_path.parts and not filename.startswith("__init__"):
                file_info.file_type = "django_templatetag"
                file_info.django_templatetag_details = self._parse_django_templatetag_file(content, file_path_str)
            
            # --- Celery Task File Parsing ---
            if filename.startswith("tasks") and filename.endswith(".py"): # type: ignore
                file_info.file_type = "celery_task"
                file_info.celery_task_details = self._parse_celery_task_file(content, file_path_str, functions)

            # --- Django-Specific Python File Parsing ---
            # --- FIX: More robust detection of model files ---
            # A file is a model file if it's named models.py OR it contains classes inheriting from models.Model
            is_model_file_heuristic = (filename == "models.py") or any(any(f"{alias}.Model" in base for alias in model_aliases) for cls in classes for base in cls.bases)
            if is_model_file_heuristic: # type: ignore
                file_info.file_type = "django_model"
                django_models = []
                wagtail_pages = []
                cms_plugins = []
                for cls in classes:
                    is_django_model = any(any(f"{alias}.Model" in base for alias in model_aliases) for base in cls.bases)
                    is_mptt_model = any(any(f"{alias}.MPTTModel" in base for alias in mptt_model_aliases) for base in cls.bases)
                    is_wagtail_page = any(any(f"{alias}.Page" in base for alias in wagtail_aliases) for base in cls.bases)
                    is_cms_plugin = any(any(f"{alias}.CMSPlugin" in base for alias in cms_aliases) for base in cls.bases)

                    if is_django_model or is_mptt_model or is_wagtail_page or is_cms_plugin:
                        class_ast_node = next((n for n in ast.parse(content).body if isinstance(n, ast.ClassDef) and n.name == cls.name), None)
                        if class_ast_node:
                            model_fields_extracted, meta_options_extracted = self._parse_django_model_fields(class_ast_node, model_aliases, imports)
                            
                            # Create the base model object
                            model_obj = DjangoModel(
                                name=cls.name, bases=cls.bases, methods=cls.methods,
                                decorators=cls.decorators, attributes=cls.attributes,
                                django_fields=model_fields_extracted, meta_options=meta_options_extracted,
                                is_mptt_model=is_mptt_model
                            )

                            # Specialize the model object if it matches a third-party type
                            if is_wagtail_page:
                                page_obj = WagtailPage(**model_obj.model_dump())
                                # Future: Parse Wagtail-specific attributes like content_panels here
                                wagtail_pages.append(page_obj)
                            elif is_cms_plugin:
                                plugin_obj = DjangoCMSPlugin(**model_obj.model_dump())
                                # Future: Parse django-cms specific attributes here
                                cms_plugins.append(plugin_obj)
                            else:
                                # It's a standard Django model or an MPTT model
                                django_models.append(model_obj)

                file_info.django_model_details = DjangoModelFileDetails(imports=imports, functions=functions, classes=classes, models=django_models, wagtail_pages=wagtail_pages, cms_plugins=cms_plugins)
            elif filename == "views.py": # type: ignore
                file_info.file_type = "django_view"

                # --- New: DRF ViewSet Parsing ---
                drf_viewsets: List[DRFViewSetDetails] = []
                for cls in classes:
                    # Heuristic: Inherits from a ViewSet class
                    if any("ViewSet" in base for base in cls.bases) or any("APIView" in base for base in cls.bases):
                        queryset_attr = next((attr.value_preview for attr in cls.attributes if attr.name == 'queryset'), None)
                        serializer_class_attr = next((attr.value_preview for attr in cls.attributes if attr.name == 'serializer_class'), None)
                        auth_classes_attr = next((attr.value_preview for attr in cls.attributes if attr.name == 'authentication_classes'), None)
                        perm_classes_attr = next((attr.value_preview for attr in cls.attributes if attr.name == 'permission_classes'), None)
                        pagination_class_attr = next((attr.value_preview for attr in cls.attributes if attr.name == 'pagination_class'), None)
                        drf_viewsets.append(DRFViewSetDetails(
                            name=cls.name,
                            authentication_classes=[c.strip() for c in auth_classes_attr.strip("[]()").split(",")] if auth_classes_attr else [],
                            permission_classes=[c.strip() for c in perm_classes_attr.strip("[]()").split(",")] if perm_classes_attr else [],
                            pagination_class=pagination_class_attr,
                            queryset_model=queryset_attr.split('.')[0] if queryset_attr else None,
                            serializer_class=serializer_class_attr
                        ))
                # --- End DRF ViewSet Parsing ---

                django_views = []
                model_managers = ['objects', 'all', 'get', 'filter', 'exclude', 'create', 'get_or_create', 'update_or_create']

                # --- Parse Function-Based Views (FBVs) ---
                for func_node in functions: # PythonFunction objects
                    func_ast_node = next((n for n in ast.parse(content).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_node.name), None)
                    if func_ast_node:
                        analysis_results = self._analyze_django_view_method_body(func_ast_node, content, model_managers, form_aliases)
                        
                        # Infer HTTP methods from decorators or request.method checks
                        final_http_methods = analysis_results["http_methods_allowed"]
                        if not final_http_methods:
                            # Default to GET if no explicit methods are found and it's not a CBV method
                            final_http_methods = ['GET']

                        django_views.append(DjangoView(
                            name=func_node.name, params=func_node.params, decorators=func_node.decorators,
                            return_type_hint=func_node.return_type_hint, is_async=func_node.is_async,
                            rendered_templates=analysis_results["rendered_templates"],
                            context_data_keys=analysis_results["context_keys"],
                            models_queried=analysis_results["models_queried"],
                            uses_forms=analysis_results["forms_used"],
                            redirects_to_url_name=analysis_results["redirect_target_name"],
                            allowed_http_methods=final_http_methods,
                            queryset_optimizations=analysis_results["queryset_optimizations"],
                            uses_raw_sql=analysis_results["uses_raw_sql"],
                            aggregations_annotations=analysis_results["aggregations_annotations"]
                        ))

                # --- Parse Class-Based Views (CBVs) ---
                for cls_node in classes: # Iterate over PythonClass objects
                    # Heuristic to identify a CBV: inherits from 'View' or a common generic view
                    is_cbv = any('View' in base or 'FormView' in base or 'DetailView' in base or 'ListView' in base or 'CreateView' in base or 'UpdateView' in base or 'DeleteView' in base for base in cls_node.bases)
                    if is_cbv:
                        # Extract details from the CBV's attributes and methods
                        template_name_from_attr = next((attr.value_preview for attr in cls_node.attributes if attr.name == 'template_name'), None)
                        model_from_attr = next((attr.value_preview for attr in cls_node.attributes if attr.name == 'model'), None)
                        form_class_from_attr = next((attr.value_preview for attr in cls_node.attributes if attr.name == 'form_class'), None)
                        context_object_name_from_attr = next((attr.value_preview for attr in cls_node.attributes if attr.name == 'context_object_name'), None)
                        
                        cbv_rendered_templates: List[str] = []
                        cbv_context_keys: List[str] = []
                        cbv_models_queried: List[str] = []
                        cbv_forms_used: List[str] = []
                        cbv_redirect_target: Optional[str] = None
                        cbv_http_methods: List[str] = []
                        cbv_queryset_opts: List[str] = []
                        cbv_uses_raw: bool = False
                        cbv_aggregations: List[str] = []

                        # Analyze specific CBV methods
                        for method_py_obj in cls_node.methods:
                            # Get the actual AST node for the method to walk its body
                            class_ast_node = next((n for n in ast.parse(content).body if isinstance(n, ast.ClassDef) and n.name == cls_node.name), None)
                            if class_ast_node:
                                method_ast_node = next((n for n in class_ast_node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == method_py_obj.name), None)
                                if method_ast_node:
                                    analysis_results = self._analyze_django_view_method_body(method_ast_node, content, model_managers, form_aliases)
                                    cbv_rendered_templates.extend(analysis_results["rendered_templates"])
                                    cbv_context_keys.extend(analysis_results["context_keys"])
                                    cbv_models_queried.extend(analysis_results["models_queried"])
                                    cbv_forms_used.extend(analysis_results["forms_used"])
                                    if analysis_results["redirect_target_name"]:
                                        cbv_redirect_target = analysis_results["redirect_target_name"]
                                    cbv_queryset_opts.extend(analysis_results["queryset_optimizations"])
                                    if analysis_results["uses_raw_sql"]: cbv_uses_raw = True
                                    cbv_aggregations.extend(analysis_results["aggregations_annotations"])
                                    
                                    # Infer HTTP methods from method names (get, post, etc.)
                                    if method_py_obj.name.lower() in ['get', 'post', 'put', 'patch', 'delete']:
                                        cbv_http_methods.append(method_py_obj.name.upper())
                        
                        # Add attributes to the collected data
                        if template_name_from_attr:
                            cbv_rendered_templates.append(template_name_from_attr.strip("'\""))
                        if model_from_attr:
                            cbv_models_queried.append(model_from_attr.strip("'\""))
                        if form_class_from_attr:
                            cbv_forms_used.append(form_class_from_attr.strip("'\""))
                        if context_object_name_from_attr:
                            cbv_context_keys.append(context_object_name_from_attr.strip("'\""))

                        # Default to GET if no methods are explicitly defined
                        if not cbv_http_methods: cbv_http_methods = ['GET']

                        django_views.append(DjangoView(
                            name=cls_node.name,
                            params=[], # CBV methods have standard params, not like FBVs
                            decorators=cls_node.decorators,
                            is_async=any(m.is_async for m in cls_node.methods),
                            rendered_templates=list(set(cbv_rendered_templates)),
                            context_data_keys=list(set(cbv_context_keys)),
                            models_queried=list(set(cbv_models_queried)),
                            uses_forms=list(set(cbv_forms_used)),
                            redirects_to_url_name=cbv_redirect_target,
                            allowed_http_methods=list(set(cbv_http_methods)),
                            queryset_optimizations=list(set(cbv_queryset_opts)),
                            uses_raw_sql=cbv_uses_raw,
                            aggregations_annotations=list(set(cbv_aggregations))
                        ))
                        logger.debug(f"Parsed Class-Based View: {cls_node.name}")
                # --- END NEW ---
                # Add the parsed DRF viewsets to the details
                file_info.django_view_details = DjangoViewFileDetails(
                    imports=imports, functions=functions, classes=classes, views=django_views,
                    drf_viewsets=drf_viewsets
                )
            elif filename == "serializers.py":
                file_info.file_type = "django_serializer" # type: ignore
                django_serializers: List[DjangoSerializer] = []
                try:
                    tree = ast.parse(content)
                    for node in tree.body:
                        if isinstance(node, ast.ClassDef) and any("Serializer" in base for base in [ast.unparse(b) for b in node.bases]):
                            serializer_details = self._parse_django_serializer_class(node, serializer_aliases)
                            django_serializers.append(serializer_details)
                except Exception as e_serializer:
                    logger.warning(f"Could not parse serializers from {file_path_str}: {e_serializer}")
                
                file_info.django_serializer_details = DjangoSerializerFileDetails(imports=imports, functions=functions, classes=classes, serializers=django_serializers)

            elif filename == "urls.py":
                # --- New: Channels Routing File Detection --- # type: ignore
                if "routing.py" in file_path_str:
                    file_info.file_type = "django_channels_routing"
                    # Parsing logic for routing.py is similar to urls.py, so we can reuse parts

                file_info.file_type = "django_urls"
                app_name_match = re.search(r"app_name\s*=\s*['\"]([^'\"]+)['\"]", content)
                current_app_name_for_registry = app_name_match.group(1) if app_name_match else None
                patterns = []
                # --- New: DRF Router Parsing ---
                drf_routers: List[DRFRouterRegistration] = []
                try:
                    url_tree_for_drf = ast.parse(content)
                    for node_item in url_tree_for_drf.body:
                        # Find router = DefaultRouter()
                        if isinstance(node_item, ast.Assign) and isinstance(node_item.value, ast.Call):
                            if isinstance(node_item.value.func, ast.Name) and "Router" in node_item.value.func.id:
                                router_var_name = node_item.targets[0].id # type: ignore
                                # Now find router.register(...) calls
                                for sub_node in url_tree_for_drf.body:
                                    if isinstance(sub_node, ast.Expr) and isinstance(sub_node.value, ast.Call) and \
                                       isinstance(sub_node.value.func, ast.Attribute) and sub_node.value.func.attr == 'register' and \
                                       isinstance(sub_node.value.func.value, ast.Name) and sub_node.value.func.value.id == router_var_name:
                                        prefix = ast.literal_eval(sub_node.value.args[0])
                                        viewset = ast.unparse(sub_node.value.args[1])
                                        basename = ast.literal_eval(next((kw.value for kw in sub_node.value.keywords if kw.arg == 'basename'), ast.Constant(value=None)))
                                        drf_routers.append(DRFRouterRegistration(prefix=prefix, viewset_name=viewset, basename=basename))
                except Exception as e_drf:
                    logger.warning(f"Could not parse DRF router from {file_path_str}: {e_drf}")
                # --- End DRF Router Parsing ---
                includes_parsed = []
                try:
                    url_tree = ast.parse(content)
                    for node_item in url_tree.body:
                        if isinstance(node_item, ast.Assign):
                            if any(isinstance(t, ast.Name) and t.id == "urlpatterns" for t in node_item.targets):
                                if isinstance(node_item.value, ast.List):
                                    for elt in node_item.value.elts: # elt is a path() or re_path() call
                                        if isinstance(elt, ast.Call) and hasattr(elt.func, 'id') and elt.func.id in ["path", "re_path"]:
                                            try:
                                                raw_pattern = ast.literal_eval(elt.args[0]) if isinstance(elt.args[0], ast.Constant) else ast.unparse(elt.args[0])
                                                # Do NOT unescape HTML for URL patterns. The raw string is correct.
                                                route_pattern_str = raw_pattern
                                            except (ValueError, SyntaxError, IndexError, TypeError):
                                                route_pattern_str = ast.unparse(elt.args[0]) if elt.args else "ERROR_PARSING_ROUTE"
                                            
                                            # Check if the second argument is an include() call
                                            is_include = False
                                            if len(elt.args) > 1 and isinstance(elt.args[1], ast.Call) and hasattr(elt.args[1].func, 'id') and elt.args[1].func.id == "include":
                                                is_include = True

                                            if is_include:
                                                # This is an include, e.g., path('api/', include('api.urls'))
                                                include_call_node = elt.args[1]
                                                included_urlconf_str = "ERROR_PARSING_INCLUDED_CONF"
                                                if include_call_node.args:
                                                    if isinstance(include_call_node.args[0], ast.Constant) and isinstance(include_call_node.args[0].value, str):
                                                        included_urlconf_str = include_call_node.args[0].value
                                                    elif isinstance(include_call_node.args[0], ast.Tuple) and include_call_node.args[0].elts and isinstance(include_call_node.args[0].elts[0], ast.Constant):
                                                        included_urlconf_str = include_call_node.args[0].elts[0].value
                                                includes_parsed.append(DjangoURLInclude(pattern=route_pattern_str, included_urlconf=included_urlconf_str))
                                            else:
                                                # This is a regular path to a view
                                                view_ref_str = ast.unparse(elt.args[1]) if len(elt.args) > 1 else "ERROR_PARSING_VIEW"
                                                url_name_str = None
                                                for kw in elt.keywords:
                                                    if kw.arg == 'name' and isinstance(kw.value, ast.Constant):
                                                        url_name_str = kw.value.value
                                                        break
                                                patterns.append(DjangoURLPattern(pattern=route_pattern_str, view_reference=view_ref_str, name=url_name_str))
                                        # The old `elif elt.func.id == "include"` was unreachable and is now removed.

                except Exception as e_url:
                    logger.warning(f"Could not parse urlpatterns from {file_path_str}: {e_url}")
                
                if file_info.file_type == "django_channels_routing":
                    file_info.django_channels_routing_details = DjangoChannelsRouting(
                        imports=imports, functions=functions, classes=classes,
                        websocket_patterns=patterns # Store websocket_urlpatterns here
                    )
                else:
                    file_info.django_urls_details = DjangoURLConfDetails( # type: ignore
                        imports=imports, functions=functions, classes=classes, app_name=current_app_name_for_registry, 
                        url_patterns=patterns, includes=includes_parsed, drf_routers=drf_routers
                    )
            elif filename == "forms.py":
                file_info.file_type = "django_form"
                django_forms = []
                for cls_node in classes:
                    is_django_form = any(base.endswith("Form") for base in cls_node.bases) or \
                                     any(base.endswith("ModelForm") for base in cls_node.bases) or \
                                     ("Form" in cls_node.name and not any(b.endswith("Form") for b in cls_node.bases)) # Heuristic for forms.Form

                    if is_django_form: # cls_node is PythonClass
                        form_ast_node = next((n for n in ast.parse(content).body if isinstance(n, ast.ClassDef) and n.name == cls_node.name), None)
                        meta_model_name, meta_fields_list = (None, [])
                        if form_ast_node and any(base.endswith("ModelForm") for base in cls_node.bases): # Only parse Meta for ModelForms
                            meta_model_name, meta_fields_list = self._parse_django_form_meta(form_ast_node) # type: ignore
                        # For explicitly defined fields, use the new form field parser
                        explicit_fields = self._parse_django_form_fields(form_ast_node, form_aliases) if form_ast_node else []
                        django_forms.append(DjangoForm(
                            name=cls_node.name, bases=cls_node.bases, methods=cls_node.methods,
                            decorators=cls_node.decorators, # Added decorators
                            attributes=cls_node.attributes, meta_model=meta_model_name, meta_fields=meta_fields_list, form_fields=explicit_fields
                        ))
                file_info.django_form_details = DjangoFormFileDetails(imports=imports, functions=functions, classes=classes, forms=django_forms)
            elif filename == "admin.py":
                file_info.file_type = "django_admin"
                admin_aliases = self._get_import_aliases(imports, 'django.contrib.admin')
                registered_models_parsed = []
                # --- NEW: Parse advanced admin features ---
                from .project_models import DjangoAdminInline # Local import to avoid circularity at top level
                inline_classes_details: List[DjangoAdminInline] = []
                # --- END NEW ---

                admin_classes_details = []
                try:
                    admin_tree = ast.parse(content)
                    for node_item in admin_tree.body:
                        # Case 1: admin.site.register(Question)
                        if isinstance(node_item, ast.Expr) and isinstance(node_item.value, ast.Call) and \
                           isinstance(node_item.value.func, ast.Attribute) and \
                           isinstance(node_item.value.func.value, ast.Attribute) and \
                           node_item.value.func.value.attr == 'site' and \
                           isinstance(node_item.value.func.value.value, ast.Name) and \
                           node_item.value.func.value.value.id == 'admin' and \
                           node_item.value.func.attr == 'register':
                            model_name_reg = ast.unparse(node_item.value.args[0]) if node_item.value.args else None # type: ignore
                            admin_class_name_reg = ast.unparse(node_item.value.args[1]) if len(node_item.value.args) > 1 else None
                            if model_name_reg:
                                registered_models_parsed.append(DjangoAdminRegisteredModel(model=model_name_reg, admin_class=admin_class_name_reg))
                        # Case 2: @admin.register(Article)
                        elif isinstance(node_item, ast.ClassDef):
                            for decorator in node_item.decorator_list:
                                if isinstance(decorator, ast.Call) and \
                                   isinstance(decorator.func, ast.Attribute) and \
                                   hasattr(decorator.func, 'value') and \
                                   isinstance(decorator.func.value, ast.Name) and \
                                   decorator.func.value.id in admin_aliases and \
                                   decorator.func.attr == 'register':
                                    if decorator.args:
                                        model_name_from_decorator = ast.unparse(decorator.args[0])
                                        admin_class_for_decorator = node_item.name
                                        registered_models_parsed.append(DjangoAdminRegisteredModel(model=model_name_from_decorator, admin_class=admin_class_for_decorator))
                            # --- FIX: Also parse the ModelAdmin class itself ---
                            # Check if the class inherits from ModelAdmin
                            if any("ModelAdmin" in ast.unparse(base) for base in node_item.bases):
                                # --- FIX: Corrected syntax for safe attribute parsing ---
                                list_display = next((
                                    ast.literal_eval(attr.value) for attr in node_item.body 
                                    if isinstance(attr, ast.Assign) and attr.targets and isinstance(attr.targets[0], ast.Name) and attr.targets[0].id == 'list_display'
                                ), [])
                                list_editable = next((
                                    ast.literal_eval(attr.value) for attr in node_item.body
                                    if isinstance(attr, ast.Assign) and attr.targets and isinstance(attr.targets[0], ast.Name) and attr.targets[0].id == 'list_editable'
                                ), [])
                                search_fields = next((
                                    ast.literal_eval(attr.value) for attr in node_item.body 
                                    if isinstance(attr, ast.Assign) and attr.targets and isinstance(attr.targets[0], ast.Name) and attr.targets[0].id == 'search_fields'
                                ), [])
                                list_filter = next((
                                    ast.literal_eval(attr.value) for attr in node_item.body 
                                    if isinstance(attr, ast.Assign) and attr.targets and isinstance(attr.targets[0], ast.Name) and attr.targets[0].id == 'list_filter'
                                ), [])
                                fieldsets = next((
                                    ast.literal_eval(attr.value) for attr in node_item.body
                                    if isinstance(attr, ast.Assign) and attr.targets and isinstance(attr.targets[0], ast.Name) and attr.targets[0].id == 'fieldsets'
                                ), [])
                                inlines = next((
                                    [ast.unparse(e) for e in attr.value.elts] for attr in node_item.body
                                    if isinstance(attr, ast.Assign) and attr.targets and isinstance(attr.targets[0], ast.Name) and attr.targets[0].id == 'inlines' and isinstance(attr.value, (ast.List, ast.Tuple))
                                ), [])
                                # --- END FIX ---

                                class_details = self._extract_class_details(node_item)
                                admin_classes_details.append(DjangoAdminClass(
                                    name=class_details.name, bases=class_details.bases, methods=class_details.methods,
                                    list_display=list_display, list_editable=list_editable,
                                    search_fields=search_fields,
                                    list_filter=list_filter, fieldsets=fieldsets, inlines=inlines,
                                    attributes=class_details.attributes, decorators=class_details.decorators
                                ))
                except (Exception, SyntaxError) as e_admin_ast:
                    logger.warning(f"Could not parse admin.py AST for registers: {e_admin_ast}")
                file_info.django_admin_details = DjangoAdminFileDetails(imports=imports, functions=functions, classes=classes, registered_models=registered_models_parsed, admin_classes=admin_classes_details)
            elif filename.startswith("signals"):
                file_info.file_type = "django_signal"
                file_info.django_signal_details = self._parse_django_signal_file(content, file_path_str, functions) # type: ignore
            elif filename == "consumers.py":
                file_info.file_type = "django_channels_consumer"
                consumers: List[DjangoChannelsConsumer] = []
                for cls in classes:
                    if any("Consumer" in base for base in cls.bases): # type: ignore
                        consumers.append(DjangoChannelsConsumer(**cls.model_dump()))
                file_info.django_channels_consumer_details = DjangoChannelsFileDetails(imports=imports, functions=functions, classes=classes, consumers=consumers)
            elif filename == "routing.py":
                file_info.file_type = "django_channels_routing"
                websocket_patterns: List[DjangoURLPattern] = []
                try:
                    tree = ast.parse(content) # type: ignore
                    for node in ast.walk(tree): # type: ignore
                        if isinstance(node, ast.Assign) and any(t.id == 'websocket_urlpatterns' for t in node.targets if isinstance(t, ast.Name)): # type: ignore
                            if isinstance(node.value, ast.List): # type: ignore
                                for elt in node.value.elts: # type: ignore
                                    if isinstance(elt, ast.Call) and hasattr(elt.func, 'id') and elt.func.id in ["path", "re_path"]:
                                        pattern = ast.unparse(elt.args[0]) # type: ignore
                                        consumer_ref = ast.unparse(elt.args[1]) # type: ignore
                                        name = next((kw.value.value for kw in elt.keywords if kw.arg == 'name'), None) # type: ignore
                                        websocket_patterns.append(DjangoURLPattern(pattern=pattern, view_reference=consumer_ref, name=name))
                except Exception as e_routing:
                    logger.warning(f"Could not parse Channels routing file {file_path_str}: {e_routing}")
                file_info.django_channels_routing_details = DjangoChannelsRouting(imports=imports, functions=functions, classes=classes, websocket_patterns=websocket_patterns)
            # --- MODIFIED: More flexible settings file detection --- # type: ignore
            elif filename.startswith("settings") and filename.endswith(".py"):
                file_info.file_type = "django_settings"
                key_settings = {}
                celery_beat_schedules: List[CeleryBeatSchedule] = []
                env_vars_used = {}
                asset_pipeline_tools: List[str] = []
                try:
                    settings_tree = ast.parse(content) # type: ignore

                    # --- NEW: Expanded list of key settings to parse ---
                    key_settings_to_find = {
                        "INSTALLED_APPS", "MIDDLEWARE", "DATABASES", "AUTH_USER_MODEL",
                        "ROOT_URLCONF", "STATIC_URL", "STATIC_ROOT", "STATICFILES_DIRS",
                        "MEDIA_URL", "MEDIA_ROOT", "SECRET_KEY", "DEBUG", "ALLOWED_HOSTS",
                        "AUTHENTICATION_BACKENDS", "LOGGING", "CACHES", "SESSION_ENGINE",
                        "SESSION_COOKIE_AGE", "LANGUAGE_CODE", "USE_I18N", "USE_L10N", "STATICFILES_STORAGE",
                        "USE_TZ", "LOCALE_PATHS", "STATICFILES_STORAGE", "TEMPLATES"
                    }

                    # --- NEW: Handle dynamic INSTALLED_APPS (e.g., using +=) ---
                    installed_apps_list = []
                    found_initial_apps = False

                    for node_item in ast.walk(settings_tree): # type: ignore
                        # Find initial assignment
                        if not found_initial_apps and isinstance(node_item, ast.Assign):
                            if any(isinstance(t, ast.Name) and t.id == "INSTALLED_APPS" for t in node_item.targets):
                                try:
                                    installed_apps_list = ast.literal_eval(node_item.value) # type: ignore
                                    found_initial_apps = True
                                except (ValueError, SyntaxError):
                                    pass # Will be handled by generic parsing later if this fails

                        # Find augment assignments (+=)
                        elif isinstance(node_item, ast.AugAssign) and isinstance(node_item.target, ast.Name) and node_item.target.id == "INSTALLED_APPS":
                            try:
                                apps_to_add = ast.literal_eval(node_item.value) # type: ignore
                                if isinstance(apps_to_add, (list, tuple)):
                                    installed_apps_list.extend(apps_to_add)
                            except (ValueError, SyntaxError):
                                pass

                        # Find .append() calls
                        elif isinstance(node_item, ast.Expr) and isinstance(node_item.value, ast.Call) and \
                             isinstance(node_item.value.func, ast.Attribute) and \
                             isinstance(node_item.value.func.value, ast.Name) and \
                             node_item.value.func.value.id == "INSTALLED_APPS" and node_item.value.func.attr == "append":
                            try:
                                app_to_add = ast.literal_eval(node_item.value.args[0]) # type: ignore
                                installed_apps_list.append(app_to_add)
                            except (ValueError, SyntaxError):
                                pass

                    if found_initial_apps:
                        key_settings["INSTALLED_APPS"] = installed_apps_list
                        # --- NEW: Detect asset pipeline tools from INSTALLED_APPS ---
                        if 'pipeline' in installed_apps_list:
                            asset_pipeline_tools.append('django-pipeline')
                        if 'webpack_loader' in installed_apps_list:
                            asset_pipeline_tools.append('django-webpack-loader')
                        # --- END NEW ---

                    # Generic parsing for other settings
                    for node_item in settings_tree.body: # type: ignore
                        if isinstance(node_item, ast.Assign):
                            for target in node_item.targets:
                                if isinstance(target, ast.Name):
                                    setting_name = target.id
                                    if setting_name in key_settings_to_find and setting_name not in key_settings:
                                        unparsed_value = ast.unparse(node_item.value) # type: ignore
                                        try:
                                            # Try to evaluate, but have the unparsed value ready.
                                            key_settings[setting_name] = ast.literal_eval(node_item.value)
                                        except (ValueError, SyntaxError): # For complex values like BASE_DIR / 'db.sqlite3'
                                            key_settings[setting_name] = unparsed_value
                                            # Check if it uses an environment variable
                                            env_var_match = re.search(r"os\.environ(?:.get)?\(['\"]([^'\"]+)['\"]", unparsed_value)
                                            if env_var_match:
                                                env_vars_used[setting_name] = env_var_match.group(1)
                                    # --- NEW: Parse CELERY_BEAT_SCHEDULE ---
                                    if setting_name == "CELERY_BEAT_SCHEDULE":
                                        if isinstance(node_item.value, ast.Dict):
                                            for i in range(len(node_item.value.keys)):
                                                key_node = node_item.value.keys[i]
                                                val_node = node_item.value.values[i]
                                                if isinstance(key_node, ast.Constant) and isinstance(val_node, ast.Dict):
                                                    task_name = key_node.value
                                                    task_path = next((ast.literal_eval(v) for k, v in zip(val_node.keys, val_node.values) if isinstance(k, ast.Constant) and k.value == 'task'), None)
                                                    # FIX: Use ast.unparse for schedule as it can be a function call (crontab)
                                                    schedule_str = next((ast.unparse(v) for k, v in zip(val_node.keys, val_node.values) if isinstance(k, ast.Constant) and k.value == 'schedule'), None) # type: ignore
                                                    if task_path and schedule_str:
                                                        celery_beat_schedules.append(CeleryBeatSchedule(task_name=task_path, schedule=schedule_str))
                                    # --- END NEW ---

                except Exception as e_settings:
                    logger.warning(f"Could not parse settings.py AST for {file_path_str}: {e_settings}")
                file_info.django_settings_details = DjangoSettingsDetails(
                    imports=imports, functions=functions, classes=classes,
                    key_settings=key_settings, env_vars_used=env_vars_used,
                    celery_beat_schedules=celery_beat_schedules,
                    static_url=key_settings.get("STATIC_URL"),
                    static_root=key_settings.get("STATIC_ROOT"),
                    staticfiles_dirs=key_settings.get("STATICFILES_DIRS", []),
                    staticfiles_storage=key_settings.get("STATICFILES_STORAGE"),
                    asset_pipeline_tools_detected=asset_pipeline_tools
                )

            elif filename == "apps.py":
                file_info.file_type = "django_apps_config"
                file_info.django_apps_config_details = py_details
            elif filename == "schema.py":
                file_info.file_type = "django_graphql_schema"
                file_info.graphql_schema_details = self._parse_graphql_schema_file(content, file_path_str, classes)

            elif filename.startswith("test_") or filename == "tests.py":
                file_info.file_type = "django_test" # type: ignore
                test_classes_parsed: List[DjangoTestClass] = []
                for cls_node in classes:
                    if any(base in ["TestCase", "APITestCase"] for base in cls_node.bases) or cls_node.name.startswith("Test"):
                        has_setup_test_data = any(m.name == "setUpTestData" for m in cls_node.methods)
                        # Simple regex to check for self.client or self.factory usage
                        class_source = ast.get_source_segment(content, next(n for n in ast.parse(content).body if isinstance(n, ast.ClassDef) and n.name == cls_node.name)) or ""
                        uses_api_client = bool(re.search(r"self\.client\.(get|post|put|delete)", class_source))
                        uses_request_factory = "RequestFactory" in class_source

                        test_classes_parsed.append(DjangoTestClass(
                            has_setup_test_data=has_setup_test_data,
                            uses_api_client=uses_api_client,
                            uses_request_factory=uses_request_factory,
                            **cls_node.model_dump()
                        ))
                file_info.django_test_details = DjangoTestFileDetails(imports=imports, functions=functions, classes=classes, test_classes=test_classes_parsed)

        elif filename.endswith((".html", ".htm", ".djt")): # type: ignore
            file_info.file_type = "template"
            extends_match = re.search(r"{%\s*extends\s*['\"]([^'\"]+)['\"]\s*%}", content, re.IGNORECASE)
            includes = re.findall(r"{%\s*include\s*['\"]([^'\"]+)['\"]\s*%}", content)
            statics = re.findall(r"{%\s*static\s*['\"]([^'\"]+)['\"]\s*%}", content)
            url_names = re.findall(r"{%\s*url\s*['\"]([^'\"]+)['\"]", content)
            context_vars = re.findall(r"{{\s*([\w\.]+)\s*}}", content)
            i18n_tags = re.findall(r"{%\s*(trans|blocktrans)\s", content)
            form_action_targets = re.findall(r"<form[^>]*action\s*=\s*['\"]([^'\"]*)['\"]", content, re.IGNORECASE)
            ids = re.findall(r"id\s*=\s*['\"]([^'\"]+)['\"]", content)
            file_info.template_details = TemplateFileDetails(
                extends_template=extends_match.group(1) if extends_match else None,
                i18n_tags_used=list(set(i18n_tags)),
                includes_templates=includes,
                static_files_used=statics,
                url_references=url_names,
                context_variables_used=list(set(context_vars))[:20],
                form_targets=form_action_targets,
                key_dom_ids=list(set(ids))[:10])
        elif filename.endswith(".js"): # type: ignore
            file_info.file_type = "javascript"
            ajax_urls = re.findall(r"fetch\s*\(\s*['\"]([^'\"]+)['\"]", content)
            dom_ids = re.findall(r"document\.getElementById\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content)
            js_imports = re.findall(r"import\s+.*\s+from\s+['\"]([^'\"]+)['\"]", content)
            file_info.js_details = JSFileDetails(imports_from=js_imports, ajax_calls_to_urls=ajax_urls, accesses_dom_ids=dom_ids, global_functions=[])
        elif filename.endswith(".css"):
            file_info.file_type = "css"
            imports_css = re.findall(r"@import\s*url\s*\(\s*['\"]([^'\"]+)['\"]\s*\);", content)
            selectors = re.findall(r"([#\.][\w\-]+)\s*\{", content)
            file_info.css_details = CSSFileDetails(imports_css=imports_css, defines_selectors=list(set(selectors))[:20])
        elif filename.endswith(".json"): # type: ignore
            file_info.file_type = "json_data"
            try:
                json.loads(content)
                file_info.raw_content_summary = f"JSON data file, approx {len(content)//1024}KB."
            except json.JSONDecodeError:
                file_info.raw_content_summary = "Invalid JSON file."
        elif filename.endswith((".txt", ".md", ".log", ".yaml", ".yml", ".ini", ".cfg", ".env")): # type: ignore
            file_info.file_type = "text"
            file_info.raw_content_summary = content[:200] + ("..." if len(content) > 200 else "")
        else:
            file_info.file_type = "unknown"
            file_info.raw_content_summary = f"Unknown file type. Size: {len(content)} bytes."
        
        if content_hash:
            self.in_memory_cache[file_path_str] = (content_hash, file_info)
        return file_info

    @time_function
    def parse_files_in_parallel(self, file_paths_with_content: Dict[str, str], max_workers: int = 4) -> Dict[str, Optional[FileStructureInfo]]:
        """
        Parses multiple files concurrently using a thread pool, leveraging the file cache.

        Args:
            file_paths_with_content: A dictionary mapping relative file paths to their string content.
            max_workers: The maximum number of worker threads to use.
        Returns:
            A dictionary mapping each file path to its parsed FileStructureInfo object or None.
        """
        results: Dict[str, Optional[FileStructureInfo]] = {}
        if not file_paths_with_content:
            return results

        logger.info(f"Starting parallel parsing for {len(file_paths_with_content)} files with {max_workers} workers.")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(self.parse_file, path, content): path
                for path, content in file_paths_with_content.items()
            }

            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    results[path] = future.result()
                except Exception as exc:
                    logger.error(f"An exception occurred while parsing '{path}' in parallel: {exc}", exc_info=True)
                    results[path] = None
        
        logger.info(f"Finished parallel parsing. Processed {len(results)} files.")
        return results
