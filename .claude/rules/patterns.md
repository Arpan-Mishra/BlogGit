# Common Patterns

## Skeleton Projects

When implementing new functionality:
1. Search for battle-tested skeleton projects
2. Use parallel agents to evaluate options:
   - Security assessment
   - Extensibility analysis
   - Relevance scoring
   - Implementation planning
3. Clone best match as foundation
4. Iterate within proven structure

## Design Patterns

### Repository Pattern

Encapsulate data access behind a consistent interface using Protocols:

```python
from typing import Protocol

class UserRepository(Protocol):
    def find_all(self) -> list[User]: ...
    def find_by_id(self, id: str) -> User | None: ...
    def create(self, user: User) -> User: ...
    def update(self, user: User) -> User: ...
    def delete(self, id: str) -> None: ...
```

- Concrete implementations handle storage details (database, API, file, etc.)
- Business logic depends on the Protocol, not the storage mechanism
- Enables easy swapping of data sources and simplifies testing with mocks

### API Response Format

Use a consistent envelope for all API responses:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ApiResponse:
    success: bool
    data: dict | list | None = None
    error: str | None = None
    metadata: dict | None = None  # total, page, limit for pagination
```

### Service Layer Pattern

Separate business logic from API routes:

```python
class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self._repo = repo

    def get_active_users(self) -> list[User]:
        return [u for u in self._repo.find_all() if u.is_active]
```

### Dependency Injection

Use constructor injection for testability:

```python
# Production
service = UserService(repo=PostgresUserRepository(db))

# Testing
service = UserService(repo=FakeUserRepository())
```
