import functions_framework
import requests
from datetime import datetime
import sys
import os
from typing import Any, Dict

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from utils import (
    access_secret_version,
    send_telegram_message,
    update_firestore_state,
    get_firestore_state,
    send_choice_request_message,
    transcribe_voice,
    generate_task,
    evaluate_answer,
    update_user_proficiency,
    get_user_proficiency,
    generate_progress_report,
    is_user_authorized,
    is_admin_user,
    add_user_to_whitelist,
    remove_user_from_whitelist,
    get_system_statistics,
    get_authorized_users,
    check_rate_limit,
    logger,
)

_bot_token = None
_gemini_key = None


def get_bot_token() -> str:
    global _bot_token
    if _bot_token is None:
        _bot_token = access_secret_version(config.secrets.telegram_token_secret_id)
    return _bot_token


def get_gemini_key() -> str:
    global _gemini_key
    if _gemini_key is None:
        _gemini_key = access_secret_version(config.secrets.gemini_api_key_secret_id)
    return _gemini_key


def send_user_error(bot_token: str, chat_id: str, message: str) -> None:
    try:
        send_telegram_message(bot_token, chat_id, message)
    except Exception as e:
        logger.error(
            f"Failed to send error message to user {chat_id}: {e}", exc_info=True
        )


# --- Command Handlers ---
def handle_start(bot_token: str, chat_id: str, user_doc_id: str, **kwargs) -> str:
    if is_user_authorized(chat_id):
        welcome_message = """
🎓 **Welcome to the Language Learning Tutor!**

I'm your AI-powered English learning assistant. Here's how to get started:

**Available Commands:**
• `/newtask` - Start a new learning task
• `/progress` - View your learning progress
• `/help` - Show this help message

**Task Types Available:**
• Error correction
• Vocabulary matching
• Idiom practice
• Phrasal verb practice
• Word fluency exercises
• Voice recording analysis
• Vocabulary
• Writing

Ready to start learning? Send `/newtask` to begin!
"""
        send_telegram_message(bot_token, chat_id, welcome_message)
    else:
        access_message = f"""
🚫 **Access Required**

You're not currently authorized to use this Language Learning Tutor bot.

**To get access:**
Please contact the administrator and provide your chat ID: `{chat_id}`

Once you're added to the authorized users list, you'll be able to start learning English with personalized AI-powered tasks.

Thank you for your interest!
"""
        send_telegram_message(bot_token, chat_id, access_message)
    return "OK", 200


def handle_help(bot_token: str, chat_id: str, **kwargs) -> str:
    help_message = """
🎓 **Language Learning Tutor - Help**

**Available Commands:**
• `/start` - Welcome message and bot introduction
• `/newtask` - Start a new learning task
• `/progress` - View your learning progress
• `/help` - Show this help message

**Task Types:**
• **Error correction** - Fix grammatical errors in sentences
• **Vocabulary matching** - Match words with their definitions
• **Idiom practice** - Learn and practice English idioms
• **Phrasal verb practice** - Learn and practice English phrasal verbs
• **Word fluency** - Generate words starting with specific letters
• **Voice recording** - Practice pronunciation with voice analysis
• **Vocabulary** - Learn 5 advanced but common English words and use them in sentences
• **Writing** - Answer a thoughtful, open-ended question with an extensive written response

**How it works:**
1. Send `/newtask` to start
2. Choose a task type from the keyboard
3. Complete the task (text or voice)
4. Receive personalized feedback
5. Track your progress with `/progress`

Happy learning! 🚀
"""
    send_telegram_message(bot_token, chat_id, help_message)
    return "OK", 200


def handle_progress(bot_token: str, chat_id: str, user_doc_id: str, **kwargs) -> str:
    proficiency_data = get_user_proficiency(user_doc_id)
    if proficiency_data:
        progress_message = generate_progress_report(proficiency_data)
        send_telegram_message(bot_token, chat_id, progress_message)
    else:
        send_telegram_message(
            bot_token,
            chat_id,
            "📊 **Learning Progress**: You haven't completed any tasks yet. Start practicing to see your progress!",
        )
    return "OK", 200


def handle_difficulty(
    bot_token: str,
    chat_id: str,
    user_doc_id: str,
    current_state: Dict[str, Any],
    **kwargs,
) -> str:
    current_level = current_state.get("difficulty_level", "advanced")
    difficulty_keyboard = {
        "keyboard": [["beginner"], ["intermediate"], ["advanced"]],
        "one_time_keyboard": True,
        "resize_keyboard": True,
    }
    send_telegram_message(
        bot_token,
        chat_id,
        f"**Current difficulty level:** {current_level.capitalize()}\n\nChoose your desired difficulty:",
        reply_markup=difficulty_keyboard,
    )
    update_firestore_state(
        {"interaction_state": "awaiting_difficulty_choice"},
        user_doc_id=user_doc_id,
    )
    return "OK", 200


