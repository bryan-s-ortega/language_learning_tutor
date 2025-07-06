import json
import random
import requests
import logging
import datetime

from google.cloud import secretmanager
from google.cloud import firestore
from google.cloud import speech
import google.generativeai as genai

logger = logging.getLogger(__name__)
PROJECT_ID = "daily-english-words"
TELEGRAM_TOKEN_SECRET_ID = "telegram-bot"
GEMINI_API_KEY_SECRET_ID = "gemini-api"

# Multi-user configuration
AUTHORIZED_USERS_SECRET_ID = "authorized-users"
ADMIN_USERS_SECRET_ID = "admin-users"

FIRESTORE_COLLECTION = "english_practice_state"
PROFICIENCY_COLLECTION = "user_proficiency"

GEMINI_MODEL_NAME = "gemini-2.0-flash-001"

secret_client = secretmanager.SecretManagerServiceClient()
db = firestore.Client(project=PROJECT_ID)
speech_client = speech.SpeechClient()

TASK_TYPES = [
    "Error correction",
    "Vocabulary matching",
    "Idiom/Phrasal verb",
    "Word starting with letter",
    "Voice Recording Analysis",
]


# --- Helper: Access Secret ---
def access_secret_version(secret_id, version_id="latest"):
    if not PROJECT_ID:
        logger.critical(
            "GCP_PROJECT environment variable not set or PROJECT_ID constant is empty."
        )
        raise ValueError(
            "GCP_PROJECT environment variable not set or PROJECT_ID constant is empty."
        )
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/{version_id}"
    try:
        response = secret_client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        logger.error(f"Error accessing secret {secret_id}: {e}", exc_info=True)
        raise


# --- Multi-User Authentication Helpers ---
def get_authorized_users():
    """Get list of authorized user chat IDs"""
    try:
        users_data = access_secret_version(AUTHORIZED_USERS_SECRET_ID)
        # Handle both JSON array format and line-separated format
        if users_data.strip().startswith("["):
            # JSON array format
            return json.loads(users_data)
        else:
            # Line-separated format or single value
            users = [
                line.strip() for line in users_data.strip().split("\n") if line.strip()
            ]
            return users
    except Exception as e:
        logger.error(f"Error getting authorized users: {e}")
        return []


def get_admin_users():
    """Get list of admin user chat IDs"""
    try:
        users_data = access_secret_version(ADMIN_USERS_SECRET_ID)
        # Handle both JSON array format and line-separated format
        if users_data.strip().startswith("["):
            # JSON array format
            return json.loads(users_data)
        else:
            # Line-separated format or single value
            users = [
                line.strip() for line in users_data.strip().split("\n") if line.strip()
            ]
            return users
    except Exception as e:
        logger.error(f"Error getting admin users: {e}")
        return []


def is_user_authorized(chat_id):
    """Check if user is authorized"""
    authorized_users = get_authorized_users()
    return str(chat_id) in authorized_users


def is_admin_user(chat_id):
    """Check if user is an admin"""
    admin_users = get_admin_users()
    return str(chat_id) in admin_users


def add_user_to_whitelist(chat_id):
    """Add a user to the authorized users list"""
    try:
        current_users = get_authorized_users()
        if str(chat_id) not in current_users:
            current_users.append(str(chat_id))
            # Save in line-separated format
            users_text = "\n".join(current_users)

            # Update the secret
            secret_name = f"projects/{PROJECT_ID}/secrets/{AUTHORIZED_USERS_SECRET_ID}"
            secret_client.add_secret_version(
                request={
                    "parent": secret_name,
                    "payload": {"data": users_text.encode("UTF-8")},
                }
            )
            logger.info(f"Added user {chat_id} to authorized users")
            return True
        else:
            logger.info(f"User {chat_id} already authorized")
            return True
    except Exception as e:
        logger.error(f"Error adding user {chat_id} to whitelist: {e}")
        return False


def remove_user_from_whitelist(chat_id):
    """Remove a user from the authorized users list"""
    try:
        current_users = get_authorized_users()
        if str(chat_id) in current_users:
            current_users.remove(str(chat_id))
            # Save in line-separated format
            users_text = "\n".join(current_users)

            # Update the secret
            secret_name = f"projects/{PROJECT_ID}/secrets/{AUTHORIZED_USERS_SECRET_ID}"
            secret_client.add_secret_version(
                request={
                    "parent": secret_name,
                    "payload": {"data": users_text.encode("UTF-8")},
                }
            )
            logger.info(f"Removed user {chat_id} from authorized users")
            return True
        else:
            logger.info(f"User {chat_id} not found in authorized users")
            return False
    except Exception as e:
        logger.error(f"Error removing user {chat_id} from whitelist: {e}")
        return False


