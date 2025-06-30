import os
import json
import random
import requests
import logging

from google.cloud import secretmanager
from google.cloud import firestore
from google.cloud import speech
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

logger = logging.getLogger(__name__)
PROJECT_ID = 'daily-english-words'
TELEGRAM_TOKEN_SECRET_ID = "telegram-bot"
GEMINI_API_KEY_SECRET_ID = "gemini-api"
AUTHORIZED_CHAT_ID_SECRET_ID = "telegram-user-id"

FIRESTORE_COLLECTION = "english_practice_state"
FIRESTORE_SINGLE_USER_DOC_ID = "user_main_state"
PROFICIENCY_COLLECTION = "user_proficiency"

GEMINI_MODEL_NAME = "gemini-2.0-flash-001"

secret_client = secretmanager.SecretManagerServiceClient()
db = firestore.Client(project=PROJECT_ID)
speech_client = speech.SpeechClient()

TASK_TYPES = [
    "Error correction", "Vocabulary matching",
    "Idiom/Phrasal verb", "Word starting with letter",
    "Voice Recording Analysis"
]

# --- Helper: Access Secret ---
def access_secret_version(secret_id, version_id="latest"):
    if not PROJECT_ID:
        logger.critical("GCP_PROJECT environment variable not set or PROJECT_ID constant is empty.")
        raise ValueError("GCP_PROJECT environment variable not set or PROJECT_ID constant is empty.")
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/{version_id}"
    try:
        response = secret_client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        logger.error(f"Error accessing secret {secret_id}: {e}", exc_info=True)
        raise

# --- Helper: Send Telegram Message ---
def send_telegram_message(bot_token, chat_id, text, reply_markup=None):
    telegram_api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    if text is None:
        logger.error(f"send_telegram_message called with text=None for chat_id {chat_id}. Sending a default error message.")
        text = "Sorry, an unexpected error occurred, and I don't have a specific message to send."

    # Validate and sanitize text for Telegram
    if len(text) > 4096:
        logger.warning(f"Message too long ({len(text)} chars), truncating to 4096 chars")
        text = text[:4093] + "..."
    
    # Escape problematic Markdown characters that might cause 400 errors
    # Remove or escape characters that can break Markdown parsing
    text = text.replace('_', r'\_').replace('*', r'\*').replace('[', r'\[').replace(']', r'\]').replace('`', r'\`')
    
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    
    try:
        logger.info(f"Sending message to {chat_id}: {text[:50]}...")
        logger.debug(f"Full payload: {payload}")
        response = requests.post(telegram_api_url, json=payload, timeout=15)
        
        if response.status_code == 400:
            # Log detailed error information for 400 errors
            logger.error(f"Telegram 400 Bad Request. Response: {response.text}")
            logger.error(f"Payload that caused error: {payload}")
            
            # Try sending without Markdown if parse mode is the issue
            logger.info("Retrying without Markdown parse mode...")
            payload_no_markdown = {'chat_id': chat_id, 'text': text}
            if reply_markup:
                payload_no_markdown['reply_markup'] = json.dumps(reply_markup)
            
            response = requests.post(telegram_api_url, json=payload_no_markdown, timeout=15)
            if response.status_code == 200:
                logger.info("Message sent successfully without Markdown")
                return response.json().get("ok", False)
            else:
                logger.error(f"Failed even without Markdown. Status: {response.status_code}, Response: {response.text}")
        
        response.raise_for_status()
        logger.info(f"Telegram send status: {response.status_code}")
        return response.json().get("ok", False)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending Telegram message to {chat_id}: {e}", exc_info=True)
        try:
            # Log response content if available
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response content: {e.response.text}")
        except:
            pass
        return False

# --- Helper: Get/Update Firestore State ---
def get_firestore_state(user_doc_id=FIRESTORE_SINGLE_USER_DOC_ID):
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION).document(user_doc_id)
        doc = doc_ref.get()
        if doc.exists:
            logger.info(f"Retrieved state for {user_doc_id}")
            return doc.to_dict()
        else:
            logger.info(f"No state found for {user_doc_id}, returning default.")
            return {"interaction_state": "idle"}
    except Exception as e:
        logger.error(f"Error getting Firestore state for {user_doc_id}: {e}", exc_info=True)
        return {"interaction_state": "idle"}

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

