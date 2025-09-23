<a id="core.patch_generator"></a>

# core.patch\_generator

<a id="core.patch_generator.PatchGenerator"></a>

## PatchGenerator Objects

```python
class PatchGenerator()
```

Generates a diff patch using Python's standard difflib library, ensuring
compatibility with the patch application logic.

<a id="core.patch_generator.PatchGenerator.create_diff"></a>

#### create\_diff

```python
@staticmethod
def create_diff(original_content: str, new_content: str,
                file_path: str) -> str
```

Compares the original and new content and returns a patch string
in the standard unified diff format.

**Arguments**:

- `original_content` - The original content of the file as a string.
- `new_content` - The new, corrected content of the file as a string.
- `file_path` - The path to the file, used in the diff header.
  

**Returns**:

  A string containing the patch in unified diff format, or an empty string
  if there are no differences.

