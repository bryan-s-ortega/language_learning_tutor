import functions_framework
import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from utils import (
    access_secret_version,
    update_firestore_state,
    send_choice_request_message,
    get_authorized_users,
)


def process_user(bot_token, user_id, state_to_set):
    try:
        update_success = update_firestore_state(state_to_set, user_doc_id=user_id)
        if update_success:
            send_success = send_choice_request_message(bot_token, user_id, user_id)
            if send_success:
                logging.info(
                    f"Successfully sent daily choice request to user {user_id}"
                )
                return True
            else:
                logging.error(f"Failed to send choice request to user {user_id}")
        else:
            logging.error(f"Failed to update state for user {user_id}")
    except Exception as e:
        logging.error(f"Error processing user {user_id}: {e}", exc_info=True)
    return False


@functions_framework.http
def send_daily_choice_request(request):
    try:
        bot_token = access_secret_version(config.secrets.telegram_token_secret_id)
        authorized_users = get_authorized_users()
        state_to_set = {
            "interaction_state": "awaiting_choice",
            "chosen_task_type": None,
            "current_task_details": None,
        }
        success_count = 0
        total_users = len(authorized_users)
        for user_id in authorized_users:
            if process_user(bot_token, user_id, state_to_set):
                success_count += 1
        if success_count == total_users:
            return (
                f"Daily choice request sent to all {total_users} users successfully.",
                200,
            )
        elif success_count > 0:
            return (
                f"Daily choice request sent to {success_count}/{total_users} users. Some failed.",
                207,
            )
        else:
            return ("Failed to send daily choice request to any users.", 500)
    except Exception as e:
        logging.error(f"Error in send_daily_choice_request: {e}", exc_info=True)
        return (f"Internal server error: {e}", 500)
