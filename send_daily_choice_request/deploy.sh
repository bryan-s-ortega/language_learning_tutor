#!/bin/bash

# Deploy send_daily_choice_request Google Cloud Function

set -e  # Exit on any error

echo "Deploying send_daily_choice_request function..."

# Set your project ID and region here
PROJECT_ID='daily-english-words'
REGION="us-central1"
FUNCTION_NAME="send-daily-choice-request"

# Deploy the function
gcloud functions deploy $FUNCTION_NAME \
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

echo "Deployment complete!"
echo "Function URL: https://$REGION-$PROJECT_ID.cloudfunctions.net/$FUNCTION_NAME"