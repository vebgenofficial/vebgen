# backend/src/core/tests/test_project_models.py
import pytest
import json
from pydantic import ValidationError

# Import the models to be tested
from src.core.project_models import (
    FeatureTask,
    ProjectFeature,
    ProjectState,
    FeatureStatusEnum,
    APIContractField,
    DjangoModel,
    DjangoModelField,
)

# --- Test Cases for FeatureTask ---

class TestFeatureTask:
    """Tests for the FeatureTask Pydantic model, focusing on validation."""

    def test_task_creation_success(self):
        """Tests successful creation of a FeatureTask with valid data."""
        task_data = {
            "task_id_str": "1.1",
            "action": "Create file",
            "target": "app/models.py",
            "description": "Create the user model.",
            "dependencies": ["1.0"]
        }
        task = FeatureTask(**task_data)
        assert task.task_id_str == "1.1"
        assert task.action == "Create file"
        assert task.dependencies == ["1.0"]

    def test_task_creation_missing_required_fields(self):
        """Tests that ValidationError is raised for missing required fields."""
        with pytest.raises(ValidationError, match="task_id_str"):
            FeatureTask(action="Create file", target="a.txt")

        with pytest.raises(ValidationError, match="action"):
            FeatureTask(task_id_str="1.1", target="a.txt")

        with pytest.raises(ValidationError, match="target"):
            FeatureTask(task_id_str="1.1", action="Create file")

    def test_invalid_action_fails(self):
        """Tests that an action not in the Literal type raises a ValidationError."""
        # The error message for a Literal mismatch includes the allowed values.
        # This regex is more specific to the expected Pydantic error.
        with pytest.raises(ValidationError, match="Input should be .* 'Create file'|'Modify file'"):
            FeatureTask(task_id_str="1.1", action="Invalid Action", target="a.txt")

    @pytest.mark.parametrize("dep_input, expected_output", [
        ("1.1, 1.2", ["1.1", "1.2"]),
        ("depends_on: 2.1, 2.2", ["2.1", "2.2"]),
        ("3.1 (Create model), 3.2", ["3.1", "3.2"]),
        ("None", []),
        (None, []),
        ([4.1, "4.2"], ["4.1", "4.2"]),
        (["5.1", "invalid_id", "5.2"], ["5.1", "5.2"]),  # The validator should filter out invalid formats like "invalid_id"
    ])
    def test_dependency_validator(self, dep_input, expected_output):
        """Tests the dependency validator with various input formats."""
        task = FeatureTask(
            task_id_str="10.1",
            action="Create file",
            target="a.txt", # The target is required but not relevant to this specific test
            dependencies=dep_input
        )
        assert task.dependencies == expected_output

    def test_default_test_step_validator(self):
        """Tests that a default test step is added if one isn't provided."""
        # Task with no test_step should get a default
        task1 = FeatureTask(task_id_str="1.1", action="Create file", target="a.txt")
        assert task1.test_step == 'echo "Default test step - Check manually"'

        # Task with an explicit test_step should keep it
        task2 = FeatureTask(
            task_id_str="1.2",
            action="Run command",
            target="python manage.py check",
            test_step="python manage.py check"
        )
        assert task2.test_step == "python manage.py check"

        # 'Prompt user input' action should not get a default test step
        task3 = FeatureTask(task_id_str="1.3", action="Prompt user input", target="API_KEY")
        assert task3.test_step is None


# --- Test Cases for ProjectState ---

class TestProjectState:
    """Tests for the root ProjectState model and its methods."""

    def test_project_state_creation_and_get_feature(self):
        """Tests creating a ProjectState and using the get_feature_by_id helper."""
        feature1 = ProjectFeature(id="feat_1", name="Feature One", description="First feature")
        feature2 = ProjectFeature(id="feat_2", name="Feature Two", description="Second feature")
        state = ProjectState(
            project_name="test_proj",
            framework="django",
            root_path="/fake/path",
            features=[feature1, feature2],
            current_feature_id="feat_1"
        )

        assert state.get_feature_by_id("feat_1") == feature1
        assert state.get_feature_by_id("feat_2") is not None
        assert state.get_feature_by_id("non_existent") is None

    def test_serialization_and_deserialization(self):
        """
        Tests that the state can be dumped to a dict/JSON and loaded back,
        correctly handling types like `set`.
        """
        state = ProjectState(
            project_name="test_proj",
            framework="django",
            root_path="/fake/path",
            registered_apps={"app1", "app2"} # Use a set
        )

        # Pydantic's model_dump with mode='json' handles sets correctly
        state_dict = state.model_dump(mode='json')
        assert isinstance(state_dict["registered_apps"], list) # Set is converted to list for JSON

        # Simulate saving and loading
        json_str = json.dumps(state_dict)
        loaded_dict = json.loads(json_str)

        # Load back into a Pydantic model
        loaded_state = ProjectState.model_validate(loaded_dict)
        assert isinstance(loaded_state.registered_apps, set) # List is converted back to set
        assert loaded_state.registered_apps == {"app1", "app2"}


# --- Test Cases for ForwardRef and Nested Models ---

class TestRecursiveModels:
    """Tests models that use ForwardRef for self-referencing."""

    def test_recursive_api_contract_field(self):
        """
        Tests that a nested APIContractField can be created, which relies on
        the ForwardRef and model_rebuild() logic.
        """
        nested_field_data = {
            "name": "user",
            "type": "object",
            "properties": {
                "id": {"name": "id", "type": "integer"},
                "name": {"name": "name", "type": "string"}
            }
        }
        field = APIContractField(**nested_field_data)
        assert isinstance(field.properties, dict)
        assert isinstance(field.properties["id"], APIContractField)
        assert field.properties["id"].type == "integer"


# --- Test Cases for Django-specific Models ---

class TestDjangoModels:
    """A simple test to ensure Django-specific models can be instantiated."""

    def test_django_model_creation(self):
        """Tests creating a DjangoModel instance."""
        field = DjangoModelField(name="title", field_type="CharField", max_length=200)
        model = DjangoModel(
            name="Post",
            bases=["models.Model"],
            django_fields=[field],
            meta_options={"ordering": ["-created_at"]}
        )
        assert model.name == "Post"
        assert model.django_fields[0].name == "title"
        assert model.meta_options["ordering"] == ["-created_at"]