# --- Helper: Generate Task via Gemini ---
def generate_task(gemini_key, task_type, user_doc_id, topic=None):
    prompt_base = f"Generate an English learning task for an advanced learner. Task Type: '{task_type}'. "
    if topic:
        prompt_base += f"The general theme for today is '{topic}'. "

    task_details_dict = {"type": task_type, "specific_item_tested": None, "description": None}
    prompt = ""

    if task_type == "Error correction":
        prompt = prompt_base + (
            "Focus on a common English grammatical error (e.g., subject-verb agreement, tense misuse, articles, prepositions). "
            "On a NEW line, identify the specific grammar concept being tested, like 'ITEM: [grammar concept name]'. "
            "Then, on a NEW line, provide a single sentence containing this error for the user to correct. "
            "Example for ITEM: Past Simple Irregular Verb\nSentence: He goed to the park."
        )
    elif task_type == "Vocabulary matching":
        prompt = prompt_base + (
            "Provide 3 related English vocabulary words suitable for an advanced learner. "
            "For each word, on a NEW line, identify it like 'ITEM: [word]'. "
            "After listing all ITEMs, provide their definitions. "
            "The definitions should be presented in a jumbled or randomized order. "
            "Make it clear they need to match them (e.g., 'Match the words with their definitions below.')."
        )
    elif task_type == "Idiom/Phrasal verb":
        prompt = prompt_base + (
            "Choose one common English idiom or phrasal verb. "
            "On a NEW line, identify it clearly, like 'ITEM: [idiom/phrasal verb phrase]'. "
            "Then, on subsequent lines, explain its meaning and provide one clear example sentence. "
            "Finally, ask the user to write their own sentence using it."
        )
    elif task_type == "Word starting with letter":
        letter = random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
        task_details_dict["description"] = f"This is a fluency task. List as many English words as you can starting with the letter '{letter}' in one minute."
        task_details_dict["specific_item_tested"] = f"words_starting_with_{letter}"
        logger.info(f"Generated task for Word starting with letter: {letter}")
        return task_details_dict

    elif task_type == "Voice Recording Analysis":
        instruction_generation_prompt = prompt_base + \
            "Ask the user to record a voice message of any length. " + \
            "The instruction should be to talk about any topic. " + \
            "Output only the instruction for the user."
        logger.info(f"Generating voice task instruction with prompt: {instruction_generation_prompt}")
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        instruction_response = model.generate_content(instruction_generation_prompt)
        if instruction_response.text:
            task_details_dict["description"] = instruction_response.text.strip()
            logger.info(f"Generated voice task instruction: {task_details_dict['description']}")
            return task_details_dict
        else:
            logger.warning("Gemini failed to generate voice task instruction, using fallback.")
            task_details_dict["description"] = "Please record a voice message. I will analyze your spoken English."
            return task_details_dict
    else:
        logger.warning(f"Unknown or unadapted task type for specific item generation: {task_type}")
        return None

    if not prompt:
        logger.error(f"Prompt not set for task type: {task_type}")
        return None

    logger.info(f"Generating task for type '{task_type}' with prompt: {prompt[:100]}...")
    try:
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        response = model.generate_content(prompt)

        if response.text:
            raw_gemini_response_text = response.text.strip()
            logger.info(f"Generated task content (raw): {raw_gemini_response_text[:300]}...")
            
            lines = raw_gemini_response_text.split('\n')
            items_found = []
            other_lines_for_description = []

            for line in lines:
                if line.upper().startswith("ITEM:"):
                    items_found.append(line[len("ITEM:"):].strip())
                else:
                    other_lines_for_description.append(line)
            if task_type == "Vocabulary matching":
                if items_found:
                    user_description = "Match the following words with their definitions:\n\n**Words to match:**\n"
                    for i, word in enumerate(items_found):
                        user_description += f"{i+1}. {word}\n"
                    user_description += "\n**Definitions:**\n"
                    user_description += "\n".join(other_lines_for_description).strip()
                    task_details_dict["description"] = user_description
                    task_details_dict["specific_item_tested"] = items_found
                else:
                    logger.warning("Vocabulary matching: 'ITEM:' tags not found or parsed incorrectly. Using full response as description.")
                    task_details_dict["description"] = raw_gemini_response_text
                    task_details_dict["specific_item_tested"] = [l[len("ITEM:"):].strip() for l in raw_gemini_response_text.split('\n') if l.upper().startswith("ITEM:")]

            else:
                task_details_dict["description"] = "\n".join(other_lines_for_description).strip()
                if items_found:
                    task_details_dict["specific_item_tested"] = items_found[0]

            if not task_details_dict.get("description") and raw_gemini_response_text:
                 logger.warning(f"Description for task type {task_type} was empty after parsing, falling back to raw Gemini text.")
                 task_details_dict["description"] = raw_gemini_response_text
            
            if task_details_dict.get("description") is None:
                logger.error(f"Generated task for {task_type} resulted in None description. Raw response: {raw_gemini_response_text}")
                task_details_dict["description"] = "Error: Could not generate a valid task description."

            return task_details_dict
        else:
            logger.warning(f"Gemini returned empty response for task generation. Prompt feedback: {response.prompt_feedback if response else 'N/A'}")
            return None
    except Exception as e:
        logger.error(f"Error generating task with Gemini: {e}", exc_info=True)
        return None

