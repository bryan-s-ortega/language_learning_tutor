import functions_framework
import json
from utils import (
    access_secret_version, send_telegram_message, update_firestore_state, get_firestore_state,
    send_choice_request_message, transcribe_voice, generate_task, evaluate_answer, TASK_TYPES,
    TELEGRAM_TOKEN_SECRET_ID, AUTHORIZED_CHAT_ID_SECRET_ID, GEMINI_API_KEY_SECRET_ID
)

@functions_framework.http
def handle_telegram_interaction(request):
    """
    Handles incoming Telegram messages (text & voice), manages state,
    triggers task generation and evaluation.
    """
    if request.method != 'POST':
        return 'Only POST requests are accepted', 405

    bot_token = None
    auth_chat_id_str = None
    gemini_key = None
    try:
        # --- Retrieve Secrets ---
        bot_token = access_secret_version(TELEGRAM_TOKEN_SECRET_ID)
        auth_chat_id_str = access_secret_version(AUTHORIZED_CHAT_ID_SECRET_ID)
        gemini_key = access_secret_version(GEMINI_API_KEY_SECRET_ID)
        print("Webhook secrets retrieved.")

        # --- Parse Request Body ---
        req_body = request.get_json(silent=True)
        if not req_body:
            print("Error: Invalid or empty JSON body received.")
            return "Bad Request", 400
        print(f"Webhook received body: {json.dumps(req_body)}")

        # --- Extract Message Info ---
        message = req_body.get('message')
        # TODO: Handle callback_query if using InlineKeyboard
        if not message:
            print("No 'message' key found in webhook body.")
            return "OK", 200 # Acknowledge receipt, nothing to process

        chat_id = message.get('chat', {}).get('id')
        if not chat_id:
            print("No chat_id found in message.")
            return "OK", 200

        # Use chat_id as the document ID for state
        user_doc_id = str(chat_id)

        # --- Authorization ---
        if user_doc_id != auth_chat_id_str:
            print(f"Unauthorized attempt from chat_id: {chat_id}")
            return "Forbidden", 403

        # --- Process Message (Text or Voice) ---
        message_text = message.get('text', '').strip()
        voice = message.get('voice')
        transcribed_text = None

        if voice:
            file_id = voice.get('file_id')
            if file_id:
                try:
                    transcribed_text = transcribe_voice(bot_token, file_id)
                except Exception as E:
                     print(f"ERROR: Exception occurred *during* transcribe_voice call: {E}")
                     transcribed_text = None
                if transcribed_text:
                   message_text = transcribed_text
                else:
                   send_telegram_message(bot_token, chat_id, "Sorry, I couldn't understand the voice message. Please try typing.")
                   return "OK", 200
            else:
                print("Voice message present but no file_id found.")
        else:
             print("No voice message detected in this payload.")

        # --- Now process using message_text (which is either original text or transcription) ---
        if not message_text:
             # This handles cases where there was no text AND (voice failed OR no voice was sent)
             print("No text content available to process after checking voice.")
             # Perhaps send a help message? For now, just exit gracefully.
             return "OK", 200

        # --- Handle /newtask Command FIRST ---
        if message_text.lower() == "/newtask":
            print(f"New task command received from user {user_doc_id}")
            # Reset state back to expecting a choice, clear task details
            reset_state_data = {
                "interaction_state": "awaiting_choice",
                "chosen_task_type": None,
                "current_task_details": None
            }
            update_success = update_firestore_state(reset_state_data, user_doc_id=user_doc_id)

            if update_success:
                print("State reset successfully. Now sending new choice request message.")
                # --- Call the new shared helper function ---
                send_success = send_choice_request_message(bot_token, chat_id)
                # --- --- --- --- --- --- --- --- --- --- ---
                if not send_success:
                    # Attempt to notify user that state reset but message failed
                    send_telegram_message(bot_token, chat_id, "State reset, but I had trouble sending the new options. Please try /newtask again later.")
            else:
                # Failed to reset state
                send_telegram_message(bot_token, chat_id, "Sorry, there was an issue resetting the state. Please try /newtask again.")

            return "OK", 200 # Command handled, exit function

        # --- Proceed with state machine using message_text ---
        current_state = get_firestore_state(user_doc_id=user_doc_id)
        interaction_state = current_state.get("interaction_state", "idle")
        print(f"Current interaction state for {user_doc_id}: {interaction_state}")

        # --- State Machine Logic ---
        if interaction_state == "awaiting_choice":
            chosen_task = message_text
            if chosen_task in TASK_TYPES:
                print(f"User chose task type: {chosen_task}")
                task_details = generate_task(gemini_key, chosen_task)
                if task_details:
                    new_state_data = {
                        "interaction_state": "awaiting_answer",
                        "chosen_task_type": chosen_task,
                        "current_task_details": task_details
                    }
                    update_firestore_state(new_state_data, user_doc_id=user_doc_id)
                    send_telegram_message(bot_token, chat_id, task_details['description'], reply_markup={"remove_keyboard": True})
                else:
                    send_telegram_message(bot_token, chat_id, f"Sorry, I couldn't generate a '{chosen_task}' task right now.", reply_markup={"remove_keyboard": True})
                    update_firestore_state({"interaction_state": "awaiting_choice"}, user_doc_id=user_doc_id) # Stay awaiting choice
            else:
                send_telegram_message(bot_token, chat_id, "Hmm, that doesn't look like one of the options. Please choose a task type.")

        elif interaction_state == "awaiting_answer":
            user_answer = message_text
            task_details = current_state.get("current_task_details")
            if not task_details:
                 send_telegram_message(bot_token, chat_id, "Sorry, something went wrong. I seem to have forgotten the task I gave you.")
                 update_firestore_state({"interaction_state": "idle"}, user_doc_id=user_doc_id)
                 return "OK", 200

            print(f"Received answer: {user_answer}")
            feedback = evaluate_answer(gemini_key, task_details, user_answer)
            send_telegram_message(bot_token, chat_id, feedback)
            print(f"Feedback sent. State remains 'awaiting_answer' for user {user_doc_id}.")

        else:
            print(f"Ignoring message received in state: {interaction_state}")
            send_telegram_message(bot_token, chat_id, "I'm waiting for the next daily prompt. You can use /reset if you want to clear the current state.")

        return "OK", 200

    except Exception as e:
        print(f"FATAL Error processing webhook request: {e}")
        if bot_token and auth_chat_id_str:
             try:
                 send_telegram_message(bot_token, auth_chat_id_str, f"Debug: Error in webhook function: {e}")
             except:
                 pass
        return "Internal Server Error", 500