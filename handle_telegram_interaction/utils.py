import json
import random
import requests
import logging
import datetime
import sys
import os
from typing import Optional, Dict, Any, List
from config import config

from google.cloud import secretmanager
from google.cloud import firestore
from google.cloud import speech
import google.generativeai as genai

# Add the parent directory to the path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure structured logging
logging.basicConfig(
    level=getattr(logging, config.logging.level), format=config.logging.format
)
logger = logging.getLogger(__name__)

# Initialize clients with error handling
try:
    secret_client = secretmanager.SecretManagerServiceClient()
    db = firestore.Client(project=config.database.project_id)
    speech_client = speech.SpeechClient()
except Exception as e:
    logger.error(f"Failed to initialize Google Cloud clients: {e}")
    raise


class LanguageLearningError(Exception):
    """Base exception for language learning application"""

    pass


class SecretAccessError(LanguageLearningError):
    """Raised when secret access fails"""

    pass


class FirestoreError(LanguageLearningError):
    """Raised when Firestore operations fail"""

    pass


class TelegramAPIError(LanguageLearningError):
    """Raised when Telegram API calls fail"""

    pass


class GeminiAPIError(LanguageLearningError):
    """Raised when Gemini API calls fail"""

    pass


# --- Helper: Access Secret ---
def access_secret_version(secret_id: str, version_id: str = "latest") -> str:
    """
    Access a secret version from Google Secret Manager.

    Args:
        secret_id: The secret ID to access
        version_id: The version ID (defaults to "latest")

    Returns:
        The secret value as a string

    Raises:
        SecretAccessError: If secret access fails
    """
    if not config.database.project_id:
        error_msg = (
            "GCP_PROJECT environment variable not set or PROJECT_ID constant is empty."
        )
        logger.critical(error_msg)
        raise SecretAccessError(error_msg)

    name = f"projects/{config.database.project_id}/secrets/{secret_id}/versions/{version_id}"

    try:
        response = secret_client.access_secret_version(request={"name": name})
        logger.debug(f"Successfully accessed secret: {secret_id}")
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        error_msg = f"Error accessing secret {secret_id}: {e}"
        logger.error(error_msg, exc_info=True)
        raise SecretAccessError(error_msg) from e


# --- Multi-User Authentication Helpers ---
def get_authorized_users() -> List[str]:
    """
    Get list of authorized user chat IDs.

    Returns:
        List of authorized user chat IDs

    Raises:
        SecretAccessError: If secret access fails
    """
    try:
        users_data = access_secret_version(config.secrets.authorized_users_secret_id)

        # Handle both JSON array format and line-separated format
        if users_data.strip().startswith("["):
            # JSON array format
            return json.loads(users_data)
        else:
            # Line-separated format or single value
            users = [
                line.strip() for line in users_data.strip().split("\n") if line.strip()
            ]
            logger.debug(f"Retrieved {len(users)} authorized users")
            return users
    except Exception as e:
        logger.error(f"Error getting authorized users: {e}", exc_info=True)
        return []


def get_admin_users() -> List[str]:
    """
    Get list of admin user chat IDs.

    Returns:
        List of admin user chat IDs

    Raises:
        SecretAccessError: If secret access fails
    """
    try:
        users_data = access_secret_version(config.secrets.admin_users_secret_id)

        # Handle both JSON array format and line-separated format
        if users_data.strip().startswith("["):
            # JSON array format
            return json.loads(users_data)
        else:
            # Line-separated format or single value
            users = [
                line.strip() for line in users_data.strip().split("\n") if line.strip()
            ]
            logger.debug(f"Retrieved {len(users)} admin users")
            return users
    except Exception as e:
        logger.error(f"Error getting admin users: {e}", exc_info=True)
        return []


def is_user_authorized(chat_id: str) -> bool:
    """
    Check if user is authorized.

    Args:
        chat_id: The user's chat ID

    Returns:
        True if user is authorized, False otherwise
    """
    try:
        authorized_users = get_authorized_users()
        is_authorized = str(chat_id) in authorized_users
        logger.debug(f"User {chat_id} authorization check: {is_authorized}")
        return is_authorized
    except Exception as e:
        logger.error(f"Error checking user authorization for {chat_id}: {e}")
        return False


def is_admin_user(chat_id: str) -> bool:
    """
    Check if user is an admin.

    Args:
        chat_id: The user's chat ID

    Returns:
        True if user is admin, False otherwise
    """
    try:
        admin_users = get_admin_users()
        is_admin = str(chat_id) in admin_users
        logger.debug(f"User {chat_id} admin check: {is_admin}")
        return is_admin
    except Exception as e:
        logger.error(f"Error checking admin status for {chat_id}: {e}")
        return False


