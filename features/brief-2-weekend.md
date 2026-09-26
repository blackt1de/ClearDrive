# Brief 2 Weekend

**Requirement**: By Sunday 2026-09-27: pin base Qwen3-14B serving on the A4500, freeze the eval set, capture real vehicles, fine-tune Qwen, and score base vs fine-tuned vs rule-based on the frozen set for H1, H2 and H4.

**Started**: 2026-09-25
**Last updated**: 2026-09-26
**Branch**: brief-2-weekend

## Files involved

- .gitignore
- eval/MANIFEST.json
- eval/codeless_set.json
- eval/composition.md
- eval/eval_set.json
- eval/schema.json
- eval/sources/adjudication.json
- eval/sources/recalls.json
- eval/taxonomy.json
- knowledge.py
- main.py
- notes/decisions.md
- ollama_client.py
- scripts/eval_build.py
- scripts/eval_run.py
- scripts/eval_score.py
- scripts/eval_validate.py
- test_diagnostics.py
- test_eval_case.py
- test_eval_scripts.py
- test_knowledge.py

## History

- 2026-09-26 `bed0615` — brief2/phase2: eval runner and scorer; backend model timeout 300 s
  - .gitignore
  - notes/decisions.md
  - ollama_client.py
  - scripts/eval_run.py
  - scripts/eval_score.py
  - test_eval_scripts.py

- 2026-09-26 `aa308a1` — brief2/phase2: freeze eval-v1 (102 cases, 30 codeless profiles)
  - eval/MANIFEST.json
  - eval/codeless_set.json
  - eval/composition.md
  - eval/eval_set.json
  - eval/schema.json
  - eval/sources/adjudication.json
  - eval/sources/recalls.json
  - eval/taxonomy.json
  - notes/decisions.md
  - scripts/eval_build.py
  - scripts/eval_validate.py
  - test_eval_scripts.py

- 2026-09-26 `5cfd3bf` — brief2/phase2: eval_case transport and CLEARDRIVE_THINK serving switch
  - main.py
  - notes/decisions.md
  - ollama_client.py
  - test_eval_case.py

- 2026-09-26 `f0cbd39` — brief2/phase2: pre-freeze fixes: NHTSA name resolution, num_predict 4096, finish_reason
  - knowledge.py
  - main.py
  - notes/decisions.md
  - ollama_client.py
  - test_diagnostics.py
  - test_knowledge.py

- 2026-09-25 `cad6465` — brief2/phase1: serve cleardrive-qwen; label research scans qwen3-14b-base
  - main.py
  - notes/decisions.md
  - ollama_client.py
  - test_diagnostics.py
