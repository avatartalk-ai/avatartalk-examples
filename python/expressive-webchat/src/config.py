import json
import logging
import sys
from enum import Enum
from pathlib import Path
from typing import ClassVar

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Load localized messages from JSON files
_DATA_DIR = Path(__file__).parent.parent / "data"


def _load_messages(filename: str) -> dict[str, str]:
    """Load localized messages from a JSON file."""
    filepath = _DATA_DIR / filename
    try:
        with open(filepath, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load {filename}: {e}")
        return {}


ERROR_MESSAGES = _load_messages("error_message.json")
TIMEOUT_MESSAGES = _load_messages("timeout_message.json")


def get_error_message(language_code: str) -> str:
    """Get localized error message for the given language."""
    return ERROR_MESSAGES.get(
        language_code, ERROR_MESSAGES.get("en", "I'm sorry, I encountered an error. Please try again.")
    )


def get_timeout_message(language_code: str) -> str:
    """Get localized timeout message for the given language."""
    return TIMEOUT_MESSAGES.get(
        language_code, TIMEOUT_MESSAGES.get("en", "I'm sorry, I'm taking too long to respond. Please try again.")
    )


class ASRModel(str, Enum):
    """ASR model to use for speech recognition."""

    FLUX = "flux"  # English only, has built-in turn detection
    NOVA3 = "nova3"  # Multilingual (10 languages), use endpointing for turn detection
    NOVA2 = "nova2"  # Single-language models for unsupported Nova-3 languages


class Expression(str, Enum):
    """Avatar expressions for emotional responses."""

    HAPPY = "happy"
    NEUTRAL = "neutral"
    SERIOUS = "serious"

    @classmethod
    def default(cls) -> "Expression":
        """Return the default expression."""
        return cls.NEUTRAL

    @classmethod
    def values(cls) -> list[str]:
        """Return list of valid expression values."""
        return [e.value for e in cls]


# Language configuration with ASR model mapping
# Format: (code, display_name, asr_model, deepgram_language_code)
LANGUAGE_CHOICES: list[tuple[str, str, ASRModel, str]] = [
    ("en", "English", ASRModel.FLUX, "en"),
    ("es", "Spanish", ASRModel.NOVA3, "es"),
    ("fr", "French", ASRModel.NOVA3, "fr"),
    ("de", "German", ASRModel.NOVA3, "de"),
    ("it", "Italian", ASRModel.NOVA3, "it"),
    ("pt", "Portuguese", ASRModel.NOVA3, "pt"),
    ("pl", "Polish", ASRModel.NOVA3, "pl"),
    ("tr", "Turkish", ASRModel.NOVA3, "tr"),
    ("ru", "Russian", ASRModel.NOVA3, "ru"),
    ("nl", "Dutch", ASRModel.NOVA3, "nl"),
    ("cs", "Czech", ASRModel.NOVA3, "cs"),
    # ("ar", "Arabic", ASRModel.NOVA3, "ar"),
    # ("cn", "Chinese", ASRModel.NOVA2, "zh"),
    ("ja", "Japanese", ASRModel.NOVA3, "ja"),
    ("hu", "Hungarian", ASRModel.NOVA3, "hu"),
    ("ko", "Korean", ASRModel.NOVA3, "ko"),
    ("hi", "Hindi", ASRModel.NOVA3, "hi"),
]


def get_language_config(code: str) -> tuple[str, str, ASRModel, str] | None:
    """Get language configuration by code."""
    for lang in LANGUAGE_CHOICES:
        if lang[0] == code:
            return lang
    return None


def get_asr_model_for_language(code: str) -> ASRModel:
    """Get the ASR model to use for a given language code."""
    config = get_language_config(code)
    if config:
        return config[2]
    return ASRModel.FLUX  # Default to Flux for unknown languages


def get_deepgram_language_code(code: str) -> str:
    """Get the Deepgram language code for a given language code."""
    config = get_language_config(code)
    if config:
        return config[3]
    return "en"  # Default to English


def get_language_display_name(code: str) -> str:
    """Get the display name for a given language code."""
    config = get_language_config(code)
    if config:
        return config[1]
    return "English"  # Default to English


class ClientConfig(BaseSettings):
    """Configuration for AvatarTalk Expressive WebChat client."""

    # API Keys (required)
    DEEPGRAM_API_KEY: str = ""
    AVATARTALK_API_KEY: str = ""  # Bearer token for authentication

    # LLM API Keys
    OPENAI_API_KEY: str = ""

    # AvatarTalk API
    AVATARTALK_API_BASE: str = "wss://api.avatartalk.ai"

    # Defaults
    DEFAULT_AVATAR: str = "mexican_woman"
    DEFAULT_EXPRESSION: str = "neutral"
    DEFAULT_LANGUAGE: str = "en"

    # LLM
    LLM_MODEL: str = "gpt-4o-mini"
    SYSTEM_PROMPT: str = "You are a helpful and friendly AI avatar."

    # Timeouts (seconds)
    WS_CONNECT_TIMEOUT: float = 30.0
    LLM_TIMEOUT: float = 60.0
    INIT_MESSAGE_TIMEOUT: float = 30.0

    # API settings
    ROOT_PATH: str = ""

    # Limits
    MAX_PROMPT_LENGTH: int = 4000  # Max system prompt length

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_required_keys(self) -> "ClientConfig":
        """Validate that required API keys are set."""
        missing = []
        if not self.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")
        if not self.DEEPGRAM_API_KEY:
            missing.append("DEEPGRAM_API_KEY")
        if not self.AVATARTALK_API_KEY:
            missing.append("AVATARTALK_API_KEY")

        if missing:
            logger.error(f"Missing required API keys: {', '.join(missing)}")
            logger.error("Please set these in your .env file. See .env.example for reference.")
            sys.exit(1)

        return self


settings = ClientConfig()
