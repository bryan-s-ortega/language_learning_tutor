import os
import json
import random
import requests
import logging

from google.cloud import secretmanager
from google.cloud import firestore
import google.generativeai as genai

logger = logging.getLogger(__name__)

# --- Configuration ---
PROJECT_ID = 'daily-english-words'
TELEGRAM_TOKEN_SECRET_ID = "telegram-bot"
AUTHORIZED_CHAT_ID_SECRET_ID = "telegram-user-id"

FIRESTORE_COLLECTION = "english_practice_state"
FIRESTORE_SINGLE_USER_DOC_ID = "user_main_state"

# --- Initialize Clients ---
secret_client = secretmanager.SecretManagerServiceClient()
db = firestore.Client(project=PROJECT_ID)

# --- Helper: Access Secret ---
def access_secret_version(secret_id, version_id="latest"):
    if not PROJECT_ID:
        # This is a configuration error, best to raise it.
        logger.critical("GCP_PROJECT environment variable not set or PROJECT_ID constant is empty.")
        raise ValueError("GCP_PROJECT environment variable not set or PROJECT_ID constant is empty.")
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/{version_id}"
    try:
        response = secret_client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        logger.error(f"Error accessing secret {secret_id}: {e}", exc_info=True) # exc_info=True includes stack trace
        raise

# --- Helper: Send Telegram Message ---
def send_telegram_message(bot_token, chat_id, text, reply_markup=None):
    telegram_api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    if text is None:
        logger.error(f"send_telegram_message called with text=None for chat_id {chat_id}. Sending a default error message.")
        text = "Sorry, an unexpected error occurred, and I don't have a specific message to send."

    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    try:
        logger.info(f"Sending message to {chat_id}: {text[:50]}...")
        response = requests.post(telegram_api_url, json=payload, timeout=15)
        response.raise_for_status()
        logger.info(f"Telegram send status: {response.status_code}")
        return response.json().get("ok", False)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending Telegram message to {chat_id}: {e}", exc_info=True)
        return False

def update_firestore_state(state_data, user_doc_id=FIRESTORE_SINGLE_USER_DOC_ID):
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION).document(user_doc_id)
        state_data['last_update'] = firestore.SERVER_TIMESTAMP
        doc_ref.set(state_data, merge=True)
        logger.info(f"Updated state for {user_doc_id}: {state_data}")
        return True
    except Exception as e:
        logger.error(f"Error updating Firestore state for {user_doc_id}: {e}", exc_info=True)
        return False

# --- Task Types Definition ---
TASK_TYPES = [
    "Error correction", "Vocabulary matching",
    "Idiom/Phrasal verb", "Word starting with letter",
    "Voice Recording Analysis"
]

# --- Helper: Send Choice Request Message ---
def send_choice_request_message(bot_token, chat_id):
    logger.info(f"Attempting to send choice request message to {chat_id}")
    try:
        keyboard_buttons = [[task_type] for task_type in TASK_TYPES]
        reply_markup = {"keyboard": keyboard_buttons, "one_time_keyboard": True, "resize_keyboard": True}
        message_text = "👋 Okay, let's start a new task! What type of English practice would you like?\nChoose one option from the keyboard below:"
        success = send_telegram_message(bot_token, chat_id, message_text, reply_markup)
        if success:
            logger.info("Choice request message sent successfully.")
            return True
        else:
            logger.error("Failed to send choice request message via Telegram helper.")
            return False
    except Exception as e:
        logger.error(f"Error within send_choice_request_message helper: {e}", exc_info=True)
        return False