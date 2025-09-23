<a id="core.file_system_manager"></a>

# core.file\_system\_manager

<a id="core.file_system_manager.FileSystemManager"></a>

## FileSystemManager Objects

```python
class FileSystemManager()
```

Handles file system operations (reading, writing, directory creation)
securely within a specified project root directory (a "sandbox").

This class acts as a security-hardened abstraction layer for all file
interactions. Its primary responsibility is to ensure that no operation
can access or modify files outside of the designated project root.

<a id="core.file_system_manager.FileSystemManager.__init__"></a>

#### \_\_init\_\_

```python
def __init__(project_root_path: str | Path)
```

Initializes the FileSystemManager.

**Arguments**:

- `project_root_path` - The absolute or relative path to the root directory
  for all file operations.
  

**Raises**:

- `ValueError` - If project_root_path is not provided.
- `FileNotFoundError` - If the resolved project_root_path does not exist.
- `NotADirectoryError` - If the resolved project_root_path is not a directory.

<a id="core.file_system_manager.FileSystemManager.write_file"></a>

#### write\_file

```python
def write_file(relative_path: str | Path,
               content: str,
               encoding: str = 'utf-8') -> None
```

Safely writes content to a file within the project root.

This method creates parent directories if they don't exist and overwrites any existing file.

**Arguments**:

- `relative_path` - The path relative to the project root where the file should be written.
- `content` - The string content to write to the file.
- `encoding` - The text encoding to use (defaults to 'utf-8').
  

**Raises**:

- `ValueError` - If the relative_path is invalid or outside the project root.
- `RuntimeError` - If any OS-level error occurs during directory creation or file writing.

<a id="core.file_system_manager.FileSystemManager.read_file"></a>

#### read\_file

```python
def read_file(relative_path: str | Path, encoding: str = 'utf-8') -> str
```

Safely reads content from a file within the project root.

**Arguments**:

- `relative_path` - The path relative to the project root from where the file should be read.
- `encoding` - The text encoding to use (defaults to 'utf-8').
  

**Returns**:

  The content of the file as a string.
  

**Raises**:

- `ValueError` - If the relative_path is invalid or outside the project root.
- `FileNotFoundError` - If the file does not exist at the resolved path.
- `RuntimeError` - If any other OS-level error occurs during file reading.

<a id="core.file_system_manager.FileSystemManager.create_directory"></a>

#### create\_directory

```python
def create_directory(relative_path: str | Path) -> None
```

Safely creates a directory (and any necessary parent directories) within the project root.

This method is idempotent; it does nothing if the directory already exists.

**Arguments**:

- `relative_path` - The path relative to the project root for the directory to be created.
  

**Raises**:

- `ValueError` - If the relative_path is invalid or outside the project root.
- `RuntimeError` - If any OS-level error occurs during directory creation.

<a id="core.file_system_manager.FileSystemManager.file_exists"></a>

#### file\_exists

```python
def file_exists(relative_path: str | Path) -> bool
```

Safely checks if a file exists at the given relative path within the project root.

Returns False if the path is invalid, outside the root, or doesn't point to a file.

<a id="core.file_system_manager.FileSystemManager.dir_exists"></a>

#### dir\_exists

```python
def dir_exists(relative_path: str | Path) -> bool
```

Safely checks if a directory exists at the given relative path within the project root.

Returns False if the path is invalid, outside the root, or doesn't point to a directory.

<a id="core.file_system_manager.FileSystemManager.get_directory_structure_markdown"></a>

#### get\_directory\_structure\_markdown

```python
def get_directory_structure_markdown(max_depth: int = 3,
                                     max_items_per_dir: int = 10,
                                     indent_char: str = "    ") -> str
```

Generates a Markdown representation of the project's directory structure.

This is used to provide context to the LLM about the project's layout.
Excludes common unhelpful directories like .git, .venv, venv, __pycache__, node_modules.

**Arguments**:

- `max_depth` - Maximum depth of directories to traverse.
- `max_items_per_dir` - Maximum number of files/subdirectories to list per directory.
- `indent_char` - String to use for indentation.
  

**Returns**:

  A string containing the markdown formatted directory structure.

<a id="core.file_system_manager.FileSystemManager.discover_django_apps"></a>

#### discover\_django\_apps

```python
def discover_django_apps() -> List[Path]
```

Scans the project root to find all directories that appear to be Django apps,
using the presence of an 'apps.py' file as the heuristic.

**Returns**:

  A list of Path objects, where each path is the relative path from the
  project root to a Django app.
  Returns an empty list if the project root isn't a directory or no apps are found.

<a id="core.file_system_manager.FileSystemManager.get_file_hash"></a>

#### get\_file\_hash

```python
def get_file_hash(relative_path: str | Path) -> Optional[str]
```

Calculates the SHA256 hash of a file's content.

This can be used to detect if a file has changed without reading its entire content.

**Arguments**:

- `relative_path` - The path relative to the project root.
  

**Returns**:

  The hex digest of the SHA256 hash, or None if the file
  cannot be read or an error occurs.

