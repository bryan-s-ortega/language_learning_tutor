"""
Configuration management for Language Learning Tutor.

This module centralizes all configuration settings, constants, and environment-specific
values used throughout the application.
"""

import os
from typing import Dict, Any, List
from dataclasses import dataclass


@dataclass
class DatabaseConfig:
    """Database configuration settings."""

    project_id: str = "daily-english-words"
    firestore_collection: str = "english_practice_state"
    proficiency_collection: str = "user_proficiency"
    rate_limit_collection: str = "rate_limits"


@dataclass
class SecretConfig:
    """Secret Manager configuration."""

    telegram_token_secret_id: str = "telegram-bot"
    gemini_api_key_secret_id: str = "gemini-api"
    authorized_users_secret_id: str = "authorized-users"
    admin_users_secret_id: str = "admin-users"


@dataclass
class AIConfig:
    """AI service configuration."""

    gemini_model_name: str = "gemini-2.0-flash-001"
    max_tokens: int = 1000
    temperature: float = 0.7


@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""

    max_requests: int = 10
    window_minutes: int = 5
    burst_limit: int = 20


@dataclass
class TaskConfig:
    """Task generation configuration."""

    task_types: List[str] = None  # type: ignore

    def __post_init__(self):
        if self.task_types is None:
            self.task_types = [
                "Error correction",
                "Vocabulary matching",
                "Idiom/Phrasal verb",
                "Word starting with letter",
                "Voice Recording Analysis",
            ]


@dataclass
class TelegramConfig:
    """Telegram Bot configuration."""

    message_timeout: int = 10
    max_message_length: int = 4096
    retry_attempts: int = 3
    parse_mode: str = "Markdown"


@dataclass
class LoggingConfig:
    """Logging configuration."""

    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    include_traceback: bool = True


class Config:
    """Main configuration class that aggregates all configuration sections."""

    def __init__(self):
        self.database = DatabaseConfig()
        self.secrets = SecretConfig()
        self.ai = AIConfig()
        self.rate_limit = RateLimitConfig()
        self.tasks = TaskConfig()
        self.telegram = TelegramConfig()
        self.logging = LoggingConfig()

        # Load environment-specific overrides
        self._load_environment_overrides()

    def _load_environment_overrides(self):
        """Load configuration overrides from environment variables."""
        # Database overrides
        if project_id := os.getenv("GCP_PROJECT_ID"):
            self.database.project_id = project_id

        # AI overrides
        if model_name := os.getenv("GEMINI_MODEL_NAME"):
            self.ai.gemini_model_name = model_name

        if temperature := os.getenv("GEMINI_TEMPERATURE"):
            self.ai.temperature = float(temperature)

        # Rate limiting overrides
        if max_requests := os.getenv("RATE_LIMIT_MAX_REQUESTS"):
            self.rate_limit.max_requests = int(max_requests)

        if window_minutes := os.getenv("RATE_LIMIT_WINDOW_MINUTES"):
            self.rate_limit.window_minutes = int(window_minutes)

        # Logging overrides
        if log_level := os.getenv("LOG_LEVEL"):
            self.logging.level = log_level.upper()

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary for serialization."""
        return {
            "database": {
                "project_id": self.database.project_id,
                "firestore_collection": self.database.firestore_collection,
                "proficiency_collection": self.database.proficiency_collection,
                "rate_limit_collection": self.database.rate_limit_collection,
            },
            "secrets": {
                "telegram_token_secret_id": self.secrets.telegram_token_secret_id,
                "gemini_api_key_secret_id": self.secrets.gemini_api_key_secret_id,
                "authorized_users_secret_id": self.secrets.authorized_users_secret_id,
                "admin_users_secret_id": self.secrets.admin_users_secret_id,
            },
            "ai": {
                "gemini_model_name": self.ai.gemini_model_name,
                "max_tokens": self.ai.max_tokens,
                "temperature": self.ai.temperature,
            },
            "rate_limit": {
                "max_requests": self.rate_limit.max_requests,
                "window_minutes": self.rate_limit.window_minutes,
                "burst_limit": self.rate_limit.burst_limit,
            },
            "tasks": {
                "task_types": self.tasks.task_types,
            },
            "telegram": {
                "message_timeout": self.telegram.message_timeout,
                "max_message_length": self.telegram.max_message_length,
                "retry_attempts": self.telegram.retry_attempts,
                "parse_mode": self.telegram.parse_mode,
            },
            "logging": {
                "level": self.logging.level,
                "format": self.logging.format,
                "include_traceback": self.logging.include_traceback,
            },
        }


# Global configuration instance
config = Config()

# Convenience exports for backward compatibility
PROJECT_ID = config.database.project_id
TELEGRAM_TOKEN_SECRET_ID = config.secrets.telegram_token_secret_id
GEMINI_API_KEY_SECRET_ID = config.secrets.gemini_api_key_secret_id
AUTHORIZED_USERS_SECRET_ID = config.secrets.authorized_users_secret_id
ADMIN_USERS_SECRET_ID = config.secrets.admin_users_secret_id
FIRESTORE_COLLECTION = config.database.firestore_collection
PROFICIENCY_COLLECTION = config.database.proficiency_collection
GEMINI_MODEL_NAME = config.ai.gemini_model_name
TASK_TYPES = config.tasks.task_types