def add_user_to_whitelist(chat_id: str) -> bool:
    """
    Add a user to the authorized users list.

    Args:
        chat_id: The user's chat ID to add

    Returns:
        True if successful, False otherwise
    """
    try:
        current_users = get_authorized_users()
        if str(chat_id) not in current_users:
            current_users.append(str(chat_id))
            # Save in line-separated format
            users_text = "\n".join(current_users)

            # Update the secret
            secret_name = f"projects/{config.database.project_id}/secrets/{config.secrets.authorized_users_secret_id}"
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
        logger.error(f"Error adding user {chat_id} to whitelist: {e}", exc_info=True)
        return False


def remove_user_from_whitelist(chat_id: str) -> bool:
    """
    Remove a user from the authorized users list.

    Args:
        chat_id: The user's chat ID to remove

    Returns:
        True if successful, False otherwise
    """
    try:
        current_users = get_authorized_users()
        if str(chat_id) in current_users:
            current_users.remove(str(chat_id))
            # Save in line-separated format
            users_text = "\n".join(current_users)

            # Update the secret
            secret_name = f"projects/{config.database.project_id}/secrets/{config.secrets.authorized_users_secret_id}"
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
        logger.error(
            f"Error removing user {chat_id} from whitelist: {e}", exc_info=True
        )
        return False


def get_system_statistics() -> Dict[str, Any]:
    """
    Get overall system statistics.

    Returns:
        Dictionary containing system statistics
    """
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
            (total_accuracy / active_users * 100) if active_users > 0 else 0.0
        )

        logger.info(f"System statistics calculated: {stats}")
        return stats
    except Exception as e:
        logger.error(f"Error calculating system statistics: {e}", exc_info=True)
        return stats


# --- Rate Limiting ---
def get_user_rate_limit_key(user_id: str) -> str:
    """Get the Firestore document key for user rate limiting."""
    return f"rate_limit_{user_id}"


def check_rate_limit(
    user_id: str, max_requests: int = 10, window_minutes: int = 5
) -> bool:
    """
    Check if user has exceeded rate limit.

    Args:
        user_id: The user's ID
        max_requests: Maximum requests allowed in the time window
        window_minutes: Time window in minutes

    Returns:
        True if user is within rate limit, False otherwise
    """
    try:
        doc_ref = db.collection("rate_limits").document(
            get_user_rate_limit_key(user_id)
        )
        doc = doc_ref.get()

        now = datetime.datetime.now(datetime.timezone.utc)
        window_start = now - datetime.timedelta(minutes=window_minutes)

        if not doc.exists:
            # First request for this user
            doc_ref.set(
                {
                    "requests": [{"timestamp": now.isoformat()}],
                    "last_updated": now.isoformat(),
                }
            )
            logger.debug(f"Rate limit: First request for user {user_id}")
            return True

        # Get existing requests
        data = doc.to_dict()
        requests_list = data.get("requests", [])

        # Filter requests within the time window
        recent_requests = [
            req
            for req in requests_list
            if datetime.datetime.fromisoformat(req["timestamp"]) > window_start
        ]

        if len(recent_requests) >= max_requests:
            logger.warning(
                f"Rate limit exceeded for user {user_id}: {len(recent_requests)} requests in {window_minutes} minutes"
            )
            return False

        # Add current request
        recent_requests.append({"timestamp": now.isoformat()})

        # Update Firestore
        doc_ref.update({"requests": recent_requests, "last_updated": now.isoformat()})

        logger.debug(
            f"Rate limit: User {user_id} has {len(recent_requests)} requests in current window"
        )
        return True

    except Exception as e:
        logger.error(
            f"Error checking rate limit for user {user_id}: {e}", exc_info=True
        )
        # In case of error, allow the request to proceed
        return True


# --- Telegram API Helpers ---
def send_telegram_message(
    bot_token: str, chat_id: str, text: str, reply_markup: Optional[Dict] = None
) -> bool:
    """
    Send a message via Telegram Bot API.

    Args:
        bot_token: The bot token
        chat_id: The chat ID to send message to
        text: The message text
        reply_markup: Optional reply markup for keyboard

    Returns:
        True if successful, False otherwise
    """
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}

        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)

        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()

        result = response.json()
        if result.get("ok"):
            logger.debug(f"Telegram message sent successfully to {chat_id}")
            return True
        else:
            logger.error(
                f"Telegram API error: {result.get('description', 'Unknown error')}"
            )
            return False

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error sending Telegram message: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}", exc_info=True)
        return False


