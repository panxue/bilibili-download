# .agents protocol checklist (dotagentsprotocol.com)

Source: https://dotagentsprotocol.com/ — DRAFT standard (2026-02-24). A
directory convention that *converges* other standards; each sub-standard keeps
its own specification. The protocol also has a sharing catalog, the
[.agents Hub](https://hub.dotagentsprotocol.com), for installable bundle
artifacts.

## Layout (workspace `./.agents/`)

```
.agents/
├── agents.md              # instructions (AGENTS.md-compatible)
├── system-prompt.md       # system prompt
├── mcp.json               # MCP server configuration
├── models.json            # model presets & provider keys
├── speakmcp-settings.json # general settings
├── layouts/               # UI/layout preferences
├── skills/<name>/         # Agent Skills (format governed by agentskills.io)
├── agents/<name>/         # sub-agent profiles (agent.md: frontmatter + system prompt)
├── tasks/<name>/          # repeat task definitions (task.md)
├── memories/*.md          # persistent knowledge entries
└── .backups/              # auto-rotated backups
```

All entries optional; adopt incrementally. Unknown directories are outside the
protocol — map them into the layout above or justify them explicitly.

## Layering & merge semantics

- Global `~/.agents/` (base) + workspace `./.agents/` (override, committed to git).
- JSON files: shallow-merge by key, workspace wins.
- skills / memories / agents / tasks: merge by ID, workspace wins.

## Memory entry format

Frontmatter is simple `key: value` lines — **not full YAML**, no external
dependencies. Values can be quoted; list fields accept CSV (`tags: a, b, c`) or
JSON arrays (`tags: ["a", "b"]`).

```markdown
---
id: arch_001
title: Database Architecture
content: PostgreSQL with Drizzle ORM
importance: high
tags: database, architecture, orm
---
Body text of the memory.
```

## Reconciliation notes

- The protocol's own examples sketch `skill.md` (lowercase, `id`/`enabled`
  fields). The Agent Skills spec (the steward of that format) requires
  `SKILL.md` with `name` matching the directory — **the sub-standard wins**.
- Vendor dirs (`.claude/`, `.cursor/`, `.pi/`) should hold symlinks into
  `.agents/`, not canonical copies.

## Audit questions

1. Any agent-facing knowledge/config living outside `.agents/` (or root
   AGENTS.md)?
2. Any non-protocol directories under `.agents/`? Propose a mapping — but
   respect scope: full project documents belong in root `docs/`, app resources
   in `assets/`; only distilled facts become `memories/` entries.
3. Do memory entries carry `id`/`title`/`content`/`importance`/`tags` frontmatter?
