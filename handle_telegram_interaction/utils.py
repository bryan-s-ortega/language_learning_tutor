import json
import random
import requests
import logging
import datetime
from typing import Optional, Dict, Any, List
from config import config
import re
import google.generativeai as genai

logging.basicConfig(
    level=getattr(logging, config.logging.level), format=config.logging.format
)
logger = logging.getLogger(__name__)


# --- Lazy Google Cloud Client Initialization ---
def get_secret_client():
    if not hasattr(get_secret_client, "_client"):
        from google.cloud import secretmanager

        get_secret_client._client = secretmanager.SecretManagerServiceClient()
    return get_secret_client._client


def get_firestore_client():
    if not hasattr(get_firestore_client, "_client"):
        from google.cloud import firestore

        get_firestore_client._client = firestore.Client(
            project=config.database.project_id
        )
        get_firestore_client.SERVER_TIMESTAMP = firestore.SERVER_TIMESTAMP
        get_firestore_client.transactional = firestore.transactional
    return get_firestore_client._client


def get_firestore_server_timestamp():
    return get_firestore_client().SERVER_TIMESTAMP


def get_firestore_transactional():
    return get_firestore_client().transactional


def get_speech_client():
    if not hasattr(get_speech_client, "_client"):
        from google.cloud import speech

        get_speech_client._client = speech.SpeechClient()
    return get_speech_client._client


# --- Exception Classes ---
class LanguageLearningError(Exception):
    pass


class SecretAccessError(LanguageLearningError):
    pass


class FirestoreError(LanguageLearningError):
    pass


class TelegramAPIError(LanguageLearningError):
    pass


class GeminiAPIError(LanguageLearningError):
    pass


# --- Secret Caching ---
_secret_cache = {}


def access_secret_version(secret_id: str, version_id: str = "latest") -> str:
    cache_key = f"{secret_id}:{version_id}"
    if cache_key in _secret_cache:
        return _secret_cache[cache_key]
    if not config.database.project_id:
        error_msg = (
            "GCP_PROJECT environment variable not set or PROJECT_ID constant is empty."
        )
        logger.critical(error_msg)
        raise SecretAccessError(error_msg)
    name = f"projects/{config.database.project_id}/secrets/{secret_id}/versions/{version_id}"
    try:
        response = get_secret_client().access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8")
        _secret_cache[cache_key] = secret_value
        logger.debug(f"Successfully accessed secret: {secret_id}")
        return secret_value
    except Exception as e:
        error_msg = f"Error accessing secret {secret_id}: {e}"
        logger.error(error_msg, exc_info=True)
        raise SecretAccessError(error_msg) from e


# --- User Management Helpers ---
def _get_users_from_secret(secret_id: str) -> List[str]:
    try:
        users_data = access_secret_version(secret_id)
        if users_data.strip().startswith("["):
            return json.loads(users_data)
        return [line.strip() for line in users_data.strip().split("\n") if line.strip()]
    except Exception as e:
        logger.error(f"Error getting users from secret {secret_id}: {e}", exc_info=True)
        return []


def get_authorized_users() -> List[str]:
    return _get_users_from_secret(config.secrets.authorized_users_secret_id)


def get_admin_users() -> List[str]:
    return _get_users_from_secret(config.secrets.admin_users_secret_id)


def update_user_list(secret_id: str, chat_id: str, add: bool) -> bool:
    users = _get_users_from_secret(secret_id)
    chat_id = str(chat_id)

    # Validate chat_id format (should be numeric)
    if not chat_id.isdigit():
        logger.error(f"Invalid chat_id format: {chat_id}")
        return False

    operation_performed = False

    if add and chat_id not in users:
        users.append(chat_id)
        operation_performed = True
        logger.info(f"Added user {chat_id} to secret {secret_id}")
    elif not add and chat_id in users:
        users.remove(chat_id)
        operation_performed = True
        logger.info(f"Removed user {chat_id} from secret {secret_id}")
    elif not add and chat_id not in users:
        logger.warning(f"Attempted to remove user {chat_id} who was not in the list")
        return False  # Return False if trying to remove non-existent user

    try:
        # Always save in line-separated format for consistency
        users_text = "\n".join(users)
        secret_name = f"projects/{config.database.project_id}/secrets/{secret_id}"
        get_secret_client().add_secret_version(
            request={
                "parent": secret_name,
                "payload": {"data": users_text.encode("UTF-8")},
            }
        )
        logger.info(f"Successfully updated secret {secret_id} with {len(users)} users")
        return operation_performed
    except Exception as e:
        logger.error(f"Error updating user list secret {secret_id}: {e}", exc_info=True)
        return False


