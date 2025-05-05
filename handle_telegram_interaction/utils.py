import os
import sys
import json
import requests

from google.cloud import secretmanager
from google.cloud import firestore
from google.cloud import speech
import google.generativeai as genai

# --- Configuration ---
# Your Google Cloud Project ID
PROJECT_ID = 'daily-english-words'
# Secret Manager Secret IDs 
TELEGRAM_TOKEN_SECRET_ID = "telegram-bot"
GEMINI_API_KEY_SECRET_ID = "gemini-api"
AUTHORIZED_CHAT_ID_SECRET_ID = "telegram-user-id"

FIRESTORE_COLLECTION = "english_practice"
FIRESTORE_SINGLE_USER_DOC_ID = "user_main_state"

# Gemini Model
GEMINI_MODEL_NAME = "gemini-2.0-flash-001"

# --- Initialize Clients ---
secret_client = secretmanager.SecretManagerServiceClient()
db = firestore.Client(project=PROJECT_ID)
speech_client = speech.SpeechClient()

# --- Helper: Access Secret ---
def access_secret_version(secret_id, version_id="latest"):
    if not PROJECT_ID:
        raise ValueError("GCP_PROJECT environment variable not set.")
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/{version_id}"
    try:
        response = secret_client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        print(f"Error accessing secret {secret_id}: {e}")
        raise

# --- Helper: Send Telegram Message ---
def send_telegram_message(bot_token, chat_id, text, reply_markup=None):
    telegram_api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)

    try:
        print(f"Sending message to {chat_id}: {text[:50]}...")
        response = requests.post(telegram_api_url, json=payload, timeout=15) # Increased timeout
        response.raise_for_status()
        print(f"Telegram send status: {response.status_code}")
        return response.json().get("ok", False)
    except requests.exceptions.RequestException as e:
        print(f"Error sending Telegram message to {chat_id}: {e}")
        return False
    
# --- Helper: Get/Update Firestore State ---
def get_firestore_state(user_doc_id=FIRESTORE_SINGLE_USER_DOC_ID):
    """Retrieves the user's state document."""
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION).document(user_doc_id)
        doc = doc_ref.get()
        if doc.exists:
            print(f"Retrieved state for {user_doc_id}")
            return doc.to_dict()
        else:
            print(f"No state found for {user_doc_id}, returning default.")
            # Return a default initial state
            return {"interaction_state": "idle"}
    except Exception as e:
        print(f"Error getting Firestore state for {user_doc_id}: {e}")
        # Return default state on error to avoid breaking flow, but log it
        return {"interaction_state": "idle"}
    
def update_firestore_state(state_data, user_doc_id=FIRESTORE_SINGLE_USER_DOC_ID):
    """Updates the user's state document, adding a timestamp."""
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION).document(user_doc_id)
        state_data['last_update'] = firestore.SERVER_TIMESTAMP
        doc_ref.set(state_data, merge=True) # Merge=True updates fields without overwriting others
        print(f"Updated state for {user_doc_id}: {state_data}")
        return True
    except Exception as e:
        print(f"Error updating Firestore state for {user_doc_id}: {e}")
        return False
    
# --- Helper: Transcribe Voice (Requires google-cloud-speech) ---
def transcribe_voice(bot_token, file_id):
    """Downloads voice file from Telegram and transcribes using Google Speech-to-Text."""
    try:
        # 1. Get file path from Telegram
        get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
        res_file_path = requests.get(get_file_url, timeout=10)
        res_file_path.raise_for_status()
        file_path = res_file_path.json().get('result', {}).get('file_path')
        if not file_path:
            print("Error: Could not get file_path from Telegram")
            return None

        # 2. Download the audio file content
        file_download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        print(f"Downloading audio from: {file_download_url}")
        res_audio = requests.get(file_download_url, timeout=20) # Longer timeout for download
        res_audio.raise_for_status()
        audio_content = res_audio.content
        print(f"Audio downloaded, size: {len(audio_content)} bytes")

        # 3. Call Speech-to-Text API
        audio = speech.RecognitionAudio(content=audio_content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
            sample_rate_hertz=48000,
            language_code="en-US",
            enable_automatic_punctuation=True
        )

        print("Sending audio to Speech-to-Text API...")
        response = speech_client.recognize(config=config, audio=audio)
        print("Received response from Speech-to-Text API.")

        # 4. Process results
        transcript = ""
        if response.results:
            transcript = response.results[0].alternatives[0].transcript
            print(f"Transcription: {transcript}")
            return transcript.strip()
        else:
            print("Speech-to-Text returned no results.")
            return None

    except requests.exceptions.RequestException as req_err:
         print(f"Error during Telegram file download: {req_err}")
         return None
    except Exception as e:
        print(f"Error during transcription: {e}")
        return None
    
# --- Task Types Definition ---
# Using simple strings, map these to prompts later
TASK_TYPES = [
    "Fill-in-the-blanks",
    "Error correction",
    "Vocabulary matching",
    "Pronunciation focus",
    "Idiom/Phrasal verb",
    "Word starting with letter", # Name words starting with...
    "Reordering sentences"
]

