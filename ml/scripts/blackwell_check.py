"""Verify Blackwell (sm_120) capability + sdpa attention before training on 5090.

Run before any 5090 training operation. Fails loudly if the environment isn't
right — better than discovering it 4 hours into a QLoRA run.
"""

from __future__ import annotations

import sys


def main() -> int:
    ok = True

    try:
        import torch  # type: ignore
    except ImportError:
        print("FAIL: torch not installed in this environment")
        return 1

    print(f"  torch:        {torch.__version__}")
    print(f"  cuda built:   {torch.version.cuda}")

    if not torch.cuda.is_available():
        print("FAIL: torch.cuda.is_available() == False")
        return 1

    n = torch.cuda.device_count()
    print(f"  cuda devices: {n}")

    cap = torch.cuda.get_device_capability(0)
    name = torch.cuda.get_device_name(0)
    print(f"  device[0]:    {name}")
    print(f"  capability:   sm_{cap[0]}{cap[1]}")

    if cap != (12, 0):
        print(f"FAIL: expected (12, 0) for Blackwell 5090; got {cap}")
        ok = False

    # Confirm sdpa attention is settable on Gemma 4. We don't load the model
    # weights here (slow + GPU memory) — just touch the config.
    try:
        from transformers import AutoConfig  # type: ignore

        from chat_template import MODEL_ID

        cfg = AutoConfig.from_pretrained(MODEL_ID)
        cfg.attn_implementation = "sdpa"
        print(f"  sdpa attn:    settable on {MODEL_ID}")
    except Exception as e:
        print(f"FAIL: cannot set sdpa on {MODEL_ID!r}: {e!r}")
        ok = False

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
