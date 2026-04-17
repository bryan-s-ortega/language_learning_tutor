# Language Learning Tutor - Project Management Commands

# Default recipe to show available commands
default:
    @just --list

# Configuration variables
project-id := "daily-english-words"
region := "us-central1"

# Development and testing commands
test:
    echo "Running tests..."
    pytest

test-coverage:
    echo "Running tests with coverage..."
    pytest --cov=app_core --cov-report=term-missing --cov-report=html

lint:
    echo "Running linting checks..."
    ruff check .

format:
    echo "Formatting code..."
    ruff format .

run-web:
    echo "Starting web application..."
    uv run uvicorn web_app:app --host 0.0.0.0 --port 8000 --reload

check-all: lint format test
    echo "All checks completed successfully!"

# Install development dependencies
install-dev:
    echo "Installing development dependencies..."
    uv sync
    echo "Development dependencies installed!"