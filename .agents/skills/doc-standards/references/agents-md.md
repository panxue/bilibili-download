# AGENTS.md checklist (agents.md standard)

Source: https://agents.md/ — stewarded by the Agentic AI Foundation (Linux Foundation).

## What it is

A README for agents: one predictable place for the context and instructions a
coding agent needs. Complements README.md (which stays human-focused).

## Rules

- Location: repo root. Standard Markdown. **No required fields, no schema** —
  any headings work.
- `README.md` is the human-facing counterpart at the same root: agents read
  `AGENTS.md`, humans read `README.md`. Keep the two from duplicating each
  other — commands and conventions go in `AGENTS.md`, marketing and install
  instructions in `README.md`.
- Monorepos: nested AGENTS.md per subproject; the closest file to the edited
  code wins. Explicit user chat prompts override everything.
- Agents will run commands listed in it (build/test), so commands must be
  correct and safe to execute.
- Living documentation: update it in the same change that invalidates it.

## Recommended sections

- Project overview
- Build and test commands (agents execute these)
- Code style guidelines / conventions
- Architecture map (key files and their roles)
- Testing instructions
- Security considerations
- Commit / PR guidelines

## Audit questions

1. Does AGENTS.md describe the *current* architecture, or a superseded design?
2. Do the listed commands actually work (`npm run typecheck`, etc.)?
3. Is content agent-relevant (conventions, commands, maps) rather than
   human-marketing prose that belongs in README.md?
