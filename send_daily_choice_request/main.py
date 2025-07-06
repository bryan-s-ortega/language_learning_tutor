import functions_framework
from utils import (
    access_secret_version,
    update_firestore_state,
    send_choice_request_message,
    TELEGRAM_TOKEN_SECRET_ID,
    get_authorized_users,
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
        print("Secrets retrieved for daily choice request.")

        # --- Get all authorized users ---
        authorized_users = get_authorized_users()
        print(f"Found {len(authorized_users)} authorized users")

        # --- Update State for all users (Acts as Daily Reset) ---
        state_to_set = {
            "interaction_state": "awaiting_choice",
            "chosen_task_type": None,
            "current_task_details": None,
        }

        success_count = 0
        total_users = len(authorized_users)

        for user_id in authorized_users:
            try:
                # Update state for each user
                update_success = update_firestore_state(
                    state_to_set, user_doc_id=user_id
                )

                if update_success:
                    # Send choice request to each user
                    send_success = send_choice_request_message(
                        bot_token, user_id, user_id
                    )
                    if send_success:
                        success_count += 1
                        print(
                            f"Successfully sent daily choice request to user {user_id}"
                        )
                    else:
                        print(f"Failed to send choice request to user {user_id}")
                else:
                    print(f"Failed to update state for user {user_id}")

            except Exception as e:
                print(f"Error processing user {user_id}: {e}")

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
        print(f"Error in send_daily_choice_request: {e}")
        if bot_token and auth_chat_id:
            # Avoid calling the helper here to prevent potential loops if it also fails
            pass  # Maybe log error differently or send simpler text message if needed
        return (f"Internal server error: {e}", 500)
