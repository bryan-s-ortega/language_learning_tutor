from datetime import datetime
from typing import Any, Dict, Optional

from handle_telegram_interaction.config import config
from handle_telegram_interaction.utils import (
    access_secret_version,
    update_firestore_state,
    get_firestore_state,
    generate_task,
    evaluate_answer,
    update_user_proficiency,
    get_user_proficiency,
    generate_progress_report,
    generate_tutor_chat_response,
)

# Initialize secrets
_gemini_key = None


def get_gemini_key() -> str:
    global _gemini_key
    if _gemini_key is None:
        _gemini_key = access_secret_version(config.secrets.gemini_api_key_secret_id)
    return _gemini_key


class TutorService:
    def __init__(self):
        self.gemini_key = get_gemini_key()

    def get_user_state(self, user_id: str) -> Dict[str, Any]:
        return get_firestore_state(user_doc_id=user_id)

    def handle_start(self, user_id: str) -> str:
        welcome_message = """
🎓 **Welcome to the Language Learning Tutor!**

I'm your AI-powered English learning assistant. Here's how to get started:

**Language Setting:**
You can set your preferred language for model responses at any time.

**Available Actions:**
• Start a new learning task
• View your learning progress
• Change difficulty or language

Ready to start learning? Click 'New Task' to begin!
"""
        return welcome_message

    def handle_progress(self, user_id: str) -> str:
        proficiency_data = get_user_proficiency(user_id)
        if proficiency_data:
            return generate_progress_report(proficiency_data)
        else:
            return "📊 **Learning Progress**: You haven't completed any tasks yet. Start practicing to see your progress!"

    def start_new_task(self, user_id: str) -> Dict[str, Any]:
        reset_state_data = {
            "interaction_state": "awaiting_choice",
            "chosen_task_type": None,
            "current_task_details": None,
        }
        update_firestore_state(reset_state_data, user_doc_id=user_id)

        # Return available task types for the frontend to display
        return {
            "message": "Please choose a task type:",
            "options": config.tasks.task_types,
        }

    def select_task_type(self, user_id: str, task_type: str) -> Dict[str, Any]:
        if task_type not in config.tasks.task_types:
            return {"error": "Invalid task type"}

        task_details = generate_task(self.gemini_key, task_type, user_id)
        if task_details and task_details.get("description"):
            new_state_data = {
                "interaction_state": "awaiting_answer",
                "chosen_task_type": task_type,
                "current_task_details": task_details,
                "task_id": f"{task_type}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            }
            update_firestore_state(new_state_data, user_doc_id=user_id)
            return {
                "message": task_details["description"],
                "task_details": task_details,
            }
        else:
            return {
                "error": f"Could not generate a '{task_type}' task. Please try again."
            }

    def process_answer(
        self,
        user_id: str,
        text_answer: Optional[str] = None,
        voice_file_id: Optional[str] = None,
        voice_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        current_state = get_firestore_state(user_doc_id=user_id)
        interaction_state = current_state.get("interaction_state", "idle")

        if interaction_state != "awaiting_answer":
            return self.handle_free_conversation(user_id, text_answer, voice_bytes)

        task_details = current_state.get("current_task_details")
        if not task_details:
            return {"error": "Session error: Task details lost. Please start over."}

        task_type = task_details.get("type")
        task_id = current_state.get("task_id", "unknown_task")
        evaluation_result = None
        is_correct_for_proficiency = False

        # Handle Voice Input
        if task_type in ["Free Style Voice Recording", "Topic Voice Recording"]:
            if voice_bytes:
                evaluation_result = evaluate_answer(
                    self.gemini_key,
                    task_details,
                    user_audio_bytes=voice_bytes,
                    user_doc_id=user_id,
                )
            else:
                return {
                    "message": f"For the task '{task_details.get('description')}', please send me a voice message."
                }

        # Handle Text Input
        else:
            if not text_answer:
                return {"message": "Please provide a text answer."}

            evaluation_result = evaluate_answer(
                self.gemini_key,
                task_details,
                user_answer_text=text_answer,
                user_doc_id=user_id,
            )

        feedback_text = "Sorry, I couldn't process your answer."
        if isinstance(evaluation_result, dict):
            feedback_text = evaluation_result.get("feedback_text", feedback_text)
            is_correct_for_proficiency = evaluation_result.get("is_correct", False)
        elif evaluation_result:
            feedback_text = str(evaluation_result)

        # Update proficiency (background task in a real app, but synchronous here for simplicity)
        self._update_proficiency(
            user_id, task_details, task_type, task_id, is_correct_for_proficiency
        )
        self._update_recent_items(user_id, task_details, task_type)

        # Reset state to idle after answering
        update_firestore_state({"interaction_state": "idle"}, user_doc_id=user_id)

        return {"message": feedback_text, "is_correct": is_correct_for_proficiency}

    def _update_proficiency(
        self, user_id, task_details, task_type, task_id, is_correct
    ):
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

        if item_type_for_proficiency and items_to_update and is_correct is not None:
            for item_name in items_to_update:
                update_user_proficiency(
                    user_id,
                    item_type_for_proficiency,
                    item_name,
                    is_correct,
                    task_id,
                )

    def _update_recent_items(self, user_id, task_details, task_type):
        specific_item_tested = task_details.get("specific_item_tested")
        if not specific_item_tested:
            return

        user_state = get_firestore_state(user_doc_id=user_id)
        field_map = {
            "Topic Voice Recording": "recent_topic_voice_recording",
            "Idiom": "recent_idiom",
            "Phrasal verb": "recent_phrasal_verb",
            "Vocabulary matching": "recent_vocabulary_matching",
            "Vocabulary": "recent_vocabulary",
            "Writing": "recent_writing",
            "Error correction": "recent_error_correction",
            "Word starting with letter": "recent_word_starting_with_letter",
        }

        if task_type in field_map:
            field_name = field_map[task_type]
            recent_items = user_state.get(field_name, [])

            if isinstance(specific_item_tested, list):
                for item in specific_item_tested:
                    if item not in recent_items:
                        recent_items.append(item)
            else:
                if specific_item_tested not in recent_items:
                    recent_items.append(specific_item_tested)

            # Limit list size if needed (e.g., keep last 15)
            if len(recent_items) > 15:
                recent_items = recent_items[-15:]

            update_firestore_state({field_name: recent_items}, user_doc_id=user_id)

    def handle_free_conversation(
        self, user_id: str, text: Optional[str] = None, voice: Optional[bytes] = None
    ) -> Dict[str, Any]:
        """Handle non-task messages as a natural tutoring conversation."""
        current_state = get_firestore_state(user_doc_id=user_id)
        sensitivity = current_state.get("correction_sensitivity", "standard")

        response_data = generate_tutor_chat_response(
            self.gemini_key,
            user_id,
            text_query=text,
            voice_query=voice,
            sensitivity=sensitivity,
        )

        # Update gamification (smaller XP for chat than tasks)
        xp_gain = 5  # Base XP for chatting
        if response_data.get("is_mostly_correct"):
            xp_gain += 10

        gamification_update = self._update_gamification(user_id, xp_gain=xp_gain)

        return {
            "message": response_data.get("chat_response"),
            "tutor_notes": response_data.get("tutor_notes"),
            "gamification": gamification_update,
        }

    def set_difficulty(self, user_id: str, level: str) -> bool:
        if level.lower() in ["beginner", "intermediate", "advanced"]:
            update_firestore_state(
                {"difficulty_level": level.lower()}, user_doc_id=user_id
            )
            return True
        return False

    def set_config(self, user_id: str, config_data: Dict[str, Any]) -> bool:
        """Update multiple configuration settings at once."""
        allowed_keys = [
            "difficulty_level",
            "response_language",
            "correction_sensitivity",
        ]
        updates = {}
        for key, value in config_data.items():
            if key in allowed_keys:
                updates[key] = value

        if updates:
            return update_firestore_state(updates, user_doc_id=user_id)
        return False

    def set_language(self, user_id: str, language: str) -> bool:
        # Simple validation, can be expanded
        update_firestore_state({"response_language": language}, user_doc_id=user_id)
        return True

    def _update_gamification(self, user_id: str, xp_gain: int = 0):
        """Update streaks and add XP."""
        current_state = get_firestore_state(user_doc_id=user_id)

        # 1. Update XP
        total_xp = current_state.get("total_xp", 0) + xp_gain

        # 2. Update Streak
        streak = current_state.get("current_streak", 0)
        last_date_str = current_state.get("last_practice_date")

        # We use simple UTC date for logic, but in a real app we'd use user's local date
        # For now, let's stick to a robust day-tracking
        today_date = datetime.utcnow().date()

        if last_date_str:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            days_diff = (today_date - last_date).days

            if days_diff == 1:
                streak += 1
            elif days_diff > 1:
                streak = 1
            # if days_diff == 0, streak remains the same
        else:
            streak = 1

        update_data = {
            "total_xp": total_xp,
            "current_streak": streak,
            "last_practice_date": today_date.strftime("%Y-%m-%d"),
        }
        update_firestore_state(update_data, user_doc_id=user_id)
        return update_data
