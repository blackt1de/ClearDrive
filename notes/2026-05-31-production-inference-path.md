# Production Inference Path Verification - 2026-05-31

Read-only investigation requested alongside the Qwen SKU fit check.

## Verdict

The live public backend is currently:

```text
https://api.cleardriveapp.com
  -> FastAPI /health
  -> local Ollama host
  -> model: gemma4:e4b
```

This is **not** SGLang/Qwen yet. It is also not Groq/Llama according to the public health response.

## Evidence

### Public production health

Command:

```powershell
Invoke-RestMethod -Uri 'https://api.cleardriveapp.com/health' -TimeoutSec 20
```

Response:

```json
{
  "status": "ok",
  "ai": {
    "status": "ok",
    "models": [
      "gemma4:e4b"
    ],
    "host": "localhost"
  }
}
```

Interpretation: production FastAPI can reach a local LLM service and sees Ollama model `gemma4:e4b`. The `host: localhost` value matches the current `AGENTS.md` production topology: FastAPI and Ollama on the same A4500 box.

### Tailscale/dev direct checks

Commands:

```powershell
Invoke-RestMethod -Uri 'http://100.100.254.15:8000/health' -TimeoutSec 8
Invoke-RestMethod -Uri 'http://100.100.254.15:11434/api/tags' -TimeoutSec 8
```

Both timed out from this Windows/Codex session.

Interpretation: the public Cloudflare path is reachable, but direct Tailscale access from this session is not currently usable. This does not contradict the public health response; it only means I could not verify the private path from here.

### SSH check

Command:

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=8 ajb1ubuntu 'hostname && systemctl is-active cleardrive ollama cloudflared'
```

Result:

```text
ssh: Could not resolve hostname ajb1ubuntu: No such host is known.
```

Interpretation: no local SSH alias for `ajb1ubuntu` is available in this Windows session. I did not attempt any destructive or configuration-changing operation.

## Local code evidence

Relevant local code state:

- `main.py` imports `ask_ollama` and `check_ollama` from `ollama_client.py`.
- `ollama_client.py` uses model `gemma4:e4b`.
- `ollama_client.py` talks to Ollama `/api/chat` and `/api/tags`.
- No live code evidence found for Groq as the active production LLM path.

## Migration implication

The v0.2 target architecture says the future target is SGLang + Qwen, but current production is still Ollama + Gemma E4B. The migration risk is therefore a real service migration:

1. Stand up SGLang separately on the A4500.
2. Keep Ollama/Gemma as the rollback path until SGLang health and endpoint compatibility are measured.
3. Replace the backend LLM client only after the model SKU is pinned and a serving load test passes.

## Open blockers

- SSH alias or direct host details for A4500 from this Windows session.
- Direct Tailscale reachability to `100.100.254.15`.
- Confirmation of exact systemd unit state on the A4500, since public `/health` is the only successful live probe in this pass.
