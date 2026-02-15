# Contributing to pg_plan_alternatives

Thank you for your interest in contributing to pg_plan_alternatives! This document provides guidelines for contributing to the project.

## Development Setup

1. Clone the repository:
```bash
git clone https://github.com/jnidzwetzki/pg_plan_alternatives.git
cd pg_plan_alternatives
```

2. Install development dependencies:
```bash
pip install -r requirements_dev.txt
pip install -e .
```

3. Install system dependencies (BCC, PostgreSQL with debug symbols):
```bash
# See INSTALL.md for detailed instructions
sudo apt-get install bpfcc-tools python3-bpfcc postgresql-16-dbgsym
```

## Code Style

- Python code should follow PEP 8 style guidelines
- C code should follow the Google C++ Style Guide (enforced by .clang-format)
- Use meaningful variable names and add comments for complex logic

### Running Linters

```bash
# Python linting
pylint src/pg_plan_alternatives/

# Format C code
clang-format -i src/pg_plan_alternatives/bpf/*.c
```

## Testing

Run the test suite before submitting changes:

```bash
# Run tests
python -m pytest tests/ -v

# Or using unittest
PYTHONPATH=src python -m unittest discover tests/
```

## Making Changes

1. Create a new branch for your feature or bugfix:
```bash
git checkout -b feature/my-new-feature
```

2. Make your changes, ensuring:
   - Code follows the style guidelines
   - Tests pass
   - New features include tests
   - Documentation is updated

3. Commit your changes with clear, descriptive messages:
```bash
git commit -m "Add feature: description of what was added"
```

4. Push your branch and create a pull request:
```bash
git push origin feature/my-new-feature
```

## Pull Request Guidelines

- Provide a clear description of the changes
- Reference any related issues
- Ensure all tests pass
- Update documentation as needed
- Keep changes focused and atomic

## Reporting Bugs

When reporting bugs, please include:
- Operating system and version
- PostgreSQL version
- Python version
- BCC version
- Steps to reproduce the issue
- Expected vs actual behavior
- Any error messages or logs

## Feature Requests

Feature requests are welcome! Please:
- Check if the feature has already been requested
- Provide a clear description of the feature
- Explain the use case and benefits
- Consider contributing the feature yourself

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on the code, not the person
- Help create a positive community

## Questions?

If you have questions, feel free to:
- Open an issue for discussion
- Reach out to the maintainer

Thank you for contributing!
