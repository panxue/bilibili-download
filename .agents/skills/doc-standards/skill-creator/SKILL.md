---
name: skill-creator
description: Create, edit, audit, and optimize Agent Skills (SKILL.md) per the Agent Skills spec (agentskills.io). Use when the user wants to create a new skill, improve or refactor an existing SKILL.md, check a skill's frontmatter or directory layout for spec compliance, split a large SKILL.md into references, or tune a skill's description for better triggering. Applies whenever the user mentions skills, SKILL.md, agent skills, or spec compliance for skills, even if they don't say "skill" explicitly.
metadata:
  sources: "https://agentskills.io/specification | https://agentskills.io/skill-creation/best-practices | https://agentskills.io/skill-creation/optimizing-descriptions | https://agentskills.io/skill-creation/using-scripts"
  spec-snapshot: "2026-07"
---

# Skill Creator

A skill for designing Agent Skills that comply with the Agent Skills spec
(agentskills.io). It walks through the format rules, a creation workflow, and
the patterns that make skills trigger reliably and act effectively.

If the user's question is about *which spec governs a file* (e.g. AGENTS.md vs
skills), see the `doc-standards` skill instead. This skill owns the *skill*
part of the docs standards.

## Workflow

Follow this loop, but stay flexible — jump in wherever the user is:

1. **Capture intent.** What should the skill enable the agent to do? When
   should it trigger (phrases/contexts)? What is the expected output format?
   If the conversation already contains a workflow the user wants to capture,
   extract the steps, tools, and corrections from history first.
2. **Research before writing.** Ask about edge cases, input/output formats,
   example files, dependencies, and success criteria. Check the user's own
   source material (runbooks, code, existing conventions) rather than writing
   from generic knowledge alone.
3. **Draft the skill** following the format rules and patterns below.
4. **Validate** the result (frontmatter, naming, structure — see Audit below).
5. **Iterate** with the user until they are satisfied. Run a few realistic test
   prompts through an agent with access to the skill and review the outputs
   together before refining.
6. **Offer description optimization** as a final step if triggering matters.

## Format rules (the spec)

- A skill is a directory containing `SKILL.md` (uppercase, exact name) plus
  optional `scripts/`, `references/`, `assets/`.
- **`name`** (required): ≤64 chars; lowercase `a-z0-9` + hyphens only; no
  leading/trailing/consecutive hyphens; **must equal the parent directory
  name**.
- **`description`** (required): 1–1024 chars; states *what* the skill does AND
  *when* to use it; include trigger keywords. This is the only thing agents
  see before deciding to load the skill — write it to be found.
- **`license`** / **`compatibility`** (≤500 chars) / **`metadata`** (string→string
  map) / **`allowed-tools`**: optional. Include `compatibility` only when there
  are real environment requirements.

Full field table and examples: [references/spec.md](references/spec.md).

## Progressive disclosure

Agents load skills in three stages. Structure the skill to match:

1. **Metadata** (~100 tokens, always loaded): `name` + `description`.
2. **SKILL.md body** (loaded on activation): keep under **500 lines** / ~5,000
   tokens. Only what is needed on every run.
3. **Resources** (loaded on demand): `references/`, `scripts/`, `assets/`.

Rules of thumb:

