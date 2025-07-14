# Language Learning Tutor - Deployment and Management Commands

# Default recipe to show available commands
default:
    @just --list

# Configuration variables
project-id := "daily-english-words"
region := "us-central1"
build-service-account := "projects/daily-english-words/serviceAccounts/daily-english-words@appspot.gserviceaccount.com"
service-account := "daily-english-words@appspot.gserviceaccount.com"

# Development and testing commands
test:
    echo "Running tests..."
    pytest

test-coverage:
    echo "Running tests with coverage..."
    pytest --cov=handle_telegram_interaction --cov=send_daily_choice_request --cov-report=term-missing --cov-report=html

lint:
    echo "Running linting checks..."
    ruff check .

format:
    echo "Formatting code..."
    ruff format .

check-all: lint format test
    echo "All checks completed successfully!"

# Refresh requirements.txt files using uv
refresh-requirements:
    echo "Refreshing requirements.txt files using uv..."
    cd handle_telegram_interaction && uv sync --reinstall && uv pip compile pyproject.toml > requirements.txt
    cd send_daily_choice_request && uv sync --reinstall && uv pip compile pyproject.toml > requirements.txt
    echo "Requirements refreshed successfully!"

# Install development dependencies
install-dev:
    echo "Installing development dependencies..."
    uv sync
    echo "Development dependencies installed!"

# Deploy handle_telegram_interaction function
deploy-telegram: refresh-requirements
    echo "Deploying handle_telegram_interaction function..."
    echo "-----------------------------------------------"
    cd handle_telegram_interaction && gcloud functions deploy handle-telegram-interaction --gen2 --runtime=python312 --region={{region}} --build-service-account={{build-service-account}} --service-account={{service-account}} --source=. --entry-point=handle_telegram_interaction --trigger-http --allow-unauthenticated --memory=512MB --project={{project-id}}
    echo "handle_telegram_interaction deployed successfully!"

# Deploy send_daily_choice_request function
deploy-daily-choice: refresh-requirements
    echo "Deploying send_daily_choice_request function..."
    echo "----------------------------------------------"
    cd send_daily_choice_request && gcloud functions deploy send-daily-choice-request --gen2 --runtime=python312 --region={{region}} --build-service-account={{build-service-account}} --service-account={{service-account}} --source=. --entry-point=send_daily_choice_request --trigger-http --allow-unauthenticated --memory=256MB --project={{project-id}}
    echo "send_daily_choice_request deployed successfully!"

# Deploy all functions
deploy-all: refresh-requirements
    echo "Starting deployment of all Google Cloud Functions..."
    echo "================================================"
    just deploy-telegram
    just deploy-daily-choice
    echo ""
    echo "================================================"
    echo "All functions deployed successfully!"
    echo "================================================"

# Show function URLs
urls:
    echo "Function URLs:"
    echo "=============="
    echo "handle_telegram_interaction: https://{{region}}-{{project-id}}.cloudfunctions.net/handle-telegram-interaction"
    echo "send_daily_choice_request: https://{{region}}-{{project-id}}.cloudfunctions.net/send-daily-choice-request"

# Show function logs
logs-telegram:
    echo "Showing logs for handle_telegram_interaction..."
    gcloud functions logs read handle-telegram-interaction --limit=50

logs-daily-choice:
    echo "Showing logs for send_daily_choice_request..."
    gcloud functions logs read send-daily-choice-request --limit=50