def get_system_statistics():
    """Get overall system statistics"""
    stats = {
        "total_users": 0,
        "active_users_today": 0,
        "total_tasks_completed": 0,
        "average_accuracy": 0.0,
    }

    try:
        # Count total users
        authorized_users = get_authorized_users()
        stats["total_users"] = len(authorized_users)

        # Calculate system-wide statistics
        total_accuracy = 0.0
        total_tasks = 0
        active_users = 0

        for user_id in authorized_users:
            # Get user proficiency data
            proficiency_data = get_user_proficiency(user_id)
            if proficiency_data:
                user_tasks = 0
                user_correct = 0

                for category, items in proficiency_data.items():
                    for item_name, item_stats in items.items():
                        user_tasks += item_stats.get("attempts", 0)
                        user_correct += item_stats.get("correct", 0)

                total_tasks += user_tasks
                if user_tasks > 0:
                    total_accuracy += user_correct / user_tasks
                    active_users += 1

        stats["active_users_today"] = active_users
        stats["total_tasks_completed"] = total_tasks
        stats["average_accuracy"] = (
            (total_accuracy / stats["total_users"]) if stats["total_users"] > 0 else 0.0
        )

    except Exception as e:
        logger.error(f"Error getting system statistics: {e}")

    return stats


# --- Rate Limiting ---
def get_user_rate_limit_key(user_id):
    """Get the Firestore key for user rate limiting"""
    return f"rate_limit_{user_id}"


def check_rate_limit(user_id, max_requests=10, window_minutes=5):
    """Check if user has exceeded rate limit"""
    try:
        rate_key = get_user_rate_limit_key(user_id)
        current_time = datetime.datetime.now()

        # Get current rate limit data
        rate_data = get_firestore_state(user_doc_id=rate_key)
        if not rate_data:
            # First request, initialize
            rate_data = {
                "requests": [current_time.isoformat()],
                "window_start": current_time.isoformat(),
            }
            update_firestore_state(rate_data, user_doc_id=rate_key)
            return True

        # Parse existing data
        requests = [
            datetime.datetime.fromisoformat(req)
            for req in rate_data.get("requests", [])
        ]
        window_start = datetime.datetime.fromisoformat(
            rate_data.get("window_start", current_time.isoformat())
        )

        # Remove old requests outside the window
        window_end = window_start + datetime.timedelta(minutes=window_minutes)
        requests = [
            req for req in requests if req >= window_start and req <= current_time
        ]

        # Check if we need to start a new window
        if current_time > window_end:
            window_start = current_time
            requests = []

        # Check rate limit
        if len(requests) >= max_requests:
            return False

        # Add current request
        requests.append(current_time)

        # Update rate limit data
        new_rate_data = {
            "requests": [req.isoformat() for req in requests],
            "window_start": window_start.isoformat(),
        }
        update_firestore_state(new_rate_data, user_doc_id=rate_key)

        return True

    except Exception as e:
        logger.error(f"Error checking rate limit for user {user_id}: {e}")
        # On error, allow the request (fail open)
        return True


# --- Helper: Send Telegram Message ---
def send_telegram_message(bot_token, chat_id, text, reply_markup=None):
    telegram_api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    if text is None:
        logger.error(
            f"send_telegram_message called with text=None for chat_id {chat_id}. Sending a default error message."
        )
        text = "Sorry, an unexpected error occurred, and I don't have a specific message to send."

    # Validate and sanitize text for Telegram
    if len(text) > 4096:
        logger.warning(
            f"Message too long ({len(text)} chars), truncating to 4096 chars"
        )
        text = text[:4093] + "..."

    # Escape problematic Markdown characters that might cause 400 errors
    # Remove or escape characters that can break Markdown parsing
    text = (
        text.replace("_", r"\_")
        .replace("*", r"\*")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace("`", r"\`")
    )

    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

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
            payload_no_markdown = {"chat_id": chat_id, "text": text}
            if reply_markup:
                payload_no_markdown["reply_markup"] = json.dumps(reply_markup)

            response = requests.post(
                telegram_api_url, json=payload_no_markdown, timeout=15
            )
            if response.status_code == 200:
                logger.info("Message sent successfully without Markdown")
                return response.json().get("ok", False)
            else:
                logger.error(
                    f"Failed even without Markdown. Status: {response.status_code}, Response: {response.text}"
                )

        response.raise_for_status()
        logger.info(f"Telegram send status: {response.status_code}")
        return response.json().get("ok", False)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending Telegram message to {chat_id}: {e}", exc_info=True)
        try:
            # Log response content if available
            if hasattr(e, "response") and e.response is not None:
                logger.error(f"Response content: {e.response.text}")
        except Exception:
            pass
        return False


