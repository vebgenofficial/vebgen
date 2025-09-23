<a id="core.code_intelligence_service"></a>

# core.code\_intelligence\_service

<a id="core.code_intelligence_service.CodeIntelligenceService"></a>

## CodeIntelligenceService Objects

```python
class CodeIntelligenceService()
```

Provides advanced code analysis by parsing source files into structured data models.

This service uses Abstract Syntax Trees (AST) for Python files to understand their
structure, including classes, functions, imports, and framework-specific details
(like Django models and views). For other file types (HTML, CSS, JS), it uses
regular expressions for a more basic level of analysis. The goal is to provide
rich, structured context to the AI agents.

<a id="core.code_intelligence_service.CodeIntelligenceService.run_static_checks"></a>

#### run\_static\_checks

```python
def run_static_checks(file_paths: List[str]) -> Tuple[bool, str]
```

Runs static code analysis (linting, type checking, basic security scans) on specified files.
(This is a placeholder for future implementation).

<a id="core.code_intelligence_service.CodeIntelligenceService.analyze_dependencies"></a>

#### analyze\_dependencies

```python
def analyze_dependencies(file_path_str: str) -> Dict[str, Any]
```

Analyzes a file to identify its dependencies (e.g., imports).
(This is a placeholder for future implementation).

<a id="core.code_intelligence_service.CodeIntelligenceService.get_file_summary"></a>

#### get\_file\_summary

```python
def get_file_summary(file_path_str: str, max_lines: int = 20) -> str
```

Generates a brief summary of a file by extracting its first few lines.
This is used to provide quick, high-level context without parsing the whole file.

**Arguments**:

- `file_path_str` - The relative path to the file.
- `max_lines` - The maximum number of lines to include in the summary.
  

**Returns**:

  A string containing the first `max_lines` of the file, or an error message.

<a id="core.code_intelligence_service.CodeIntelligenceService.parse_file"></a>

#### parse\_file

```python
def parse_file(file_path_str: str,
               content: str) -> Optional[FileStructureInfo]
```

Parses a file and extracts structured information based on its type.
Uses AST for Python files and regex/BeautifulSoup for templates.

<a id="core.code_intelligence_service.CodeIntelligenceService.get_functions_in_file"></a>

#### get\_functions\_in\_file

```python
def get_functions_in_file(file_path_str: str) -> List[str]
```

A simplified legacy method to get a list of function names from a Python file.

Note: This is kept for compatibility. The `parse_file` method provides
much richer, structured data.

<a id="core.code_intelligence_service.CodeIntelligenceService.get_classes_in_file"></a>

#### get\_classes\_in\_file

```python
def get_classes_in_file(file_path_str: str) -> Dict[str, List[str]]
```

A simplified legacy method to get a dictionary of class names and their methods.

Note: This is kept for compatibility. The `parse_file` method provides
much richer, structured data.

<a id="core.code_intelligence_service.CodeIntelligenceService.extract_error_context"></a>

#### extract\_error\_context

```python
def extract_error_context(file_path: str, line_number: int) -> Optional[str]
```

Extracts the source code of the function or class containing the error.
This is used during remediation to provide the LLM with the precise code
block that caused the failure, rather than the whole file.

It walks the file's AST to find the node whose line number range
contains the error line.

