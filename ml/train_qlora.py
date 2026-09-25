"""QLoRA fine-tune of the pinned base model (Qwen3-14B) on the ClearDrive SFT pairs.

Brief 2, Phase 4.3 (written) / Phase 6.2 (run). Inputs are the chat-format JSONL files
produced by Brief 2c step 7: one {"messages": [system, user, assistant]} object per line.

    python ml/train_qlora.py                 # full run (Phase 6.2)
    python ml/train_qlora.py --pilot         # 5% of train, 200 steps (required first; root CLAUDE.md)

Run `ml/scripts/blackwell_check.py` before either. Chat template is the model's own, applied
via tokenizer.apply_chat_template(); loss is computed on the assistant turn only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import unsloth  # noqa: F401  (must import before transformers/trl)
import torch
from datasets import load_dataset
from transformers import TrainerCallback
from trl import SFTConfig, SFTTrainer
from unsloth import FastLanguageModel
from unsloth.chat_templates import train_on_responses_only

REPO = Path(__file__).resolve().parent.parent
MODEL_ID = "Qwen/Qwen3-14B"            # notes/decisions.md 2026-09-25; fallback unsloth/Qwen3-14B
TRAIN = REPO / "data/train/train.jsonl"
VAL = REPO / "data/train/val.jsonl"
OUT = REPO / "ml/out"
ADAPTER_DIR = OUT / "cleardrive-qwen-lora"
LOG_PATH = OUT / "train_log.jsonl"

# Qwen chat-format markers, used only to locate the assistant span for loss masking.
INSTRUCTION_PART = "<|im_start|>user\n"
RESPONSE_PART = "<|im_start|>assistant\n"

SEED = 42


class JsonlLogger(TrainerCallback):
    """Append every trainer log event (loss, lr, eval_loss, ...) to ml/out/train_log.jsonl."""

    def __init__(self, path: Path):
        self.path = path

    def on_log(self, args, state, control, logs=None, **kwargs):
        if not logs:
            return
        rec = {"step": state.global_step, "epoch": state.epoch, "time": time.time(), **logs}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MODEL_ID)
    ap.add_argument("--max-seq-length", type=int, default=4096)
    ap.add_argument("--pilot", action="store_true", help="5%% of train data, 200 steps")
    ap.add_argument("--report-to", default="none", help="HF Trainer report_to, e.g. wandb")
    args = ap.parse_args()

    for p in (TRAIN, VAL):
        if not p.exists():
            print(f"FAIL: missing {p}")
            return 1
    OUT.mkdir(parents=True, exist_ok=True)
    if not torch.cuda.is_available():
        print("FAIL: CUDA not available")
        return 1

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model,
        max_seq_length=args.max_seq_length,
        load_in_4bit=True,
        dtype=torch.bfloat16,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=SEED,
    )

    ds = load_dataset("json", data_files={"train": str(TRAIN), "val": str(VAL)})

    def render(batch):
        return {"text": [
            tokenizer.apply_chat_template(m, tokenize=False, add_generation_prompt=False)
            for m in batch["messages"]
        ]}

    ds = ds.map(render, batched=True, remove_columns=ds["train"].column_names)

    # Truncation would cut the assistant turn (it comes last), so refuse instead of training
    # on clipped targets. Raise --max-seq-length or drop the long pairs upstream.
    for split in ("train", "val"):
        lens = [len(tokenizer(t, add_special_tokens=False)["input_ids"]) for t in ds[split]["text"]]
        over = sum(n > args.max_seq_length for n in lens)
        print(f"{split}: {len(lens)} pairs, max {max(lens)} tokens, {over} over {args.max_seq_length}")
        if over:
            print(f"FAIL: {over} {split} pairs exceed --max-seq-length {args.max_seq_length}")
            return 1

    train_ds, max_steps = ds["train"], -1
    if args.pilot:
        n = max(1, len(train_ds) // 20)
        train_ds = train_ds.shuffle(seed=SEED).select(range(n))
        max_steps = 200
        print(f"PILOT: {n} train pairs, max_steps={max_steps}")

    adapter_dir = ADAPTER_DIR.with_name(ADAPTER_DIR.name + "-pilot") if args.pilot else ADAPTER_DIR
    config = SFTConfig(
        output_dir=str(OUT / ("checkpoints-pilot" if args.pilot else "checkpoints")),
        dataset_text_field="text",
        max_length=args.max_seq_length,
        packing=False,
        per_device_train_batch_size=4,
        gradient_accumulation_steps=4,
        per_device_eval_batch_size=4,
        num_train_epochs=2,
        max_steps=max_steps,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        optim="adamw_8bit",
        weight_decay=0.0,
        bf16=True,
        fp16=False,
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=100,
        save_strategy="steps",
        save_steps=100,
        save_total_limit=3,
        seed=SEED,
        data_seed=SEED,
        report_to=args.report_to,
    )
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=train_ds,
        eval_dataset=ds["val"],
        args=config,
        callbacks=[JsonlLogger(LOG_PATH)],
    )
    trainer = train_on_responses_only(
        trainer, instruction_part=INSTRUCTION_PART, response_part=RESPONSE_PART,
    )

    stats = trainer.train()
    metrics = trainer.evaluate()
    print(json.dumps({"train": stats.metrics, "eval": metrics}, indent=2))

    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"adapter saved: {adapter_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
