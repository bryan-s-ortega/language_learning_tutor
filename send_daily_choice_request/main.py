import functions_framework
from utils import (
    access_secret_version, update_firestore_state, send_choice_request_message,
    TELEGRAM_TOKEN_SECRET_ID, AUTHORIZED_CHAT_ID_SECRET_ID
)

@functions_framework.http
def send_daily_choice_request(request):
    """
    Sends the daily message asking the user to choose a task type.
    Triggered by Cloud Scheduler (via HTTP call or Pub/Sub).
    """
    print("Daily choice request function triggered.")
    bot_token = None
    auth_chat_id = None
    try:
        # --- Retrieve Secrets ---
        bot_token = access_secret_version(TELEGRAM_TOKEN_SECRET_ID)
        auth_chat_id = access_secret_version(AUTHORIZED_CHAT_ID_SECRET_ID)
        print("Secrets retrieved for daily choice request.")

        # --- Update State (Acts as Daily Reset) ---
        state_to_set = {
            "interaction_state": "awaiting_choice",
            "chosen_task_type": None,
            "current_task_details": None
        }
        # Using auth_chat_id as the document ID for this single-user setup
        update_success = update_firestore_state(
            state_to_set,
            user_doc_id=auth_chat_id
        )

        if update_success:
            print("State updated successfully. Now sending choice request message.")
            # --- Call the new shared helper function ---
            send_success = send_choice_request_message(bot_token, auth_chat_id)
            # --- --- --- --- --- --- --- --- --- --- ---
            if send_success:
                return ("Choice request sent and state updated.", 200)
            else:
                 # State was updated, but message failed
                 return ("State updated BUT failed to send choice request message.", 500)
        else:
             print("Failed to update Firestore state.")
             return ("Failed to update state before sending choice request.", 500)

    except Exception as e:
        print(f"Error in send_daily_choice_request: {e}")
        if bot_token and auth_chat_id:
             # Avoid calling the helper here to prevent potential loops if it also fails
             pass # Maybe log error differently or send simpler text message if needed
        return (f"Internal server error: {e}", 500)