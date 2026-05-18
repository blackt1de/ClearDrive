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

SYSTEM_PROMPT = """You are ClearDrive, a friendly car diagnostic expert. CRITICAL RULES:
1. Follow the response format EXACTLY - use the EXACT section headers provided
2. Start your response with "SAFETY LEVEL:" then the content
3. NEVER use markdown formatting like ** or * or __
4. EVERY section must have meaningful content - no empty sections
5. If you don't have specific data for a section, provide general advice relevant to the vehicle
6. Be specific to this exact vehicle make/model/engine
7. Use plain English - explain technical terms in parentheses
8. For "WHAT'S HAPPENING" always start with "Your [vehicle] is showing code [code]..."
9. Include the KNOWN ISSUES section even if you have to provide general advice for this engine type"""


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
                        "num_predict": 4000,
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
