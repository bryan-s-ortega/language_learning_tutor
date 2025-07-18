"""
Configuration management for Language Learning Tutor.
Centralizes all configuration settings, constants, and environment-specific values.
"""

import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class DatabaseConfig:
    project_id: str = "daily-english-words"
    firestore_collection: str = "english_practice_state"
    proficiency_collection: str = "user_proficiency"
    rate_limit_collection: str = "rate_limits"


@dataclass
class SecretConfig:
    telegram_token_secret_id: str = "telegram-bot"
    gemini_api_key_secret_id: str = "gemini-api"
    authorized_users_secret_id: str = "authorized-users"
    admin_users_secret_id: str = "admin-users"


@dataclass
class AIConfig:
    gemini_model_name: str = "gemini-2.0-flash-001"
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
                "Voice Recording Analysis",
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "database": self.database.__dict__,
            "secrets": self.secrets.__dict__,
            "ai": self.ai.__dict__,
            "tasks": {"task_types": self.tasks.task_types},
            "logging": self.logging.__dict__,
        }


config = Config()

PROJECT_ID = config.database.project_id
TELEGRAM_TOKEN_SECRET_ID = config.secrets.telegram_token_secret_id
GEMINI_API_KEY_SECRET_ID = config.secrets.gemini_api_key_secret_id
AUTHORIZED_USERS_SECRET_ID = config.secrets.authorized_users_secret_id
ADMIN_USERS_SECRET_ID = config.secrets.admin_users_secret_id
FIRESTORE_COLLECTION = config.database.firestore_collection
PROFICIENCY_COLLECTION = config.database.proficiency_collection
GEMINI_MODEL_NAME = config.ai.gemini_model_name
TASK_TYPES = config.tasks.task_types
