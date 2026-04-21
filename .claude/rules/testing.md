# Testing Requirements

## Minimum Test Coverage: 80%

Test Types (ALL required):
1. **Unit Tests** - Individual functions, utilities, classes
2. **Integration Tests** - API endpoints, database operations
3. **E2E Tests** - Critical user flows (playwright/selenium)

## Test-Driven Development

MANDATORY workflow:
1. Write test first (RED)
2. Run test - it should FAIL (`pytest tests/ -x -v`)
3. Write minimal implementation (GREEN)
4. Run test - it should PASS
5. Refactor (IMPROVE)
6. Verify coverage (`pytest --cov=src --cov-report=term-missing`, 80%+)

## Troubleshooting Test Failures

1. Use **tdd-guide** agent
2. Check test isolation
3. Verify mocks are correct
4. Fix implementation, not tests (unless tests are wrong)

## Agent Support

- **tdd-guide** - Use PROACTIVELY for new features, enforces write-tests-first

## Test Structure (AAA Pattern)

Prefer Arrange-Act-Assert structure for tests:

```python
def test_calculates_similarity_correctly():
    # Arrange
    vector1 = [1, 0, 0]
    vector2 = [0, 1, 0]

    # Act
    similarity = calculate_cosine_similarity(vector1, vector2)

    # Assert
    assert similarity == 0
```

### Test Naming

Use descriptive names that explain the behavior under test:

```python
def test_returns_empty_list_when_no_markets_match_query(): ...
def test_raises_error_when_api_key_is_missing(): ...
def test_falls_back_to_substring_search_when_redis_unavailable(): ...
```
