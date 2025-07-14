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

    @patch("utils.db")
    def test_check_rate_limit_new_user(self, mock_db):
        # Mock Firestore operations
        mock_doc = Mock()
        mock_doc.get.return_value.exists = False
        mock_db.collection.return_value.document.return_value = mock_doc

        # New user should be allowed
        assert check_rate_limit("new_user")

    @patch("utils.db")
    def test_check_rate_limit_exceeded(self, mock_db):
        # Mock existing user with recent requests
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
            "Idiom/Phrasal verb",
            "Word starting with letter",
            "Voice Recording Analysis",
        ]

        for task_type in expected_types:
            assert task_type in config.tasks.task_types

        assert len(config.tasks.task_types) == 5