# --- Helper: Generate Task via Gemini ---
def generate_task(gemini_key, task_type, topic=None):
    """Generates task content using Gemini based on the chosen type."""
    # --- IMPORTANT: Refine these prompts heavily! ---
    prompt_base = f"Generate an English learning task for an intermediate learner. Task Type: '{task_type}'. "
    if topic:
        prompt_base += f"The general theme for today is '{topic}'. "

    if task_type == "Fill-in-the-blanks":
        prompt = prompt_base + "Create one sentence with a single blank (use '___') related to the theme if provided. Provide the correct answer on a new line prefixed with 'ANSWER: '."
    elif task_type == "Error correction":
        prompt = prompt_base + "Create one sentence with a common grammatical error related to the theme if provided. Ask the user to correct it."
    elif task_type == "Vocabulary matching":
        prompt = prompt_base + "Provide 3 related vocabulary words and their definitions (related to the theme if provided). Format clearly for matching, like 'WORD1 - DEF1\\nWORD2 - DEF2\\nWORD3 - DEF3'."
    elif task_type == "Pronunciation focus":
        prompt = prompt_base + "Choose two commonly confused English words based on pronunciation (like ship/sheep or desert/dessert). Briefly explain the difference and ask the user to write a sentence using one of them."
    elif task_type == "Idiom/Phrasal verb":
        prompt = prompt_base + "Choose a common English idiom or phrasal verb. Explain its meaning and provide one example sentence. Ask the user to write their own sentence using it."
    elif task_type == "Word starting with letter":
        import random
        letter = random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
        prompt = f"This is a timed fluency task. Ask the user to list as many English words as they can starting with the letter '{letter}' in one minute." # Gemini just generates the instruction text
    elif task_type == "Reordering sentences":
        prompt = prompt_base + "Create a simple sentence (5-8 words) related to the theme if provided, but present the words in a jumbled order. Ask the user to reorder them correctly."
    else:
        print(f"Unknown task type requested: {task_type}")
        return None # Or default task

    print(f"Generating task for type '{task_type}'...")
    try:
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        response = model.generate_content(prompt)

        if response.text:
            print(f"Generated task content: {response.text[:100]}...")
            # Basic structure assumes Gemini directly outputs the task description/content
            # For matching/fill-in-blank, you might need to parse out the answer
            task_details = {"description": response.text.strip(), "type": task_type}
            if task_type == "Fill-in-the-blanks":
                 # Example parsing - adjust based on actual Gemini output
                 parts = response.text.strip().split("ANSWER:")
                 if len(parts) == 2:
                     task_details["description"] = parts[0].strip()
                     task_details["answer"] = parts[1].strip()

            # Add more specific parsing/structuring if needed for other types
            return task_details
        else:
            print("Gemini returned empty response for task generation.")
            return None
    except Exception as e:
        print(f"Error generating task with Gemini: {e}")
        return None
    
# --- Helper: Evaluate Answer via Gemini ---
def evaluate_answer(gemini_key, task_details, user_answer):
    """Evaluates user's answer using Gemini based on the task."""
    print(f"Evaluating answer for task type '{task_details.get('type')}'...")
    task_description = task_details.get('description', 'Not specified')
    task_type = task_details.get('type', 'Unknown')
    # --- IMPORTANT: Refine this prompt heavily! ---
    prompt = f"""
    Act as a friendly and supportive English tutor providing feedback.
    The user was given the following task (type: {task_type}):
    --- TASK START ---
    {task_description}
    --- TASK END ---

    The user responded:
    --- USER RESPONSE START ---
    {user_answer}
    --- USER RESPONSE END ---

    Please evaluate the user's response based ONLY on the given task.
    - Be concise and clear.
    - If correct, acknowledge it positively.
    - If incorrect, gently point out the error and provide the correction or a hint.
    - If the task was subjective (like listing words), comment on their effort or provide interesting examples.
    - Keep the feedback focused and encouraging.
    - Structure the feedback simply (e.g., start with "Good job!" or "Almost there!").
    """

    # Add specific context for certain types if helpful
    if task_type == "Fill-in-the-blanks" and "answer" in task_details:
      prompt += f"\nThe expected answer for the blank was: {task_details['answer']}"
    # Add more context hints for other types as needed

    try:
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        response = model.generate_content(prompt)
        if response.text:
            feedback = response.text.strip()
            print(f"Generated feedback: {feedback[:100]}...")
            return feedback
        else:
            print("Gemini returned empty response for evaluation.")
            return "Sorry, I couldn't generate feedback this time."
    except Exception as e:
        print(f"Error evaluating answer with Gemini: {e}")
        return f"Sorry, an error occurred while generating feedback: {e}"
    
def send_choice_request_message(bot_token, chat_id):
    """Formats and sends the 'Choose task type' message with a keyboard."""
    print(f"Attempting to send choice request message to {chat_id}")
    try:
        # Prepare Keyboard Options
        keyboard_buttons = [[task_type] for task_type in TASK_TYPES]
        reply_markup = {
            "keyboard": keyboard_buttons,
            "one_time_keyboard": True,
            "resize_keyboard": True
        }

        # Format Message
        message_text = "👋 Okay, let's start a new task! What type of English practice would you like?\nChoose one option from the keyboard below:"

        # Send Message using existing helper
        success = send_telegram_message(bot_token, chat_id, message_text, reply_markup)
        if success:
            print("Choice request message sent successfully.")
            return True
        else:
            print("Failed to send choice request message via Telegram helper.")
            return False
    except Exception as e:
        print(f"Error within send_choice_request_message helper: {e}")
        return False
