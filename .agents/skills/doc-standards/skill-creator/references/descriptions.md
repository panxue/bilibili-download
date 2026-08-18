# Optimizing skill descriptions

Source: https://agentskills.io/skill-creation/optimizing-descriptions (snapshot 2026-07)

## How triggering works

At startup agents load only each skill's `name` + `description`. A task
matches a description → the agent loads the full SKILL.md. The description
carries the entire burden of triggering.

Agents typically only consult skills for tasks needing knowledge beyond basic
tool use. One-step requests ("read this PDF") may not trigger even a matching
skill. Specialized knowledge, domain workflows, and uncommon formats are where
descriptions matter.

## Writing effective descriptions

- **Imperative phrasing**: "Use this skill when..." rather than "This skill
  does..."
- **Focus on user intent, not implementation**: what the user is trying to
  achieve, not internal mechanics.
- **Err on the side of being pushy**: list contexts explicitly, including
  cases where the user doesn't name the domain ("even if they don't mention
  'CSV' or 'analysis'").
- **Keep it concise**: a few sentences to a short paragraph; ≤1024 chars hard
  limit.

## Designing trigger eval queries

~20 queries: 8–10 should-trigger, 8–10 should-not-trigger.

```json
[
  { "query": "I've got a spreadsheet in ~/data/q4_results.xlsx with revenue in col C and expenses in col D — can you add a profit margin column and highlight anything under 10%?", "should_trigger": true },
  { "query": "whats the quickest way to convert this json file to yaml", "should_trigger": false }
]
```

### Should-trigger: vary the axes

- Phrasing: formal, casual, typos, abbreviations.
- Explicitness: some name the domain ("analyze this CSV"), others describe the
  need without naming it ("my boss wants a chart from this data file").
- Detail: terse prompts vs context-heavy ones (paths, column names, backstory).
- Complexity: single-step vs multi-step workflows.

The most useful should-triggers are where the connection isn't obvious from
the query — that's where description wording decides.

### Should-not-trigger: near-misses

The most valuable negatives share keywords but need something different:

- Weak: "Write a fibonacci function", "What's the weather today?" — no overlap.
- Strong: "I need to update the formulas in my Excel budget spreadsheet"
  (spreadsheet editing, not CSV analysis); "write a python script that reads a
  csv and uploads each row to our postgres database" (ETL, not analysis).

### Tips for realism

Include file paths, personal context ("my manager asked me to..."), specific
details (column names, values), casual language, and occasional typos.

## Testing whether a description triggers

Run each query through the agent with the skill installed; check logs for
whether the skill's SKILL.md was loaded. A query passes if trigger outcome
matches `should_trigger`.

Model behavior is nondeterministic: run each query 3× and compute a trigger
rate. Pass if rate ≥ 0.5 (default threshold). For ~20 queries × 3 runs, script
it. Stop a run early once the outcome is clear (consulted the skill or not).

## Avoid overfitting: train/validation splits

- **Train set (~60%)**: used to identify failures and guide improvements.
- **Validation set (~40%)**: set aside, used only to check generalization.
- Both proportional in should-trigger/not mix; shuffle randomly; keep the split
  fixed across iterations.

## The optimization loop

1. **Evaluate** current description on train AND validation sets.
2. **Identify failures** in the train set only: which should-triggers didn't
   trigger? Which should-not-triggers did?
3. **Revise the description**, generalizing:
   - Undertriggering → too narrow: broaden scope, add context about when it's
     useful.
   - Overtriggering → too broad: add specificity about what it does *not* do,
     or clarify the boundary with adjacent capabilities.
   - Avoid adding keywords from specific failed queries (overfitting) — find
     the general category they represent.
   - Stuck? Try a structurally different framing.
   - Keep it ≤1024 chars.
4. **Repeat** until all train queries pass or progress stops (5 iterations is
   usually enough).
5. **Select the best iteration by validation pass rate** — the best may be an
   earlier iteration, not the last.

## Example

```yaml
# Before
description: Process CSV files.

# After
description: >
  Analyze CSV and tabular data files — compute summary statistics,
  add derived columns, generate charts, and clean messy data. Use this
  skill when the user has a CSV, TSV, or Excel file and wants to
  explore, transform, or visualize the data, even if they don't
  explicitly mention "CSV" or "analysis."
```

More specific about what it does, broader about when it applies.

## Applying the result

1. Update the `description` in SKILL.md frontmatter.
2. Verify ≤1024 chars.
3. Sanity-check with a few manual prompts, then 5–10 fresh queries never used
   in optimization for an honest generalization check.
