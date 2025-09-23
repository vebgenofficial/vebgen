# Contributing to Vebgen

First off, thank you for considering contributing! Your help is appreciated and is essential for making this project better.

## How Can I Contribute?

There are many ways to contribute, from writing tutorials or improving the documentation to submitting bug reports and feature requests or writing code which can be incorporated into the Web Agent itself.

### Reporting Bugs

- **Ensure the bug was not already reported** by searching on GitHub under Issues.
- If you're unable to find an open issue addressing the problem, open a new one. Be sure to include a **title and clear description**, as much relevant information as possible, and a **code sample** or an **executable test case** demonstrating the expected behavior that is not occurring.

### Suggesting Enhancements

- Open a new issue to discuss your enhancement. Please provide a clear description of the enhancement and its potential benefits. We're particularly interested in:
  - Support for new frameworks (e.g., Vue, Svelte, FastAPI).
  - Improvements to the self-remediation logic.
  - Enhancements to the `CodeIntelligenceService`.
  - UI/UX improvements.

### Pull Requests

We love pull requests. If you're planning to contribute back to the repository, please follow these steps:

1.  Fork the repository and create your branch from `main`.
2.  Set up your development environment (see below).
3.  Make your changes. If you've added code that should be tested, please add tests.
4.  Ensure the test suite passes (`pytest`).
5.  Format your code (`black .`) and check for linting errors (`flake8 .`).
6.  Issue that pull request!

## Development Environment Setup

1.  **Fork and clone the repository:**

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

3.  **Install the project in editable mode:**

    This installs all required dependencies and makes your project's source code available in the environment. For development, include the `[dev]` extra to install tools like `pytest` and `black`.

    ```sh
    pip install -e .[dev]
    ```

## Running Tests

To run the test suite, use the following command:

```sh
pytest
```

## Code Style

### Python Styleguide

- All Python code must adhere to [PEP 8](https://www.python.org/dev/peps/pep-0008/).
- We use `black` for code formatting. Before submitting a pull request, please format your code with `black`:

  ```sh
  black .
  ```

- We use `flake8` for linting. Please ensure your changes pass the linter:

  ```sh
  flake8 .
  ```

### Git Commit Messages

- Use the present tense ("Add feature" not "Added feature").
- Use the imperative mood ("Move cursor to..." not "Moves cursor to...").
- Limit the first line to 72 characters or less.
- Reference issues and pull requests liberally after the first line.

## Code of Conduct

This project and everyone participating in it is governed by the [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior.