# --- Helper: Get/Update Firestore State ---
def get_firestore_state(user_doc_id):
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
        logger.error(
            f"Error getting Firestore state for {user_doc_id}: {e}", exc_info=True
        )
        return {"interaction_state": "idle"}


def update_firestore_state(state_data, user_doc_id):
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION).document(user_doc_id)
        state_data["last_update"] = firestore.SERVER_TIMESTAMP
        doc_ref.set(state_data, merge=True)
        logger.info(f"Updated state for {user_doc_id}: {state_data}")
        return True
    except Exception as e:
        logger.error(
            f"Error updating Firestore state for {user_doc_id}: {e}", exc_info=True
        )
        return False


# --- Helper: Generate Task via Gemini ---
def generate_task(gemini_key, task_type, user_doc_id, topic=None):
    # Get user proficiency data for adaptive learning
    proficiency_data = get_user_proficiency(user_doc_id)

    # Analyze weak areas for this task type
    weak_items = analyze_user_weaknesses(proficiency_data, task_type)

    # Get items that need review based on spaced repetition
    review_items = get_items_for_review(proficiency_data, task_type)

    # Generate adaptive prompt
    prompt_base = get_adaptive_task_prompt(task_type, weak_items, topic)

    # Add review items to prompt if available
    if review_items and not weak_items:
        review_areas = [item["name"] for item in review_items[:2]]
        prompt_base += (
            f"\n\nConsider including review of these areas: {', '.join(review_areas)}."
        )

    task_details_dict = {
        "type": task_type,
        "specific_item_tested": None,
        "description": None,
    }
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
        letter = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        task_details_dict["description"] = (
            f"This is a fluency task. List as many English words as you can starting with the letter '{letter}' in one minute."
        )
        task_details_dict["specific_item_tested"] = f"words_starting_with_{letter}"
        logger.info(f"Generated task for Word starting with letter: {letter}")
        return task_details_dict

    elif task_type == "Voice Recording Analysis":
        instruction_generation_prompt = (
            prompt_base
            + "Ask the user to record a voice message of any length. "
            + "The instruction should be to talk about any topic. "
            + "Output only the instruction for the user."
        )
        logger.info(
            f"Generating voice task instruction with prompt: {instruction_generation_prompt}"
        )
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        instruction_response = model.generate_content(instruction_generation_prompt)
        if instruction_response.text:
            task_details_dict["description"] = instruction_response.text.strip()
            logger.info(
                f"Generated voice task instruction: {task_details_dict['description']}"
            )
            return task_details_dict
        else:
            logger.warning(
                "Gemini failed to generate voice task instruction, using fallback."
            )
            task_details_dict["description"] = (
                "Please record a voice message. I will analyze your spoken English."
            )
            return task_details_dict
    else:
        logger.warning(
            f"Unknown or unadapted task type for specific item generation: {task_type}"
        )
        return None

    if not prompt:
        logger.error(f"Prompt not set for task type: {task_type}")
        return None

    logger.info(
        f"Generating task for type '{task_type}' with prompt: {prompt[:100]}..."
    )
    try:
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        response = model.generate_content(prompt)

        if response.text:
            raw_gemini_response_text = response.text.strip()
            logger.info(
                f"Generated task content (raw): {raw_gemini_response_text[:300]}..."
            )

            lines = raw_gemini_response_text.split("\n")
            items_found = []
            other_lines_for_description = []

            for line in lines:
                if line.upper().startswith("ITEM:"):
                    items_found.append(line[len("ITEM:") :].strip())
                else:
                    other_lines_for_description.append(line)
            if task_type == "Vocabulary matching":
                if items_found:
                    user_description = "Match the following words with their definitions:\n\n**Words to match:**\n"
                    for i, word in enumerate(items_found):
                        user_description += f"{i + 1}. {word}\n"
                    user_description += "\n**Definitions:**\n"
                    user_description += "\n".join(other_lines_for_description).strip()
                    task_details_dict["description"] = user_description
                    task_details_dict["specific_item_tested"] = items_found
                else:
                    logger.warning(
                        "Vocabulary matching: 'ITEM:' tags not found or parsed incorrectly. Using full response as description."
                    )
                    task_details_dict["description"] = raw_gemini_response_text
                    task_details_dict["specific_item_tested"] = [
                        letter[len("ITEM:") :].strip()
                        for letter in raw_gemini_response_text.split("\n")
                        if letter.upper().startswith("ITEM:")
                    ]

            else:
                task_details_dict["description"] = "\n".join(
                    other_lines_for_description
                ).strip()
                if items_found:
                    task_details_dict["specific_item_tested"] = items_found[0]

            if not task_details_dict.get("description") and raw_gemini_response_text:
                logger.warning(
                    f"Description for task type {task_type} was empty after parsing, falling back to raw Gemini text."
                )
                task_details_dict["description"] = raw_gemini_response_text

            if task_details_dict.get("description") is None:
                logger.error(
                    f"Generated task for {task_type} resulted in None description. Raw response: {raw_gemini_response_text}"
                )
                task_details_dict["description"] = (
                    "Error: Could not generate a valid task description."
                )

            return task_details_dict
        else:
            logger.warning(
                f"Gemini returned empty response for task generation. Prompt feedback: {response.prompt_feedback if response else 'N/A'}"
            )
            return None
    except Exception as e:
        logger.error(f"Error generating task with Gemini: {e}", exc_info=True)
        return None


