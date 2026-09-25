"""Phase 4.2 smoke test: load the pinned base model in 4-bit via Unsloth and report VRAM."""
import sys

import unsloth  # noqa: F401  (must import before transformers)
import torch
from unsloth import FastLanguageModel

MODEL_ID = sys.argv[1] if len(sys.argv) > 1 else "Qwen/Qwen3-14B"

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=MODEL_ID, max_seq_length=4096, load_in_4bit=True, dtype=None,
)
print(f"model:     {MODEL_ID} ({model.config._name_or_path})")
print(f"dtype:     {model.dtype}")
print(f"allocated: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
