"""OpenClaw adapter for LLMWiki.

Integrates the ContextMemoryHarness with OpenClaw agents.
Provides per-turn hooks for context injection and capture.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from llmwiki.core.harness import ContextMemoryHarness

logger = logging.getLogger(__name__)


class OpenClawMemoryHook:
    """Memory hook for OpenClaw agents.

    Usage in an OpenClaw agent session:

        hook = OpenClawMemoryHook("~/Documents/selfwiki")

        # On each turn start:
        wiki_context = hook.on_turn_start(user_message)
        # Inject wiki_context into system prompt

        # On each turn end:
        hook.on_turn_end(user_message, assistant_message)

        # On session end:
        hook.on_session_end()
    """

    def __init__(
        self,
        vault_path: str = "~/Documents/selfwiki",
        config: Optional[Dict[str, Any]] = None,
        token_budget: int = 3000,
    ):
        self.harness = ContextMemoryHarness(vault_path=vault_path, config=config)
        self.token_budget = token_budget
        self._turn_count = 0

    def on_turn_start(self, user_message: str) -> str:
        """Called before processing a user message.

        Retrieves relevant wiki context and returns it as a formatted string
        suitable for injection into the system prompt.

        Args:
            user_message: The user's input message.

        Returns:
            Wiki context string (may be empty if no relevant knowledge found).
        """
        self._turn_count += 1
        try:
            context = self.harness.retrieve_and_assemble(
                query=user_message,
                token_budget=self.token_budget,
            )
            if context:
                logger.debug("Injected %d chars of wiki context", len(context))
            return context
        except Exception as e:
            logger.warning("Failed to retrieve wiki context: %s", e)
            return ""

    def on_turn_end(
        self,
        user_message: str,
        assistant_message: str,
        *,
        context: str = "primary",
        session_id: str = "",
    ) -> None:
        """Called after completing a turn.

        Captures the conversation to the chronicle for later curation.

        Args:
            user_message: The user's message.
            assistant_message: The assistant's response.
            context: Agent context. Non-primary contexts are skipped.
            session_id: Optional session identifier.
        """
        try:
            self.harness.capture_turn(
                user_content=user_message,
                assistant_content=assistant_message,
                context=context,
                session_id=session_id,
            )
        except Exception as e:
            logger.warning("Failed to capture turn: %s", e)

    def on_session_end(self, messages: Optional[List[Dict[str, Any]]] = None) -> None:
        """Called when the session ends.

        Optionally triggers curation if enabled.

        Args:
            messages: Full conversation history (optional).
        """
        logger.info("Session ended after %d turns", self._turn_count)
        # Curation is typically run on a schedule (cron), not every session,
        # but can be triggered manually here if desired.

    def curate_now(self, llm_generate: Optional[Any] = None) -> Dict[str, Any]:
        """Manually trigger curation."""
        return self.harness.curate(llm_generate=llm_generate)

    def system_prompt_addon(self) -> str:
        """Return a system prompt block describing wiki access."""
        return self.harness.system_prompt_block()
