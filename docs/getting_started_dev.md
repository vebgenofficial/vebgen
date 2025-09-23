# Getting Started for Developers

This guide provides a more in-depth overview of the Vebgen AI Agent for developers who want to contribute to the project.

## Architecture

The Vebgen AI Agent is built with a modular architecture to separate concerns. The main components are:

*   **UI (`backend/src/ui/`)**: The Tkinter-based graphical user interface. It communicates with the backend via a thread-safe queue to remain responsive.
*   **Core (`backend/src/core/`)**: The heart of the application, containing the main logic for the agent.
    *   `WorkflowManager`: Orchestrates the entire development process.
    *   `AgentManager`: Manages the lifecycle of the LLM agents (Tars and Case).
    *   `LLM Agents (Tars and Case)`: The AI agents that perform the planning, coding, and remediation tasks.
    *   `FileSystemManager`: Provides a sandboxed environment for file system operations.
    *   `CommandExecutor`: Safely executes shell commands.
    *   `MemoryManager`: Persists the project state to disk.
    *   `ConfigManager`: Manages the application's configuration.
*   **Plugins (`backend/src/plugins/`)**: Contains framework-specific prompts and provider configurations, making the agent highly adaptable.

## Adding Support for a New Framework

The agent is extensible through a plugin system. For detailed instructions on adding a new framework, please refer to the [Plugin System Guide](plugin_system.md).

## Extending the Agent's Capabilities

The Vebgen AI Agent is designed to be extensible. You can extend its capabilities by:

*   **Adding new tools:** You can add new tools to the agent by creating new Python files in the `backend/src/tools` directory. Each tool should be a class that inherits from the `BaseTool` class.
*   **Adding new commands:** You can add new commands to the `CommandExecutor` by adding them to the `command_blocklist.json` file.
*   **Improving the prompts:** You can improve the prompts for the Tars and Case agents by editing the `prompts.py` files in the `plugins` directory.