# --- Helper: Evaluate Answer via Gemini ---
def evaluate_answer(gemini_key, task_details, user_answer_text=None, user_audio_bytes=None, audio_mime_type="audio/ogg"):
    logger.info(f"Evaluating answer for task type '{task_details.get('type')}'...")
    task_description = task_details.get('description', 'Task not specified')
    task_type = task_details.get('type', 'Unknown')

    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel(GEMINI_MODEL_NAME)

    prompt_parts = [
        f"Act as a friendly and supportive English tutor providing feedback.",
        f"The user was given the following task (type: {task_type}):",
        f"--- TASK INSTRUCTION START ---\n{task_description}\n--- TASK INSTRUCTION END ---"
    ]
    content_for_gemini = []
    is_correct_assessment_possible = True

    if task_type == "Voice Recording Analysis":
        is_correct_assessment_possible = False
        if user_audio_bytes:
            prompt_parts.append(
                "The user responded with this voice recording. "
                "Please analyze their spoken English focusing on aspects like: "
                "1. Pronunciation (clarity, specific sounds if the task was a sentence). "
                "2. Grammar (correct usage of tenses, articles, etc.). "
                "3. Vocabulary (appropriate word choice, idioms, etc.). "
                "4. Fluency (natural flow, pauses, etc.). "
                "Provide specific, actionable feedback and positive encouragement. "
                "Evaluate their coherence and usage."
            )
            audio_part = {"mime_type": audio_mime_type, "data": user_audio_bytes}
            content_for_gemini = prompt_parts + [audio_part]
        else:
            logger.error("Expected audio for Voice Recording Analysis, but none provided.")
            return {"feedback_text": "It seems you were supposed to send a voice message for this task, but I didn't receive any audio.", "is_correct": False}
    else:
        if user_answer_text:
            prompt_parts.append(f"The user responded with text:\n--- USER RESPONSE START ---\n{user_answer_text}\n--- USER RESPONSE END ---")
            prompt_parts.append(
                "Please evaluate the user's text response based ONLY on the given task. "
                "Be concise and clear. If correct, acknowledge it positively. "
                "If incorrect, gently point out the error and provide the correction or a hint."
            )
        else:
            logger.error("Expected text answer, but none provided.")
            return {"feedback_text": "I didn't receive your text answer for this task. Please try again.", "is_correct": False}

    if is_correct_assessment_possible:
        prompt_parts.append(
            "\nAfter providing feedback, on a new separate line, explicitly state if the user's answer was "
            "substantially correct for the main goal of the task by writing 'CORRECTNESS: YES' or 'CORRECTNESS: NO'."
        )
    
    if not content_for_gemini and task_type != "Voice Recording Analysis":
        content_for_gemini = "\n".join(prompt_parts)
    
    if not content_for_gemini:
         logger.error("Content for Gemini evaluation is empty.")
         return {"feedback_text": "Sorry, I couldn't prepare the content for evaluation.", "is_correct": False}

    try:
        logger.info(f"Sending content to Gemini for evaluation (type: {task_type})...")
        response = model.generate_content(content_for_gemini)
        
        feedback_text = ""
        is_correct = False

        if response.text:
            raw_feedback = response.text.strip()
            lines = raw_feedback.split('\n')
            cleaned_feedback_lines = []
            for line in lines:
                if line.upper().startswith("CORRECTNESS: YES"):
                    is_correct = True
                elif line.upper().startswith("CORRECTNESS: NO"):
                    is_correct = False
                else:
                    cleaned_feedback_lines.append(line)
            feedback_text = "\n".join(cleaned_feedback_lines).strip()
            
            if not is_correct_assessment_possible:
                is_correct = None
            
            logger.info(f"Generated feedback: {feedback_text[:100]}... Correct: {is_correct}")
            return {"feedback_text": feedback_text, "is_correct": is_correct}
        else:
            logger.warning(f"Gemini returned empty response for evaluation. Prompt feedback: {response.prompt_feedback}")
            return {"feedback_text": "Sorry, I couldn't generate feedback this time (Gemini returned no text).", "is_correct": False}
    except Exception as e:
        logger.error(f"Error evaluating answer with Gemini: {e}", exc_info=True)
        return {"feedback_text": f"Sorry, an error occurred while generating feedback with the AI model.", "is_correct": False}

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

