# Testing Guide

## Overview

The VAPI Skills System includes a comprehensive test suite that validates:
- **Unit Tests**: BaseSkill, SkillRegistry, skill instantiation
- **Integration Tests**: API endpoints, skill endpoints, health checks
- **Health Checks**: Server responsiveness, configuration

## Quick Start

### Run All Tests
```bash
source venv/bin/activate
python scripts/run_tests.py
```

The test runner will:
1. ✅ Start a temporary test server
2. ✅ Run health checks
3. ✅ Run all unit and integration tests
4. ✅ Show clear pass/fail summary
5. ✅ Stop the test server

### Run with Existing Server (Faster)
If you already have a server running:
```bash
# Terminal 1: Server running
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Run tests
python scripts/run_tests.py --use-existing-server
```

### Run Specific Test Files
```bash
# Run only unit tests
python scripts/run_tests.py tests/test_skill_system.py

# Run only integration tests
python scripts/run_tests.py tests/test_api_endpoints.py
```

### Verbose Output
```bash
python scripts/run_tests.py -v
```

## Test Structure

```
tests/
├── __init__.py
├── test_skill_system.py      # Unit tests for skill architecture
└── test_api_endpoints.py     # Integration tests for API endpoints
```

## What's Tested

### Unit Tests (test_skill_system.py)

**BaseSkill Tests:**
- ✅ Cannot instantiate abstract BaseSkill directly
- ✅ VoiceNotesSkill instantiates correctly
- ✅ get_info() returns correct metadata

**SkillRegistry Tests:**
- ✅ Registry initializes empty
- ✅ Can register skills
- ✅ Duplicate registration replaces skill
- ✅ Get non-existent skill returns None
- ✅ list_skills() returns all registered skills
- ✅ get_assistant_ids() returns correct mapping
- ✅ get_skills_for_squad() filters by assistant_id

**VoiceNotesSkill Tests:**
- ✅ Has all required methods (create_tools, create_assistant, register_routes)
- ✅ Has VAPI configuration

### Integration Tests (test_api_endpoints.py)

**Health Endpoints:**
- ✅ /health returns healthy status
- ✅ / root endpoint returns service info

**Skill Registry Endpoints:**
- ✅ /api/v1/skills/list returns all skills
- ✅ VoiceNotesSkill is registered
- ✅ Skill data structure is correct

**Environment Endpoints:**
- ✅ /debug/env-check returns configuration
- ✅ Environment is set correctly

**Voice Notes Endpoints:**
- ✅ /api/v1/vapi/authenticate-by-phone exists
- ✅ /api/v1/skills/voice-notes/identify-context exists
- ✅ /api/v1/skills/voice-notes/save-note exists

**CORS:**
- ✅ CORS headers are configured

### Health Checks

The test runner also performs basic health checks:
- ✅ Server responds on port 8000
- ✅ Health endpoint returns 200
- ✅ Skills list is accessible
- ✅ Environment check works

## Running Tests Before Commits

### Manual Pre-Commit Check
```bash
# Run tests before committing
python scripts/run_tests.py

# If all pass, commit
git add .
git commit -m "Your changes"
```

### Automated Pre-Commit Hook (Optional)

Create `.git/hooks/pre-commit`:
```bash
#!/bin/bash

echo "Running tests before commit..."

# Run tests
python scripts/run_tests.py --use-existing-server

if [ $? -eq 0 ]; then
    echo "✓ Tests passed - proceeding with commit"
    exit 0
else
    echo "✗ Tests failed - commit blocked"
    echo "Fix the tests and try again"
    exit 1
fi
```

Make it executable:
```bash
chmod +x .git/hooks/pre-commit
```

**Note:** This requires a server to be running. For a better experience, modify to start/stop server automatically.

## CI/CD Integration

### GitHub Actions Example

Create `.github/workflows/test.yml`:
```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'

    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install -r requirements-dev.txt

    - name: Run tests
      run: python scripts/run_tests.py
```

## Troubleshooting

### Tests Fail to Start Server
```bash
# Check if port 8000 is in use
lsof -i :8000

# Kill any process on 8000
kill -9 <PID>

# Try again
python scripts/run_tests.py
```

### Tests Timeout
```bash
# Increase timeout in scripts/run_tests.py
# Or use existing server
python scripts/run_tests.py --use-existing-server
```

### Import Errors
```bash
# Make sure you're in the project root
cd /Users/kevinmorrell/projects/vapi-skills-system

# Activate virtual environment
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements-dev.txt
```

### Tests Pass Locally But Fail in CI
- Check environment variables are set
- Ensure test database/fixtures are available
- Verify Python version matches

## Writing New Tests

### Add Unit Test

Edit `tests/test_skill_system.py`:
```python
def test_my_new_feature(self):
    """Test description"""
    # Arrange
    skill = VoiceNotesSkill()

    # Act
    result = skill.some_method()

    # Assert
    assert result == expected_value
```

### Add Integration Test

Edit `tests/test_api_endpoints.py`:
```python
def test_my_new_endpoint(self):
    """Test new endpoint"""
    response = client.get("/api/v1/my-endpoint")
    assert response.status_code == 200
    assert "expected_key" in response.json()
```

### Run Your New Test
```bash
python scripts/run_tests.py tests/test_skill_system.py::TestClass::test_my_new_feature -v
```

## Test Coverage (Future)

To add code coverage:
```bash
# Install coverage tool
pip install pytest-cov

# Run with coverage
pytest --cov=app tests/

# Generate HTML report
pytest --cov=app --cov-report=html tests/
open htmlcov/index.html
```

## Best Practices

1. **Run tests before every commit**
2. **Write tests for new features**
3. **Keep tests fast** (< 5 seconds total)
4. **Use descriptive test names**
5. **Test one thing per test**
6. **Use fixtures for common setup**
7. **Mock external API calls**

## Current Test Stats

- **Total Tests**: 21
- **Unit Tests**: 11
- **Integration Tests**: 10
- **Health Checks**: 4
- **Coverage**: ~70% (core functionality)

## Next Steps

- [ ] Add tests for VAPI tool creation
- [ ] Add tests for authentication flow
- [ ] Add tests for database operations
- [ ] Increase test coverage to 90%+
- [ ] Add performance benchmarks
- [ ] Add load testing
