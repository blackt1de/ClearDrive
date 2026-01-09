import httpx

OLLAMA_URL = "http://localhost:11434/api/generate"

async def ask_ollama(prompt: str) -> str:
    """Send a prompt to Ollama and get a response."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                OLLAMA_URL,
                json={
                    "model": "llama3:8b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 1500,
                    }
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "No response generated")
    except httpx.TimeoutException:
        return "ERROR: Request timed out. The model took too long to respond."
    except httpx.ConnectError:
        return "ERROR: Could not connect to Ollama. Make sure it's running (ollama serve)."
    except Exception as e:
        return f"ERROR: {str(e)}"


async def check_ollama() -> dict:
    """Check if Ollama is running and which models are available."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://localhost:11434/api/tags")
            response.raise_for_status()
            data = response.json()
            models = [m["name"] for m in data.get("models", [])]
            return {"status": "ok", "models": models}
    except Exception as e:
        return {"status": "error", "message": str(e)}