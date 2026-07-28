import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

# override=True so local .env wins over stale OS env vars during dev.
# Production deploys don't ship a .env file, so override is a no-op there.
load_dotenv(Path(__file__).parent / ".env", override=True)

# OLLAMA_HOST may be a bare hostname/IP or `host:port`. Defaults to the
# A4500 over Tailscale (dev). Production should override via env to a
# Cloudflare Tunnel hostname (or wherever the A4500 is exposed).
_raw_host = os.environ.get("OLLAMA_HOST", "100.100.254.15")
if ":" in _raw_host:
    OLLAMA_HOST, _port_str = _raw_host.rsplit(":", 1)
    OLLAMA_PORT = int(_port_str)
else:
    OLLAMA_HOST = _raw_host
    OLLAMA_PORT = int(os.environ.get("OLLAMA_PORT", "11434"))

OLLAMA_BASE = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
OLLAMA_CHAT_URL = f"{OLLAMA_BASE}/api/chat"
OLLAMA_TAGS_URL = f"{OLLAMA_BASE}/api/tags"

DEFAULT_MODEL = "gemma4:e4b"

# NOTE: rules 5 and 9 of the previous version told the model to invent content
# for any section it lacked data for ("provide general advice", "even if you have
# to provide general advice for this engine type"). That is the same gap-filling
# defect removed from main.py's prompt, hiding one file further out — it silently
# overrode the user prompt's instruction to report missing evidence honestly.
SYSTEM_PROMPT = """You are ClearDrive, a car diagnostic expert writing for a driver who does not know cars.

OUTPUT RULES:
1. Reply with ONLY the sections listed in the user message, each introduced by its
   exact header in capitals followed by a colon, in the order given.
2. Your first line must be exactly: SAFETY LEVEL: followed by SAFE, CAUTION, or STOP.
3. No preamble, no disclaimer, no safety warning, no closing note, no "[End of Report]".
   Do not invent section headers of your own.
4. Never use markdown formatting such as **, *, __ or #.
5. Plain English. Explain any technical term in parentheses the first time it appears.

EVIDENCE RULES — these outrank everything above:
6. Reason only over evidence supplied in the user message. Never state a fact about
   this vehicle from your own knowledge: no known issues, recalls, service bulletins,
   failure patterns, or maintenance specifications.
7. Never invent content to fill a section. If the evidence for a section is absent,
   say plainly that it was not available and what would be needed. An honest gap is
   correct output, not a failure.
8. Never state a number that does not appear in the user message."""


async def ask_ollama(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Send a prompt to Ollama (Gemma 4 E4B on the A4500) and get a response.

    Uses /api/chat (not /api/generate) — Gemma 4 is chat-trained, and
    /api/generate returns an empty response field for chat-trained models
    in Ollama 0.24.
    """
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                OLLAMA_CHAT_URL,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 1600,
                        # num_ctx MUST be set explicitly. Ollama defaults it to
                        # 4096, and the payload-v2 prompt (vehicle context +
                        # tiered code definitions + computed differential +
                        # retrieved NHTSA material) is around 4,000 tokens on
                        # its own. At the default the prompt was silently
                        # truncated, taking the response-format instructions out
                        # of the window — which is why the model first invented
                        # its own structure and then degenerated into a loop.
                        "num_ctx": 16384,
                        # Degeneracy control. num_predict was 4000, a long leash
                        # for a small model; 1600 is comfortably above the
                        # longest well-formed response observed.
                        "repeat_penalty": 1.15,
                        "repeat_last_n": 256,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("message", {}).get("content", "No response generated")
            # Strip markdown bold/italic that won't render in the app
            content = content.replace("**", "").replace("__", "")
            content = content.replace("*", "").replace("_", "")
            return content
    except httpx.TimeoutException:
        return "ERROR: Request timed out. The model took too long to respond."
    except httpx.ConnectError:
        return f"ERROR: Could not connect to Ollama at {OLLAMA_HOST}:{OLLAMA_PORT}."
    except Exception as e:
        return f"ERROR: {str(e)}"


async def check_ollama() -> dict:
    """Check if Ollama is running and which models are available."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(OLLAMA_TAGS_URL)
            response.raise_for_status()
            data = response.json()
            models = [m["name"] for m in data.get("models", [])]
            return {"status": "ok", "models": models, "host": OLLAMA_HOST}
    except Exception as e:
        return {"status": "error", "message": str(e)}