# --- Helper: Evaluate Answer via Gemini ---
def evaluate_answer(
    gemini_key,
    task_details,
    user_answer_text=None,
    user_audio_bytes=None,
    audio_mime_type="audio/ogg",
    user_doc_id=None,
):
    logger.info(f"Evaluating answer for task type '{task_details.get('type')}'...")
    task_description = task_details.get("description", "Task not specified")
    task_type = task_details.get("type", "Unknown")

    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel(GEMINI_MODEL_NAME)

    # Get user's learning history for personalized feedback
    learning_context = ""
    if user_doc_id:
        proficiency_data = get_user_proficiency(user_doc_id)
        if proficiency_data:
            specific_item = task_details.get("specific_item_tested")
            if specific_item:
                # Check if this specific item has been practiced before
                item_type_key = None
                if task_type == "Error correction":
                    item_type_key = "grammar_topics"
                elif task_type == "Vocabulary matching":
                    item_type_key = "vocabulary_words"
                elif task_type == "Idiom/Phrasal verb":
                    item_type_key = "phrasal_verbs"

                if item_type_key and item_type_key in proficiency_data:
                    if specific_item in proficiency_data[item_type_key]:
                        item_stats = proficiency_data[item_type_key][specific_item]
                        attempts = item_stats.get("attempts", 0)
                        mastery_level = item_stats.get("mastery_level", 0.0)

                        if attempts > 1:
                            if mastery_level < 0.5:
                                learning_context = f"\n\nNote: The user has practiced this specific topic ({specific_item}) {attempts} times with {mastery_level * 100:.0f}% success rate. They seem to find this challenging, so provide extra encouragement and clear explanations."
                            elif mastery_level > 0.8:
                                learning_context = f"\n\nNote: The user has practiced this specific topic ({specific_item}) {attempts} times with {mastery_level * 100:.0f}% success rate. They're doing well with this, so you can provide more challenging feedback or advanced tips."

    prompt_parts = [
        "Act as a friendly and supportive English tutor providing feedback.",
        f"The user was given the following task (type: {task_type}):",
        f"--- TASK INSTRUCTION START ---\n{task_description}\n--- TASK INSTRUCTION END ---",
    ]

    if learning_context:
        prompt_parts.append(learning_context)
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
            logger.error(
                "Expected audio for Voice Recording Analysis, but none provided."
            )
            return {
                "feedback_text": "It seems you were supposed to send a voice message for this task, but I didn't receive any audio.",
                "is_correct": False,
            }
    else:
        if user_answer_text:
            prompt_parts.append(
                f"The user responded with text:\n--- USER RESPONSE START ---\n{user_answer_text}\n--- USER RESPONSE END ---"
            )
            prompt_parts.append(
                "Please evaluate the user's text response based ONLY on the given task. "
                "Be concise and clear. If correct, acknowledge it positively. "
                "If incorrect, gently point out the error and provide the correction or a hint."
            )
        else:
            logger.error("Expected text answer, but none provided.")
            return {
                "feedback_text": "I didn't receive your text answer for this task. Please try again.",
                "is_correct": False,
            }

    if is_correct_assessment_possible:
        prompt_parts.append(
            "\nAfter providing feedback, on a new separate line, explicitly state if the user's answer was "
            "substantially correct for the main goal of the task by writing 'CORRECTNESS: YES' or 'CORRECTNESS: NO'."
        )

    if not content_for_gemini and task_type != "Voice Recording Analysis":
        content_for_gemini = "\n".join(prompt_parts)

    if not content_for_gemini:
        logger.error("Content for Gemini evaluation is empty.")
        return {
            "feedback_text": "Sorry, I couldn't prepare the content for evaluation.",
            "is_correct": False,
        }

    try:
        logger.info(f"Sending content to Gemini for evaluation (type: {task_type})...")
        response = model.generate_content(content_for_gemini)

        feedback_text = ""
        is_correct = False

        if response.text:
            raw_feedback = response.text.strip()
            lines = raw_feedback.split("\n")
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

            logger.info(
                f"Generated feedback: {feedback_text[:100]}... Correct: {is_correct}"
            )
            return {"feedback_text": feedback_text, "is_correct": is_correct}
        else:
            logger.warning(
                f"Gemini returned empty response for evaluation. Prompt feedback: {response.prompt_feedback}"
            )
            return {
                "feedback_text": "Sorry, I couldn't generate feedback this time (Gemini returned no text).",
                "is_correct": False,
            }
    except Exception as e:
        logger.error(f"Error evaluating answer with Gemini: {e}", exc_info=True)
        return {
            "feedback_text": "Sorry, an error occurred while generating feedback with the AI model.",
            "is_correct": False,
        }


