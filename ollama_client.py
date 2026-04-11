import httpx

OLLAMA_HOST = "192.168.1.182"
OLLAMA_PORT = 11434
OLLAMA_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/generate"
OLLAMA_TAGS_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/tags"

DEFAULT_MODEL = "gemma4:e4b"


async def ask_ollama(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Send a prompt to Ollama (Gemma 4 E4B on local GPU) and get a response."""
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                OLLAMA_URL,
                json={
                    "model": model,
                    "prompt": prompt,
                    "system": """You are ClearDrive, a friendly car diagnostic expert. CRITICAL RULES:
1. Follow the response format EXACTLY - use the EXACT section headers provided
2. Start your response with "SAFETY LEVEL:" then the content
3. NEVER use markdown formatting like ** or * or __
4. EVERY section must have meaningful content - no empty sections
5. If you don't have specific data for a section, provide general advice relevant to the vehicle
6. Be specific to this exact vehicle make/model/engine
7. Use plain English - explain technical terms in parentheses
8. For "WHAT'S HAPPENING" always start with "Your [vehicle] is showing code [code]..."
9. Include the KNOWN ISSUES section even if you have to provide general advice for this engine type""",
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 4000,
                    }
                }
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("response", "No response generated")
            # Strip markdown bold/italic that won't render in the app
            content = content.replace("**", "").replace("__", "")
            content = content.replace("*", "").replace("_", "")
            return content
    except httpx.TimeoutException:
        return "ERROR: Request timed out. The model took too long to respond."
    except httpx.ConnectError:
        return f"ERROR: Could not connect to Ollama at {OLLAMA_HOST}:{OLLAMA_PORT}. Make sure Ollama is running on your PC."
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
