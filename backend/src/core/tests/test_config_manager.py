# c/Users/USER/Documents/webagent/vebgen sharp updated/backend/src/core/tests/test_config_manager.py
import pytest
import json
from pathlib import Path
from unittest.mock import patch
from typing import Generator

from src.core.config_manager import ConfigManager, FrameworkPrompts
from src.core.llm_client import ChatMessage

# --- Test Fixtures ---

@pytest.fixture
def mock_plugins_dir(tmp_path: Path) -> Path:
    """Creates a mock plugins directory structure for testing."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()

    # 1. Valid Django plugin
    django_dir = plugins_dir / "django"
    django_dir.mkdir()
    (django_dir / "__init__.py").touch()
    django_prompts_content = """
from src.core.config_manager import FrameworkPrompts

django_prompts = FrameworkPrompts(
    system_tars_markdown_planner={"role": "system", "content": "You are a Django planner."},
    system_case_executor={"role": "system", "content": "You are a Django executor."},
    system_tars_validator={"role": "system", "content": "You are a Django validator."},
    system_tars_error_analyzer={"role": "system", "content": "You are a Django error analyzer."}
)
"""
    (django_dir / "prompts.py").write_text(django_prompts_content)

    # 2. Invalid Flask plugin (missing __init__.py)
    flask_dir = plugins_dir / "flask"
    flask_dir.mkdir()
    (flask_dir / "prompts.py").write_text("# Flask prompts")

    # 3. Valid React plugin with a malformed prompts.py (missing required prompt)
    react_dir = plugins_dir / "react"
    react_dir.mkdir()
    (react_dir / "__init__.py").touch()
    react_prompts_content_bad = """
from src.core.config_manager import FrameworkPrompts

react_prompts = FrameworkPrompts(
    system_tars_markdown_planner={"role": "system", "content": "You are a React planner."},
    # Missing system_case_executor and others
    system_tars_validator={"role": "system", "content": "You are a React validator."}
)
"""
    (react_dir / "prompts.py").write_text(react_prompts_content_bad)

    # 4. Valid Node plugin with prompts variable named incorrectly
    node_dir = plugins_dir / "node"
    node_dir.mkdir()
    (node_dir / "__init__.py").touch()
    node_prompts_content_wrong_var = """
from src.core.config_manager import FrameworkPrompts

wrong_name_prompts = FrameworkPrompts(
    system_tars_markdown_planner={"role": "system", "content": "You are a Node planner."},
    system_case_executor={"role": "system", "content": "You are a Node executor."},
    system_tars_validator={"role": "system", "content": "You are a Node validator."},
    system_tars_error_analyzer={"role": "system", "content": "You are a Node error analyzer."}
)
"""
    (node_dir / "prompts.py").write_text(node_prompts_content_wrong_var)

    return plugins_dir

@pytest.fixture
def mock_providers_config(tmp_path: Path):
    """Creates a mock providers.json file."""
    providers_content = {
        "openai": {
            "display_name": "OpenAI",
            "models": ["gpt-4", "gpt-3.5-turbo"]
        },
        "google": {
            "display_name": "Google",
            "models": ["gemini-pro"]
        },
        "openrouter": {
            "display_name": "OpenRouter",
            "client_config": {"model_prefix": "openrouter/"},
            "models": ["google/gemini-flash-1.5"]
        }
    }
    # The config manager looks for providers.json in src/core, so we replicate that
    core_dir = tmp_path / "src" / "core"
    core_dir.mkdir(parents=True)
    providers_file = core_dir / "providers.json"
    providers_file.write_text(json.dumps(providers_content))
    return tmp_path / "src"

# --- Test Cases ---

class TestConfigManagerInitialization:
    """Tests for the initialization logic of ConfigManager."""

    def test_init_with_default_path(self, mock_providers_config: Path):
        """Tests initialization when plugins_dir is not provided."""
        # To test the default path, we need to patch where the ConfigManager *thinks* it is.
        # We patch its `__file__` attribute to point inside our mock `src` directory.
        with patch('src.core.config_manager.__file__', str(mock_providers_config / 'core' / 'config_manager.py')):
             # Now, when we initialize without a plugins_dir, it will correctly find
             # the mock providers relative to its patched location.
             manager = ConfigManager()
             assert manager.plugins_dir.name == "plugins"
             assert manager.providers_config is not None
             assert "openai" in manager.providers_config

    def test_init_with_custom_path(self, mock_plugins_dir: Path, mock_providers_config: Path):
        """Tests initialization with an explicitly provided plugins directory."""
        manager = ConfigManager(plugins_dir=mock_plugins_dir)
        assert manager.plugins_dir == mock_plugins_dir

    def test_init_with_nonexistent_plugins_dir(self, tmp_path: Path):
        """Tests that initialization does not fail if the plugins directory is missing."""
        non_existent_path = tmp_path / "non_existent_plugins"
        # Should log a warning but not raise an error
        manager = ConfigManager(plugins_dir=non_existent_path)
        assert not manager.get_available_frameworks()

    def test_init_with_missing_providers_config(self, tmp_path: Path):
        """Tests that initialization handles a missing providers.json file gracefully."""
        manager = ConfigManager(plugins_dir=tmp_path)
        assert manager.providers_config == {}


class TestFrameworkDiscovery:
    """Tests for get_available_frameworks method."""

    def test_get_available_frameworks_success(self, mock_plugins_dir: Path):
        """Tests that valid frameworks are discovered and invalid ones are ignored."""
        manager = ConfigManager(plugins_dir=mock_plugins_dir)
        frameworks = manager.get_available_frameworks()
        
        # django, react, and node are valid plugins
        assert len(frameworks) == 3
        assert "django" in frameworks
        assert "react" in frameworks
        assert "node" in frameworks
        # flask is invalid because it's missing __init__.py
        assert "flask" not in frameworks

    def test_get_available_frameworks_no_plugins(self, tmp_path: Path):
        """Tests behavior with an empty plugins directory."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        manager = ConfigManager(plugins_dir=plugins_dir)
        frameworks = manager.get_available_frameworks()
        assert frameworks == []


