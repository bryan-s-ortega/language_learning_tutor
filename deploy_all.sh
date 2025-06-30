#!/bin/bash

# Deploy all Google Cloud Functions for Language Learning Tutor

set -e  # Exit on any error

echo "Starting deployment of all Google Cloud Functions..."
echo "================================================"

# Configuration - UPDATE THESE VALUES
PROJECT_ID='daily-english-words'
REGION="us-central1"

# Check if gcloud is installed and authenticated
if ! command -v gcloud &> /dev/null; then
    echo "Error: gcloud CLI is not installed. Please install it first."
    echo "Visit: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check if user is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n1 &> /dev/null; then
    echo "Error: You are not authenticated with gcloud."
    echo "Please run: gcloud auth login"
    exit 1
fi

# Set the project
echo "Setting project to: $PROJECT_ID"
gcloud config set project $PROJECT_ID

# Deploy handle_telegram_interaction function
echo ""
echo "Deploying handle_telegram_interaction function..."
echo "-----------------------------------------------"
cd handle_telegram_interaction
gcloud functions deploy handle-telegram-interaction \
  --gen2 \
  --runtime=python312 \
  --region=$REGION \
  --build-service-account=projects/daily-english-words/serviceAccounts/daily-english-words@appspot.gserviceaccount.com \
  --service-account=daily-english-words@appspot.gserviceaccount.com \
  --source=. \
  --entry-point=handle_telegram_interaction \
  --trigger-http \
  --allow-unauthenticated \
  --memory=512MB \
  --project=$PROJECT_ID

echo "handle_telegram_interaction deployed successfully!"
echo "Function URL: https://$REGION-$PROJECT_ID.cloudfunctions.net/handle-telegram-interaction"

# Deploy send_daily_choice_request function
echo ""
echo "Deploying send_daily_choice_request function..."
echo "----------------------------------------------"
cd ../send_daily_choice_request
gcloud functions deploy send-daily-choice-request \
  --gen2 \
  --runtime=python312 \
  --region=$REGION \
  --build-service-account=projects/daily-english-words/serviceAccounts/daily-english-words@appspot.gserviceaccount.com \
  --service-account=daily-english-words@appspot.gserviceaccount.com \
  --source=. \
  --entry-point=send_daily_choice_request \
  --trigger-http \
  --allow-unauthenticated \
  --memory=256MB \
  --project=$PROJECT_ID

echo "send_daily_choice_request deployed successfully!"
echo "Function URL: https://$REGION-$PROJECT_ID.cloudfunctions.net/send-daily-choice-request"

echo ""
echo "================================================"
echo "All functions deployed successfully!"
echo "================================================"
