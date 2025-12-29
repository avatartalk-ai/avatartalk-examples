"""Global context store for managing chat history and interactions."""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """Represents a chat message in the global context."""

    author: str
    text: str
    timestamp: datetime


@dataclass
class ChatInteraction:
    """Represents a user question and AI response pair."""

    user_message: ChatMessage
    ai_response: str
    timestamp: datetime


class GlobalContextStore:
    """
    Thread-safe global store for chat history and interactions.

    Maintains two separate histories:
    1. Recent chat messages from users
    2. Q&A interactions (questions from users + AI responses)

    The avatar narration uses both histories to understand what's happening
    in the stream, while the chat thread responds directly to questions.
    """

    def __init__(self, max_chat_messages: int = 50, max_interactions: int = 10):
        """
        Initialize the global context store.

        Args:
            max_chat_messages: Maximum number of recent chat messages to keep
            max_interactions: Maximum number of Q&A interactions to keep

        """
        self._lock = threading.RLock()
        self._chat_messages: deque[ChatMessage] = deque(maxlen=max_chat_messages)
        self._interactions: deque[ChatInteraction] = deque(maxlen=max_interactions)

    def add_chat_message(self, author: str, text: str) -> None:
        """Add a new chat message to the store."""
        with self._lock:
            message = ChatMessage(
                author=author,
                text=text,
                timestamp=datetime.now(UTC),
            )
            self._chat_messages.append(message)
            logger.debug("Added chat message from %s: %s", author, text[:50])

    def add_interaction(self, user_message: ChatMessage, ai_response: str) -> None:
        """Add a Q&A interaction to the store."""
        with self._lock:
            interaction = ChatInteraction(
                user_message=user_message,
                ai_response=ai_response,
                timestamp=datetime.now(UTC),
            )
            self._interactions.append(interaction)
            logger.debug("Added interaction: Q: %s, A: %s", user_message.text[:50], ai_response[:50])

    def get_recent_chat_messages(self, count: int | None = None) -> list[ChatMessage]:
        """
        Get recent chat messages.

        Args:
            count: Number of messages to retrieve (None = all)

        Returns:
            List of recent chat messages, oldest first

        """
        with self._lock:
            messages = list(self._chat_messages)
            if count is not None:
                messages = messages[-count:]
            return messages

    def get_recent_interactions(self, count: int | None = None) -> list[ChatInteraction]:
        """
        Get recent Q&A interactions.

        Args:
            count: Number of interactions to retrieve (None = all)

        Returns:
            List of recent interactions, oldest first

        """
        with self._lock:
            interactions = list(self._interactions)
            if count is not None:
                interactions = interactions[-count:]
            return interactions

    def get_context_summary(self) -> str:
        """
        Generate a text summary of recent context for avatar narration.

        Returns:
            Formatted string containing recent chat messages and Q&A pairs

        """
        with self._lock:
            lines = []

            # Add recent chat messages
            recent_messages = list(self._chat_messages)[-10:]
            if recent_messages:
                lines.append("=== Recent Chat Messages ===")
                for msg in recent_messages:
                    lines.append(f"{msg.author}: {msg.text}")
                lines.append("")

            # Add recent Q&A interactions
            recent_qa = list(self._interactions)[-5:]
            if recent_qa:
                lines.append("=== Recent Q&A Interactions ===")
                for interaction in recent_qa:
                    lines.append(f"Q ({interaction.user_message.author}): {interaction.user_message.text}")
                    lines.append(f"A: {interaction.ai_response}")
                    lines.append("")

            return "\n".join(lines) if lines else "No recent context available."

    def clear(self) -> None:
        """Clear all stored context (useful for testing)."""
        with self._lock:
            self._chat_messages.clear()
            self._interactions.clear()
            logger.info("Context store cleared")