# --- Main Handler ---
@functions_framework.http
def handle_telegram_interaction(request) -> Any:
    import uuid

    request_id = str(uuid.uuid4())[:8]
    logger.info(f"[{request_id}] Starting webhook processing")

    if request.method != "POST":
        logger.warning(f"[{request_id}] Received non-POST request: {request.method}")
        return "Only POST requests are accepted", 405

    bot_token = get_bot_token()
    gemini_key = get_gemini_key()
    chat_id = None

    try:
        req_body = request.get_json(silent=True)
        if not req_body:
            logger.error(f"[{request_id}] Error: Invalid or empty JSON body received.")
            return "Bad Request", 400

        message = req_body.get("message")
        if not message:
            return "OK", 200

        chat_id_from_message = message.get("chat", {}).get("id")
        if not chat_id_from_message:
            return "OK", 200

        chat_id = chat_id_from_message
        user_doc_id = str(chat_id)
        current_state = get_firestore_state(user_doc_id=user_doc_id)
        interaction_state = current_state.get("interaction_state", "idle")

        message_text = message.get("text", "").strip()
        voice = message.get("voice")
        transcribed_text = None

        # Blocked state check
        if interaction_state == "blocked_due_to_error" and message_text.lower() not in [
            "/start",
            "/newtask",
        ]:
            send_user_error(
                bot_token,
                chat_id,
                "⚠️ The bot is temporarily unavailable due to a system error or quota issue. Please use /start or /newtask to reset.",
            )
            return "OK", 200

        # Command dispatch dictionary
        command_handlers = {
            "/start": handle_start,
            "/help": handle_help,
            "/progress": handle_progress,
            "/difficulty": handle_difficulty,
        }

        # Handle commands
        if message_text.lower() in command_handlers:
            handler = command_handlers[message_text.lower()]
            if message_text.lower() == "/difficulty":
                return handler(
                    bot_token, chat_id, user_doc_id, current_state=current_state
                )
            elif message_text.lower() in ["/start", "/progress"]:
                return handler(bot_token, chat_id, user_doc_id)
            else:
                return handler(bot_token, chat_id)

        # Multi-user authentication
        if not is_user_authorized(chat_id):
            send_user_error(
                bot_token,
                chat_id,
                "🚫 **Access Denied**: You are not authorized to use this bot. Please contact the administrator to get access.",
            )
            return "Forbidden", 403

        if not is_admin_user(chat_id) and not check_rate_limit(user_doc_id):
            send_user_error(
                bot_token,
                chat_id,
                "⏰ **Rate Limit Exceeded**: Please wait a few minutes before making more requests.",
            )
            return "Too Many Requests", 429

        if voice:
            file_id = voice.get("file_id")
            if file_id:
                try:
                    transcribed_text = transcribe_voice(bot_token, file_id, gemini_key)
                except Exception as E:
                    logger.error(
                        f"ERROR: Exception during transcribe_voice: {E}", exc_info=True
                    )
                    transcribed_text = None
                if transcribed_text:
                    message_text = transcribed_text
                else:
                    send_user_error(
                        bot_token,
                        chat_id,
                        "Sorry, I couldn't understand the voice message. Please try typing.",
                    )
                    return "OK", 200
        if message_text is None:
            message_text = ""

        # New task command
        if message_text.lower() == "/newtask":
            reset_state_data = {
                "interaction_state": "awaiting_choice",
                "chosen_task_type": None,
                "current_task_details": None,
            }
            update_success = update_firestore_state(
                reset_state_data, user_doc_id=user_doc_id
            )
            if update_success:
                send_success = send_choice_request_message(
                    bot_token, chat_id, user_doc_id
                )
                if not send_success:
                    send_user_error(
                        bot_token,
                        chat_id,
                        "State reset, but I had trouble sending the new task options. Please try /newtask again later or wait for the daily prompt.",
                    )
            else:
                send_user_error(
                    bot_token,
                    chat_id,
                    "Sorry, there was an issue resetting for a new task. Please try /newtask again.",
                )
            return "OK", 200

        # Difficulty selection
        if interaction_state == "awaiting_difficulty_choice":
            if message_text.lower() in ["beginner", "intermediate", "advanced"]:
                update_firestore_state(
                    {
                        "difficulty_level": message_text.lower(),
                        "interaction_state": "idle",
                    },
                    user_doc_id=user_doc_id,
                )
                send_telegram_message(
                    bot_token,
                    chat_id,
                    f"✅ Difficulty level set to: {message_text.capitalize()}!",
                    reply_markup={"remove_keyboard": True},
                )
            else:
                send_user_error(
                    bot_token,
                    chat_id,
                    "Please choose a valid difficulty: beginner, intermediate, or advanced.",
                )
            return "OK", 200

        # Admin commands
        if message_text.lower() == "/admin" and is_admin_user(chat_id):
            admin_message = """
🔧 **Admin Commands**:
• `/adduser <chat_id>` - Add new user
• `/removeuser <chat_id>` - Remove user  
• `/listusers` - List all users
• `/stats` - System statistics
• `/help` - Show this help
"""
            send_telegram_message(bot_token, chat_id, admin_message)
            return "OK", 200

        if message_text.lower().startswith("/adduser ") and is_admin_user(chat_id):
            try:
                new_chat_id = message_text.split()[1]
                if add_user_to_whitelist(new_chat_id):
                    send_telegram_message(
                        bot_token, chat_id, f"✅ User {new_chat_id} added successfully!"
                    )
                else:
                    send_user_error(bot_token, chat_id, "❌ Failed to add user")
            except IndexError:
                send_user_error(bot_token, chat_id, "❌ Usage: /adduser <chat_id>")
            return "OK", 200

        if message_text.lower().startswith("/removeuser ") and is_admin_user(chat_id):
            try:
                user_to_remove = message_text.split()[1]
                if remove_user_from_whitelist(user_to_remove):
                    send_telegram_message(
                        bot_token,
                        chat_id,
                        f"✅ User {user_to_remove} removed successfully!",
                    )
                else:
                    send_user_error(bot_token, chat_id, "❌ Failed to remove user")
            except IndexError:
                send_user_error(bot_token, chat_id, "❌ Usage: /removeuser <chat_id>")
            return "OK", 200

        if message_text.lower() == "/listusers" and is_admin_user(chat_id):
            users = get_authorized_users()
            if users:
                user_list = "\n".join([f"• {user}" for user in users])
                send_telegram_message(
                    bot_token,
                    chat_id,
                    f"👥 **Authorized Users** ({len(users)}):\n{user_list}",
                )
            else:
                send_telegram_message(
                    bot_token, chat_id, "👥 **No authorized users found**"
                )
            return "OK", 200

        if message_text.lower() == "/stats" and is_admin_user(chat_id):
            stats = get_system_statistics()
            stats_message = f"""
📊 **System Statistics**:
👥 **Total Users**: {stats["total_users"]}
📈 **Active Users Today**: {stats["active_users_today"]}
🎯 **Total Tasks Completed**: {stats["total_tasks_completed"]}
📊 **Average Accuracy**: {stats["average_accuracy"]:.1f}%
"""
            send_telegram_message(bot_token, chat_id, stats_message)
            return "OK", 200

        # Main interaction state machine
        current_state = get_firestore_state(user_doc_id=user_doc_id)
        interaction_state = current_state.get("interaction_state", "idle")
        if interaction_state == "awaiting_choice":
            chosen_task_type = message_text
            if chosen_task_type in config.tasks.task_types:
                task_details = generate_task(gemini_key, chosen_task_type, user_doc_id)
                if task_details and task_details.get("description"):
                    new_state_data = {
                        "interaction_state": "awaiting_answer",
                        "chosen_task_type": chosen_task_type,
                        "current_task_details": task_details,
                        "task_id": f"{chosen_task_type}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                    }
                    update_firestore_state(new_state_data, user_doc_id=user_doc_id)
                    send_telegram_message(
                        bot_token,
                        chat_id,
                        task_details["description"],
                        reply_markup={"remove_keyboard": True},
                    )
                else:
                    send_user_error(
                        bot_token,
                        chat_id,
                        f"Sorry, I couldn't generate a '{chosen_task_type}' task. Try another or /newtask.",
                    )
                    update_firestore_state(
                        {"interaction_state": "awaiting_choice"},
                        user_doc_id=user_doc_id,
                    )
            else:
                send_user_error(
                    bot_token,
                    chat_id,
                    "Hmm, that doesn't look like one of the options. Please choose a task type from the list I sent.",
                )

        elif interaction_state == "awaiting_answer":
            task_details = current_state.get("current_task_details")
            if not task_details:
                send_user_error(
                    bot_token,
                    chat_id,
                    "Sorry, I lost track of the current task. Please wait for the next prompt or use /newtask.",
                )
                update_firestore_state(
                    {"interaction_state": "idle"}, user_doc_id=user_doc_id
                )
                return "OK", 200

            task_type = task_details.get("type")
            task_id = current_state.get("task_id", "unknown_task")
            evaluation_result = None
            feedback_text_to_send = (
                "Sorry, I couldn't process your answer for evaluation."
            )
            is_correct_for_proficiency = False

            if task_type == "Voice Recording Analysis":
                if voice:
                    file_id = voice.get("file_id")
                    if file_id:
                        audio_bytes_for_eval = None
                        try:
                            get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
                            res_file_path = requests.get(get_file_url, timeout=10)
                            res_file_path.raise_for_status()
                            file_path_tg = (
                                res_file_path.json().get("result", {}).get("file_path")
                            )
                            if file_path_tg:
                                file_download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path_tg}"
                                res_audio = requests.get(file_download_url, timeout=20)
                                res_audio.raise_for_status()
                                audio_bytes_for_eval = res_audio.content
                            else:
                                logger.error(
                                    "Could not get file_path from Telegram for voice analysis."
                                )
                        except Exception as dl_err:
                            logger.error(
                                f"Failed to download voice for analysis: {dl_err}",
                                exc_info=True,
                            )
                        if audio_bytes_for_eval:
                            evaluation_result = evaluate_answer(
                                gemini_key,
                                task_details,
                                user_audio_bytes=audio_bytes_for_eval,
                                user_doc_id=user_doc_id,
                            )
                        else:
                            feedback_text_to_send = "I had trouble downloading your voice message for analysis. Please try sending it again."
                            is_correct_for_proficiency = False
                    else:
                        feedback_text_to_send = "I detected a voice message for analysis, but couldn't get its file ID. Please try sending it again."
                        is_correct_for_proficiency = False
                else:
                    feedback_text_to_send = f"For the task '{task_details.get('description')}', please send me a voice message as your answer."
                    is_correct_for_proficiency = False
            else:
                user_answer_text_for_eval = message_text
                if not user_answer_text_for_eval:
                    feedback_text_to_send = "I didn't receive any text or understandable voice for your answer. Please try again."
                    is_correct_for_proficiency = False
                else:
                    evaluation_result = evaluate_answer(
                        gemini_key,
                        task_details,
                        user_answer_text=user_answer_text_for_eval,
                        user_doc_id=user_doc_id,
                    )
            if isinstance(evaluation_result, dict):
                feedback_text_to_send = evaluation_result.get(
                    "feedback_text", feedback_text_to_send
                )
                is_correct_for_proficiency = evaluation_result.get("is_correct", False)
            elif evaluation_result is not None:
                feedback_text_to_send = str(evaluation_result)

            send_telegram_message(bot_token, chat_id, feedback_text_to_send)

            specific_item_tested = task_details.get("specific_item_tested")
            item_type_for_proficiency = None
            items_to_update = []

            if task_type == "Idiom" and specific_item_tested:
                item_type_for_proficiency = "phrasal_verbs"
                items_to_update.append(specific_item_tested)
            elif task_type == "Phrasal verb" and specific_item_tested:
                item_type_for_proficiency = "phrasal_verbs"
                items_to_update.append(specific_item_tested)
            elif task_type == "Error correction" and specific_item_tested:
                item_type_for_proficiency = "grammar_topics"
                items_to_update.append(specific_item_tested)
            elif task_type == "Vocabulary matching" and isinstance(
                specific_item_tested, list
            ):
                item_type_for_proficiency = "vocabulary_words"
                items_to_update.extend(specific_item_tested)
            if (
                item_type_for_proficiency
                and items_to_update
                and is_correct_for_proficiency is not None
            ):
                for item_name in items_to_update:
                    update_user_proficiency(
                        user_doc_id,
                        item_type_for_proficiency,
                        item_name,
                        is_correct_for_proficiency,
                        task_id,
                    )

        else:
            send_user_error(
                bot_token,
                chat_id,
                "I'm waiting for the next daily prompt to select a task type. You can use `/newtask` to reset if needed.",
            )

        return "OK", 200

    except Exception as e:
        logger.error(f"FATAL Error processing webhook request: {e}", exc_info=True)
        if bot_token and chat_id and user_doc_id:
            try:
                update_firestore_state(
                    {"interaction_state": "blocked_due_to_error"},
                    user_doc_id=user_doc_id,
                )
                send_user_error(
                    bot_token,
                    chat_id,
                    f"Debug: A critical error occurred in the webhook: {str(e)[:100]}\nThe bot is now paused. Please use /start or /newtask to reset.",
                )
            except Exception:
                logger.error(
                    "Failed to update state or notify user after fatal error.",
                    exc_info=True,
                )
        return "Internal Server Error", 500
