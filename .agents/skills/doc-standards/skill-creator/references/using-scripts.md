# Using scripts in skills

Source: https://agentskills.io/skill-creation/using-scripts (snapshot 2026-07)

## One-off commands

When an existing package already does the job, reference it directly from
SKILL.md instead of bundling a script:

- `uvx ruff@0.8.0 check .` — uv's runner (requires uv).
- `pipx run 'black==24.10.0' .` — mature alternative, broader OS availability.
- `npx eslint@9 --fix .` — ships with Node.js.
- `bunx eslint@9 --fix .` — Bun's equivalent.
- `deno run npm:create-vite@6 my-app` — needs `--allow-*` flags; use `--` to
  separate Deno flags.
- `go run golang.org/x/tools/cmd/goimports@v0.28.0 .` — built into Go.

Tips:

- Pin versions (`npx eslint@9.0.0`) for reproducibility.
- State prerequisites in SKILL.md ("Requires Node.js 18+"); use the
  `compatibility` frontmatter field for runtime-level requirements.
- Move complex commands into a tested script in `scripts/`.

## Referencing scripts from SKILL.md

Use relative paths from the skill root. List available scripts so the agent
knows they exist, then instruct how to run them:

```markdown
## Available scripts
- **`scripts/validate.sh`** — Validates configuration files
- **`scripts/process.py`** — Processes input data
```

```bash
bash scripts/validate.sh "$INPUT_FILE"
python3 scripts/process.py --input results.json
```

The same relative-path convention works inside `references/*.md` — execution
paths are relative to the skill root.

## Self-contained scripts

Declare dependencies inline so one command runs the script — no install step:

- **Python (PEP 723)** — dependencies in `# /// script` TOML markers; run with
  `uv run scripts/extract.py` (or `pipx run`). Pin with PEP 508 specifiers;
  use `requires-python`; `uv lock --script` for a lockfile.
- **Deno** — `npm:` / `jsr:` import specifiers make scripts self-contained;
  version like `@1.0.0` / `@^1.0.0`; packages with native addons may not work.
- **Bun** — auto-installs missing packages when no `node_modules` is found;
  pin versions in the import path (`import * as cheerio from "cheerio@1.0.0"`).
- **Ruby** — `require 'bundler/inline'` + `gemfile do ... end`; pin explicitly
  (`gem 'nokogiri', '~> 1.16'`); an existing Gemfile can interfere.

## Designing scripts for agentic use

Agents read stdout/stderr to decide what to do next.

### Avoid interactive prompts (hard requirement)

Agents run non-interactive shells and cannot answer TTY prompts. Accept input
via CLI flags, env vars, or stdin. Fail fast with guidance:

```
Error: --env is required. Options: development, staging, production.
Usage: python scripts/deploy.py --env staging --tag v1.2.3
```

### Document usage with `--help`

Keep it concise — the output enters the agent's context window. Include
description, flags, defaults, and usage examples.

### Write helpful error messages

Say what went wrong, what was expected, and what to try:

```
Error: --format must be one of: json, csv, table.
       Received: "xml"
```

### Use structured output

Prefer JSON/CSV/TSV over aligned text. Separate data from diagnostics:
structured data → stdout; progress/warnings → stderr.

### Further considerations

- **Idempotency**: "create if not exists" over "fail on duplicate" (agents
  retry).
- **Input constraints**: reject ambiguous input with a clear error; use enums
  and closed sets.
- **Dry-run support** for destructive/stateful operations.
- **Meaningful exit codes**: distinct codes for different failure types,
  documented in `--help`.
- **Safe defaults**: destructive operations require explicit confirmation
  flags (`--confirm`, `--force`).
- **Predictable output size**: default to summaries/limits; support `--offset`
  or an `--output FILE` flag (or `-`) for large output — harnesses truncate
  tool output beyond ~10–30K characters.