# --- Helper: Send Choice Request Message ---
def send_choice_request_message(bot_token, chat_id, user_doc_id):
    logger.info(f"Attempting to send choice request message to {chat_id}")
    try:
        keyboard_buttons = [[task_type] for task_type in TASK_TYPES]
        reply_markup = {
            "keyboard": keyboard_buttons,
            "one_time_keyboard": True,
            "resize_keyboard": True,
        }

        message_text = "👋 Okay, let's start a new task! What type of English practice would you like?\nChoose one option from the keyboard below:"

        # Add adaptive learning suggestions if user_doc_id is provided
        if user_doc_id:
            proficiency_data = get_user_proficiency(user_doc_id)
            if proficiency_data:
                suggested_task_type = get_adaptive_task_type(proficiency_data)
                message_text += f"\n\n💡 **Adaptive Suggestion**: Based on your learning progress, I recommend trying **{suggested_task_type}** to focus on areas where you can improve most!"

        success = send_telegram_message(bot_token, chat_id, message_text, reply_markup)
        if success:
            logger.info("Choice request message sent successfully.")
            return True
        else:
            logger.error("Failed to send choice request message via Telegram helper.")
            return False
    except Exception as e:
        logger.error(
            f"Error within send_choice_request_message helper: {e}", exc_info=True
        )
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
            logger.info(
                f"No proficiency data found for {user_doc_id}, returning empty."
            )
            return {}
    except Exception as e:
        logger.error(
            f"Error getting user proficiency for {user_doc_id}: {e}", exc_info=True
        )
        return {}


