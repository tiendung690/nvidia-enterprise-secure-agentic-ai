from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationTurn:
    user: str
    assistant: str


class BoundedConversationStore:
    """Bounded recent-turn projection; raw replay belongs in the trace store."""

    def __init__(self, *, recent_turns: int = 4, max_chars: int = 12000) -> None:
        self.recent_turns = recent_turns
        self.max_chars = max_chars
        self._turns: dict[str, deque[ConversationTurn]] = defaultdict(
            lambda: deque(maxlen=recent_turns)
        )
        self._lock = threading.RLock()

    def append(self, session_key: str, *, user: str, assistant: str) -> None:
        with self._lock:
            self._turns[session_key].append(
                ConversationTurn(user=user[: self.max_chars], assistant=assistant[: self.max_chars])
            )

    def prompt_fragment(self, session_key: str) -> str:
        with self._lock:
            turns = list(self._turns.get(session_key, ()))
        if not turns:
            return ""
        rows = ["<recent_conversation>"]
        for turn in turns:
            rows.extend((f"User: {turn.user}", f"Assistant: {turn.assistant}"))
        rows.append("</recent_conversation>")
        fragment = "\n".join(rows)
        return fragment[-self.max_chars :]

    def clear(self, session_key: str) -> None:
        with self._lock:
            self._turns.pop(session_key, None)
