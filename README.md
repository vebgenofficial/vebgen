# Vebgen AI Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/vebgenofficial/vebgen/blob/main/LICENSE)

[![Contributions Welcome](https://img.shields.io/badge/Contributions-welcome-brightgreen.svg?style=flat)](CONTRIBUTING.md)

**Vebgen** is a sophisticated, AI-powered software engineering agent designed to autonomously plan and execute development tasks. Given a high-level prompt, it generates a detailed implementation plan, writes code, runs commands, and even attempts to debug its own errors, all within a secure, sandboxed desktop application.

![Vebgen Application Demo](./docs/assets/VebGen%20Gif.gif)

---

## Table of Contents

- [How It Works](#how-it-works)
- [Key Features](#key-features)
- [Architecture Overview](#architecture-overview)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Configuration](#configuration)
  - [Running the Application](#running-the-application)
- [For Developers](#for-developers)
  - [Development Setup](#development-setup)
  - [Running Tests](#running-tests)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [Roadmap](#roadmap)
- [Community](#community)
- [Security](#security)
- [License](#license)

## How It Works

Vebgen operates through a cyclical process of planning, execution, and self-correction, driven by two primary AI personas:

1.  **Feature Identification (Tars)**: The user provides a high-level prompt. An AI agent named **Tars** analyzes this prompt to identify distinct, actionable software features.
2.  **Detailed Planning (Tars)**: For each feature, Tars generates a granular, step-by-step Markdown plan. This plan breaks the feature down into atomic tasks like creating files, modifying code, or running commands, complete with dependencies and validation steps.
3.  **Task Execution (Case & CommandExecutor)**: The `WorkflowManager` executes each task in the plan.
    -   For coding tasks, an AI agent named **Case** writes the necessary code.
    -   For command tasks, the security-hardened `CommandExecutor` runs the command.
4.  **Validation**: After each task, a predefined `test_step` is executed to verify its success.
5.  **Self-Remediation (Tars & Case)**: If a task or its test fails, the `RemediationManager` is invoked. Tars analyzes the error, and Case generates a patch to fix it. The original task is then re-attempted.
6.  **Cycle Completion**: The cycle repeats until all features are successfully implemented and merged.

## Key Features

*   **🤖 Autonomous Planning & Execution**: Takes high-level prompts and breaks them down into a granular, executable Markdown plan.
*   **🛠️ Advanced Self-Remediation**: When a command or test fails, the agent analyzes the error, formulates a hypothesis, and generates a patch to fix the bug.
*   **🔒 Secure by Design**: All file system operations are sandboxed, and command execution is restricted by a strict whitelist. API keys are stored securely in the OS keychain.
*   **🔌 Extensible Plugin System**: Easily add support for new frameworks or LLM providers by adding configuration files to the `plugins` directory.
*   **🧠 Deep Code Intelligence**: Uses Abstract Syntax Trees (AST) to parse and understand the structure of your Python code, providing richer context to the AI.
*   **🖥️ Desktop UI**: A user-friendly Tkinter-based interface to manage projects, select models, and interact with the agent.

## Architecture Overview

The application is built with a modular architecture to separate concerns. For a more detailed explanation of the architecture, please see the [Architecture Deep Dive](docs/architecture.md).

*   **UI (`backend/src/ui/`)**: The Tkinter-based graphical user interface. It communicates with the backend via a thread-safe queue to remain responsive.
*   **Core (`backend/src/core/`)**: The heart of the application, containing the main logic for the agent.
    -   `WorkflowManager`: Orchestrates the entire development process.
    -   `AgentManager`: Manages the lifecycle of the LLM agents (Tars and Case).
    -   `LLM Agents (Tars and Case)`: The AI agents that perform the planning, coding, and remediation tasks.
    -   `FileSystemManager`: Provides a sandboxed environment for file system operations.
    -   `CommandExecutor`: Safely executes shell commands.
    -   `MemoryManager`: Persists the project state to disk.
    -   `ConfigManager`: Manages the application's configuration.
*   **Plugins (`backend/src/plugins/`)**: Contains framework-specific prompts and provider configurations, making the agent highly adaptable.

## Getting Started

### Prerequisites

*   Python 3.10 or higher
*   An API key from an LLM provider (e.g., OpenRouter, OpenAI, Google).

### Installation

1.  **Clone the repository:**
    ```sh
    git clone https://github.com/vebgenofficial/vebgen.git
    cd vebgen
    ```

2.  **Create and activate a virtual environment:**
    ```sh
    # For Windows
    python -m venv venv
    .\venv\Scripts\activate

    # For macOS/Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install the project and its dependencies:**

    The recommended way to install the project is using `pip` in editable mode. This installs all required dependencies and makes your project's source code available in the environment.

    ```sh
    pip install -e .
    ```

### Configuration

Upon first run, the application will prompt you for any required API keys. These keys are stored securely in your operating system's credential manager (e.g., Windows Credential Manager, macOS Keychain). You can manage these keys later from the `Settings` > `Manage API Keys...` menu.

### Running the Application

1.  **Launch the UI:**

    Once the project is installed (using `pip install -e .`), you can launch the application by simply running the `vebgen` command in your terminal:
    ```sh
    vebgen
    ```

2.  **Select Project Directory**: From the `File` menu, choose "Select Project Directory...".
    - For a **new project**, select an **empty** folder and ensure the "New Project" checkbox is ticked.
    - For an **existing project**, select the project's root folder and uncheck the "New Project" box.

3.  **Configure Agents**:
    - Select a framework (e.g., "django").
    - Select an API Provider and Model (e.g., OpenRouter and `deepseek/deepseek-chat-v3-0324:free`).

4.  **Enter a Prompt**: In the prompt box, type a high-level goal for your project.
    > **Example Prompt:** `Create a simple calculator web application that can add two numbers.`

5.  **Start the Agent**: Click the "Start" button and watch the agent plan and execute the tasks in the "Updates / Logs" tab.

## For Developers

### Development Setup

If you want to contribute to the development of Vebgen, you should install the project in editable mode with the `[dev]` extra. This will install all base dependencies plus the tools needed for testing and development, like `pytest`.

```sh
pip install -e .[dev]
```

### Running Tests

The test suite uses `pytest` for test discovery and execution. To run all tests, navigate to the project root directory and run:

```sh
pytest
```

## Documentation

- [API Reference](docs/api/README.md)
- [Architecture Deep Dive](docs/architecture.md)
- Core Components
  - [`WorkflowManager`](docs/api/core/workflow_manager.md)
  - [`AgentManager`](docs/api/core/agent_manager.md)
  - [`MemoryManager`](docs/api/core/memory_manager.md)
  - [`ConfigManager`](docs/api/core/config_manager.md)
  - [`FileSystemManager`](docs/api/core/file_system_manager.md)
  - [`CommandExecutor`](docs/api/core/command_executor.md)
  - [`RemediationManager`](docs/api/core/remediation_manager.md)
- [Plugin System](docs/plugin_system.md)

## Contributing

Contributions are welcome! Whether it's adding support for a new framework, improving the self-remediation logic, or fixing a bug, we'd love your help. Please read our [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to get started.

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).

## Roadmap

*   [ ] Enhance the `CodeIntelligenceService` to support more languages and provide deeper analysis.
*   [ ] Implement a more sophisticated UI for visualizing the task dependency graph.
*   [ ] Add support for running the agent headlessly from the command line.
*   [ ] Integrate with version control systems more deeply (e.g., automatic feature branching).
*   [ ] Package the application for easy distribution (e.g., PyPI, standalone executables).
*   [ ] Improve the testing framework and increase test coverage.

## Community

*   **Issue Tracker**: If you find a bug or have a feature request, please open an issue on our [GitHub Issues](https://github.com/vebgenofficial/vebgen/issues) page.
*   **Discussion Forum**: Join our [GitHub Discussions](https://github.com/vebgenofficial/vebgen/discussions) to ask questions, share ideas, and connect with other users and contributors.

## Security

For information on how to report security vulnerabilities, please see our [Security Policy](SECURITY.md).

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.