# --- Adaptive Learning Helpers ---
def analyze_user_weaknesses(proficiency_data, task_type):
    """
    Analyze user proficiency data to identify weak areas for a specific task type.
    Returns a list of items that need more practice.
    """
    if not proficiency_data:
        return []

    weak_items = []
    item_type_key = None

    # Map task types to proficiency categories
    if task_type == "Error correction":
        item_type_key = "grammar_topics"
    elif task_type == "Vocabulary matching":
        item_type_key = "vocabulary_words"
    elif task_type == "Idiom/Phrasal verb":
        item_type_key = "phrasal_verbs"

    if not item_type_key or item_type_key not in proficiency_data:
        return []

    items = proficiency_data[item_type_key]

    # Find items with low mastery level (below 0.7) and sufficient attempts (at least 2)
    for item_name, stats in items.items():
        mastery_level = stats.get("mastery_level", 0.0)
        attempts = stats.get("attempts", 0)

        if attempts >= 2 and mastery_level < 0.7:
            weak_items.append(
                {
                    "name": item_name,
                    "mastery_level": mastery_level,
                    "attempts": attempts,
                    "priority_score": (0.7 - mastery_level)
                    * attempts,  # Higher priority for more attempts with low mastery
                }
            )

    # Sort by priority score (highest first)
    weak_items.sort(key=lambda x: x["priority_score"], reverse=True)

    logger.info(
        f"Found {len(weak_items)} weak items for {task_type}: {[item['name'] for item in weak_items[:3]]}"
    )
    return weak_items


def get_adaptive_task_prompt(task_type, weak_items, topic=None):
    """
    Generate an adaptive prompt based on user's weak areas.
    """
    prompt_base = f"Generate an English learning task for an advanced learner. Task Type: '{task_type}'. "

    if topic:
        prompt_base += f"The general theme for today is '{topic}'. "

    if weak_items:
        weak_areas = [
            item["name"] for item in weak_items[:3]
        ]  # Focus on top 3 weak areas
        prompt_base += f"\n\nIMPORTANT: The user has been struggling with these specific areas: {', '.join(weak_areas)}. "
        prompt_base += "Please focus the task on one or more of these weak areas to help them improve. "
        prompt_base += "Make the task slightly easier than usual since these are challenging areas for the user."
    else:
        prompt_base += "\n\nThe user has been performing well in this area. Please provide a task that challenges them appropriately."

    return prompt_base


def get_adaptive_task_type(proficiency_data):
    """
    Suggest the best task type based on user's overall performance.
    Returns the task type that needs the most attention.
    """
    if not proficiency_data:
        return random.choice(TASK_TYPES)

    task_type_scores = {}

    # Calculate average mastery for each task type
    for task_type in ["Error correction", "Vocabulary matching", "Idiom/Phrasal verb"]:
        item_type_key = None
        if task_type == "Error correction":
            item_type_key = "grammar_topics"
        elif task_type == "Vocabulary matching":
            item_type_key = "vocabulary_words"
        elif task_type == "Idiom/Phrasal verb":
            item_type_key = "phrasal_verbs"

        if item_type_key in proficiency_data and proficiency_data[item_type_key]:
            items = proficiency_data[item_type_key]
            total_mastery = 0
            total_attempts = 0

            for item_name, stats in items.items():
                mastery_level = stats.get("mastery_level", 0.0)
                attempts = stats.get("attempts", 0)
                total_mastery += mastery_level * attempts
                total_attempts += attempts

            if total_attempts > 0:
                avg_mastery = total_mastery / total_attempts
                # Lower score = more practice needed
                task_type_scores[task_type] = avg_mastery
            else:
                task_type_scores[task_type] = 0.0  # No practice yet
        else:
            task_type_scores[task_type] = 0.0  # No data yet

    # Find task type with lowest average mastery
    if task_type_scores:
        worst_task_type = min(
            task_type_scores.keys(), key=lambda x: task_type_scores[x]
        )
        logger.info(
            f"Adaptive task type selection: {worst_task_type} (avg mastery: {task_type_scores[worst_task_type]:.2f})"
        )
        return worst_task_type

    return random.choice(TASK_TYPES)


def should_review_item(item_stats, days_since_last_attempt=7):
    """
    Determine if an item should be reviewed based on spaced repetition principles.
    """
    if not item_stats or "last_attempt_timestamp" not in item_stats:
        return True  # Never attempted, should review

    last_attempt = item_stats["last_attempt_timestamp"]
    if not last_attempt:
        return True

    # Convert Firestore timestamp to datetime
    from datetime import datetime, timezone

    if hasattr(last_attempt, "timestamp"):
        last_attempt_dt = datetime.fromtimestamp(
            last_attempt.timestamp(), tz=timezone.utc
        )
    else:
        last_attempt_dt = last_attempt

    days_elapsed = (datetime.now(timezone.utc) - last_attempt_dt).days

    mastery_level = item_stats.get("mastery_level", 0.0)

    # Spaced repetition logic:
    # - Low mastery (< 0.5): review every 3 days
    # - Medium mastery (0.5-0.8): review every 7 days
    # - High mastery (> 0.8): review every 14 days
    if mastery_level < 0.5:
        return days_elapsed >= 3
    elif mastery_level < 0.8:
        return days_elapsed >= 7
    else:
        return days_elapsed >= 14