- If SKILL.md is approaching 500 lines, move detail into `references/` and tell
  the agent *when* to read each file ("Read `references/api-errors.md` if the
  API returns a non-200"). A generic "see references/" pointer is weak.
- Keep file references relative to the skill root and at most one level deep —
  no nested reference chains.
- For skills spanning multiple domains/frameworks, split by variant
  (`references/aws.md`, `references/gcp.md`, ...) with a selection step in
  SKILL.md.

## Writing good instructions

- **Add what the agent lacks; omit what it knows.** Don't explain what a PDF
  is — say which library to use and the non-obvious edge cases. Ask of each
  line: "Would the agent get this wrong without it?" If no, cut it.
- **Match specificity to fragility.** Give freedom where approaches vary;
  be prescriptive where sequence or consistency matters (exact commands,
  required flags). Explain the *why* behind directives instead of stacking
  "ALWAYS/NEVER" — modern agents generalize better from understanding.
- **Provide defaults, not menus.** Pick one default tool/approach and mention
  alternatives briefly, rather than listing options as equals.
- **Favor procedures over declarations.** Teach *how to approach a class of
  problems*, not the answer to one instance. Specific details are fine when
  they generalize (output templates, constraints).
- **Gotchas section.** The highest-value content: environment-specific facts
  that defy reasonable assumptions. When the user corrects a mistake, add the
  correction here.
- **Templates for output.** When output must match a format, show a concrete
  template in `assets/` or inline — agents pattern-match templates better than
  prose descriptions.
- **Checklists for multi-step workflows** with validation gates between steps.
- **Validation loops**: do work → run validator → fix → repeat until it passes.

See [references/best-practices.md](references/best-practices.md) for the full
patterns guide with examples.

## Scripts

When a skill needs deterministic or reusable logic, bundle it in `scripts/`.
Design for agents:

- **Never block on interactive input** — agents run non-interactive shells.
  Take input via CLI flags, env vars, or stdin; fail fast with a helpful error.
- Provide `--help` output documenting flags and examples — that is how an
  agent learns the interface.
- Write helpful error messages: what went wrong, what was expected, what to try.
- Prefer structured output (JSON/CSV) on stdout; send diagnostics to stderr.
- Support `--dry-run` and safe defaults for destructive operations; make
  commands idempotent.
- Prefer self-contained scripts with inline dependencies (PEP 723 + `uv run`,
  `deno run npm:...`, bun auto-install) over manual install steps.

See [references/using-scripts.md](references/using-scripts.md) for the pattern
details.

## Audit (validation checklist)

After writing or when asked to review a skill, check:

1. `name` == directory name? Lowercase-hyphen form valid (no uppercase, no
   leading/trailing/double hyphen, ≤64 chars)?
2. `description` answers both *what* and *when*, is ≤1024 chars, and reads
   like an instruction to the agent ("Use when...") with trigger keywords?
3. Body under 500 lines; heavy detail pushed to `references/` with "read when"
   pointers?
4. File references relative and at most one level deep?
5. Free-standing `SKILL.md` outside a `skills/<name>/` directory? Relocate or
   retire it (exception: vendored submodules).
6. If bundled, scripts are non-interactive, documented, and safe?

Report findings as a proposal first; get approval before changing things.

## Description optimization

The `description` drives triggering, so tune it deliberately. Offer to run
this after the skill content is settled.

1. **Write ~20 trigger eval queries** — 8–10 should-trigger, 8–10
   should-not-trigger. Realistic prompts (file paths, job context, casual
   phrasing, typos). The negatives must be **near-misses** — queries sharing
   keywords but needing something else — not obviously irrelevant ones.
2. **Split** ~60% train / 40% held-out validation; keep both proportional.
3. **Evaluate trigger rate** on each set (each query run 3x; pass if rate
   ≥0.5). Fix the description from *train* failures only.
   - Undertriggering → description too narrow: broaden scope, add context
     about when it's useful, add "even if the user doesn't explicitly
     mention X".
   - Overtriggering → too broad: add specificity or state what it does *not*
     do.
   - Don't add keywords from specific failed queries — generalize.
4. **Select best description by validation pass rate** (avoid overfitting);
   verify ≤1024 chars.

See [references/descriptions.md](references/descriptions.md) for the full
method and an example before/after.

## Reference files

- [references/spec.md](references/spec.md) — the SKILL.md format spec in full
- [references/best-practices.md](references/best-practices.md) — patterns for
  effective skill instructions
- [references/descriptions.md](references/descriptions.md) — description
  triggering, trigger evals, train/validation split
- [references/using-scripts.md](references/using-scripts.md) — scripts design
  for agentic use
