<a id="core.parsing_utils"></a>

# core.parsing\_utils

<a id="core.parsing_utils.extract_file_contents_from_llm_output"></a>

#### extract\_file\_contents\_from\_llm\_output

```python
def extract_file_contents_from_llm_output(raw_output: str) -> Dict[str, str]
```

Robustly extracts one or more file contents from a raw LLM output string.

This function is designed to parse a string that may contain conversational
text or markdown surrounding one or more XML-like `<file_content>` tags.
It specifically looks for tags with a 'path' attribute and a CDATA block
containing the file's code, making it resilient to messy LLM responses.

**Arguments**:

- `raw_output` - The potentially messy string response from the LLM, which
  may contain code blocks wrapped in <file_content> tags.
  

**Returns**:

  A dictionary mapping each file path to its corresponding string content.
  Returns an empty dictionary if no valid tags are found.

