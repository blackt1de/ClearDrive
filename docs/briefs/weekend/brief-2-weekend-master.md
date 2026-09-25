# Brief 2: Weekend data-collection push (Fri Sep 25 to Sun Sep 27, 2026)

Executor: Claude Code. Phases 0 to 3 and 5 to 7 run from the ClearDrive repo root on the Windows box. Phase 1 also needs an SSH session to the A4500 over Tailscale. Phase 4 and Phase 6 run ON the 5090 (same Windows box, this repo). Companion files: `notes/briefs/brief-2a-eval-set-freeze.md` and `notes/briefs/brief-2c-training-data-distillation.md` (copy both in from the outputs Austin gives you before starting).
Architect: Claude Opus. Austin holds decision authority.

## Why this exists

WESEF submission is Dec 1. Four hypotheses. H3 (human comprehension study) is gated on IRB approval and runs later. H1, H2 and H4 all require: a frozen evaluation set, a pinned base Qwen model serving on the A4500, real vehicle captures, a fine-tuned Qwen, and both models scored on the same frozen set. None of that exists yet. It has to exist by Sunday night. Every phase below feeds the next. Do them in order.

## Turn-taking protocol (mandatory)

- Each phase ends with a commit, a push, and a report file at `notes/reports/<date>-phase-<n>.md` using that phase's template. Then STOP and print `PHASE <n> COMPLETE. AWAITING GO.`
- Do not start the next phase until Austin replies `GO <n+1>`.
- Phase 0 is a read-only scan. It changes nothing. It is the only phase that may not be skipped even if Austin says GO.
- If any step cannot be done as written, write `BLOCKED: <step> <reason>` in the report and stop. Do not improvise around it.

## Anti-hallucination rules (apply to every phase)

1. Never invent a path, hostname, port, model tag, env var name, or script name. Every one you use must appear in the Phase 0 report, a tool output, or this brief. If it is in none of those, run a command to discover it or stop.
2. Every command's output goes to `notes/reports/logs/<date>-phase-<n>.log` (`tee -a`). Reports cite the log line, never a paraphrase of what you think happened.
3. Verify before claiming. "Backend is up" means a curl returned 200 and the body is in the log. "Model loaded" means `ollama ps` shows it. "Tag exists" means `git tag` printed it.
4. Do not modify: `diagnostics.py`, `dtc_definitions.py`, `knowledge.py`, any prompt text, any file under `ios/`, anything under `research_scans/`, or anything under `eval/` after the freeze tag. Config files that select the model are the exception in Phase 1 and Phase 6.
5. Commit message format: `brief2/phase<n>: <one line>`. Branch: `brief-2-weekend`. Push after every phase.
6. When you are unsure, the answer is stop and ask, not guess.

---

## PHASE 0: Deep state scan (read-only, Friday, ~20 min)

Produce `notes/reports/<date>-phase-0.md` with EXACTLY these sections. Every bullet is a command output, quoted or summarized with the log line number. "Unknown" is an acceptable value. A guessed value is not.

### 0.1 Repo
- `git status`, `git branch -a`, `git log --oneline -25`, `git tag`, `git remote -v`
- Open PRs: `gh pr list --state all --limit 20`
- Tree: `find . -path ./.git -prune -o -path ./node_modules -prune -o -type f -print | grep -v -E "\.(pyc|png|jpg)$" | head -300`
- `cat CLAUDE.md`; `cat notes/decisions.md` (last 40 lines); `ls notes/ai-collab/ notes/briefs/ 2>/dev/null`
- Python entry points: `grep -rn "app = FastAPI\|@app.post\|@app.get\|@router" --include=*.py . | grep -v test`
- Model selection: `grep -rn -i "ollama\|OLLAMA_\|model_name\|MODEL=\|gemma\|qwen\|num_ctx\|sglang" --include=*.py --include=*.env* --include=*.toml --include=*.yaml --include=*.yml --include=*.json --include=Modelfile . | grep -v -E "node_modules|\.git/"` (list every file and line)
- Scan storage: `grep -rn -i "research_scans\|save_scan\|capture\|scan_id" --include=*.py . | head -50`; `ls research_scans/ | head; find research_scans -type f | wc -l`
- Fixtures: `ls fixtures/ tests/fixtures/ 2>/dev/null`; count
- Eval: `ls -R eval/ 2>/dev/null`; `git tag | grep -i eval`
- Training data: `ls data/ ml/ training/ 2>/dev/null`; `find . -iname "*.jsonl" -not -path "./.git/*" | xargs -I{} sh -c 'echo {}; wc -l {}'`
- known_issues: `python -c "import json;d=json.load(open('<path from tree>'));print(len(d))"` (find the path first)
- oem_verified count (find where the DTC tiers live; report the count per tier)
- Tests: `pytest -q 2>&1 | tail -5`