# --- Firestore Helpers ---
def get_firestore_state(user_doc_id: str) -> Dict[str, Any]:
    """
    Get user's current state from Firestore.

    Args:
        user_doc_id: The user's document ID

    Returns:
        Dictionary containing user state
    """
    try:
        doc_ref = db.collection(config.database.firestore_collection).document(
            user_doc_id
        )
        doc = doc_ref.get()

        if doc.exists:
            state_data = doc.to_dict()
            logger.debug(f"Retrieved state for user {user_doc_id}: {state_data}")
            return state_data
        else:
            logger.debug(f"No existing state found for user {user_doc_id}")
            return {}

    except Exception as e:
        logger.error(
            f"Error getting Firestore state for user {user_doc_id}: {e}", exc_info=True
        )
        return {}


def update_firestore_state(state_data: Dict[str, Any], user_doc_id: str) -> bool:
    """
    Update user's state in Firestore.

    Args:
        state_data: The state data to update
        user_doc_id: The user's document ID

    Returns:
        True if successful, False otherwise
    """
    try:
        doc_ref = db.collection(config.database.firestore_collection).document(
            user_doc_id
        )
        doc_ref.set(state_data, merge=True)
        logger.debug(f"Updated state for user {user_doc_id}: {state_data}")
        return True

    except Exception as e:
        logger.error(
            f"Error updating Firestore state for user {user_doc_id}: {e}", exc_info=True
        )
        return False


# --- Helper: Generate Task via Gemini ---
def generate_task(gemini_key, task_type, user_doc_id, topic=None):
    # Get user proficiency data for adaptive learning
    proficiency_data = get_user_proficiency(user_doc_id)

    # Get user difficulty level from Firestore state
    user_state = get_firestore_state(user_doc_id)
    difficulty_level = user_state.get("difficulty_level", "advanced")

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
            f"Provide 3 related English vocabulary words suitable for a {difficulty_level} learner. "
            "For each word, on a NEW line, identify it like 'ITEM: [word]'. "
            "After listing all ITEMs, provide their definitions. "
            "The definitions should be presented in a jumbled or randomized order. "
            "Make it clear they need to match them (e.g., 'Match the words with their definitions below.')."
        )
    elif task_type == "Idiom":
        prompt = prompt_base + (
            "Choose one common English idiom. "
            "On a NEW line, identify it clearly, like 'ITEM: [idiom]'. "
            "Then, on subsequent lines, explain its meaning and provide one clear example sentence. "
            "Finally, ask the user to write their own sentence using it."
        )
    elif task_type == "Phrasal verb":
        prompt = prompt_base + (
            "Choose one common English phrasal verb. "
            "On a NEW line, identify it clearly, like 'ITEM: [phrasal verb]'. "
            "Then, on subsequent lines, explain its meaning and provide one clear example sentence. "
            "Finally, ask the user to write their own sentence using it."
        )
    elif task_type == "Vocabulary (5 advanced words)":
        prompt = prompt_base + (
            f"Provide 5 English words suitable for a {difficulty_level} learner. "
            "For each word, on a NEW line, identify it like 'ITEM: [word]'. "
            "After listing all ITEMs, provide their definitions. "
            "Make it clear the user should try to use each word in a sentence."
        )
    elif task_type == "Writing (thoughtful question)":
        prompt = prompt_base + (
            "Ask the user a thoughtful, open-ended question that encourages them to write an extensive answer (at least 5 sentences). "
            "The question should be relevant to daily life, culture, or personal growth. "
            "Make it clear that the user should write as much as possible."
        )
    elif task_type == "Listening (YouTube scene)":
        prompt = prompt_base + (
            f"Share a short scene from a movie or TV series on YouTube (provide the link) suitable for a {difficulty_level} English learner. "
            "Ask the user to watch the scene and then answer a comprehension question about it. "
            "The question should check their understanding of the main idea or details, and be appropriate for the chosen English learner difficulty."
        )
    elif task_type == "Describing (image or video)":
        prompt = prompt_base + (
            f"Share an image or a YouTube video link suitable for a {difficulty_level} English learner. "
            "Ask the user to provide a comprehensive description of what they see. "
            "Encourage the user to use as much detail as possible in their description, and tailor the expected detail to the chosen English learner difficulty."
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
        model = genai.GenerativeModel(config.ai.gemini_model_name)
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
        model = genai.GenerativeModel(config.ai.gemini_model_name)
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
    model = genai.GenerativeModel(config.ai.gemini_model_name)

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
        keyboard_buttons = [[task_type] for task_type in config.tasks.task_types]
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
        doc_ref = db.collection(config.database.proficiency_collection).document(
            user_doc_id
        )
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
        return random.choice(config.tasks.task_types)

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

    return random.choice(config.tasks.task_types)


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
        doc_ref = db.collection(config.database.proficiency_collection).document(
            user_doc_id
        )
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
            model = genai.GenerativeModel(config.ai.gemini_model_name)

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