<a id="core.file_system_manager.FileSystemManager.delete_all_default_tests_py"></a>

#### delete\_all\_default\_tests\_py

```python
def delete_all_default_tests_py() -> bool
```

Discovers all Django apps in the project and deletes the default `tests.py`
file from each one, preparing for the custom `test/` directory structure.

Returns True if all deletions were successful (or files didn't exist), False otherwise.

<a id="core.file_system_manager.FileSystemManager.delete_file"></a>

#### delete\_file

```python
def delete_file(relative_path: str | Path) -> None
```

Safely deletes a file within the project root.

**Arguments**:

- `relative_path` - The path relative to the project root of the file to be deleted.
  

**Raises**:

- `ValueError` - If the relative_path is invalid or outside the project root.
- `FileNotFoundError` - If the file does not exist at the resolved path.
- `RuntimeError` - If any OS-level error occurs during file deletion.

<a id="core.file_system_manager.FileSystemManager.delete_default_tests_py_for_app"></a>

#### delete\_default\_tests\_py\_for\_app

```python
def delete_default_tests_py_for_app(app_name: str) -> bool
```

Deletes the default `tests.py` file from a specific Django app directory.

**Arguments**:

- `app_name` - The name of the Django app (which is also its directory name).
  

**Returns**:

  True if deletion was successful or file didn't exist, False otherwise.

<a id="core.file_system_manager.FileSystemManager.apply_xml_code_changes"></a>

#### apply\_xml\_code\_changes

```python
def apply_xml_code_changes(xml_string: str) -> List[str]
```

Parses an XML string containing one or more `<file_content>` tags
and writes the content of each to its specified file path. This is a
primary way the system applies code generated by the LLM.

**Arguments**:

- `xml_string` - A string containing XML data with <file_content> tags.

**Example**:

  <file_content path="app/views.py"><![CDATA[print("Hello")]]></file_content>
  <file_content path="app/models.py"><![CDATA[class Model...]]></file_content>
  

**Returns**:

  A list of file paths that were successfully written.
  

**Raises**:

- `RuntimeError` - If XML parsing fails or file writing fails for any file.

<a id="core.file_system_manager.FileSystemManager.backup_file"></a>

#### backup\_file

```python
def backup_file(relative_path: str | Path) -> Optional[Path]
```

Creates a backup of a file by copying it with a `.bak` extension.

This is a key part of the atomic update process, allowing for rollbacks
if a subsequent step in a multi-file change fails.

<a id="core.file_system_manager.FileSystemManager.create_snapshot"></a>

#### create\_snapshot

```python
async def create_snapshot() -> Dict[str, Dict[str, Any]]
```

Creates an in-memory snapshot of all relevant project files.

The snapshot stores each file's content and SHA256 hash. It excludes
common unnecessary files and directories (like `.git`, `venv`, `__pycache__`).

**Returns**:

  A dictionary where keys are relative file paths and values are
  dictionaries {'content': str, 'sha256': str}.

<a id="core.file_system_manager.FileSystemManager.write_snapshot"></a>

#### write\_snapshot

```python
async def write_snapshot(snapshot: Dict[str, Dict[str, Any]]) -> None
```

Writes an entire file snapshot to disk, overwriting the current project state.

This is a powerful but destructive operation. It first writes all files from
the snapshot, then deletes any files currently on disk that are *not*
present in the snapshot, ensuring the disk matches the snapshot exactly.

<a id="core.file_system_manager.FileSystemManager.apply_atomic_file_updates"></a>

#### apply\_atomic\_file\_updates

```python
def apply_atomic_file_updates(
        updates: Dict[str, str]) -> Tuple[bool, List[str], Dict[str, Path]]
```

Atomically applies a set of file updates using a two-phase approach.

1. **Backup Phase:** Creates a `.bak` backup for every file that will be modified.
2. **Write Phase:** Writes the new content for all files.
If any step fails, it automatically rolls back all changes from the backups.

**Arguments**:

- `updates` - A dictionary mapping relative file paths to their new, complete content.
  

**Returns**:

  A tuple containing:
  - A boolean indicating success.
  - A list of successfully updated file paths.
  - A dictionary mapping original paths to their backup paths.
  

**Raises**:

- `PatchApplyError` - If the operation fails.

<a id="core.file_system_manager.FileSystemManager.rollback_from_backup"></a>

#### rollback\_from\_backup

```python
def rollback_from_backup(backup_paths: Dict[str, Path]) -> None
```

Restores files from their backups. This is the recovery mechanism for
a failed atomic update.

<a id="core.file_system_manager.FileSystemManager.cleanup_backups"></a>

#### cleanup\_backups

```python
def cleanup_backups(backup_paths: Dict[str, Path]) -> None
```

Deletes backup files after a successful and verified atomic update.

This is called after the entire remediation cycle is confirmed to be successful.

<a id="core.file_system_manager.FileSystemManager.revert_patch"></a>

#### revert\_patch

```python
def revert_patch(patch: str, original_file_path: str)
```

Reverts a previously applied patch by applying it in reverse.

