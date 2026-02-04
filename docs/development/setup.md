# Development Environment Setup

## Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis (optional, for caching)
- Git

## Quick Start

### 1. Clone and Setup Virtual Environment

```bash
git clone <repo-url>
cd spring-mvp

# Create virtual environment
python -m venv venv

# Activate (macOS/Linux)
source venv/bin/activate

# Activate (Windows)
.\venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
# Copy example env file
cp .env.example .env

# Edit .env with your settings
DATABASE_URL=postgresql://user:password@localhost:5432/spring_mvp
REDIS_URL=redis://localhost:6379/0
```

### 4. Setup Database

```bash
# Create database
createdb spring_mvp

# Run migrations (when implemented)
alembic upgrade head
```

### 5. Run Development Server

```bash
# Start backend
python -m backend.api.app

# Server runs at http://localhost:8000
# API docs at http://localhost:8000/docs
```

## Development Workflow

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=backend

# Run specific test file
pytest tests/unit/test_models.py
```

### Code Quality

```bash
# Type checking
mypy backend/

# Linting
ruff check backend/

# Formatting
black backend/
```

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## IDE Setup

### VSCode

Recommended extensions:
- Python
- Pylance
- Ruff
- Even Better TOML

Settings (`.vscode/settings.json`):
```json
{
  "python.linting.enabled": true,
  "python.linting.mypyEnabled": true,
  "python.formatting.provider": "black",
  "editor.formatOnSave": true
}
```

### PyCharm

- Enable type checking: Settings → Python Integrated Tools → Type Checker → mypy
- Set Python interpreter to virtual environment

## Troubleshooting

### Database Connection Issues

```bash
# Check PostgreSQL is running
pg_isready

# Verify credentials
psql -U user -d spring_mvp
```

### Import Errors

```bash
# Ensure virtual environment is activated
which python  # Should point to venv/bin/python

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

## Next Steps

- Read `/mvp-summary.md` for implementation guide
- See `/docs/architecture/decisions.md` for architecture decisions
- Check `/docs/api/` for API documentation
