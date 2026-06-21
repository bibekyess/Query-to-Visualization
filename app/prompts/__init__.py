"""
Prompt loading.

Prompts live as editable text files in this package so they can be tuned,
diffed, and versioned without touching Python code. Import SYSTEM_PROMPT
wherever the agent needs it.
"""
from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent

SYSTEM_PROMPT = (_PROMPTS_DIR / "system.md").read_text(encoding="utf-8")
