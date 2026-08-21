# A4500 server sanity check — 2026-08-21

One-time check of what is actually serving, run on `ajb1ubuntu` (the A4500 itself).

| Fact | Measured |
|---|---|
| Serving | **Ollama** (`ollama.service` active, drop-in override present). No SGLang process. `gemma4:e4b` and `qwen3:14b-q4_K_M` loaded; `/health` reports `gemma4:e4b` in use. |
| Context window | `ollama_client.py:86` sets `"num_ctx": 16384` explicitly; `num_predict` 2800. ≥ 8192 requirement met. |
| GPU | RTX A4500, 10,487 / 20,470 MiB resident at idle. During one `/interpret` request: **91–93 % utilisation, ~198 W**; back to 0 % / 53 W within 2 s of completion. Inference is on the GPU. |
| Latency | Full sweep of 11 fixtures, mean 13.6 s per `/interpret` (range 9.7–21.1 s), measured with `scripts/smoke_run.py`. |

## Production checkout is stale

`cleardrive.service` runs uvicorn from `/home/abrennan/cleardrive`, which is at
**18cd60c (PR #7)** — behind `origin/main` (a6469c8, PR #12) and without Brief 1b.
Its local `main` has not been fetched since. The smoke sweep above was therefore
run against a dev server started from the Brief 1b/1c checkout on `:8001`, not
against `:8000`. Deploy per CLAUDE.md (`git pull && sudo systemctl restart
cleardrive`) once 1b is merged; `:8000` will not return `safety` until then.

## GitHub access from this box

The SSH key and `gh` login on `ajb1ubuntu` are `conorpbrennan`, which has
pull-only access to `blackt1de/ClearDrive` and a fine-grained PAT that cannot
fork or open PRs. Branches `brief-1b-safety-verdict` and `brief-1c-smoke-runner`
exist locally only until that is resolved.