# --- Helper: Get User Proficiency ---
def get_user_proficiency(user_doc_id):
    try:
        doc_ref = db.collection(PROFICIENCY_COLLECTION).document(user_doc_id)
        doc = doc_ref.get()
        if doc.exists:
            logger.info(f"Retrieved proficiency for {user_doc_id}")
            return doc.to_dict()
        else:
            logger.info(f"No proficiency data found for {user_doc_id}, returning empty.")
            return {}
    except Exception as e:
        logger.error(f"Error getting user proficiency for {user_doc_id}: {e}", exc_info=True)
        return {}

# --- Helper: Update User Proficiency ---
@firestore.transactional
def _update_proficiency_transaction(transaction, doc_ref, item_type_key, item_name, is_correct, task_id="unknown"):
    snapshot = doc_ref.get(transaction=transaction)
    data = snapshot.to_dict() if snapshot.exists else {}

    if item_type_key not in data:
        data[item_type_key] = {}
    
    if item_name not in data[item_type_key]:
        data[item_type_key][item_name] = {
            "attempts": 0, "correct": 0, "mastery_level": 0.0, "history": []
        }

    item_stats = data[item_type_key][item_name]
    item_stats["attempts"] += 1
    if is_correct:
        item_stats["correct"] += 1
    
    if item_stats["attempts"] > 0:
        item_stats["mastery_level"] = item_stats["correct"] / item_stats["attempts"]
    else:
        item_stats["mastery_level"] = 0.0
        
    item_stats["last_attempt_timestamp"] = firestore.SERVER_TIMESTAMP
    item_stats["last_task_id"] = task_id

    item_stats["history"].append({"timestamp": firestore.SERVER_TIMESTAMP, "correct": is_correct})
    if len(item_stats["history"]) > 1000:
        item_stats["history"] = item_stats["history"][-1000:]

    transaction.set(doc_ref, data)

def update_user_proficiency(user_doc_id, item_type_key, item_name, is_correct, task_id=None):
    if item_name is None:
        logger.warning(f"Skipping proficiency update for {user_doc_id}: item_name is None for item_type {item_type_key}")
        return False
    if is_correct is None:
        logger.info(f"Subjective task {item_name}, not updating mastery, only history/timestamp.")
    try:
        doc_ref = db.collection(PROFICIENCY_COLLECTION).document(user_doc_id)
        transaction = db.transaction()
        _update_proficiency_transaction(transaction, doc_ref, item_type_key, item_name, is_correct, task_id or "unknown")
        logger.info(f"Proficiency update committed for {user_doc_id}, {item_type_key}/{item_name}, Correct: {is_correct}")
        return True
    except Exception as e:
        logger.error(f"Error updating user proficiency for {user_doc_id}: {e}", exc_info=True)
        return False

# --- Helper: Transcribe Voice ---
def transcribe_voice(bot_token, file_id):
    try:
        get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
        res_file_path = requests.get(get_file_url, timeout=10)
        res_file_path.raise_for_status()
        file_path = res_file_path.json().get('result', {}).get('file_path')
        if not file_path:
            logger.error("Error: Could not get file_path from Telegram for transcription")
            return None

        file_download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        logger.info(f"Downloading audio from: {file_download_url}")
        res_audio = requests.get(file_download_url, timeout=20)
        res_audio.raise_for_status()
        audio_content = res_audio.content
        logger.info(f"Audio downloaded, size: {len(audio_content)} bytes")

        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
            sample_rate_hertz=48000,
            language_code="en-US",
            enable_automatic_punctuation=True
        )
        logger.debug(f"Using RecognitionConfig for transcription: {config}")
        audio = speech.RecognitionAudio(content=audio_content)
        
        logger.info("Sending audio to Speech-to-Text API...")
        response = speech_client.recognize(config=config, audio=audio)
        logger.debug(f"Full Speech API Response object: {response}")

        transcript = ""
        if response.results:
            transcript = response.results[0].alternatives[0].transcript
            logger.debug(f"Transcription successful: '{transcript}'")
            return transcript.strip()
        else:
            logger.warning("Speech-to-Text returned no results (response.results is empty).")
            return None
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Error inside transcribe_voice (Telegram Download): {req_err}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Error inside transcribe_voice (Transcription or Other): {e}", exc_info=True)
        return None