import functions_framework
import requests
from datetime import datetime
import sys
import os

# Add the parent directory to the path to import config
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


@functions_framework.http
def handle_telegram_interaction(request):
    # Generate a unique request ID for tracking
    import uuid

    request_id = str(uuid.uuid4())[:8]
    logger.info(f"[{request_id}] Starting webhook processing")

    if request.method != "POST":
        logger.warning(f"[{request_id}] Received non-POST request: {request.method}")
        return "Only POST requests are accepted", 405

    bot_token = None
    gemini_key = None
    chat_id = None

    try:
        bot_token = access_secret_version(config.secrets.telegram_token_secret_id)
        gemini_key = access_secret_version(config.secrets.gemini_api_key_secret_id)
        logger.info("Webhook secrets retrieved.")

        logger.debug(f"[{request_id}] Attempting to parse JSON body...")
        req_body = request.get_json(silent=True)
        logger.debug(f"[{request_id}] JSON body parsed. Type: {type(req_body)}")
        if not req_body:
            logger.error(f"[{request_id}] Error: Invalid or empty JSON body received.")
            return "Bad Request", 400

        message = req_body.get("message")
        if not message:
            logger.info(
                f"[{request_id}] No 'message' key found in webhook body. Acknowledging."
            )
            return "OK", 200

        chat_id_from_message = message.get("chat", {}).get("id")
        if not chat_id_from_message:
            logger.warning(
                f"[{request_id}] No chat_id found in message. Acknowledging."
            )
            return "OK", 200

        chat_id = chat_id_from_message
        user_doc_id = str(chat_id)
        logger.info(f"[{request_id}] Processing message from chat_id: {chat_id}")

        # Fetch user state early to check for blocked state
        current_state = get_firestore_state(user_doc_id=user_doc_id)
        interaction_state = current_state.get("interaction_state", "idle")
        # Blocked state check
        if interaction_state == "blocked_due_to_error":
            if message.get("text", "").strip().lower() in ["/start", "/newtask"]:
                # Allow reset
                pass
            else:
                send_telegram_message(
                    bot_token,
                    chat_id,
                    "⚠️ The bot is temporarily unavailable due to a system error or quota issue. Please use /start or /newtask to reset.",
                )
                return "OK", 200

        message_text = message.get("text", "").strip()
        voice = message.get("voice")
        transcribed_text = None

        # Handle /start command specifically BEFORE auth check
        if message_text.lower() == "/start":
            logger.info(f"/start command received from user {user_doc_id}")
            if is_user_authorized(chat_id):
                # Authorized user - send welcome message
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
• Vocabulary (5 advanced words)
• Writing (thoughtful question)
• Listening (YouTube scene)
• Describing (image or video)

