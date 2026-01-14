import os
import httpx

# Groq API configuration
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Available Groq models
# - llama-3.1-8b-instant: Fast, good for simple tasks
# - llama-3.3-70b-versatile: Best for complex reasoning
# - mixtral-8x7b-32768: Good balance
DEFAULT_MODEL = "llama-3.1-8b-instant"


async def ask_groq(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Send a prompt to Groq and get a response."""
    if not GROQ_API_KEY:
        return "ERROR: GROQ_API_KEY environment variable not set. Get your key at https://console.groq.com"

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": """You are ClearDrive, a friendly car diagnostic expert. CRITICAL RULES:
1. Follow the response format EXACTLY - use the EXACT section headers provided
2. Start your response with "SAFETY LEVEL:" then the content
3. NEVER use markdown formatting like ** or * or __
4. EVERY section must have meaningful content - no empty sections
5. If you don't have specific data for a section, provide general advice relevant to the vehicle
6. Be specific to this exact vehicle make/model/engine
7. Use plain English - explain technical terms in parentheses
8. For "WHAT'S HAPPENING" always start with "Your [vehicle] is showing code [code]..."
9. Include the KNOWN ISSUES section even if you have to provide general advice for this engine type"""
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.2,  # Even lower for strict format following
                    "max_tokens": 4000,  # Longer for detailed responses
                }
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            # Strip markdown bold/italic that won't render in the app
            content = content.replace("**", "").replace("__", "")
            content = content.replace("*", "").replace("_", "")
            return content
    except httpx.TimeoutException:
        return "ERROR: Request timed out. The model took too long to respond."
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return "ERROR: Invalid Groq API key. Check your GROQ_API_KEY environment variable."
        elif e.response.status_code == 429:
            return "ERROR: Rate limit exceeded. Please wait a moment and try again."
        else:
            return f"ERROR: HTTP {e.response.status_code}: {e.response.text}"
    except httpx.ConnectError:
        return "ERROR: Could not connect to Groq API. Check your internet connection."
    except Exception as e:
        return f"ERROR: {str(e)}"


async def check_groq() -> dict:
    """Check if Groq API is accessible and key is valid."""
    if not GROQ_API_KEY:
        return {"status": "error", "message": "GROQ_API_KEY not set"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": DEFAULT_MODEL,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 5,
                }
            )
            response.raise_for_status()
            return {"status": "ok", "model": DEFAULT_MODEL}
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return {"status": "error", "message": "Invalid API key"}
        return {"status": "error", "message": f"HTTP {e.response.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# Compatibility alias - so we can swap in place of ollama
ask_ollama = ask_groq
check_ollama = check_groq
