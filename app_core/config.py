"""
Configuration management for Language Learning Tutor.
Centralizes all configuration settings, constants, and environment-specific values.
"""

import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@dataclass
class DatabaseConfig:
    project_id: str = "daily-english-words"
    firestore_collection: str = "english_practice_state"
    proficiency_collection: str = "user_proficiency"
    rate_limit_collection: str = "rate_limits"


@dataclass
class FirebaseConfig:
    api_key: Optional[str] = None
    auth_domain: Optional[str] = None
    project_id: Optional[str] = None
    storage_bucket: Optional[str] = None
    messaging_sender_id: Optional[str] = None
    app_id: Optional[str] = None


@dataclass
class SecretConfig:
    gemini_api_key_secret_id: str = "gemini-api"
    authorized_users_secret_id: str = "authorized-users"
    admin_users_secret_id: str = "admin-users"


@dataclass
class AIConfig:
    gemini_model_name: str = "gemini-2.5-flash"
    max_tokens: int = 1000
    temperature: float = 0.7


@dataclass
class TaskConfig:
    task_types: Optional[List[str]] = None

    def __post_init__(self):
        if self.task_types is None:
            self.task_types = [
                "Error correction",
                "Vocabulary matching",
                "Idiom",
                "Phrasal verb",
                "Word starting with letter",
                "Free Style Voice Recording",
                "Topic Voice Recording",
                "Vocabulary",
                "Writing",
            ]


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    include_traceback: bool = True


class Config:
    def __init__(self):
        self.database = DatabaseConfig()
        self.secrets = SecretConfig()
        self.ai = AIConfig()
        self.tasks = TaskConfig()
        self.logging = LoggingConfig()
        self.firebase = FirebaseConfig()
        self._load_environment_overrides()

    def _load_environment_overrides(self):
        def override(attr_path: str, env_var: str, cast_type=None):
            value = os.getenv(env_var)
            if value is not None:
                obj = self
                attrs = attr_path.split(".")
                for attr in attrs[:-1]:
                    obj = getattr(obj, attr)
                if cast_type:
                    value = cast_type(value)
                setattr(obj, attrs[-1], value)

        override("database.project_id", "GCP_PROJECT_ID")
        override("ai.gemini_model_name", "GEMINI_MODEL_NAME")
        override("ai.temperature", "GEMINI_TEMPERATURE", float)
        override("logging.level", "LOG_LEVEL", str.upper)

        # Firebase overrides
        override("firebase.api_key", "FIREBASE_API_KEY")
        override("firebase.auth_domain", "FIREBASE_AUTH_DOMAIN")
        override("firebase.project_id", "FIREBASE_PROJECT_ID")
        override("firebase.storage_bucket", "FIREBASE_STORAGE_BUCKET")
        override("firebase.messaging_sender_id", "FIREBASE_MESSAGING_SENDER_ID")
        override("firebase.app_id", "FIREBASE_APP_ID")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "database": self.database.__dict__,
            "secrets": self.secrets.__dict__,
            "ai": self.ai.__dict__,
            "tasks": {"task_types": self.tasks.task_types},
            "logging": self.logging.__dict__,
            "firebase": self.get_firebase_config(),
        }

    def get_firebase_config(self) -> Dict[str, Any]:
        """Fetch Firebase config from environment or fallback to Secret Manager."""
        from .utils import access_secret_version

        # Mapping of config fields to environmental variables and Secret Manager IDs
        fields = {
            "api_key": "FIREBASE_API_KEY",
            "auth_domain": "FIREBASE_AUTH_DOMAIN",
            "project_id": "FIREBASE_PROJECT_ID",
            "storage_bucket": "FIREBASE_STORAGE_BUCKET",
            "messaging_sender_id": "FIREBASE_MESSAGING_SENDER_ID",
            "app_id": "FIREBASE_APP_ID",
        }

        result = {}
        for field, secret_id in fields.items():
            # Already set in config via _load_environment_overrides if .env existed
            val = getattr(self.firebase, field)
            if not val:
                try:
                    # Try to fetch from Secret Manager using the same ID
                    val = access_secret_version(secret_id)
                except Exception:
                    val = None
            result[field] = val
        return result


config = Config()

PROJECT_ID = config.database.project_id
GEMINI_API_KEY_SECRET_ID = config.secrets.gemini_api_key_secret_id
AUTHORIZED_USERS_SECRET_ID = config.secrets.authorized_users_secret_id
ADMIN_USERS_SECRET_ID = config.secrets.admin_users_secret_id
FIRESTORE_COLLECTION = config.database.firestore_collection
PROFICIENCY_COLLECTION = config.database.proficiency_collection
GEMINI_MODEL_NAME = config.ai.gemini_model_name
TASK_TYPES = config.tasks.task_types
