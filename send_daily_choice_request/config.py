"""
Configuration management for Language Learning Tutor.

This module centralizes all configuration settings, constants, and environment-specific
values used throughout the application.
"""

from typing import List
from dataclasses import dataclass


@dataclass
class SecretConfig:
    """Secret Manager configuration."""

    telegram_token_secret_id: str = "telegram-bot"
    gemini_api_key_secret_id: str = "gemini-api"
    authorized_users_secret_id: str = "authorized-users"
    admin_users_secret_id: str = "admin-users"


@dataclass
class TaskConfig:
    """Task generation configuration."""

    task_types: List[str] = None  # type: ignore

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
                "Listening",
                "Describing",
            ]


@dataclass
class DatabaseConfig:
    """Database configuration settings."""

    project_id: str = "daily-english-words"
    firestore_collection: str = "english_practice_state"


class Config:
    """Main configuration class that aggregates all configuration sections."""

    def __init__(self):
        self.secrets = SecretConfig()
        self.tasks = TaskConfig()
        self.database = DatabaseConfig()


# Global configuration instance
config = Config()

# Convenience exports for backward compatibility
TELEGRAM_TOKEN_SECRET_ID = config.secrets.telegram_token_secret_id
FIRESTORE_COLLECTION = config.database.firestore_collection
TASK_TYPES = config.tasks.task_types