### 0.2 A4500 (over Tailscale)
- `tailscale status` on Windows; note the A4500 hostname/IP it prints
- `ssh <host> 'hostname; uptime; nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv'`
- `ssh <host> 'ollama --version; ollama list; ollama ps'`
- `ssh <host> 'systemctl list-units --type=service | grep -i -E "cleardrive|ollama|cloudflared|uvicorn|fastapi"'` and for each: `systemctl status <unit> --no-pager | head -12`
- `ssh <host> 'ps aux | grep -E "uvicorn|gunicorn|python.*main|cloudflared|sglang" | grep -v grep'`
- `ssh <host> 'ls ~/ClearDrive 2>/dev/null && cd ~/ClearDrive && git log --oneline -3 && git status --short'` (or wherever the deployed checkout is; find it from the service unit's WorkingDirectory)
- `ssh <host> 'curl -s localhost:11434/api/tags'`; `ssh <host> 'curl -s localhost:<backend port>/health'` (port from 0.1 or the unit file)
- `ssh <host> 'cat ~/.cloudflared/config.yml 2>/dev/null; cloudflared tunnel list 2>/dev/null'`
- Disk: `ssh <host> 'df -h / /home | tail -2'`

### 0.3 Public endpoint
- `nslookup api.cleardriveapp.com`
- `curl -s -o /dev/null -w "%{http_code}\n" https://api.cleardriveapp.com/health` (or whatever the health route is from 0.1)
- One scenario-mode diagnose call against the public URL using an existing fixture, full request and response in the log. Note latency.

### 0.4 iOS
- `ls ios/`; find the `.xcodeproj`/`.xcworkspace`; `grep -rn "cleardriveapp.com\|baseURL\|BASE_URL" ios/ | head`
- Report which URL the app is compiled to hit. Do NOT attempt to build (no Xcode here).

### 0.5 5090 / training environment (Windows, this box)
- `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv`
- `python -c "import torch;print(torch.__version__, torch.cuda.is_available(), torch.version.cuda)"`
- `pip show unsloth 2>&1 | head -3`; `pip show transformers peft bitsandbytes trl 2>&1 | grep -E "Name|Version"`
- `where ollama` / `ollama list` on Windows
- Free disk on the drive holding the repo and on the drive where HF models cache (`echo %HF_HOME%`)
- `echo %OPENROUTER_API_KEY%` presence only: print `SET` or `UNSET`, never the value

### 0.6 Delta against this brief
For each of the following, one line: TRUE / FALSE / UNKNOWN, with the evidence line:
- Backend on A4500 is running and reachable at api.cleardriveapp.com
- Ollama on A4500 currently serves Gemma (and which tag)
- A Qwen model is already present on the A4500
- An eval set exists; a freeze tag exists
- Training JSONL exists
- Unsloth imports cleanly on the 5090 with CUDA
- research_scans has any real (non-fixture, non-synthetic) captures
- The backend saves live scans to disk, and where

STOP. Print `PHASE 0 COMPLETE. AWAITING GO.`

---

## PHASE 1: Qwen on the A4500, backend serving it, phone-ready (Friday)

### 1.1 Pin the model
1. Decision rule, no discussion: the base model is `qwen3:14b` on Ollama (Qwen3-14B dense, standard attention) and `unsloth/Qwen3-14B` (or the official `Qwen/Qwen3-14B`) for training. Do NOT choose a Qwen3.5/3.6 (Gated DeltaNet) variant this weekend. If Phase 0 showed a different Qwen already deployed AND already downloaded on the 5090 AND `pip show unsloth` supports it, report that as an option and stop for Austin's call. Otherwise proceed with 14B.
2. Append to `notes/decisions.md`: date, `Base model pinned: Qwen3-14B dense (Ollama qwen3:14b; HF <exact repo>). Reason: standard attention, verified Unsloth QLoRA support, fits A4500 20GB at Q4_K_M with 8k ctx. Gemma 4 E4B was a placeholder and is retired from serving.`

### 1.2 Pull and configure on the A4500
1. `ssh <host> 'ollama pull qwen3:14b'` (log it; this is ~9 GB).
2. Create a Modelfile on the A4500 at `~/cleardrive-qwen.Modelfile`:
   ```
   FROM qwen3:14b
   PARAMETER num_ctx 8192
   PARAMETER temperature 0.2
   ```
   `ssh <host> 'ollama create cleardrive-qwen -f ~/cleardrive-qwen.Modelfile'`
3. `ssh <host> 'ollama run cleardrive-qwen "Reply with the single word READY" '` and log the reply.
4. Confirm VRAM after load: `ssh <host> 'ollama ps; nvidia-smi --query-gpu=memory.used --format=csv'`. If used > 18500 MiB, STOP and report.

### 1.3 Point the backend at it
1. Using the exact file and line from Phase 0.1 "Model selection", change the model name to `cleardrive-qwen`. One config change. If the model name is hardcoded in more than one place, change all of them and list each in the report. If it is set by env var in the systemd unit, edit the unit (`systemctl edit` or the EnvironmentFile) and `daemon-reload`.
2. Confirm the backend passes `num_ctx` explicitly on every Ollama call (grep `num_ctx` in the request builder). If it doesn't, the Modelfile above covers it, but write that fact in the report.
3. Deploy: on the A4500 checkout, `git fetch && git checkout brief-2-weekend && git pull` (after you have pushed the config change), then `systemctl restart <backend unit>`. Wait 10s. `systemctl status` + `journalctl -u <unit> -n 30 --no-pager` in the log.
4. Health: `curl -s localhost:<port>/health` on the A4500, then `curl -s https://api.cleardriveapp.com/health` from Windows. Both 200 or stop.
5. End-to-end: scenario-mode diagnose against `https://api.cleardriveapp.com` with the P0171 fixture and the P0301 fixture. Log full responses. Confirm the response was produced by `cleardrive-qwen` (check the backend log line or a model field in the response). Record latency for each.
6. If cloudflared was not running in Phase 0, `systemctl restart cloudflared`, re-check 1.3.4.

### 1.4 Live-scan storage check
1. From Phase 0.6, confirm the code path that stores a live (non-scenario) scan and the directory it writes to. If live scans are NOT persisted, add the minimum: on every non-scenario `/diagnose` request, write the raw request payload and the response to `research_scans/live/<YYYYMMDD-HHMMSS>-<vin_last6 or "novin">.json`. This is the only backend code change permitted this weekend. Keep it under 20 lines. Add one test.
2. Send one live-shaped request (no scenario field, a fixture payload) to the public URL and confirm a file appears in `research_scans/live/` on the A4500.

### 1.5 Report template
Model tag serving; VRAM after load; config lines changed; health URLs and codes; two end-to-end latencies; live-scan path confirmed; anything blocked.

STOP. Print `PHASE 1 COMPLETE. AWAITING GO.` Austin now installs the app on the phone and scans cars (Appendix A). Phase 2 can run in parallel.

---

## PHASE 2: Eval set build, freeze, base-condition run (Friday, overnight OK)

Execute `notes/briefs/brief-2a-eval-set-freeze.md` exactly as written, with these overrides:
- Step 9 must show `cleardrive-qwen` serving. If it shows anything else, STOP.
- The baseline run in step 12 IS the H1 base-Qwen condition. Name the run `base-qwen3-14b-<date>`, not `baseline-<date>`.
- Also run the rule-based arm in step 11 and record it as run `rulebased-<date>`.
- Include the V70 as a reconstructed case ONLY IF Austin has placed the confirmed-repair note in `research_scans/live/README-v70.md` before step 8 (freeze). Otherwise leave it out; it goes into the replay-validity real arm instead.

Report per 2a step 15. STOP. Print `PHASE 2 COMPLETE. AWAITING GO.`

---

## PHASE 3: Real-capture intake (after Austin's scans land, Friday night or Saturday morning)

1. `ls -la research_scans/live/` on the A4500; `rsync` or `scp` the directory to the repo on Windows under `research_scans/live/`. Never delete the A4500 copy.
2. Write `scripts/capture_manifest.py`: for each file, extract vehicle (VIN last 6, year/make/model if decoded), DTC list, PID count, timestamp, and whether the response was ok/caution/stop/insufficient. Output `research_scans/live/MANIFEST.csv`. Commit.
3. Validate: at least 3 distinct vehicles, at least 5 files each. The V70 must have at least one file with P0305 present and, if the coil was swapped, at least one later file without it. Report any shortfall; do not fabricate.
4. Replay-validity real arm: for each real capture, build the matching synthetic fixture the way the pilot did (same vehicle facts, same DTCs, synthetic live data), run both through the backend in scenario mode, and score with the pilot's existing rubric script (find it in PR #18). Strip arm labels from filenames before scoring (name them `A-<n>` and `B-<n>`, keep the key in a separate file). Write `research_scans/replay_validity/real_arm_results.md` with pass/fail against the pre-registered criteria.

STOP. Print `PHASE 3 COMPLETE. AWAITING GO.`

---

## PHASE 4: 5090 training environment (Friday night, parallel with Phase 2)

1. `pip install -U unsloth` (or per Unsloth's current Windows/Blackwell instructions; log the exact command used and the doc URL you followed). If Phase 0 showed a working install, skip.
2. Smoke: a 15-line script `ml/smoke_load.py` that loads the pinned HF repo via `FastLanguageModel.from_pretrained(..., load_in_4bit=True, max_seq_length=4096)` and prints model name, dtype, and `torch.cuda.memory_allocated()/1e9`. Run it. Log output. If it fails, try the `unsloth/` mirror of the same model, then STOP if still failing.
3. Write `ml/train_qlora.py` (do not run): Unsloth QLoRA, r=16, alpha=32, dropout=0.05, target all linear proj layers, lr 2e-4, cosine, warmup 3%, 2 epochs, batch 4, grad accum 4, max_seq_length 4096, bf16, train on `data/train/train.jsonl`, eval on `val.jsonl` every 100 steps, save adapter to `ml/out/cleardrive-qwen-lora/`, log to `ml/out/train_log.jsonl`. Chat template = the model's own. Mask the prompt (train on assistant turn only). Seed 42.
4. Write `ml/merge_and_export.py` (do not run): merge adapter into base in bf16, save to `ml/out/cleardrive-qwen-merged/`, export GGUF Q4_K_M via Unsloth's `save_pretrained_gguf`, output path `ml/out/cleardrive-qwen-Q4_K_M.gguf`.
5. Commit both scripts. Report: Unsloth version, smoke output, VRAM at load, disk free.

STOP. Print `PHASE 4 COMPLETE. AWAITING GO.`

---

## PHASE 5: Training data distillation (Friday night, overnight)

Requires tag `eval-v1-frozen` (Phase 2 step 8). Execute `notes/briefs/brief-2c-training-data-distillation.md` exactly as written. Report per its step 8.

STOP. Print `PHASE 5 COMPLETE. AWAITING GO.`

---

## PHASE 6: QLoRA, merge, serve, touch two (Saturday)

1. Pre-flight: `data/train/MANIFEST.json` hashes match the files; `train.jsonl` between 3000 and 5000 lines; `git tag | grep eval-v1-frozen`.
2. Run `python ml/train_qlora.py 2>&1 | tee ml/out/train_stdout.log`. Expected wall time on a 5090 for 4k pairs, 2 epochs, 14B 4-bit: roughly 1.5 to 3 hours. If loss is NaN or not decreasing after 200 steps, STOP and report.
3. Run `python ml/merge_and_export.py`. Confirm the GGUF exists and its size (~9 GB).
4. `scp` the GGUF to the A4500 (`~/models/`). Modelfile `~/cleardrive-qwen-ft.Modelfile`:
   ```
   FROM ~/models/cleardrive-qwen-Q4_K_M.gguf
   PARAMETER num_ctx 8192
   PARAMETER temperature 0.2
   ```
   `ollama create cleardrive-qwen-ft -f ...`; `ollama run cleardrive-qwen-ft "Reply READY"`; `ollama ps`.
5. Switch the backend config (same lines as Phase 1.3) to `cleardrive-qwen-ft`. Restart. Health. One scenario call. Log which model answered.
6. Touch two: `python scripts/eval_run.py` with run_id `ft-qwen3-14b-<date>`. Then `scripts/eval_score.py`. This is the second and final run of the frozen set. The base run was touch one.
7. Codeless set (H4) runs inside eval_run.py in both touches; confirm hit rate appears in both scores files.
8. Commit run outputs. Report: training loss start/end, eval loss, wall time, GGUF size, VRAM serving, macro-F1 base vs ft vs rule-based, H4 hit rate base vs ft, latency both.

STOP. Print `PHASE 6 COMPLETE. AWAITING GO.`

---

## PHASE 7: H2 judge, results, package (Sunday)

1. Blinding: `scripts/h2_blind.py` takes `h2_pending.jsonl` from all three runs (base, ft, rule-based), assigns random IDs, writes `eval/h2/blinded.jsonl` and `eval/h2/key.json` (key committed but not read by the judge step).
2. Judge: Opus via OpenRouter, the H2 rubric text from the repo verbatim (find it; if there are two versions, STOP and ask which), temperature 0, one call per item, output score per rubric line + total. Save raw judge outputs.
3. Unblind, aggregate: mean rubric score per condition, per-item table, and a paired comparison (same case, base vs ft). `eval/h2/results.md`.
4. `results/results.md`: one table per hypothesis with the pre-registered criterion in the left column and the measured value in the right. H3 row says "pending IRB". Replay-validity real-arm result included.
5. Export the three H3 stimulus texts (the three scenarios rendered as raw DTC only / base output / ft output) to `h3/stimuli/` so Austin can paste them into the three Google Forms and attach to Form 4.
6. Commit, push, open a PR `brief-2-weekend` → main with the results.md in the description.

STOP. Print `PHASE 7 COMPLETE.`

---

## Appendix A: Human procedure, scanning the cars (Austin, Friday afternoon)

Getting the app on the phone (TestFlight build is expired):
1. On the Mac: open the Xcode project, plug the iPhone in, select it as the run target, Signing & Capabilities → Team = your personal Apple ID. Run. A personal-team build lasts 7 days, which is enough. If the phone says "Untrusted Developer", Settings → General → VPN & Device Management → trust.
2. Confirm the app's base URL is `https://api.cleardriveapp.com` (Phase 0.4 says what it's compiled to). If it isn't, change the one constant and re-run.
3. Before going to the cars, on Wi-Fi, run one scenario/demo diagnose from the app and confirm a response comes back. Phase 1 must be COMPLETE first.

Per car, in this order:
1. Adapter in the OBD port (driver's footwell). Engine running, warmed up (coolant ≥ 80°C on the app's readout or 10 min of idle).
2. Do NOT clear any codes before scanning.
3. Scan 1. Wait 60 seconds. Scan 2 through 5. Same procedure. Five scans per car.
4. Do not touch settings between scans. If a scan fails, note it and redo; don't count it.
5. After the five: write the car into `research_scans/live/README-<car>.md`: year, make, model, engine, mileage, VIN last 6, what's known to be wrong with it, and how you know.

The V70 (cylinder 5 misfire):
1. Scan five times WITH the P0305 active, per above.
2. Swap the coil. Clear codes. Drive 10 minutes, mixed speeds.
3. Scan five more times. Note whether P0305 is absent, pending, or back.
4. In `README-v70.md` write: `Confirmed repair: ignition coil, cylinder 5. Pre-repair scans: <files>. Post-repair scans: <files>. P0305 status post-repair: <absent/pending/present>.` This line is what makes it a labeled ground-truth case.

Each scan lands on the A4500 automatically (Phase 1.4). You don't need to save anything on the phone. When all three cars are done, tell Claude Code `GO 3`.
