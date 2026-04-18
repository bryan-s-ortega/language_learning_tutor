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

deploy:
    gcloud run deploy language-tutor --source . --region us-central1 --set-secrets="FIREBASE_API_KEY=FIREBASE_API_KEY:latest,FIREBASE_AUTH_DOMAIN=FIREBASE_AUTH_DOMAIN:latest,FIREBASE_PROJECT_ID=FIREBASE_PROJECT_ID:latest,GEMINI_API_KEY=gemini-api:latest,FIREBASE_STORAGE_BUCKET=STORAGE_BUCKET:latest,FIREBASE_MESSAGING_SENDER_ID=MESSAGING_SENDER_ID:latest,FIREBASE_APP_ID=APP_ID:latest" --allow-unauthenticated --build-service-account="projects/daily-english-words/serviceAccounts/tutor-deployer@daily-english-words.iam.gserviceaccount.com" --service-account="tutor-runtime@daily-english-words.iam.gserviceaccount.com"