import functions_framework
import requests
from datetime import datetime
from utils import (
    access_secret_version, send_telegram_message, update_firestore_state, get_firestore_state,
    send_choice_request_message, transcribe_voice, generate_task, evaluate_answer, TASK_TYPES,
    TELEGRAM_TOKEN_SECRET_ID, AUTHORIZED_CHAT_ID_SECRET_ID, GEMINI_API_KEY_SECRET_ID,
    update_user_proficiency, get_adaptive_task_type, get_user_proficiency, generate_progress_report,
    logger
)

@functions_framework.http
def handle_telegram_interaction(request):
    if request.method != 'POST':
        logger.warning("Received non-POST request.")
        return 'Only POST requests are accepted', 405

    bot_token = None
    auth_chat_id_str = None
    gemini_key = None
    chat_id = None

    try:
        bot_token = access_secret_version(TELEGRAM_TOKEN_SECRET_ID)
        auth_chat_id_str = access_secret_version(AUTHORIZED_CHAT_ID_SECRET_ID)
        gemini_key = access_secret_version(GEMINI_API_KEY_SECRET_ID)
        logger.info("Webhook secrets retrieved.")

        logger.debug("Attempting to parse JSON body...")
        req_body = request.get_json(silent=True)
        logger.debug(f"JSON body parsed. Type: {type(req_body)}")
        if not req_body:
            logger.error("Error: Invalid or empty JSON body received.")
            return "Bad Request", 400

        message = req_body.get('message')
        if not message:
            logger.info("No 'message' key found in webhook body. Acknowledging.")
            return "OK", 200

        chat_id_from_message = message.get('chat', {}).get('id')
        if not chat_id_from_message:
            logger.warning("No chat_id found in message. Acknowledging.")
            return "OK", 200
        
        chat_id = chat_id_from_message
        user_doc_id = str(chat_id)

        if user_doc_id != auth_chat_id_str:
            logger.warning(f"Unauthorized attempt from chat_id: {chat_id}")
            return "Forbidden", 403

        message_text = message.get('text', '').strip()
        voice = message.get('voice')
        transcribed_text = None

        if voice:
            logger.debug("Entered voice processing block.")
            file_id = voice.get('file_id')
            if file_id:
                logger.debug(f"Got file_id {file_id}. Calling transcribe_voice...")
                try:
                    transcribed_text = transcribe_voice(bot_token, file_id, gemini_key)
                except Exception as E:
                     logger.error(f"ERROR: Exception occurred *during* transcribe_voice call: {E}", exc_info=True)
                     transcribed_text = None
                
                logger.debug(f"Returned from transcribe_voice. Result type: {type(transcribed_text)}, Value: '{transcribed_text}'")
                if transcribed_text:
                   logger.debug(f"Transcription succeeded. Using text: '{transcribed_text}'")
                   message_text = transcribed_text
                else:
                   logger.warning("Transcription failed or returned empty. Informing user.")
                   send_telegram_message(bot_token, chat_id, "Sorry, I couldn't understand the voice message. Please try typing.")
                   return "OK", 200
            else:
                logger.warning("Voice message present but no file_id found.")
        else:
             logger.debug("No voice message detected in this payload.")

        if message_text is None: message_text = ""
        logger.debug(f"Effective message_text before command/state check: '{message_text}'")

        if message_text.lower() == "/newtask":
            logger.info(f"/newtask command received from user {user_doc_id}")
            reset_state_data = {"interaction_state": "awaiting_choice", "chosen_task_type": None, "current_task_details": None}
            update_success = update_firestore_state(reset_state_data, user_doc_id=user_doc_id)
            if update_success:
                logger.info("State reset successfully for /newtask. Now sending new choice request message.")
                send_success = send_choice_request_message(bot_token, chat_id, user_doc_id)
                if not send_success:
                     logger.error("Failed to send choice request message after /newtask state reset.")
                     send_telegram_message(bot_token, chat_id, "State reset, but I had trouble sending the new task options. Please try /newtask again later or wait for the daily prompt.")
            else:
                logger.error("Failed to reset state for /newtask.")
                send_telegram_message(bot_token, chat_id, "Sorry, there was an issue resetting for a new task. Please try /newtask again.")
            return "OK", 200
        
        elif message_text.lower() == "/progress":
            logger.info(f"/progress command received from user {user_doc_id}")
            proficiency_data = get_user_proficiency(user_doc_id)
            if proficiency_data:
                progress_message = generate_progress_report(proficiency_data)
                send_telegram_message(bot_token, chat_id, progress_message)
            else:
                send_telegram_message(bot_token, chat_id, "📊 **Learning Progress**: You haven't completed any tasks yet. Start practicing to see your progress!")
            return "OK", 200

        current_state = get_firestore_state(user_doc_id=user_doc_id)
        interaction_state = current_state.get("interaction_state", "idle")
        logger.info(f"Current interaction state for {user_doc_id}: {interaction_state}")

        if interaction_state == "awaiting_choice":
            chosen_task_type = message_text
            if chosen_task_type in TASK_TYPES:
                logger.info(f"User chose task type: {chosen_task_type}")
                task_details = generate_task(gemini_key, chosen_task_type, user_doc_id)
                if task_details and task_details.get("description"):
                    new_state_data = {
                        "interaction_state": "awaiting_answer",
                        "chosen_task_type": chosen_task_type,
                        "current_task_details": task_details,
                        "task_id": f"{chosen_task_type}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                    }
                    update_firestore_state(new_state_data, user_doc_id=user_doc_id)
                    send_telegram_message(bot_token, chat_id, task_details['description'], reply_markup={"remove_keyboard": True})
                else:
                    logger.error(f"Task generation failed or no description for type {chosen_task_type}. Task details: {task_details}")
                    send_telegram_message(bot_token, chat_id, f"Sorry, I couldn't generate a '{chosen_task_type}' task. Try another or /newtask.", reply_markup={"remove_keyboard": True})
                    update_firestore_state({"interaction_state": "awaiting_choice"}, user_doc_id=user_doc_id)
            else:
                logger.warning(f"Invalid task choice: {chosen_task_type}")
                send_telegram_message(bot_token, chat_id, "Hmm, that doesn't look like one of the options. Please choose a task type from the list I sent.")

        elif interaction_state == "awaiting_answer":
            task_details = current_state.get("current_task_details")
            if not task_details:
                logger.error("Awaiting answer but no task_details found in state.")
                send_telegram_message(bot_token, chat_id, "Sorry, I lost track of the current task. Please wait for the next prompt or use /newtask.")
                update_firestore_state({"interaction_state": "idle"}, user_doc_id=user_doc_id)
                return "OK", 200

            task_type = task_details.get('type')
            task_id = current_state.get("task_id", "unknown_task")
            evaluation_result = None 
            feedback_text_to_send = "Sorry, I couldn't process your answer for evaluation."
            is_correct_for_proficiency = False

            if task_type == "Voice Recording Analysis":
                if voice:
                    logger.debug(f"Voice answer received for Voice Recording Analysis task.")
                    file_id = voice.get('file_id')
                    if file_id:
                        audio_bytes_for_eval = None
                        try:
                            get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
                            res_file_path = requests.get(get_file_url, timeout=10)
                            res_file_path.raise_for_status()
                            file_path_tg = res_file_path.json().get('result', {}).get('file_path')
                            if file_path_tg:
                                file_download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path_tg}"
                                res_audio = requests.get(file_download_url, timeout=20)
                                res_audio.raise_for_status()
                                audio_bytes_for_eval = res_audio.content
                                logger.debug(f"Downloaded audio for analysis, size: {len(audio_bytes_for_eval)} bytes")
                            else:
                                logger.error("Could not get file_path from Telegram for voice analysis.")
                        except Exception as dl_err:
                            logger.error(f"Failed to download voice for analysis: {dl_err}", exc_info=True)

                        if audio_bytes_for_eval:
                            evaluation_result = evaluate_answer(gemini_key, task_details, user_audio_bytes=audio_bytes_for_eval, user_doc_id=user_doc_id)
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
                    logger.debug(f"Received text answer/follow-up: {user_answer_text_for_eval} for task type {task_type}")
                    evaluation_result = evaluate_answer(gemini_key, task_details, user_answer_text=user_answer_text_for_eval, user_doc_id=user_doc_id)
            if isinstance(evaluation_result, dict):
                feedback_text_to_send = evaluation_result.get("feedback_text", feedback_text_to_send)
                is_correct_for_proficiency = evaluation_result.get("is_correct", False)
            elif evaluation_result is not None:
                feedback_text_to_send = str(evaluation_result)

            send_telegram_message(bot_token, chat_id, feedback_text_to_send)

            specific_item_tested = task_details.get("specific_item_tested")
            item_type_for_proficiency = None
            items_to_update = []

            if task_type == "Idiom/Phrasal verb" and specific_item_tested:
                item_type_for_proficiency = "phrasal_verbs"
                items_to_update.append(specific_item_tested)
            elif task_type == "Error correction" and specific_item_tested:
                item_type_for_proficiency = "grammar_topics"
                items_to_update.append(specific_item_tested)
            elif task_type == "Vocabulary matching" and isinstance(specific_item_tested, list):
                item_type_for_proficiency = "vocabulary_words"
                items_to_update.extend(specific_item_tested)
            
            if item_type_for_proficiency and items_to_update and is_correct_for_proficiency is not None:
                for item_name in items_to_update:
                    update_user_proficiency(user_doc_id, item_type_for_proficiency, item_name, is_correct_for_proficiency, task_id)
            else:
                logger.info(f"No specific item, item type, or valid correctness determined for proficiency update. Task type: {task_type}, Correctness: {is_correct_for_proficiency}")

            logger.info(f"Feedback sent. State remains 'awaiting_answer' for user {user_doc_id}.")

        else:
            logger.info(f"Message received in state: {interaction_state}. Defaulting to help/wait message.")
            send_telegram_message(bot_token, chat_id, "I'm waiting for the next daily prompt to select a task type. You can use `/newtask` to reset if needed.")

        return "OK", 200

    except Exception as e:
        logger.error(f"FATAL Error processing webhook request: {e}", exc_info=True)
        if bot_token and chat_id:
             try:
                 send_telegram_message(bot_token, chat_id, f"Debug: A critical error occurred in the webhook: {str(e)[:100]}")
             except:
                 pass
        return "Internal Server Error", 500