def add_user_to_whitelist(chat_id: str) -> bool:
    operation_performed = update_user_list(
        config.secrets.authorized_users_secret_id, chat_id, add=True
    )
    if operation_performed:
        clear_secret_cache(config.secrets.authorized_users_secret_id)
    return operation_performed


def remove_user_from_whitelist(chat_id: str) -> bool:
    operation_performed = update_user_list(
        config.secrets.authorized_users_secret_id, chat_id, add=False
    )
    if operation_performed:
        clear_secret_cache(config.secrets.authorized_users_secret_id)
    return operation_performed


def is_user_authorized(chat_id: str) -> bool:
    try:
        authorized_users = get_authorized_users()
        is_authorized = str(chat_id) in authorized_users
        logger.debug(f"User {chat_id} authorization check: {is_authorized}")
        return is_authorized
    except Exception as e:
        logger.error(
            f"Error checking user authorization for {chat_id}: {e}", exc_info=True
        )
        return False


def is_admin_user(chat_id: str) -> bool:
    try:
        admin_users = get_admin_users()
        is_admin = str(chat_id) in admin_users
        logger.debug(f"User {chat_id} admin check: {is_admin}")
        return is_admin
    except Exception as e:
        logger.error(f"Error checking admin status for {chat_id}: {e}", exc_info=True)
        return False


# --- Firestore Helpers ---
def get_firestore_state(user_doc_id: str) -> Dict[str, Any]:
    try:
        db = get_firestore_client()
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
    try:
        db = get_firestore_client()
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
        db = get_firestore_client()
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


