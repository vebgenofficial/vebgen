# 🤝 Contributing to VebGen

Thank you for your interest in contributing to VebGen! This project thrives because of contributors like you. Whether you're fixing a bug, adding a feature, or improving documentation, your help is invaluable.

---

## 📋 Table of Contents

- [How Can I Contribute?](#-how-can-i-contribute)
- [Reporting Bugs](#-reporting-bugs)
- [Suggesting Enhancements](#-suggesting-enhancements)
- [Contributing Code](#-contributing-code)
- [Development Environment Setup](#-development-environment-setup)
- [Running Tests](#-running-tests)
- [Code Style Guidelines](#-code-style-guidelines)
- [Documentation Contributions](#-documentation-contributions)
- [Code of Conduct](#-code-of-conduct)

---

## 🎯 How Can I Contribute?

There are many ways to contribute to VebGen:

### 🐛 Report Bugs
Found a bug? Help us fix it by reporting it with details.

### ✨ Suggest Features
Have an idea? We'd love to hear it!

### 💻 Write Code
Implement features, fix bugs, or improve performance.

### 📚 Improve Documentation
Fix typos, clarify instructions, or add examples.

### 🧪 Write Tests
Increase code coverage and catch edge cases.

### 🌍 Add Framework Support
Help us support more frameworks (Vue, Svelte, FastAPI, Laravel, etc.).

### 🎨 Enhance UI/UX
Improve the desktop application's usability.

---

## 🐛 Reporting Bugs

Before reporting a bug:
1. **Search existing issues** - Check if someone already reported it
2. **Try the latest version** - The bug might already be fixed

### How to Report

Open a GitHub Issue with:

**Required Information:**
- **Title**: Clear, concise description (e.g., "Sandbox escape in file_system_manager.py")
- **VebGen Version**: Run `python -m vebgen --version`
- **Operating System**: Windows 11, macOS 14.5, Ubuntu 22.04, etc.
- **Python Version**: `python --version`
- **LLM Provider**: OpenAI, Anthropic, Google, etc.
- **Expected Behavior**: What should happen?
- **Actual Behavior**: What actually happens?
- **Steps to Reproduce**:
```text
Start VebGen with Django project
Send command: "Add blog feature"
Observe error: ...
```
- **Screenshots/Logs**: Attach error messages or screenshots

**Example Bug Report:**
Title: CASE agent fails to parse Django models with nested Meta class

Environment:
```text
VebGen: 0.3.0
OS: Windows 11 Pro
Python: 3.10.8
LLM: GPT-4o via OpenAI
```
Expected: CASE should parse the model and generate migrations

Actual: Error: "Unexpected indentation at line 15"

Steps:
```text
1. Create Django model with nested Meta class
2. Ask VebGen to "add unique_together constraint"
3. Error appears in terminal
```
Logs:
[Attach full error traceback]

---

## ✨ Suggesting Enhancements

We're particularly interested in:

### 🎯 High-Priority Areas

1. **New Framework Support**
   - Vue.js, Svelte, Angular
   - FastAPI, Laravel, Ruby on Rails
   - Next.js, Nuxt.js

2. **Self-Remediation Improvements**
   - Better error analysis
   - Smarter retry strategies
   - Root cause detection

3. **Code Intelligence Enhancements**
   - More Django constructs (current: 95+)
   - Better context caching
   - Framework-agnostic AST parsing

4. **UI/UX Improvements**
   - Dark mode theme
   - Progress visualization
   - Command history search

### How to Suggest

Open a GitHub Issue with:
- **Use Case**: Why is this enhancement needed?
- **Proposed Solution**: How would it work?
- **Alternatives**: Did you consider other approaches?
- **Benefits**: Who benefits and how?

**Example Enhancement:**
Title: Add FastAPI framework support

Use Case: FastAPI is the #1 Python web framework for APIs (45% of new projects in 2024).

Proposed Solution:
```text
1. Create backend/src/plugins/fastapi/ directory
2. Add FastAPI-specific prompts (async/await, Pydantic models)
3. Implement FastAPI construct detection in AST parser
```
Benefits:
```text
- Expands VebGen to API development (not just full-stack)
- FastAPI has 70k+ GitHub stars (high demand)
- Complements existing Django support
```
I can help: I'm willing to contribute the FastAPI plugin if given guidance!

---

## 💻 Contributing Code

### Development Workflow

1. **Fork the repository**
   Click "Fork" on GitHub, then:
   ```text
   git clone https://github.com/YOUR_USERNAME/vebgen.git
   cd vebgen
   git remote add upstream https://github.com/vebgenofficial/vebgen.git
   ```

2. **Create a feature branch**
   ```text
   git checkout -b feature/your-feature-name
   ```
   or
   ```text
   git checkout -b fix/issue-123-bug-description
   ```

3. **Make your changes**
   - Write code
   - Add tests
   - Update documentation

4. **Commit with clear messages**
   ```text
   git commit -m "Add FastAPI framework plugin"
   ```
   NOT: "fixed stuff" or "updates"

5. **Push and create Pull Request**
   ```text
   git push origin feature/your-feature-name
   ```
   Then open PR on GitHub

### Pull Request Guidelines

**Before submitting:**
- [ ] Tests pass (`pytest`)
- [ ] Code is formatted (`black .`)
- [ ] No linting errors (`flake8 .`)
- [ ] Documentation updated (if needed)
- [ ] CHANGELOG.md updated (for features/fixes)

**PR Title Format:**
- `feat: Add FastAPI framework support`
- `fix: Resolve sandbox escape in file_system_manager`
- `docs: Update CONTRIBUTING.md with new guidelines`
- `test: Add unit tests for command_executor`

**PR Description Should Include:**
- **What** - What does this PR do?
- **Why** - Why is this change needed?
- **How** - How does it work? (for complex changes)
- **Testing** - How did you test it?
- **Screenshots** (if UI changes)

---

## 🛠️ Development Environment Setup

### 1. Fork and Clone

```text
git clone https://github.com/YOUR_USERNAME/vebgen.git
cd vebgen
```

### 2. Create Virtual Environment

**Windows:**
```text
python -m venv venv
.\venv\Scripts\activate
```

**macOS/Linux:**
```text
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

Install VebGen in editable mode with dev dependencies
```text
pip install -e .[dev]
```
This installs:
- All runtime dependencies
- pytest (testing)
- black (code formatting)
- flake8 (linting)
- mypy (type checking)

### 4. Set Up API Keys

VebGen will prompt for API keys on first run
```text
python -m vebgen
```
Or set environment variables:
```text
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GOOGLE_API_KEY="..."
```

### 5. Verify Installation

Run tests
```text
pytest
```
Should see: 135+ tests passed

---

## 🧪 Running Tests

### Run All Tests

```text
pytest
```

### Run Specific Test File

```text
pytest backend/src/core/tests/test_command_executor.py
```

### Run with Coverage Report

```text
pytest --cov=backend/src/core --cov-report=html
```
Open `htmlcov/index.html` in browser

### Run Only Fast Tests (Skip Integration Tests)

```text
pytest -m "not slow"
```

### Test Guidelines

- **Unit tests** for all new functions/classes
- **Integration tests** for component interactions
- **Minimum 80% code coverage** for new code
- **Mock external APIs** (don't call real LLM APIs in tests)

---

## 📏 Code Style Guidelines

### Python Style (PEP 8)

Format code with Black
```text
black .
```
Check linting
```text
flake8 .
```
Type check (optional but recommended)
```text
mypy backend/src/core
```

### Code Standards

- **Line Length**: 88 characters (Black default)
- **Imports**: Sort with `isort`
- **Docstrings**: Google style
- **Type Hints**: Use for all functions

**Example:**
```text
def execute_command(
    command: str,
    project_root: Path,
    timeout: int = 30
) -> ExecutionResult:
    """
    Execute a shell command in the project sandbox.

    Args:
        command: Shell command to execute
        project_root: Root directory of the project
        timeout: Maximum execution time in seconds

    Returns:
        ExecutionResult with stdout, stderr, and exit code

    Raises:
        SecurityError: If command is blocked
        TimeoutError: If command exceeds timeout
    """
    # Implementation here
```

### Git Commit Messages

**Format:**
```
<type>: <subject>

<body (optional)>
<footer (optional)>
```
Types:
```text
feat: New feature
fix: Bug fix
docs: Documentation changes
style: Code formatting (no logic change)
refactor: Code restructuring (no behavior change)
test: Adding or updating tests
chore: Build process, dependencies
```
Examples:
```text
feat: Add FastAPI framework plugin

Implements FastAPI support with:
- FastAPI-specific prompts
- Async/await construct detection
- Pydantic model parsing

Closes #123
```
---
```text
fix: Resolve sandbox escape via Unicode normalization

Normalize all paths with NFC before validation to prevent
bypassing directory traversal checks with Unicode tricks.

CVE-2025-XXXXX
```

## 📚 Documentation Contributions
Documentation is just as important as code! Help us by:

### Fixing Typos/Grammar
- Edit files directly on GitHub
- Submit PR with `docs:` prefix

### Adding Examples
- Real-world use cases
- Code snippets
- Screenshots

### Improving Clarity
- Simplify complex explanations
- Add diagrams (Mermaid supported!)
- Break up long paragraphs

### Documentation Files
- `README.md` - Project overview
- `docs/ARCHITECTURE.md` - System architecture
- `docs/*.md` - Component documentation (15 files)
- `CONTRIBUTING.md` - This file
- `SECURITY.md` - Security policy

Before editing documentation:
- Read `ARCHITECTURE.md` to understand the system
- Follow existing formatting style
- Test Markdown rendering on GitHub

## 📜 Code of Conduct
This project follows the Contributor Covenant Code of Conduct.

By participating, you agree to:
- Be respectful and inclusive
- Accept constructive feedback
- Focus on what's best for the community

Report violations: vebgenofficial@gmail.com

## 🙏 Thank You!
Every contribution matters - whether it's a typo fix, a bug report, or a major feature. Thank you for making VebGen better!

Questions? Join our GitHub Discussions

Happy coding! 🚀

Last updated: October 26, 2025