def get_items_for_review(proficiency_data, task_type):
    """
    Get items that should be reviewed based on spaced repetition.
    """
    if not proficiency_data:
        return []

    item_type_key = None
    if task_type == "Error correction":
        item_type_key = "grammar_topics"
    elif task_type == "Vocabulary matching":
        item_type_key = "vocabulary_words"
    elif task_type == "Idiom/Phrasal verb":
        item_type_key = "phrasal_verbs"

    if not item_type_key or item_type_key not in proficiency_data:
        return []

    items = proficiency_data[item_type_key]
    review_items = []

    for item_name, stats in items.items():
        if should_review_item(stats):
            review_items.append(
                {
                    "name": item_name,
                    "mastery_level": stats.get("mastery_level", 0.0),
                    "attempts": stats.get("attempts", 0),
                }
            )

    # Sort by mastery level (lowest first for review priority)
    review_items.sort(key=lambda x: x["mastery_level"])

    logger.info(f"Found {len(review_items)} items for review in {task_type}")
    return review_items


def generate_progress_report(proficiency_data):
    """
    Generate a user-friendly progress report from proficiency data.
    """
    if not proficiency_data:
        return "📊 **Learning Progress**: No data available yet."

    report_parts = ["📊 **Your Learning Progress**\n"]

    # Track overall statistics
    total_attempts = 0
    total_correct = 0
    category_stats = {}

    for category, items in proficiency_data.items():
        if not items:
            continue

        category_attempts = 0
        category_correct = 0

        for item_name, stats in items.items():
            attempts = stats.get("attempts", 0)
            correct = stats.get("correct", 0)

            category_attempts += attempts
            category_correct += correct
            total_attempts += attempts
            total_correct += correct

        if category_attempts > 0:
            category_accuracy = (category_correct / category_attempts) * 100
            category_stats[category] = {
                "attempts": category_attempts,
                "correct": category_correct,
                "accuracy": category_accuracy,
            }

    # Overall progress
    if total_attempts > 0:
        overall_accuracy = (total_correct / total_attempts) * 100
        report_parts.append(
            f"🎯 **Overall Accuracy**: {overall_accuracy:.1f}% ({total_correct}/{total_attempts} correct)"
        )
        report_parts.append(f"📚 **Total Practice Sessions**: {total_attempts}\n")

    # Category breakdown
    if category_stats:
        report_parts.append("📈 **Progress by Category**:")

        category_names = {
            "grammar_topics": "Grammar Topics",
            "vocabulary_words": "Vocabulary Words",
            "phrasal_verbs": "Phrasal Verbs & Idioms",
        }

        for category, stats in category_stats.items():
            category_name = category_names.get(
                category, category.replace("_", " ").title()
            )
            emoji = (
                "🔧"
                if stats["accuracy"] < 60
                else "✅"
                if stats["accuracy"] >= 80
                else "📈"
            )
            report_parts.append(
                f"{emoji} **{category_name}**: {stats['accuracy']:.1f}% ({stats['correct']}/{stats['attempts']})"
            )

    # Weak areas
    weak_areas = []
    for category, items in proficiency_data.items():
        for item_name, stats in items.items():
            if stats.get("attempts", 0) >= 2 and stats.get("mastery_level", 0.0) < 0.6:
                weak_areas.append(item_name)

    if weak_areas:
        report_parts.append(f"\n⚠️ **Areas for Improvement** ({len(weak_areas)} items):")
        for area in weak_areas[:5]:  # Show top 5 weak areas
            report_parts.append(f"• {area}")
        if len(weak_areas) > 5:
            report_parts.append(f"• ... and {len(weak_areas) - 5} more")

    # Recommendations
    report_parts.append("\n💡 **Recommendations**:")
    if total_attempts == 0:
        report_parts.append(
            "• Start with any task type to begin tracking your progress"
        )
    elif overall_accuracy < 60:
        report_parts.append("• Focus on reviewing challenging areas")
        report_parts.append("• Try more practice sessions to improve accuracy")
    elif overall_accuracy >= 80:
        report_parts.append("• Great progress! Try more challenging tasks")
        report_parts.append("• Consider exploring new vocabulary and grammar concepts")
    else:
        report_parts.append("• Good progress! Keep practicing to reach mastery")
        report_parts.append("• Review areas where you made mistakes")

    return "\n".join(report_parts)


