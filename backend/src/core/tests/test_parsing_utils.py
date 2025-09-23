# src/core/tests/test_parsing_utils.py
import unittest
from src.core.parsing_utils import extract_file_contents_from_llm_output

class TestParsingUtils(unittest.TestCase):
    """
    Unit tests for the LLM output parsing utilities.
    """

    def setUp(self):
        """Set up for tests."""
        print(f"\n--- Running test: {self._testMethodName} ---")

    def test_extract_single_clean_file(self):
        """Test with a single, clean <file_content> tag."""
        raw_output = """<file_content path="app/views.py"><![CDATA[print("hello")]]></file_content>"""
        expected = {"app/views.py": 'print("hello")'}
        result = extract_file_contents_from_llm_output(raw_output)
        self.assertEqual(result, expected)

    def test_extract_multiple_files_with_commentary(self):
        """Test with multiple <file_content> tags surrounded by conversational text."""
        raw_output = """
        Of course! Here is the code you requested.

        <file_content path="app/views.py"><![CDATA[import os]]></file_content>

        And here is the model file.
        <file_content path="app/models.py"><![CDATA[class MyModel: pass]]></file_content>

        Let me know if you need anything else!
        """
        expected = {
            "app/views.py": "import os",
            "app/models.py": "class MyModel: pass"
        }
        result = extract_file_contents_from_llm_output(raw_output)
        self.assertEqual(result, expected)

    def test_extract_with_multiline_content(self):
        """Test with multi-line content inside the CDATA block."""
        raw_output = '''<file_content path="script.js"><![CDATA[
function hello() {
    console.log("world");
}]]></file_content>'''
        expected_content = 'function hello() {\n    console.log("world");\n}'
        expected = {"script.js": expected_content}
        result = extract_file_contents_from_llm_output(raw_output)
        self.assertEqual(result, expected)

    def test_no_files_found_in_conversational_text(self):
        """Test with raw output that contains no valid tags."""
        raw_output = "I am sorry, but I cannot fulfill this request as it violates my policy."
        expected = {}
        result = extract_file_contents_from_llm_output(raw_output)
        self.assertEqual(result, expected)

    def test_empty_cdata_is_handled(self):
        """Test with a tag that has an empty CDATA section, which is valid."""
        raw_output = '<file_content path="empty.txt"><![CDATA[]]></file_content>'
        expected = {"empty.txt": ""}
        result = extract_file_contents_from_llm_output(raw_output)
        self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()