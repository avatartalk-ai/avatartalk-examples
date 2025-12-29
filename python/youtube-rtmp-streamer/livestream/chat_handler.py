"""Chat handler for direct Q&A interactions with viewers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from openai import OpenAI

from livestream.context_store import ChatMessage, GlobalContextStore

logger = logging.getLogger(__name__)


class ChatHandler:
    """
    Handles direct chat interactions with viewers.

    This runs in a separate thread/coroutine and responds to questions
    from the YouTube Live chat independently from the avatar narration.
    """

    def __init__(
        self,
        openai_client: OpenAI,
        model: str,
        context_store: GlobalContextStore,
        system_prompt: str | None = None,
        language: str = "English",
    ):
        """
        Initialize the chat handler.

        Args:
            openai_client: OpenAI client instance
            model: Model to use for chat responses
            context_store: Global context store for chat history
            system_prompt: Optional custom system prompt for chat responses
            language: Target language for teaching (e.g., "English", "French", "Spanish")

        """
        self.client = openai_client
        self.model = model
        self.context_store = context_store
        self.language = language
        self.system_prompt = system_prompt or self._default_system_prompt()

    def _default_system_prompt(self) -> str:
        """Default system prompt for chat interactions based on language."""
        with open("chat.prompt") as f:
            template = f.read()
        return template.replace("{language}", self.language)

    def _build_chat_context(self, user_message: ChatMessage) -> list[dict[str, str]]:
        """
        Build message context for chat response.

        Args:
            user_message: The user's message/question

        Returns:
            List of messages for OpenAI API

        """
        messages = [{"role": "system", "content": self.system_prompt}]

        # Add recent interactions for context (last 3)
        recent_interactions = self.context_store.get_recent_interactions(count=3)
        for interaction in recent_interactions:
            messages.append({"role": "user", "content": interaction.user_message.text})
            messages.append({"role": "assistant", "content": interaction.ai_response})

        # Add current user message
        messages.append({"role": "user", "content": user_message.text})

        return messages

    async def generate_response(self, user_message: ChatMessage) -> str | None:
        """
        Generate a response to a user question.

        Args:
            user_message: The user's message

        Returns:
            Generated response text, or None if generation failed

        """
        try:
            messages = self._build_chat_context(user_message)

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=200,
                    temperature=0.7,
                ),
            )

            response_text = response.choices[0].message.content.strip()
            logger.info("Generated chat response: %s", response_text[:100])
            self.context_store.add_interaction(user_message, response_text)

            return response_text

        except Exception as e:
            logger.exception("Error generating chat response: %s", e)
            return None

    async def process_comment(self, comment: dict[str, Any]) -> str | None:
        """
        Process a YouTube comment and generate a response.

        Args:
            comment: Comment dict with 'text', 'author', 'timestamp'

        Returns:
            Generated response

        """
        text = comment.get("text", "").strip()
        author = comment.get("author", "Unknown")

        if not text:
            return None

        # Add to context store
        chat_message = ChatMessage(
            author=author,
            text=text,
            timestamp=comment.get("timestamp"),
        )
        self.context_store.add_chat_message(author, text)
        return await self.generate_response(chat_message)