# --- Helper: Update User Proficiency ---
@firestore.transactional
def _update_proficiency_transaction(
    transaction, doc_ref, item_type_key, item_name, is_correct, task_id="unknown"
):
    snapshot = doc_ref.get(transaction=transaction)
    data = snapshot.to_dict() if snapshot.exists else {}

    if item_type_key not in data:
        data[item_type_key] = {}

    if item_name not in data[item_type_key]:
        data[item_type_key][item_name] = {
            "attempts": 0,
            "correct": 0,
            "mastery_level": 0.0,
            "history": [],
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

    item_stats["history"].append(
        {"timestamp": firestore.SERVER_TIMESTAMP, "correct": is_correct}
    )
    if len(item_stats["history"]) > 1000:
        item_stats["history"] = item_stats["history"][-1000:]

    transaction.set(doc_ref, data)


def update_user_proficiency(
    user_doc_id, item_type_key, item_name, is_correct, task_id=None
):
    if item_name is None:
        logger.warning(
            f"Skipping proficiency update for {user_doc_id}: item_name is None for item_type {item_type_key}"
        )
        return False
    if is_correct is None:
        logger.info(
            f"Subjective task {item_name}, not updating mastery, only history/timestamp."
        )
    try:
        doc_ref = db.collection(PROFICIENCY_COLLECTION).document(user_doc_id)
        transaction = db.transaction()
        _update_proficiency_transaction(
            transaction,
            doc_ref,
            item_type_key,
            item_name,
            is_correct,
            task_id or "unknown",
        )
        logger.info(
            f"Proficiency update committed for {user_doc_id}, {item_type_key}/{item_name}, Correct: {is_correct}"
        )
        return True
    except Exception as e:
        logger.error(
            f"Error updating user proficiency for {user_doc_id}: {e}", exc_info=True
        )
        return False


# --- Helper: Transcribe Voice using Gemini Multi-Modal ---
def transcribe_voice(bot_token, file_id, gemini_key=None):
    try:
        get_file_url = (
            f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
        )
        res_file_path = requests.get(get_file_url, timeout=10)
        res_file_path.raise_for_status()
        file_path = res_file_path.json().get("result", {}).get("file_path")
        if not file_path:
            logger.error(
                "Error: Could not get file_path from Telegram for transcription"
            )
            return None

        file_download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        logger.info(f"Downloading audio from: {file_download_url}")
        res_audio = requests.get(
            file_download_url, timeout=30
        )  # Increased timeout for longer audio
        res_audio.raise_for_status()
        audio_content = res_audio.content
        logger.info(f"Audio downloaded, size: {len(audio_content)} bytes")

        # Use Gemini multi-modal for audio transcription
        if gemini_key:
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel(GEMINI_MODEL_NAME)

            prompt = """
            Please transcribe this audio message. Extract the spoken text accurately and return ONLY the transcription.
            If the audio is unclear or contains background noise, do your best to transcribe what you can hear.
            Return the transcription as plain text without any additional formatting or commentary.
            """

            # Create audio part for Gemini
            audio_part = {"mime_type": "audio/ogg", "data": audio_content}

            logger.info("Sending audio to Gemini for transcription...")
            response = model.generate_content([prompt, audio_part])

            if response.text:
                transcript = response.text.strip()
                logger.info(f"Gemini transcription successful: '{transcript[:100]}...'")
                return transcript
            else:
                logger.warning("Gemini returned empty response for transcription")
                return None
        else:
            logger.error("No Gemini API key provided for transcription")
            return None

    except requests.exceptions.RequestException as req_err:
        logger.error(
            f"Error inside transcribe_voice (Telegram Download): {req_err}",
            exc_info=True,
        )
        return None
    except Exception as e:
        logger.error(
            f"Error inside transcribe_voice (Gemini Transcription): {e}", exc_info=True
        )
        return None
