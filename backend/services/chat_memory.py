from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class ConversationTurn:
    user_question: str
    copilot_summary: str


@dataclass
class ConversationState:
    session_id: str
    turns: List[ConversationTurn] = field(default_factory=list)
    last_records: List[Dict[str, Any]] = field(default_factory=list)
    last_result: Dict[str, Any] = field(default_factory=dict)


class InMemoryChatMemory:
    def __init__(self) -> None:
        self._store: Dict[str, ConversationState] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: Optional[str] = None) -> ConversationState:
        with self._lock:
            sid = session_id or str(uuid4())
            if sid not in self._store:
                self._store[sid] = ConversationState(session_id=sid)
            return self._store[sid]

    def update(
        self,
        session_id: str,
        question: str,
        summary: str,
        records: List[Dict[str, Any]],
        result: Dict[str, Any],
    ) -> None:
        with self._lock:
            state = self._store.get(session_id)
            if not state:
                state = ConversationState(session_id=session_id)
                self._store[session_id] = state
            state.turns.append(ConversationTurn(user_question=question, copilot_summary=summary))
            state.turns = state.turns[-12:]
            state.last_records = records
            state.last_result = result

    def clear_all(self) -> None:
        """Reset all sessions (e.g. after a new CSV upload so answers use only the new file)."""
        with self._lock:
            self._store.clear()