Ready to start learning? Send `/newtask` to begin!
"""
                send_telegram_message(bot_token, chat_id, welcome_message)
            else:
                # Unauthorized user - send one-time access request message
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

        # Multi-user authentication
        if not is_user_authorized(chat_id):
            logger.warning(
                f"[{request_id}] Unauthorized attempt from chat_id: {chat_id}"
            )
            send_telegram_message(
                bot_token,
                chat_id,
                "🚫 **Access Denied**: You are not authorized to use this bot. "
                "Please contact the administrator to get access.",
            )
            logger.info(
                f"[{request_id}] Sent access denied message to unauthorized user {chat_id}"
            )
            return "Forbidden", 403

        # Rate limiting (skip for admin commands)
        if not is_admin_user(chat_id) and not check_rate_limit(user_doc_id):
            logger.warning(f"Rate limit exceeded for user: {chat_id}")
            send_telegram_message(
                bot_token,
                chat_id,
                "⏰ **Rate Limit Exceeded**: Please wait a few minutes before making more requests.",
            )
            return "Too Many Requests", 429

        if voice:
            logger.debug("Entered voice processing block.")
            file_id = voice.get("file_id")
            if file_id:
                logger.debug(f"Got file_id {file_id}. Calling transcribe_voice...")
                try:
                    transcribed_text = transcribe_voice(bot_token, file_id, gemini_key)
                except Exception as E:
                    logger.error(
                        f"ERROR: Exception occurred *during* transcribe_voice call: {E}",
                        exc_info=True,
                    )
                    transcribed_text = None

                logger.debug(
                    f"Returned from transcribe_voice. Result type: {type(transcribed_text)}, Value: '{transcribed_text}'"
                )
                if transcribed_text:
                    logger.debug(
                        f"Transcription succeeded. Using text: '{transcribed_text}'"
                    )
                    message_text = transcribed_text
                else:
                    logger.warning(
                        "Transcription failed or returned empty. Informing user."
                    )
                    send_telegram_message(
                        bot_token,
                        chat_id,
                        "Sorry, I couldn't understand the voice message. Please try typing.",
                    )
                    return "OK", 200
            else:
                logger.warning("Voice message present but no file_id found.")
        else:
            logger.debug("No voice message detected in this payload.")

        if message_text is None:
            message_text = ""
        logger.debug(
            f"Effective message_text before command/state check: '{message_text}'"
        )

        if message_text.lower() == "/newtask":
            logger.info(f"/newtask command received from user {user_doc_id}")
            reset_state_data = {
                "interaction_state": "awaiting_choice",
                "chosen_task_type": None,
                "current_task_details": None,
            }
            update_success = update_firestore_state(
                reset_state_data, user_doc_id=user_doc_id
            )
            if update_success:
                logger.info(
                    "State reset successfully for /newtask. Now sending new choice request message."
                )
                send_success = send_choice_request_message(
                    bot_token, chat_id, user_doc_id
                )
                if not send_success:
                    logger.error(
                        "Failed to send choice request message after /newtask state reset."
                    )
                    send_telegram_message(
                        bot_token,
                        chat_id,
                        "State reset, but I had trouble sending the new task options. Please try /newtask again later or wait for the daily prompt.",
                    )
            else:
                logger.error("Failed to reset state for /newtask.")
                send_telegram_message(
                    bot_token,
                    chat_id,
                    "Sorry, there was an issue resetting for a new task. Please try /newtask again.",
                )
            return "OK", 200

        elif message_text.lower() == "/help":
            logger.info(f"/help command received from user {user_doc_id}")
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
• **Vocabulary (5 advanced words)** - Learn 5 advanced but common English words and use them in sentences
• **Writing (thoughtful question)** - Answer a thoughtful, open-ended question with an extensive written response
• **Listening (YouTube scene)** - Watch a short YouTube scene and answer a comprehension question
• **Describing (image or video)** - Describe an image or YouTube video in detail

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

        elif message_text.lower() == "/progress":
            logger.info(f"/progress command received from user {user_doc_id}")
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

        elif message_text.lower() == "/difficulty":
            logger.info(f"/difficulty command received from user {user_doc_id}")
            current_state = get_firestore_state(user_doc_id=user_doc_id)
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
            # Set a state so we know to update on next message
            update_firestore_state(
                {"interaction_state": "awaiting_difficulty_choice"},
                user_doc_id=user_doc_id,
            )
            return "OK", 200

        # Handle difficulty selection
        current_state = get_firestore_state(user_doc_id=user_doc_id)
        interaction_state = current_state.get("interaction_state", "idle")
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
                send_telegram_message(
                    bot_token,
                    chat_id,
                    "Please choose a valid difficulty: beginner, intermediate, or advanced.",
                )
            return "OK", 200

        # Admin commands
        elif message_text.lower() == "/admin" and is_admin_user(chat_id):
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

        elif message_text.lower().startswith("/adduser ") and is_admin_user(chat_id):
            try:
                new_chat_id = message_text.split()[1]
                if add_user_to_whitelist(new_chat_id):
                    send_telegram_message(
                        bot_token, chat_id, f"✅ User {new_chat_id} added successfully!"
                    )
                else:
                    send_telegram_message(bot_token, chat_id, "❌ Failed to add user")
            except IndexError:
                send_telegram_message(
                    bot_token, chat_id, "❌ Usage: /adduser <chat_id>"
                )
            return "OK", 200

        elif message_text.lower().startswith("/removeuser ") and is_admin_user(chat_id):
            try:
                user_to_remove = message_text.split()[1]
                if remove_user_from_whitelist(user_to_remove):
                    send_telegram_message(
                        bot_token,
                        chat_id,
                        f"✅ User {user_to_remove} removed successfully!",
                    )
                else:
                    send_telegram_message(
                        bot_token, chat_id, "❌ Failed to remove user"
                    )
            except IndexError:
                send_telegram_message(
                    bot_token, chat_id, "❌ Usage: /removeuser <chat_id>"
                )
            return "OK", 200

        elif message_text.lower() == "/listusers" and is_admin_user(chat_id):
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

        elif message_text.lower() == "/stats" and is_admin_user(chat_id):
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

        current_state = get_firestore_state(user_doc_id=user_doc_id)
        interaction_state = current_state.get("interaction_state", "idle")
        logger.info(f"Current interaction state for {user_doc_id}: {interaction_state}")

        if interaction_state == "awaiting_choice":
            chosen_task_type = message_text
            if chosen_task_type in config.tasks.task_types:
                logger.info(f"User chose task type: {chosen_task_type}")
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
                    logger.error(
                        f"Task generation failed or no description for type {chosen_task_type}. Task details: {task_details}"
                    )
                    send_telegram_message(
                        bot_token,
                        chat_id,
                        f"Sorry, I couldn't generate a '{chosen_task_type}' task. Try another or /newtask.",
                        reply_markup={"remove_keyboard": True},
                    )
                    update_firestore_state(
                        {"interaction_state": "awaiting_choice"},
                        user_doc_id=user_doc_id,
                    )
            else:
                logger.warning(f"Invalid task choice: {chosen_task_type}")
                send_telegram_message(
                    bot_token,
                    chat_id,
                    "Hmm, that doesn't look like one of the options. Please choose a task type from the list I sent.",
                )

        elif interaction_state == "awaiting_answer":
            task_details = current_state.get("current_task_details")
            if not task_details:
                logger.error("Awaiting answer but no task_details found in state.")
                send_telegram_message(
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
                    logger.debug(
                        "Voice answer received for Voice Recording Analysis task."
                    )
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
                                logger.debug(
                                    f"Downloaded audio for analysis, size: {len(audio_bytes_for_eval)} bytes"
                                )
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
                    logger.debug(
                        f"Received text answer/follow-up: {user_answer_text_for_eval} for task type {task_type}"
                    )
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
                item_type_for_proficiency = (
                    "phrasal_verbs"  # Or use 'idioms' if you want to track separately
                )
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
            # For new tasks, only update proficiency if a specific item and type are defined
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
                logger.info(
                    f"No specific item, item type, or valid correctness determined for proficiency update. Task type: {task_type}, Correctness: {is_correct_for_proficiency}"
                )

            logger.info(
                f"Feedback sent. State remains 'awaiting_answer' for user {user_doc_id}."
            )

        else:
            logger.info(
                f"Message received in state: {interaction_state}. Defaulting to help/wait message."
            )
            send_telegram_message(
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
                send_telegram_message(
                    bot_token,
                    chat_id,
                    f"Debug: A critical error occurred in the webhook: {str(e)[:100]}\nThe bot is now paused. Please use /start or /newtask to reset.",
                )
            except Exception:
                pass
        return "Internal Server Error", 500
