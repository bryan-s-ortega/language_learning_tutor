import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone

# Mock Google Cloud dependencies before importing utils
with (
    patch("google.cloud.secretmanager.SecretManagerServiceClient"),
    patch("google.cloud.firestore.Client"),
    patch("google.cloud.speech.SpeechClient"),
):
    # Import the functions to test
    import sys
    import os

    sys.path.append(
        os.path.join(os.path.dirname(__file__), "..", "handle_telegram_interaction")
    )

    from utils import (
        is_user_authorized,
        is_admin_user,
        check_rate_limit,
        generate_task,
        generate_progress_report,
        get_firestore_state,
        update_firestore_state,
        access_secret_version,
        send_telegram_message,
        add_user_to_whitelist,
        remove_user_from_whitelist,
        get_user_proficiency,
        update_user_proficiency,
        transcribe_voice,
    )


class TestAuthentication:
    """Test authentication and user management functions"""

    @patch("utils.access_secret_version")
    def test_is_user_authorized(self, mock_access_secret):
        # Test with authorized user
        mock_access_secret.return_value = "123456\n789012"
        assert is_user_authorized("123456")

        # Test with unauthorized user
        assert not is_user_authorized("999999")

    @patch("utils.access_secret_version")
    def test_is_admin_user(self, mock_access_secret):
        # Test with admin user
        mock_access_secret.return_value = "123456\n789012"
        assert is_admin_user("123456")

        # Test with non-admin user
        assert not is_admin_user("999999")


class TestRateLimiting:
    """Test rate limiting functionality"""

    @patch("utils.get_firestore_client")
    def test_check_rate_limit_new_user(self, mock_get_firestore_client):
        # Mock Firestore operations
        mock_db = Mock()
        mock_doc = Mock()
        mock_doc.get.return_value.exists = False
        mock_db.collection.return_value.document.return_value = mock_doc
        mock_get_firestore_client.return_value = mock_db

        # New user should be allowed
        assert check_rate_limit("new_user")

    @patch("utils.get_firestore_client")
    def test_check_rate_limit_exceeded(self, mock_get_firestore_client):
        # Mock existing user with recent requests
        mock_db = Mock()
        mock_doc = Mock()
        mock_doc.get.return_value.exists = True
        mock_doc.get.return_value.to_dict.return_value = {
            "requests": [
                {"timestamp": datetime.now(timezone.utc).isoformat()},
                {"timestamp": datetime.now(timezone.utc).isoformat()},
                {"timestamp": datetime.now(timezone.utc).isoformat()},
                {"timestamp": datetime.now(timezone.utc).isoformat()},
                {"timestamp": datetime.now(timezone.utc).isoformat()},
                {"timestamp": datetime.now(timezone.utc).isoformat()},
                {"timestamp": datetime.now(timezone.utc).isoformat()},
                {"timestamp": datetime.now(timezone.utc).isoformat()},
                {"timestamp": datetime.now(timezone.utc).isoformat()},
                {"timestamp": datetime.now(timezone.utc).isoformat()},
                {"timestamp": datetime.now(timezone.utc).isoformat()},
            ]
        }
        mock_db.collection.return_value.document.return_value = mock_doc
        mock_get_firestore_client.return_value = mock_db

        # User with too many recent requests should be rate limited
        assert not check_rate_limit("rate_limited_user")


class TestTaskGeneration:
    """Test task generation functionality"""

    @patch("utils.get_user_proficiency")
    @patch("utils.genai")
    def test_generate_task_error_correction(self, mock_genai, mock_proficiency):
        # Mock user proficiency data
        mock_proficiency.return_value = {
            "grammar_topics": {
                "Past Simple": {
                    "attempts": 5,
                    "correct": 3,
                    "last_attempt": "2024-01-01",
                }
            }
        }

        # Mock Gemini response
        mock_model = Mock()
        mock_model.generate_content.return_value.text = """
        ITEM: Subject-Verb Agreement
        The students is going to the library.
        """
        mock_genai.GenerativeModel.return_value = mock_model

        result = generate_task("fake_key", "Error correction", "test_user")

        assert result["type"] == "Error correction"
        assert result["description"] is not None
        assert result["specific_item_tested"] == "Subject-Verb Agreement"


class TestProgressReporting:
    """Test progress reporting functionality"""

    def test_generate_progress_report_empty_data(self):
        # Test with no proficiency data
        result = generate_progress_report({})
        assert "📊 **Learning Progress**: No data available yet." in result

    def test_generate_progress_report_with_data(self):
        # Test with sample proficiency data
        proficiency_data = {
            "grammar_topics": {
                "Past Simple": {
                    "attempts": 10,
                    "correct": 8,
                    "last_attempt": "2024-01-01",
                },
                "Present Perfect": {
                    "attempts": 5,
                    "correct": 3,
                    "last_attempt": "2024-01-01",
                },
            },
            "vocabulary_words": {
                "apple": {"attempts": 3, "correct": 2, "last_attempt": "2024-01-01"}
            },
        }

        result = generate_progress_report(proficiency_data)
        assert "📊 **Your Learning Progress**" in result
        assert "Past Simple" in result
        assert "80.0%" in result or "72.2%" in result  # Accept either possible accuracy