class TestPromptLoading:
    """Tests for the load_prompts method."""

    @pytest.fixture
    def manager(self, mock_plugins_dir: Path) -> ConfigManager:
        """Provides a ConfigManager instance pointing to the mock plugins directory."""
        # The 'src' dir needs to be on the path for the plugin's imports to work.
        # The manager handles this, but we need to give it the correct base path.
        src_dir = mock_plugins_dir.parent
        return ConfigManager(plugins_dir=src_dir / "plugins")

    def test_load_prompts_success(self, manager: ConfigManager):
        """Tests successfully loading a valid prompts file."""
        prompts = manager.load_prompts("django")
        assert isinstance(prompts, FrameworkPrompts)
        assert prompts.system_tars_markdown_planner["content"] == "You are a Django planner."

    def test_load_prompts_framework_not_found(self, manager: ConfigManager):
        """Tests loading a non-existent framework."""
        with pytest.raises(ValueError, match="prompts file not found"):
            manager.load_prompts("non_existent_framework")

    def test_load_prompts_missing_variable(self, manager: ConfigManager):
        """Tests loading a prompts file that is missing the correctly named variable."""
        with pytest.raises(ValueError, match="Variable 'node_prompts' not found"):
            manager.load_prompts("node")

    def test_load_prompts_invalid_structure(self, manager: ConfigManager):
        """Tests loading a prompts file with an invalid FrameworkPrompts structure."""
        # The 'react' plugin fixture is set up with missing required prompts, which causes a TypeError on instantiation.
        with pytest.raises(ValueError, match="Invalid prompts data or module for framework 'react'"):
            manager.load_prompts("react")

    def test_load_prompts_import_error_in_plugin(self, manager: ConfigManager, mock_plugins_dir: Path):
        """Tests that an ImportError within the plugin's prompts.py is handled."""
        # Create a plugin with a bad import
        bad_import_dir = mock_plugins_dir / "bad_import"
        bad_import_dir.mkdir()
        (bad_import_dir / "__init__.py").touch()
        (bad_import_dir / "prompts.py").write_text("from non_existent_module import something")

        with pytest.raises(ValueError, match="Invalid prompts data or module"):
            manager.load_prompts("bad_import")


class TestProviderConfig:
    """Tests for provider and model configuration methods."""

    @pytest.fixture
    def manager(self, mock_providers_config: Path) -> Generator[ConfigManager, None, None]:
        """Provides a ConfigManager instance pointing to the mock providers config."""
        # The manager's __init__ logic finds providers.json relative to its own file location.
        # We patch its `__file__` attribute to point inside our mock `src` directory.
        with patch('src.core.config_manager.__file__', str(mock_providers_config / 'core' / 'config_manager.py')):
            yield ConfigManager()

    def test_get_providers(self, manager: ConfigManager):
        """Tests retrieving the list of provider display names."""
        providers = manager.get_providers()
        assert providers == {
            "all": "All",
            "openai": "OpenAI",
            "google": "Google",
            "openrouter": "OpenRouter"
        }

    def test_get_models_for_specific_provider(self, manager: ConfigManager):
        """Tests retrieving models for a single provider."""
        models = manager.get_models_for_provider("openai")
        assert len(models) == 2
        model_ids = {m['id'] for m in models}
        assert "gpt-4" in model_ids
        assert "gpt-3.5-turbo" in model_ids

    def test_get_models_for_all_providers(self, manager: ConfigManager):
        """Tests retrieving all models from all providers."""
        models = manager.get_models_for_provider("all")
        assert len(models) == 4
        model_ids = {m['id'] for m in models}
        assert "gpt-4" in model_ids
        assert "gemini-pro" in model_ids
        assert "openrouter/google/gemini-flash-1.5" in model_ids # Check prefix

    def test_get_models_for_provider_with_prefix(self, manager: ConfigManager):
        """Tests that the model prefix from the config is correctly applied."""
        models = manager.get_models_for_provider("openrouter")
        assert len(models) == 1
        assert models[0]['id'] == "openrouter/google/gemini-flash-1.5"
        assert models[0]['display'] == "google/gemini-flash-1.5 - OpenRouter"

    def test_get_models_for_nonexistent_provider(self, manager: ConfigManager):
        """Tests retrieving models for a provider that doesn't exist."""
        models = manager.get_models_for_provider("nonexistent")
        assert models == []