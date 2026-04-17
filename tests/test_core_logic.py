import pytest
from unittest.mock import patch
from core_logic import TutorService


@pytest.fixture
def mock_tutor_service():
    with patch("core_logic.get_gemini_key", return_value="fake_key"):
        service = TutorService()
        return service


@patch("core_logic.get_firestore_state")
def test_handle_start(mock_get_state, mock_tutor_service):
    response = mock_tutor_service.handle_start("user123")
    assert "Welcome to the Language Learning Tutor" in response


@patch("core_logic.get_firestore_state")
@patch("core_logic.update_firestore_state")
def test_start_new_task(mock_update, mock_get_state, mock_tutor_service):
    response = mock_tutor_service.start_new_task("user123")
    assert "options" in response
    assert isinstance(response["options"], list)
    mock_update.assert_called_once()


@patch("core_logic.get_firestore_state")
@patch("core_logic.update_firestore_state")
@patch("core_logic.generate_task")
def test_select_task_type_success(
    mock_gen_task, mock_update, mock_get_state, mock_tutor_service
):
    mock_gen_task.return_value = {"description": "Test Task", "type": "Vocabulary"}

    response = mock_tutor_service.select_task_type("user123", "Vocabulary")

    assert response["message"] == "Test Task"
    assert response["task_details"]["type"] == "Vocabulary"
    mock_update.assert_called_once()


@patch("core_logic.get_firestore_state")
def test_select_task_type_invalid(mock_get_state, mock_tutor_service):
    response = mock_tutor_service.select_task_type("user123", "InvalidType")
    assert "error" in response


@patch("core_logic.get_firestore_state")
@patch("core_logic.update_firestore_state")
@patch("core_logic.evaluate_answer")
def test_process_answer_text(
    mock_eval, mock_update, mock_get_state, mock_tutor_service
):
    mock_get_state.return_value = {
        "interaction_state": "awaiting_answer",
        "current_task_details": {"type": "Vocabulary", "description": "Test"},
        "task_id": "task1",
    }
    mock_eval.return_value = {"feedback_text": "Good job!", "is_correct": True}

    response = mock_tutor_service.process_answer("user123", text_answer="answer")

    assert response["message"] == "Good job!"
    assert response["is_correct"] is True
    mock_update.assert_called()
