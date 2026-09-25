"""Merge the ClearDrive LoRA adapter into the base model and export a Q4_K_M GGUF.

Brief 2, Phase 4.4 (written) / Phase 6.3 (run). Reads the adapter saved by
ml/train_qlora.py; writes the bf16 merged model and the GGUF the A4500's Ollama serves.

    python ml/merge_and_export.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import unsloth  # noqa: F401  (must import before transformers)
import torch
from unsloth import FastLanguageModel

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "ml/out"
ADAPTER_DIR = OUT / "cleardrive-qwen-lora"
MERGED_DIR = OUT / "cleardrive-qwen-merged"
GGUF_PATH = OUT / "cleardrive-qwen-Q4_K_M.gguf"
GGUF_WORK = OUT / "cleardrive-qwen-gguf"
MAX_SEQ_LENGTH = 4096  # keep equal to ml/train_qlora.py --max-seq-length


def main() -> int:
    if not (ADAPTER_DIR / "adapter_config.json").exists():
        print(f"FAIL: no adapter at {ADAPTER_DIR}")
        return 1

    # Loading the adapter dir pulls the base model named in adapter_config.json. Load it
    # 4-bit, as trained; save_pretrained_merged("merged_16bit") merges into 16-bit weights.
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(ADAPTER_DIR),
        max_seq_length=MAX_SEQ_LENGTH,
        load_in_4bit=True,
        dtype=torch.bfloat16,
    )

    model.save_pretrained_merged(str(MERGED_DIR), tokenizer, save_method="merged_16bit")
    print(f"merged bf16: {MERGED_DIR}")

    model.save_pretrained_gguf(str(GGUF_WORK), tokenizer, quantization_method="q4_k_m")
    ggufs = sorted(GGUF_WORK.rglob("*.gguf"), key=lambda p: p.stat().st_mtime)
    q4 = [p for p in ggufs if "q4_k_m" in p.name.lower()]
    if not q4:
        print(f"FAIL: no Q4_K_M gguf under {GGUF_WORK}: {[p.name for p in ggufs]}")
        return 1
    q4[-1].replace(GGUF_PATH)
    print(f"gguf: {GGUF_PATH} ({GGUF_PATH.stat().st_size / 1e9:.2f} GB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
