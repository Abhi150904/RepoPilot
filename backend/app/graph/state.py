from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    issue: str
    analysis: dict[str, object]
    plan: dict[str, object]