# --- Helper: Generate Task via Gemini ---
def generate_task(gemini_key, task_type, user_doc_id, topic=None):
    user_state = get_firestore_state(user_doc_id)
    difficulty_level = user_state.get("difficulty_level", "advanced")
    response_language = user_state.get("response_language", "English")
    # Add language instruction for the model
    language_instruction = (
        f"\n\nIMPORTANT: The main learning objective (e.g., the word, idiom, phrasal verb, or topic) must always be in English. However, all other instructions, explanations, and feedback should be in {response_language}."
        if response_language.lower() != "english"
        else ""
    )
    task_details_dict = {
        "type": task_type,
        "specific_item_tested": None,
        "description": None,
    }
    prompt = ""
    instruction_prefix = "Present the following task for the user to answer. Do NOT answer or solve the task yourself. Do NOT justify or explain your instructions. "
    if task_type == "Error correction":
        recent_objectives = user_state.get("recent_error_correction", [])[-15:]
        avoid_text = ""
        if recent_objectives:
            avoid_text = (
                "\nIMPORTANT: Do NOT use any of these grammar concepts, as the user has already practiced them: "
                + "; ".join(recent_objectives)
                + ". Choose a new, unique concept."
            )
        prompt = (
            instruction_prefix
            + "Focus on a common English grammatical error (e.g., subject-verb agreement, tense misuse, articles, prepositions). "
            "On a NEW line, identify the specific grammar concept being tested, like 'ITEM: [grammar concept name]'. "
            "Then, on a NEW line, provide a single sentence containing this error for the user to correct. "
            "Example for ITEM: Past Simple Irregular Verb\nSentence: He goed to the park."
            + avoid_text
            + language_instruction
        )
    elif task_type == "Vocabulary matching":
        recent_objectives = user_state.get("recent_vocabulary_matching", [])
        avoid_text = ""
        if recent_objectives:
            avoid_text = (
                "\nIMPORTANT: Do NOT use any of these words, as the user has already practiced them: "
                + "; ".join(recent_objectives)
                + ". Choose new, unique words."
            )
        prompt = (
            instruction_prefix
            + f"Provide 3 related English vocabulary words suitable for a {difficulty_level} learner. "
            "For each word, on a NEW line, identify it like 'ITEM: [word]'. "
            "After listing all ITEMs, provide their definitions labeled as A, B, C in jumbled order. "
            "Make it clear they need to match them by writing the word number and letter (e.g., '1-A, 2-B, 3-C'). "
            "Example format:\n"
            "ITEM: word1\n"
            "ITEM: word2\n"
            "ITEM: word3\n\n"
            "A. definition for word2\n"
            "B. definition for word1\n"
            "C. definition for word3" + avoid_text + language_instruction
        )
    elif task_type == "Idiom":
        recent_objectives = user_state.get("recent_idiom", [])
        avoid_text = ""
        if recent_objectives:
            avoid_text = (
                "\nIMPORTANT: Do NOT use any of these idioms, as the user has already practiced them: "
                + "; ".join(recent_objectives)
                + ". Choose a new, unique idiom."
            )
        prompt = (
            instruction_prefix + "Choose one common English idiom. "
            "On a NEW line, identify it clearly, like 'ITEM: [idiom]'. "
            "Then, on subsequent lines, explain its meaning and provide one clear example sentence. "
            "Finally, ask the user to write their own sentence using it."
            + avoid_text
            + language_instruction
        )
    elif task_type == "Phrasal verb":
        recent_objectives = user_state.get("recent_phrasal_verb", [])
        avoid_text = ""
        if recent_objectives:
            avoid_text = (
                "\nIMPORTANT: Do NOT use any of these phrasal verbs, as the user has already practiced them: "
                + "; ".join(recent_objectives)
                + ". Choose a new, unique phrasal verb."
            )
        prompt = (
            instruction_prefix + "Choose one common English phrasal verb. "
            "On a NEW line, identify it clearly, like 'ITEM: [phrasal verb]'. "
            "Then, on subsequent lines, explain its meaning and provide one clear example sentence. "
            "Finally, ask the user to write their own sentence using it."
            + avoid_text
            + language_instruction
        )
    elif task_type == "Vocabulary":
        recent_objectives = user_state.get("recent_vocabulary", [])
        avoid_text = ""
        if recent_objectives:
            avoid_text = (
                "\nIMPORTANT: Do NOT use any of these words, as the user has already practiced them: "
                + "; ".join(recent_objectives)
                + ". Choose new, unique words."
            )
        prompt = (
            instruction_prefix
            + f"Provide 5 English words suitable for a {difficulty_level} learner. "
            "For each word, on a NEW line, identify it like 'ITEM: [word]'. "
            "After listing all ITEMs, provide their definitions. "
            "Make it clear the user should try to use each word in a sentence."
            + avoid_text
            + language_instruction
        )
    elif task_type == "Writing":
        recent_objectives = user_state.get("recent_writing", [])
        avoid_text = ""
        if recent_objectives:
            avoid_text = (
                "\nIMPORTANT: Do NOT use any of these writing prompts, as the user has already practiced them: "
                + "; ".join(recent_objectives)
                + ". Choose a new, unique prompt."
            )
        prompt = (
            instruction_prefix
            + "Ask the user a thoughtful, open-ended question that encourages them to write an extensive answer (at least 5 sentences). "
            "The question should be relevant to daily life, culture, or personal growth. "
            "Make it clear that the user should write as much as possible."
            + avoid_text
            + language_instruction
        )
    elif task_type == "Word starting with letter":
        recent_objectives = user_state.get("recent_word_starting_with_letter", [])[-15:]
        avoid_text = ""
        if recent_objectives:
            avoid_text = (
                "\nIMPORTANT: Do NOT use any of these letters, as the user has already practiced them: "
                + "; ".join(recent_objectives)
                + ". Choose a new, unique letter."
            )
        chosen_letter = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        prompt = (
            instruction_prefix
            + f"This is a fluency task. List as many English words as you can starting with the letter '{chosen_letter}' in one minute."
            + avoid_text
            + language_instruction
        )
        task_details_dict["description"] = (
            f"This is a fluency task. List as many English words as you can starting with the letter '{chosen_letter}' in one minute."
        )
        task_details_dict["specific_item_tested"] = (
            f"words_starting_with_{chosen_letter}"
        )
        logger.info(f"Generated task for Word starting with letter: {chosen_letter}")
        return task_details_dict
    elif task_type == "Free Style Voice Recording":
        prompt = (
            instruction_prefix
            + "Ask the user to record a voice message of any length. The instruction should be to talk about any topic they wish. Output only the instruction for the user."
        ) + language_instruction
        logger.info(
            f"Generating free style voice task instruction with prompt: {prompt}"
        )
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(config.ai.gemini_model_name)
        instruction_response = model.generate_content(prompt)
        if instruction_response.text:
            task_details_dict["description"] = instruction_response.text.strip()
            logger.info(
                f"Generated free style voice task instruction: {task_details_dict['description']}"
            )
            return task_details_dict
        else:
            logger.warning(
                "Gemini failed to generate free style voice task instruction, using fallback."
            )
            task_details_dict["description"] = (
                "Please record a voice message about any topic you wish. I will analyze your spoken English."
            )
            return task_details_dict
    elif task_type == "Topic Voice Recording":
        # Get recent topics from user state
        recent_topics = user_state.get("recent_topic_voice_recording", [])
        avoid_topics_text = ""
        if recent_topics:
            avoid_topics_text = (
                "\nIMPORTANT: Do NOT use any of these topics, as the user has already practiced them: "
                + "; ".join(recent_topics)
                + ". Choose a new, unique topic."
            )
        prompt = (
            instruction_prefix
            + "Ask the user to record a voice message of any length. First, generate a specific topic for the user to talk about (the topic can be anything). Output only the instruction for the user, including the topic."
            + avoid_topics_text
            + language_instruction
        )
        logger.info(f"Generating topic voice task instruction with prompt: {prompt}")
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(config.ai.gemini_model_name)
        instruction_response = model.generate_content(prompt)
        if instruction_response.text:
            desc = instruction_response.text.strip()
            task_details_dict["description"] = desc
            # Try to extract the topic from the instruction
            topic_match = re.search(r"topic[:\-\s]+(.+)", desc, re.IGNORECASE)
            if topic_match:
                topic = topic_match.group(1).strip()
            else:
                # Fallback: use the first sentence or line
                topic = (
                    desc.split(". ")[0]
                    .replace("Record a voice message about ", "")
                    .strip()
                )
            task_details_dict["specific_item_tested"] = topic
            logger.info(
                f"Generated topic voice task instruction: {desc} | Extracted topic: {topic}"
            )
            return task_details_dict
        else:
            logger.warning(
                "Gemini failed to generate topic voice task instruction, using fallback."
            )
            task_details_dict["description"] = (
                "Please record a voice message about the following topic: [AI will provide a topic]. I will analyze your spoken English."
            )
            task_details_dict["specific_item_tested"] = None
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
    max_retries = 2
    for attempt in range(max_retries + 1):
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
                        user_description = "**Vocabulary Matching Task**\n\nMatch the following words with their definitions:\n\n**Words:**\n"
                        for i, word in enumerate(items_found):
                            user_description += f"{i + 1}. {word}\n"
                        user_description += "\n**Definitions:**\n"
                        user_description += "\n".join(
                            other_lines_for_description
                        ).strip()
                        user_description += "\n\n**How to answer:** Write your matches in the format '1-A, 2-B, 3-C' where the number is the word and the letter is the definition."
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
                if (
                    not task_details_dict.get("description")
                    and raw_gemini_response_text
                ):
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
                if attempt < max_retries:
                    continue
                return None
        except Exception as e:
            logger.error(f"Error generating task with Gemini: {e}", exc_info=True)
            return None
    return task_details_dict


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

    if task_type in ["Free Style Voice Recording", "Topic Voice Recording"]:
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
            logger.error(f"Expected audio for {task_type}, but none provided.")
            return {
                "feedback_text": "It seems you were supposed to send a voice message for this task, but I didn't receive any audio.",
                "is_correct": False,
            }
    else:
        if user_answer_text:
            # Task-specific evaluation prompts
            if task_type == "Vocabulary matching":
                prompt_parts.append(
                    f"The user responded with text:\n--- USER RESPONSE START ---\n{user_answer_text}\n--- USER RESPONSE END ---"
                )
                prompt_parts.append(
                    "This is a VOCABULARY MATCHING task. The user should match words with their definitions. "
                    "Evaluate their response by checking if they correctly matched each word with its definition. "
                    "Look for patterns like '1-A', '2-B', 'word-definition', or similar matching formats. "
                    "If they provided the correct matches, acknowledge their success. "
                    "If they made errors, point out which matches were incorrect and provide the correct answers. "
                    "Be encouraging and educational in your feedback."
                )
            else:
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

    if not content_for_gemini and task_type not in [
        "Free Style Voice Recording",
        "Topic Voice Recording",
    ]:
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
        task_types = config.tasks.task_types
        keyboard_buttons = [[task_type] for task_type in task_types]
        reply_markup = {
            "keyboard": keyboard_buttons,
            "one_time_keyboard": True,
            "resize_keyboard": True,
        }

        # Build a numbered menu
        numbered_menu = "\n".join(
            [f"{i + 1}. {task_type}" for i, task_type in enumerate(task_types)]
        )
        message_text = (
            "👋 Okay, let's start a new task! What type of English practice would you like?\n"
            "You can reply with the *number* of the task or tap a button below.\n\n"
            f"{numbered_menu}"
        )

        # Add adaptive learning suggestions if user_doc_id is provided
        # (Optional: can be removed if old logic is not wanted)

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
        db = get_firestore_client()
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

    item_stats["last_attempt_timestamp"] = get_firestore_server_timestamp()
    item_stats["last_task_id"] = task_id

    item_stats["history"].append(
        {"timestamp": get_firestore_server_timestamp(), "correct": is_correct}
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
        db = get_firestore_client()
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


def is_valid_youtube_url(url):
    # Use YouTube oEmbed endpoint to check if the video exists
    oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
    try:
        resp = requests.get(oembed_url, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def is_valid_image_url(url):
    try:
        resp = requests.head(url, timeout=5, allow_redirects=True)
        content_type = resp.headers.get("Content-Type", "")
        return resp.status_code == 200 and ("image" in content_type)
    except Exception:
        return False


def extract_first_url(text, youtube_only=False):
    # Simple regex for URLs
    url_pattern = r"https?://[\w\-\.\?&=/%#]+"
    urls = re.findall(url_pattern, text)
    if youtube_only:
        for url in urls:
            if "youtube.com" in url or "youtu.be" in url:
                return url
        return None
    return urls[0] if urls else None


def youtube_search(query, api_key, max_results=1):
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "key": api_key,
        "maxResults": max_results,
        "safeSearch": "strict",
    }
    resp = requests.get(url, params=params, timeout=5)
    items = resp.json().get("items", [])
    if items:
        video_id = items[0]["id"]["videoId"]
        return f"https://www.youtube.com/watch?v={video_id}"
    return None


def get_system_statistics() -> dict:
    """Compute system statistics for admin /stats command."""
    stats = {
        "total_users": 0,
        "active_users_today": 0,
        "total_tasks_completed": 0,
        "average_accuracy": 0.0,
    }
    try:
        authorized_users = get_authorized_users()
        stats["total_users"] = len(authorized_users)
        total_accuracy = 0.0
        total_tasks = 0
        active_users = 0
        for user_id in authorized_users:
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


# --- Secret Cache Management ---
_secret_cache = {}


def clear_secret_cache(secret_id: Optional[str] = None):
    """Clear the secret cache for a specific secret or all secrets."""
    global _secret_cache
    if secret_id:
        # Clear specific secret
        keys_to_remove = [
            key for key in _secret_cache.keys() if key.startswith(f"{secret_id}:")
        ]
        for key in keys_to_remove:
            del _secret_cache[key]
        logger.info(f"Cleared cache for secret: {secret_id}")
    else:
        # Clear all secrets
        _secret_cache.clear()
        logger.info("Cleared all secret cache")