class TestTaskTypes:
    """Test task type constants"""

    def test_task_types_defined(self):
        """Ensure all expected task types are defined"""
        from config import config

        expected_types = [
            "Error correction",
            "Vocabulary matching",
            "Idiom",
            "Phrasal verb",
            "Word starting with letter",
            "Voice Recording Analysis",
            "Vocabulary",
            "Writing",
        ]

        for task_type in expected_types:
            assert task_type in config.tasks.task_types

        assert len(config.tasks.task_types) == len(expected_types)


@pytest.mark.parametrize(
    "task_type",
    [
        "Error correction",
        "Vocabulary matching",
        "Idiom",
        "Phrasal verb",
        "Word starting with letter",
        "Voice Recording Analysis",
        "Vocabulary",
        "Writing",
    ],
)
@patch("utils.get_user_proficiency")
@patch("utils.genai")
def test_generate_task_all_types(mock_genai, mock_proficiency, task_type):
    mock_proficiency.return_value = {}
    mock_model = Mock()
    mock_model.generate_content.return_value.text = "ITEM: Test\nTest sentence."
    mock_genai.GenerativeModel.return_value = mock_model
    result = generate_task("fake_key", task_type, "test_user")
    assert result["type"] == task_type
    assert result["description"] is not None


@patch("utils.get_firestore_client")
def test_get_firestore_state_and_update(mock_get_firestore_client):
    mock_db = Mock()
    mock_doc = Mock()
    mock_doc.get.return_value.exists = True
    mock_doc.get.return_value.to_dict.return_value = {"foo": "bar"}
    mock_db.collection.return_value.document.return_value = mock_doc
    mock_get_firestore_client.return_value = mock_db
    state = get_firestore_state("user1")
    assert state == {"foo": "bar"}
    # Test update
    mock_doc.set.return_value = None
    assert update_firestore_state({"foo": "baz"}, "user1")


@patch("utils.get_secret_client")
def test_access_secret_version(mock_get_secret_client):
    mock_client = Mock()
    mock_response = Mock()
    mock_response.payload.data.decode.return_value = "secret-value"
    mock_client.access_secret_version.return_value = mock_response
    mock_get_secret_client.return_value = mock_client
    assert access_secret_version("my-secret") == "secret-value"


@patch("utils.requests.post")
def test_send_telegram_message_success(mock_post):
    mock_post.return_value.json.return_value = {"ok": True}
    mock_post.return_value.raise_for_status.return_value = None
    assert send_telegram_message("token", "chat", "text")


@patch("utils.requests.post")
def test_send_telegram_message_failure(mock_post):
    mock_post.return_value.json.return_value = {"ok": False, "description": "fail"}
    mock_post.return_value.raise_for_status.return_value = None
    assert not send_telegram_message("token", "chat", "text")


@patch("utils.get_secret_client")
def test_add_and_remove_user_to_whitelist(mock_get_secret_client):
    mock_client = Mock()
    mock_get_secret_client.return_value = mock_client
    # Patch _get_users_from_secret to simulate current users
    with patch("utils._get_users_from_secret", return_value=["123"]):
        assert add_user_to_whitelist("456")
        assert remove_user_from_whitelist("123")


@patch("utils.get_firestore_client")
def test_get_user_proficiency_and_update(mock_get_firestore_client):
    mock_db = Mock()
    mock_doc = Mock()
    mock_doc.get.return_value.exists = True
    mock_doc.get.return_value.to_dict.return_value = {"foo": "bar"}
    mock_db.collection.return_value.document.return_value = mock_doc
    mock_get_firestore_client.return_value = mock_db
    assert get_user_proficiency("user1") == {"foo": "bar"}
    # update_user_proficiency is more complex, but we can check it doesn't crash
    with patch("utils.get_firestore_server_timestamp", return_value="now"):
        assert update_user_proficiency("user1", "grammar_topics", "Past Simple", True)


@patch("utils.requests.get")
@patch("utils.genai")
def test_transcribe_voice(mock_genai, mock_requests):
    # Mock Telegram file download
    mock_requests.side_effect = [
        Mock(
            status_code=200,
            json=lambda: {"result": {"file_path": "voice.ogg"}},
            raise_for_status=lambda: None,
        ),
        Mock(status_code=200, content=b"audio-bytes", raise_for_status=lambda: None),
    ]
    # Mock Gemini response
    mock_model = Mock()
    mock_model.generate_content.return_value.text = "transcribed text"
    mock_genai.GenerativeModel.return_value = mock_model
    result = transcribe_voice("token", "file_id", gemini_key="fake_key")
    assert result == "transcribed text"
