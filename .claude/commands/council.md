---
description: Convene the 5-member strategic council on an artifact or decision. Spawns Contrarian, Executor, Expansionist, First Principles, and Outsider in parallel, then synthesizes their responses to disk.
argument-hint: "<question or path to artifact>"
---

# /council

You are about to convene the ClearDrive Council on the following question or artifact:

**$ARGUMENTS**

---

## Step 1 · Verify scope

Is this question council-worthy? The council exists for **strategic decisions with non-trivial cost of being wrong**. Convene only for:

- Major artifact reviews (research plan revisions, model card drafts, paper sections, the final WESEF deck)
- Irreversible or expensive decisions (hyperparameter commits, deployment target choice, comprehension study design)
- Pre-mortems before multi-day work (before a full QLoRA run, before a submission)
- Periodic project health checks (every 3–4 weeks)

**Do NOT convene for:**
- Quick clarifications or factual questions
- Execution tasks ("write the train.py")
- Bug fixes or routine engineering decisions
- Anything where you can't imagine being moved by what the council says

If the question doesn't meet the bar, decline. Tell Austin that this is a regular ask, not a council ask, and answer it directly without spawning agents. The council should feel like requesting a meeting, not pulling a lever.

## Step 2 · Prepare the brief

Restate the question or artifact in a form each council member can act on. One paragraph of context, then the specific question. Include relevant file paths or excerpts for the four context-aware members.

**Outsider gets a different brief: artifact content only, no file paths, no "the project context is..." preamble. Outsider's value is starting cold.**

## Step 3 · Spawn 5 parallel Agent calls

In a single message, spawn all five subagents in parallel:

- `Agent(subagent_type="contrarian", prompt=<full brief with project context>)`
- `Agent(subagent_type="executor", prompt=<full brief with project context>)`
- `Agent(subagent_type="expansionist", prompt=<full brief with project context>)`
- `Agent(subagent_type="first-principles", prompt=<full brief with project context>)`
- `Agent(subagent_type="outsider", prompt=<artifact only, no project context>)`

Parallel matters. Sequential would let later members anchor on earlier outputs, defeating the independence.

## Step 4 · Collect responses

Each returns its structured output independently. Read all 5 before synthesizing.

## Step 5 · Synthesize

Produce a verdict with these sections:

- **Convergent points** — where 3+ members reached the same conclusion. *Treat as lower signal — possibly shared model bias rather than truth.*
- **Disagreements** — where members reached different conclusions. *Treat as higher signal — examine the substance.*
- **Unique contributions** — what each member surfaced that the others didn't
- **Recommended decision** — your own synthesis with reasoning
- **Open questions for Austin or Makarov** — anything unresolved

Be explicit that the recommended decision is decision-support, not the decision itself. Austin decides.

## Step 6 · Write the verdict to disk

Save the full session to:

```
notes/council/decisions/YYYY-MM-DD--<topic-slug>.md
```

With this structure:

```markdown
# Council Session · YYYY-MM-DD · <Topic>

## Question / Artifact
<original question or artifact reference>

## Brief sent to context-aware members
<the brief>

## Brief sent to Outsider
<the cold brief>

---

## Contrarian
<verbatim response>

## Executor
<verbatim response>

## Expansionist
<verbatim response>

## First Principles
<verbatim response>

## Outsider
<verbatim response>

---

## Synthesis
<convergent / disagreements / unique / recommended decision>

## Austin's decision
<left blank for Austin to fill in>

## Follow-up tasks
- ...
```

If `notes/council/decisions/` doesn't exist yet, create it.

## Step 7 · Surface the verdict in chat

Present the synthesis to Austin in the conversation. Link to the saved decision file. Stop. Do not press for an immediate decision.

---

## Calibration reminders for synthesis

- The 5 personas share the same underlying model. Convergent agreement may reflect shared bias rather than truth. Real disagreement is the valuable signal.
- Outsider's "I don't understand X" is a finding about the artifact, not a question for you to answer.
- Contrarian will sometimes attack reasonable plans. Test critiques by asking what specifically would be observed if the failure mode were real. If the answer is hand-wavy, the critique is theater.
- Executor under-weights risk by design. Cross-check timelines against Contrarian.
- Expansionist will sometimes go too wide. Filter to what serves the WESEF arc.
- First Principles will sometimes recommend tearing down work that's already paid for. Balance against the time budget.
- **Makarov is the human check no council can replace.** When an open question genuinely needs the mentor, flag it explicitly.

## Individual invocation

Council members are individually invokable when a full session would be overkill:

```
Agent(subagent_type="executor", prompt="Gut-check this timeline: ...")
```

This is the right tool for "hey one persona, quick read" instead of convening the full five.
