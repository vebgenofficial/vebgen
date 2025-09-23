# src/core/tests/test_memory_manager.py
import unittest
import shutil
import json
from pathlib import Path

from src.core.memory_manager import MemoryManager
from src.core.project_models import ProjectState, ProjectFeature, FeatureTask, ProjectStructureMap
from src.core.llm_client import ChatMessage

class TestMemoryManager(unittest.TestCase):
    """
    Unit tests for the MemoryManager class.
    These tests verify the loading, saving, and error handling for
    project state and conversation history.
    """

    def setUp(self):
        """Set up a temporary project directory for each test."""
        self.test_dir = Path("temp_test_project_for_memory").resolve()
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir()

        self.memory_manager = MemoryManager(project_root_path=self.test_dir)
        print(f"\n--- Running test: {self._testMethodName} ---")

    def tearDown(self):
        """Clean up the temporary directory after each test."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_save_and_load_project_state(self):
        """
        Verify that a valid ProjectState object can be saved and loaded correctly.
        """
        # Arrange: Create a complex ProjectState object
        feature = ProjectFeature(id="F01", name="Test Feature", description="A feature for testing.")
        feature.tasks.append(FeatureTask(task_id_str="1.1", action="Run command", target="echo 'hello'"))
        original_state = ProjectState(
            project_name="memory_test",
            framework="django",
            root_path=str(self.test_dir),
            features=[feature],
            project_structure_map=ProjectStructureMap() # Ensure new field is present
        )

        # Act: Save and then load the state
        self.memory_manager.save_project_state(original_state)
        loaded_state = self.memory_manager.load_project_state()

        # Assert
        self.assertIsNotNone(loaded_state)
        self.assertEqual(loaded_state.project_name, original_state.project_name)
        self.assertEqual(len(loaded_state.features), 1)
        self.assertEqual(loaded_state.features[0].tasks[0].action, "Run command")
        # Verify that the new field was saved and loaded
        self.assertIsInstance(loaded_state.project_structure_map, ProjectStructureMap)

    def test_load_non_existent_state(self):
        """
        Verify that loading a non-existent state file returns None.
        """
        loaded_state = self.memory_manager.load_project_state()
        self.assertIsNone(loaded_state)

    def test_load_corrupted_state_file(self):
        """
        Verify that loading a corrupted (invalid JSON) state file returns None
        and does not crash the application.
        """
        # Arrange: Write invalid JSON to the state file
        state_file_path = self.memory_manager.storage_dir / "project_state.json"
        state_file_path.parent.mkdir(exist_ok=True)
        state_file_path.write_text("{'invalid_json': True,}") # Invalid JSON with trailing comma

        # Act & Assert
        loaded_state = self.memory_manager.load_project_state()
        self.assertIsNone(loaded_state, "Loading a corrupted state file should return None.")

    def test_load_outdated_state_file_handles_new_fields(self):
        """
        Verify that loading a state file from an older version (missing new fields)
        correctly initializes the new fields with their default values.
        """
        # Arrange: Create a state dictionary that is missing the 'project_structure_map' field
        outdated_state_dict = {
            "project_name": "outdated_project",
            "framework": "flask",
            "root_path": str(self.test_dir),
            "features": [],
            # 'project_structure_map' is intentionally missing
        }
        state_file_path = self.memory_manager.storage_dir / "project_state.json"
        state_file_path.parent.mkdir(exist_ok=True)
        state_file_path.write_text(json.dumps(outdated_state_dict))

        # Act: Load the outdated state
        loaded_state = self.memory_manager.load_project_state()

        # Assert
        self.assertIsNotNone(loaded_state)
        self.assertEqual(loaded_state.project_name, "outdated_project")
        # Check that the new field was initialized by Pydantic with its default value
        self.assertTrue(hasattr(loaded_state, 'project_structure_map'))
        self.assertIsInstance(loaded_state.project_structure_map, ProjectStructureMap)
        self.assertEqual(loaded_state.project_structure_map.apps, {}) # Should be an empty dict by default

    def test_prune_history(self):
        """
        Verify that the history pruning logic correctly keeps the first and last messages.
        """
        # Arrange: Create a history longer than the max limit (50)
        long_history: list[ChatMessage] = [
            {"role": "system", "content": "System Prompt"}
        ] + [{"role": "user", "content": f"Message {i}"} for i in range(55)]

        # Act
        pruned_history = self.memory_manager._prune_history(long_history)

        # Assert
        self.assertEqual(len(pruned_history), 50)
        self.assertEqual(pruned_history[0]['content'], "System Prompt")
        self.assertEqual(pruned_history[-1]['content'], "Message 54")
        self.assertEqual(pruned_history[1]['content'], "Message 6") # 55 - (50 - 1) = 6