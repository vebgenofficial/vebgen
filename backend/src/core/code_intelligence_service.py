# src/core/code_intelligence_service.py
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Literal
import ast
import re
import sys # Import the sys module
import json# Placeholder for AST parsing libraries (e.g., ast, esprima, etc.)
# import ast
from .project_models import (
    FileStructureInfo, PythonFileImport, PythonFunctionParam, PythonFunction,
    PythonClassAttribute, PythonClass, PythonFileDetails, DjangoModelField, DjangoModel,
    DjangoModelFileDetails, DjangoView, DjangoViewFileDetails, DjangoTestFileDetails, # Added DjangoTestFileDetails
    DjangoURLPattern, # Keep DjangoURLPattern
    GlobalURLRegistryEntry,
    APIContractEndpoint, # Added for API Contract parsing if needed in future
    DjangoURLInclude,
    DjangoURLConfDetails, DjangoForm, DjangoFormFileDetails, DjangoAdminRegisteredModel, DjangoAdminClass,
    DjangoAdminFileDetails, DjangoSettingsDetails, TemplateFileDetails, JSFileDetails, CSSFileDetails
)

logger = logging.getLogger(__name__)

class CodeIntelligenceService:
    """
    Provides advanced code analysis by parsing source files into structured data models.

    This service uses Abstract Syntax Trees (AST) for Python files to understand their
    structure, including classes, functions, imports, and framework-specific details
    (like Django models and views). For other file types (HTML, CSS, JS), it uses
    regular expressions for a more basic level of analysis. The goal is to provide
    rich, structured context to the AI agents.
    """
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        logger.info(f"CodeIntelligenceService initialized for project root: {self.project_root}")

    def run_static_checks(self, file_paths: List[str]) -> Tuple[bool, str]:
        """
        Runs static code analysis (linting, type checking, basic security scans) on specified files.
        (This is a placeholder for future implementation).
        """
        logger.info(f"Running static checks on {len(file_paths)} files (placeholder).")
        # In a real implementation, this would invoke linters (e.g., flake8, eslint),
        # type checkers (e.g., mypy, tsc), or basic security scanners.
        return True, "Static checks passed (placeholder implementation)."

    def analyze_dependencies(self, file_path_str: str) -> Dict[str, Any]:
        """
        Analyzes a file to identify its dependencies (e.g., imports).
        (This is a placeholder for future implementation).
        """
        logger.debug(f"Placeholder: Analyzing dependencies for {file_path_str}")
        # In a real implementation, this would parse the file (e.g., Python AST, package.json)
        # and return structured dependency information.
        return {"path": file_path_str, "imports": ["placeholder_import1", "placeholder_import2"]}

    def get_file_summary(self, file_path_str: str, max_lines: int = 20) -> str:
        """
        Generates a brief summary of a file by extracting its first few lines.
        This is used to provide quick, high-level context without parsing the whole file.

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

    def _extract_function_details(self, node: ast.FunctionDef) -> PythonFunction:
        """
        Extracts detailed information from a Python AST FunctionDef node.

        Args:
            node: The AST node representing a function definition.

        Returns:
            A Pydantic `PythonFunction` model populated with details.
        """
        params = []
        num_defaults = len(node.args.defaults)
        num_args = len(node.args.args)
        for i, arg_node in enumerate(node.args.args):
            param_name = arg_node.arg
            annotation_str = ast.unparse(arg_node.annotation) if arg_node.annotation else None
            default_value_str = None
            default_idx = i - (num_args - num_defaults)
            if default_idx >= 0:
                try:
                    default_value_str = ast.unparse(node.args.defaults[default_idx]) # Corrected: Use node.args.defaults
                except Exception:
                    default_value_str = "COMPLEX_DEFAULT"
            params.append(PythonFunctionParam(name=param_name, default=default_value_str, type_hint=annotation_str))

        # Ensure annotation_str and default_value_str are defined before use
        # annotation_str = None # Defined inside loop
        # default_value_str = None # Defined inside loop

        decorators = [ast.unparse(d) for d in node.decorator_list]
        return_type_hint = ast.unparse(node.returns) if node.returns else None

        return PythonFunction(
            name=node.name,
            params=params,
            decorators=decorators,
            return_type_hint=return_type_hint,
            is_async=isinstance(node, ast.AsyncFunctionDef)
        )

    def _extract_class_details(self, node: ast.ClassDef) -> PythonClass:
        """
        Extracts detailed information from a Python AST ClassDef node.

        Args:
            node: The AST node representing a class definition.

        Returns:
            A Pydantic `PythonClass` model populated with details.
        """
        bases = [ast.unparse(b) for b in node.bases]
        methods = []
        attributes = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(self._extract_function_details(item)) # Corrected: Pass item
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    # Django Model Field Parsing
                    if isinstance(target, ast.Name) and isinstance(item.value, ast.Call) and \
                       isinstance(item.value.func, ast.Attribute) and \
                       isinstance(item.value.func.value, ast.Name) and item.value.func.value.id == "models":
                        # This is likely a Django model field
                        # This logic should ideally be in a more specific Django model parser
                        # but can be initiated here.
                        # For now, we'll just add it as a generic attribute.
                        # Detailed parsing will be in _parse_django_model_fields
                        pass # Handled by _parse_django_model_fields later

                    # Generic attribute parsing
                    if isinstance(target, ast.Name):
                        try:
                            value_preview = ast.unparse(item.value)[:50]
                        except Exception:
                            value_preview = "COMPLEX_VALUE"
                        # Attempt to get type hint from a preceding AnnAssign if it's a common pattern
                        # This is a simplification; full type inference is complex.
                        type_hint_str = None # Placeholder
                        attributes.append(PythonClassAttribute(name=target.id, value_preview=value_preview, type_hint=type_hint_str))
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
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
    def _determine_import_type(self, module_name: str, project_apps: Optional[List[str]] = None) -> Literal["stdlib", "third_party", "local_app", "project_app", "unknown"]:
        """
        A heuristic-based function to classify a Python import.

        Args:
            module_name: The name of the module being imported.
            project_apps: A list of known Django app names in the project.

        Returns:
            A literal string classifying the import type.
        """
        # This is a simplified heuristic. A robust solution would inspect the virtual environment.
        if not module_name:
            return "unknown"
        
        # Simplified stdlib check
        if module_name in sys.stdlib_module_names:
            return "stdlib"

        # Check for project apps (if provided)
        if project_apps:
            # Exact match for project app
            if module_name in project_apps:
                return "project_app"
            # Relative import within the same project app structure
            if module_name.startswith(".") and any(app_name in module_name for app_name in project_apps): # Heuristic
                 return "project_app" # Or "local_app" if more granular distinction is needed

        # Check for local apps (heuristic: relative import not matching known project apps)
        if module_name.startswith("."):
            return "local_app"

        # Basic third-party check (heuristic: not stdlib, not local, not project app)
        # A more robust check would involve inspecting the virtual environment.
        # For now, if it's not caught by above, assume third_party or unknown.
        # This part is complex and often requires knowledge of the venv.
        # A simple heuristic: if it's not stdlib and doesn't start with '.', it might be third-party.
        if not module_name.startswith(".") and module_name not in sys.stdlib_module_names:
            return "third_party" # Tentative

        return "unknown"
    def _parse_python_ast(self, content: str, file_path_str: str) -> Tuple[List[PythonFileImport], List[PythonFunction], List[PythonClass]]:
        """
        Parses the content of a Python file into its core components using AST.

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
                        imports.append(PythonFileImport(module=alias.name, as_name=alias.asname))
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
                    import_type = self._determine_import_type(node.module if node.module else "", project_apps=current_project_apps)
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

    def _parse_django_model_fields(self, class_node: ast.ClassDef) -> Tuple[List[DjangoModelField], Dict[str, Any]]:
        """
        Parses Django model fields and Meta class options from an AST ClassDef node.
        Captures field types, arguments (including relationships), and Meta options.
        """
        # This function iterates through the body of a class AST node to find
        # assignments that look like Django model fields (e.g., `title = models.CharField(...)`).
        # It also looks for an inner class named `Meta` to extract model metadata.
        model_fields = []
        meta_options = {}
        for item in class_node.body:
            if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                field_name = item.targets[0].id
                if isinstance(item.value, ast.Call) and \
                   isinstance(item.value.func, ast.Attribute) and \
                   hasattr(item.value.func, 'value') and isinstance(item.value.func.value, ast.Name) and \
                   item.value.func.value.id == "models":
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

                    # Handle the positional argument for relationship fields (e.g., ForeignKey(User, ...))
                    if item.value.args:
                        first_arg = item.value.args[0]
                        if isinstance(first_arg, ast.Name):
                            related_model_val = first_arg.id
                        elif isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                            related_model_val = first_arg.value
                        
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
                                 hasattr(kw_node.value, 'value') and isinstance(kw_node.value.value, ast.Name) and kw_node.value.value.id == 'models':
                                on_delete_val = f"models.{kw_node.value.attr}"
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

    def _parse_django_form_fields(self, class_node: ast.ClassDef) -> List[DjangoModelField]:
        """
        Parses explicitly defined fields from a Django Form class.
        Captures field types and arguments.
        """
        form_fields = []
        # This is similar to the model field parser but looks for `forms.FieldType`.
        for item in class_node.body:
            if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                field_name = item.targets[0].id
                if isinstance(item.value, ast.Call) and \
                   isinstance(item.value.func, ast.Attribute) and \
                   hasattr(item.value.func, 'value') and isinstance(item.value.func.value, ast.Name) and \
                   item.value.func.value.id == "forms": # Check for 'forms.CharField' etc.
                    
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
        Extracts 'model' and 'fields' attributes.
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
                        elif meta_item.targets[0].id == "fields": meta_fields = [ast.unparse(e) for e in meta_item.value.elts] if isinstance(meta_item.value, ast.List) else []
        return meta_model, meta_fields

    def parse_file(self, file_path_str: str, content: str) -> Optional[FileStructureInfo]:
        """
        Parses a file and extracts structured information based on its type.
        Uses AST for Python files and regex/BeautifulSoup for templates.
        """
        # This is the main dispatcher method for the service.
        file_info = FileStructureInfo()
        file_path = Path(file_path_str)
        filename = file_path.name.lower()
        app_name_from_path = file_path.parts[0] if len(file_path.parts) > 1 else None

        # --- Python File Parsing Logic ---
        if filename.endswith(".py"):
            # First, perform a general AST parse for any Python file.
            imports, functions, classes = self._parse_python_ast(content, file_path_str)
            py_details = PythonFileDetails(imports=imports, functions=functions, classes=classes)
            file_info.python_details = py_details # Default to python
            file_info.file_type = "python"

            # --- Django-Specific Python File Parsing ---
            if filename == "models.py":
                file_info.file_type = "django_model"
                django_models = []
                for cls in classes:
                    is_django_model = any("models.Model" in base or base == "Model" for base in cls.bases)
                    if is_django_model:
                        class_ast_node = next((n for n in ast.parse(content).body if isinstance(n, ast.ClassDef) and n.name == cls.name), None)
                        if class_ast_node:
                            model_fields_extracted, meta_options_extracted = self._parse_django_model_fields(class_ast_node)
                            django_models.append(DjangoModel(
                                name=cls.name, bases=cls.bases, methods=cls.methods, decorators=cls.decorators, # Added decorators
                                attributes=cls.attributes, django_fields=model_fields_extracted,
                                meta_options=meta_options_extracted
                            ))
                        else: # Fallback if AST node not found (should not happen)
                            django_models.append(DjangoModel(name=cls.name, bases=cls.bases, methods=cls.methods, attributes=cls.attributes))

                file_info.django_model_details = DjangoModelFileDetails(imports=imports, functions=functions, classes=classes, models=django_models)
            elif filename == "views.py":
                file_info.file_type = "django_view"
                django_views = []
                for func_node in functions: # PythonFunction objects
                    # Basic template rendering detection
                    rendered_templates_list: List[str] = []
                    context_keys: List[str] = []
                    models_q: List[str] = []
                    forms_used_list: List[str] = []
                    redirect_target_name: Optional[str] = None
                    http_methods_allowed: List[str] = []

                    # Need to parse the function body from AST to find render calls
                    func_ast_node = next((n for n in ast.parse(content).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_node.name), None)
                    if func_ast_node:
                        # Parse decorators for @require_http_methods
                        for decorator in func_ast_node.decorator_list:
                            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name) and decorator.func.id == 'require_http_methods':
                                if decorator.args and isinstance(decorator.args[0], ast.List):
                                    http_methods_allowed.extend([elt.value for elt in decorator.args[0].elts if isinstance(elt, ast.Constant)])

                        for stmt in ast.walk(func_ast_node):
                            if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Name) and stmt.func.id == 'render':
                                if len(stmt.args) > 1 and isinstance(stmt.args[1], ast.Constant) and isinstance(stmt.args[1].value, str):
                                    rendered_templates_list.append(stmt.args[1].value)
                                if len(stmt.args) > 2 and isinstance(stmt.args[2], ast.Dict):
                                    for key_node in stmt.args[2].keys:
                                        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                                            context_keys.append(key_node.value)
                            # Infer HTTP methods from request.method checks
                            elif isinstance(stmt, ast.Compare) and isinstance(stmt.left, ast.Attribute) and \
                                 isinstance(stmt.left.value, ast.Name) and stmt.left.value.id == 'request' and \
                                 stmt.left.attr == 'method':
                                for op, val_node in zip(stmt.ops, stmt.comparators):
                                    if isinstance(op, ast.Eq) and isinstance(val_node, ast.Constant) and isinstance(val_node.value, str):
                                        http_methods_allowed.append(val_node.value.upper())
                            # Parse redirects (simple string or reverse)
                            elif isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Name) and stmt.func.id == 'redirect':
                                if stmt.args:
                                    if isinstance(stmt.args[0], ast.Constant) and isinstance(stmt.args[0].value, str):
                                        redirect_target_name = stmt.args[0].value # Direct path or URL name
                                    elif isinstance(stmt.args[0], ast.Call) and isinstance(stmt.args[0].func, ast.Name) and stmt.args[0].func.id == 'reverse':
                                        if stmt.args[0].args and isinstance(stmt.args[0].args[0], ast.Constant) and isinstance(stmt.args[0].args[0].value, str):
                                            redirect_target_name = stmt.args[0].args[0].value # URL name from reverse
                            # Parse models queried
                            elif isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Attribute) and \
                                 hasattr(stmt.func.value, 'id') and isinstance(stmt.func.value, ast.Name) and \
                                 stmt.func.value.id[0].isupper() and hasattr(stmt.func, 'attr') and stmt.func.attr == 'objects': # Model.objects
                                models_q.append(stmt.func.value.id) # Store model name
                            # Parse forms used
                            elif isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call) and \
                                 isinstance(stmt.value.func, ast.Name) and (stmt.value.func.id.endswith('Form') or stmt.value.func.id.endswith('FormSet')):
                                forms_used_list.append(stmt.value.func.id)

                    # Ensure unique values and default to GET if no methods found
                    final_http_methods = list(set(http_methods_allowed)) if http_methods_allowed else ['GET']


                    django_views.append(DjangoView(
                        name=func_node.name, params=func_node.params, decorators=func_node.decorators,
                        return_type_hint=func_node.return_type_hint, is_async=func_node.is_async,
                        rendered_templates=list(set(rendered_templates_list)), context_data_keys=list(set(context_keys)),
                        models_queried=list(set(models_q)), uses_forms=list(set(forms_used_list)), redirects_to_url_name=redirect_target_name,
                        allowed_http_methods=final_http_methods
                    ))
                # TODO: Add parsing for Class-Based Views (CBVs)
                # This would involve inspecting methods like get(), post(), get_context_data(), get_template_names(), form_valid(), get_success_url()
                file_info.django_view_details = DjangoViewFileDetails(imports=imports, functions=functions, classes=classes, views=django_views)
            elif filename == "urls.py":
                file_info.file_type = "django_urls"
                app_name_match = re.search(r"app_name\s*=\s*['\"]([^'\"]+)['\"]", content)
                current_app_name_for_registry = app_name_match.group(1) if app_name_match else None
                patterns = []
                includes_parsed = []
                try:
                    url_tree = ast.parse(content)
                    for node_item in url_tree.body:
                        if isinstance(node_item, ast.Assign):
                            if any(isinstance(t, ast.Name) and t.id == "urlpatterns" for t in node_item.targets):
                                if isinstance(node_item.value, ast.List):
                                    for elt in node_item.value.elts: # elt is a path() or re_path() call
                                        if isinstance(elt, ast.Call) and hasattr(elt.func, 'id') and elt.func.id in ["path", "re_path"]:
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
                
                file_info.django_urls_details = DjangoURLConfDetails(imports=imports, functions=functions, classes=classes, app_name=current_app_name_for_registry, url_patterns=patterns, includes=includes_parsed)
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
                        explicit_fields = self._parse_django_form_fields(form_ast_node) if form_ast_node else []
                        django_forms.append(DjangoForm(
                            name=cls_node.name, bases=cls_node.bases, methods=cls_node.methods,
                            decorators=cls_node.decorators, # Added decorators
                            attributes=cls_node.attributes, meta_model=meta_model_name, meta_fields=meta_fields_list, form_fields=explicit_fields
                        ))
                file_info.django_form_details = DjangoFormFileDetails(imports=imports, functions=functions, classes=classes, forms=django_forms)
            elif filename == "admin.py":
                file_info.file_type = "django_admin"
                registered_models_parsed = []
                admin_classes_details = []
                try:
                    admin_tree = ast.parse(content)
                    for node_item in admin_tree.body:
                        if isinstance(node_item, ast.Call) and isinstance(node_item.func, ast.Attribute) and \
                           isinstance(node_item.func.value, ast.Attribute) and node_item.func.value.attr == 'site' and \
                           isinstance(node_item.func.value.value, ast.Name) and node_item.func.value.value.id == 'admin' and \
                           node_item.func.attr == 'register':
                            model_name_reg = ast.unparse(node_item.args[0]) if node_item.args else None
                            admin_class_name_reg = ast.unparse(node_item.args[1]) if len(node_item.args) > 1 else None
                            if model_name_reg:
                                registered_models_parsed.append(DjangoAdminRegisteredModel(model=model_name_reg, admin_class=admin_class_name_reg))
                except Exception as e_admin_ast:
                    logger.warning(f"Could not parse admin.py AST for registers: {e_admin_ast}")
                admin_classes_details = [DjangoAdminClass(name=cls.name, bases=cls.bases, methods=cls.methods, attributes=cls.attributes, decorators=cls.decorators) for cls in classes if "ModelAdmin" in cls.bases] # Added decorators
                file_info.django_admin_details = DjangoAdminFileDetails(imports=imports, functions=functions, classes=classes, registered_models=registered_models_parsed, admin_classes=admin_classes_details)
            elif filename == "settings.py" and app_name_from_path and self.project_root.name == app_name_from_path : # Basic check for main settings
                file_info.file_type = "django_settings"
                key_settings = {}
                try:
                    settings_tree = ast.parse(content)
                    for node_item in settings_tree.body:
                        if isinstance(node_item, ast.Assign):
                            for target in node_item.targets:
                                if isinstance(target, ast.Name):
                                    setting_name = target.id
                                    # Only parse a few key settings for now
                                    if setting_name in ["INSTALLED_APPS", "MIDDLEWARE", "DATABASES", "AUTH_USER_MODEL", "ROOT_URLCONF", "STATIC_URL", "TEMPLATES", "STATICFILES_DIRS", "MEDIA_URL", "MEDIA_ROOT", "SECRET_KEY", "DEBUG", "ALLOWED_HOSTS"]:
                                        try:
                                            key_settings[setting_name] = ast.literal_eval(node_item.value)
                                        except (ValueError, SyntaxError): # For complex values like BASE_DIR / 'db.sqlite3'
                                            key_settings[setting_name] = ast.unparse(node_item.value)
                except Exception as e_settings:
                    logger.warning(f"Could not parse settings.py AST for {file_path_str}: {e_settings}")
                file_info.django_settings_details = DjangoSettingsDetails(imports=imports, functions=functions, classes=classes, key_settings=key_settings)

            elif filename == "apps.py":
                file_info.file_type = "django_apps_config"
                # PythonFileDetails are already set if it's a .py file
                file_info.django_apps_config_details = py_details # Store general Python details
            elif filename.startswith("test_") and filename.endswith(".py"):
                file_info.file_type = "django_test"
                test_classes_parsed: List[PythonClass] = []
                for cls_node in classes: # PythonClass objects
                    if any(base == "TestCase" for base in cls_node.bases) or "Test" in cls_node.name:
                        # Filter methods to include only those starting with "test_"
                        cls_node.methods = [m for m in cls_node.methods if m.name.startswith("test_")]
                        test_classes_parsed.append(cls_node)
                
                # Store general Python details, but also specific test structure if needed
                file_info.django_test_details = DjangoTestFileDetails(imports=imports, functions=functions, classes=test_classes_parsed)
            # else: # Already defaulted to python type
            #     file_info.file_type = "python"
            #     file_info.python_details = py_details
        # --- Template and Static File Parsing Logic (Regex-based) ---
        elif filename.endswith((".html", ".htm", ".djt")):
            file_info.file_type = "template"
            extends_match = re.search(r"{%\s*extends\s*['\"]([^'\"]+)['\"]\s*%}", content, re.IGNORECASE)
            includes = re.findall(r"{%\s*include\s*['\"]([^'\"]+)['\"]\s*%}", content)
            statics = re.findall(r"{%\s*static\s*['\"]([^'\"]+)['\"]\s*%}", content)
            
            # --- Template Dependency Analysis ---
            # extends_base_html_unresolved_flag = False # This flag's logic is complex and better handled by planner
            extended_template_name = extends_match.group(1) if extends_match else None
            # if extended_template_name == "base.html":
                # This check needs the full project structure map.
                # For now, we just note it extends base.html. The WorkflowManager or Planner
                # would use this info along with the map to see if base.html exists.
                # pass # extends_base_html_unresolved_flag would be set elsewhere

            # Capture URL names from {% url 'name' ... %}
            url_names = re.findall(r"{%\s*url\s*['\"]([^'\"]+)['\"]\s*(?:[^%]*%})?", content)
            context_vars = re.findall(r"{{\s*([\w\.]+)\s*}}", content) # Basic context var extraction
            # Capture form action targets
            form_action_targets = re.findall(r"<form[^>]*action\s*=\s*['\"]([^'\"]*)['\"]", content, re.IGNORECASE)
            ids = re.findall(r"id\s*=\s*['\"]([^'\"]+)['\"]", content)
            file_info.template_details = TemplateFileDetails(
                extends_template=extends_match.group(1) if extends_match else None,
                # extends_base_html_unresolved=extends_base_html_unresolved_flag, # Removed, planner handles this
                includes_templates=includes,
                static_files_used=statics,
                url_references=url_names,
                context_variables_used=list(set(context_vars))[:20],
                form_targets=form_action_targets, # Added form_targets
                key_dom_ids=list(set(ids))[:10])
        elif filename.endswith(".js"):
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
        elif filename.endswith(".json"):
            file_info.file_type = "json_data"
            try:
                json.loads(content)
                file_info.raw_content_summary = f"JSON data file, approx {len(content)//1024}KB."
            except json.JSONDecodeError:
                file_info.raw_content_summary = "Invalid JSON file."
        elif filename.endswith((".txt", ".md", ".log", ".yaml", ".yml", ".ini", ".cfg", ".env")):
            file_info.file_type = "text"
            file_info.raw_content_summary = content[:200] + ("..." if len(content) > 200 else "")
        else:
            file_info.file_type = "unknown"
            file_info.raw_content_summary = f"Unknown file type. Size: {len(content)} bytes."
            
        # --- Scan for required URL names (simplified example) ---
        # This is a very basic scan. A more robust solution would use AST for Python files
        # and specific regex for templates.
        required_urls = set()
        if file_info.file_type == "python": # Check python_details for Python files
            if file_info.python_details:
                for imp in file_info.python_details.imports:
                    if imp.module == "django.urls" and any(n["name"] == "reverse" or n["name"] == "reverse_lazy" for n in imp.names):
                        # Found import of reverse/reverse_lazy, now look for its usage
                        # This requires deeper AST analysis of function bodies.
                        # For now, this is a placeholder for more advanced parsing.
                        pass 
                # Simplified scan for redirect('named_url')
                for func_def in file_info.python_details.functions:
                    # This would require walking the AST of the function body
                    pass
        elif file_info.file_type == "template":
            if file_info.template_details and file_info.template_details.url_references:
                for url_ref in file_info.template_details.url_references:
                    required_urls.add(url_ref.split()[0].strip("'\"")) # Get the first part (name)
        # file_info.requires_url_names = list(required_urls) # Assuming requires_url_names is added to FileStructureInfo

        return file_info

    def get_functions_in_file(self, file_path_str: str) -> List[str]: # Kept for compatibility with existing calls

        """
        A simplified legacy method to get a list of function names from a Python file.
        
        Note: This is kept for compatibility. The `parse_file` method provides
        much richer, structured data.
        """
        try:
            full_path = (self.project_root / file_path_str).resolve(strict=True)
            if not full_path.is_file() or not file_path_str.lower().endswith(".py"): return []
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            _, functions, _ = self._parse_python_ast(content, file_path_str)
            return [f.name for f in functions]
        except Exception as e:
            logger.warning(f"Legacy get_functions_in_file failed for {file_path_str}: {e}")
            return []

    def get_classes_in_file(self, file_path_str: str) -> Dict[str, List[str]]: # Kept for compatibility
        """
        A simplified legacy method to get a dictionary of class names and their methods.

        Note: This is kept for compatibility. The `parse_file` method provides
        much richer, structured data.
        """
        try:
            full_path = (self.project_root / file_path_str).resolve(strict=True)
            if not full_path.is_file() or not file_path_str.lower().endswith(".py"): return {}
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            _, _, classes = self._parse_python_ast(content, file_path_str)
            return {cls.name: [m.name for m in cls.methods] for cls in classes}
        except Exception as e:
            logger.warning(f"Legacy get_classes_in_file failed for {file_path_str}: {e}")
            return {}

    def extract_error_context(self, file_path: str, line_number: int) -> Optional[str]:
        """
        Extracts the source code of the function or class containing the error.
        This is used during remediation to provide the LLM with the precise code
        block that caused the failure, rather than the whole file.

        It walks the file's AST to find the node whose line number range
        contains the error line.
        """
        try:
            full_path = (self.project_root / file_path).resolve(strict=True)
            if not full_path.is_file():
                return None
            content = full_path.read_text(encoding='utf-8')


            try:
                tree = ast.parse(content, filename=file_path)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if node.lineno <= line_number <= (node.end_lineno or line_number):
                            # Found the containing block, return its source
                            return ast.get_source_segment(content, node)
            except SyntaxError:
                # If the file has a syntax error, ast.parse will fail.
                # Gracefully fall back to returning None, allowing the caller (RemediationManager)
                # to use a different strategy (like sending the whole file).
                logger.warning(f"Could not parse AST for {file_path} due to SyntaxError. Cannot extract surgical context.")
                return None
            
            # If no containing block is found after walking the tree
            return None        
        except Exception as e:
            logger.error(f"Failed to extract error context from {file_path}:{line_number}: {e}")
            return None


    # Add other methods as needed:
    # - parse_ast(file_path: str) -> Any
    # - find_definitions_references(file_path: str, symbol: str) -> Dict[str, List[int]]
    # - get_code_complexity(file_path: str) -> Dict[str, float]