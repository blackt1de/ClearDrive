"""Single source of truth for the Gemma 4 chat template.

Wraps tokenizer.apply_chat_template(...). Never hand-roll the template — Gemma
4's format is owned upstream and changes quietly between revisions. Always call
through this module.

STUB: MODEL_ID is a placeholder; confirm the actual HuggingFace ID before any
serious load (likely "google/gemma-4-e4b-it" or similar). The Ollama tag in
production is `gemma4:e4b`.
"""

from __future__ import annotations

from typing import Iterable, Optional

# Loaded lazily so importing this module doesn't pull `transformers` into every
# code path. Set MODEL_ID via the env var GEMMA_MODEL_ID if it differs.
import os

MODEL_ID = os.environ.get("GEMMA_MODEL_ID", "google/gemma-4-e4b-it")

_tokenizer = None


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        from transformers import AutoTokenizer

        _tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    return _tokenizer


def apply_chat_template(
    messages: Iterable[dict],
    add_generation_prompt: bool = True,
) -> str:
    """Render a messages list to the Gemma 4 chat format.

    messages: list of {"role": "system"|"user"|"assistant", "content": str}
    """
    tok = _get_tokenizer()
    return tok.apply_chat_template(
        list(messages),
        tokenize=False,
        add_generation_prompt=add_generation_prompt,
    )


def reset_tokenizer_cache() -> None:
    """Force the next call to re-download / re-load the tokenizer."""
    global _tokenizer
    _tokenizer = None
