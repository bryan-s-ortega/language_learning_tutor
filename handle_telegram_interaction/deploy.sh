#!/bin/bash

# Deploy handle_telegram_interaction Google Cloud Function

set -e  # Exit on any error

echo "Deploying handle_telegram_interaction function..."

# Set your project ID and region here
PROJECT_ID='daily-english-words'
REGION="us-central1"
FUNCTION_NAME="handle-telegram-interaction"

# Deploy the function
gcloud functions deploy $FUNCTION_NAME \
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

echo "Deployment complete!"
echo "Function URL: https://$REGION-$PROJECT_ID.cloudfunctions.net/$FUNCTION_NAME"
