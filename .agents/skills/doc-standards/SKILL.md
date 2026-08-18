---
name: doc-standards
description: Apply and audit this project's documentation standards, which combine three specs — AGENTS.md (agents.md), the .agents directory protocol (dotagentsprotocol.com), and the Agent Skills spec (agentskills.io). Use when creating, moving, or editing AGENTS.md, README.md, SKILL.md, skills, memories, or any file under .agents/, when distributing or installing a skill (e.g. npx skills add), and when auditing the repo's docs for compliance.
metadata:
  sources: "https://agents.md/ | https://dotagentsprotocol.com/ | https://agentskills.io/specification"
  spec-snapshot: "2026-08"
  version: "1.0.1"
---

# Documentation Standards

This project's documentation follows three open standards. This skill tells you
which standard governs what, the rules that must hold, and how to apply them.

## Jurisdiction — which spec wins where

| Concern | Governing spec | Rule of thumb |
|---------|----------------|---------------|
| Where agent-facing files live | .agents protocol | everything converges under `.agents/` |
| `SKILL.md` format | Agent Skills spec | frontmatter + naming + progressive disclosure |
| `AGENTS.md` content | agents.md | README-for-agents at repo root |
| `README.md` content | project convention | human-facing doc at repo root, complements `AGENTS.md` |
| Version change records | project convention (this skill) | `docs/changelog.md` index → `docs/iterations/<version>.md` details |

Conflict rule: the .agents protocol is a *convergence point, not a replacement* —
when its illustrations disagree with an underlying standard (e.g. it sketches
lowercase `skill.md` with an `id` field), the underlying standard wins
(uppercase `SKILL.md`, `name` field, per Agent Skills spec).

Details per spec (read only the one you need):

- [references/agents-md.md](references/agents-md.md) — AGENTS.md checklist
- [references/dotagents.md](references/dotagents.md) — `.agents/` layout and merge semantics
- [skill-creator/](skill-creator/) — the SKILL.md format spec + creation workflow, vendored from the `skill-creator` repo (single source of truth; the old `references/agent-skills.md` is removed). Read `skill-creator/references/spec.md` for format rules.
- [references/distribution.md](references/distribution.md) — distributing and installing skills (`npx skills add`, vendoring, install targets)
- [references/changelog.md](references/changelog.md) — changelog index + iteration detail docs

## Core rules (the short list)

1. `AGENTS.md` lives at the repo root. Plain Markdown, no required fields.
   Keep it current: project overview, build/test commands, architecture map,
   conventions. It is living documentation — update it in the same change that
   invalidates it. `README.md` sits beside it as the human-facing doc (intro +
   install instructions): agents read `AGENTS.md`, humans read `README.md`, and
   the two do not duplicate each other.
2. Every skill is a directory `\.agents/skills/<name>/` containing `SKILL.md`.
   Frontmatter: `name` (required, lowercase-hyphen, ≤64 chars, **must equal the
   directory name**) and `description` (required, ≤1024 chars, states *what it
   does* and *when to use it*). Optional: `license`, `compatibility`,
   `metadata`, `allowed-tools`.
3. `SKILL.md` body stays under 500 lines. Detail goes to `references/` (docs),
   `scripts/` (executable), `assets/` (static), loaded on demand. File
   references are relative and at most one level deep.
4. The `.agents` protocol governs **agent configuration**, not project
   documentation. Full project documents (design docs, specs, input documents)
   live in root `docs/`; app resources (templates, seed data) in `assets/`.
   `.agents/memories/*.md` holds only *distilled* facts/decisions — small
   entries with frontmatter (`id`, `title`, `importance`, `tags`), optionally
   pointing into `docs/`.
5. No agent-facing config in vendor-specific locations. Vendor dirs (e.g.
   `.claude/skills/`) may contain **symlinks** into `.agents/` for tool
   discovery, never the canonical copy.
6. Free-standing `SKILL.md` files outside a `skills/<name>/` directory are
   non-compliant — relocate or retire them. Exceptions: `skill-creator/` is
   vendored third-party content, not a doc artifact; leave it untouched. And a
   *skill distribution repo* legitimately keeps `SKILL.md` at the repo root —
   that root file is the installable artifact (see rule 8).
7. Version changes go in `docs/changelog.md` as an **index entry only** (version,
   date, type, one-line summary, link to details). Full detail lives in
   `docs/iterations/<version>.md`. Details are decision-level, written as
   `Topic | Before → After | Reason` — **reason is mandatory**. changelog never
   duplicates design.md content; it points to it.
8. Distributing a skill means shipping a **skill distribution repo**: root
   `SKILL.md` plus vendored dependencies. `npx skills add <owner/repo>`
   installs it into project `.agents/skills/` or, with `-g`, global
   `~/.agents/skills/`. Git submodules are **not** initialized on install, so
   any referenced content (e.g. `skill-creator/`) must be vendored into the
   repo. Each release bumps `docs/changelog.md` (rule 7) and is tagged
   `v<x.y.z>` on GitHub; the `release` workflow
   (`.github/workflows/release.yml`) keeps the changelog, `metadata.version`,
   and the tag in sync. Details:
   [references/distribution.md](references/distribution.md).

## How to apply (audit procedure)

When asked to apply/audit doc standards, walk this checklist and report
findings before changing anything:

1. **Root**: `AGENTS.md` exists? `README.md` exists (human-facing, no agent
   commands)? Content matches the *current* architecture (not a previous
   design iteration)? A root `SKILL.md` is only expected when the repo is a
   skill distribution repo; otherwise flag it as stray.
2. **`.agents/` layout**: only protocol-defined entries
   (`agents.md`, `skills/`, `agents/`, `tasks/`, `memories/`, `mcp.json`,
   `models.json`, `system-prompt.md`)? Flag unknown directories and propose a
   mapping into the protocol layout.
3. **Each skill**: run the checklist in
   `skill-creator/references/spec.md` — name/dir match,
   description quality (what + when + trigger keywords), body length,
   reference depth. The `skill-creator/` content is vendored — skip it in this check.
4. **Memories**: frontmatter present and meaningful (`importance`, `tags`)?
5. **Symlinks**: vendor discovery links resolve and point into `.agents/`?
6. **Changelog**: every version has an index entry in `docs/changelog.md`
   pointing to `docs/iterations/<version>.md`? Index entries free of detail?
   Iteration entries decision-level with mandatory reasons?
7. Present the findings as a proposal (move/rewrite/delete per file), get
   approval, then execute. Deletions always need explicit user confirmation.

## Target layout for this repo

This repo is a **skill distribution repo** — the deliverable is the skill
itself, so `SKILL.md` lives at the root (the `npx skills add` entry point)
rather than under `.agents/skills/`. README.md is the human-facing entry.

```
<repo>/                             # skill distribution repo (this repo)
├── README.md                       # human-facing intro + install instructions
├── SKILL.md                        # the skill (root entry for npx skills add)
├── docs/                           # this repo's own version records
│   ├── changelog.md                #   index: version → summary → link to detail docs
│   └── iterations/                 #   per-version detail records
├── references/                     # skill references (loaded on demand)
│   ├── agents-md.md
│   ├── changelog.md
│   ├── distribution.md
│   └── dotagents.md
├── .github/
│   └── workflows/release.yml       # auto-tag + GitHub Release on push to main
└── skill-creator/                  # vendored skill spec + workflow (single source of truth)
```

A *project* repo (one that hosts agent configuration too) uses the full layout
below instead; there `SKILL.md` lives under `.agents/skills/<name>/`.

```
<project repo>/
├── README.md                       # human-facing doc
├── AGENTS.md                       # agents.md standard (root, living doc)
├── docs/                           # project documentation (outside protocol scope)
│   ├── changelog.md                #   index: version → summary → link to detail docs
│   ├── requirements.md             #   requirements baseline (stable)
│   ├── design.md                   #   current architecture (living)
│   ├── state-lifecycle.md          #   state operational reference
│   └── iterations/                 #   per-version detail records
│       └── 1.0.0.md                #     initial baseline details
├── assets/
│   └── references/                 # app resources (templates, seed data)
└── .agents/
    ├── skills/
    │   └── doc-standards/          # this skill
    │       ├── SKILL.md
    │       └── references/
    └── memories/                   # distilled decisions only (frontmatter'd, may point to docs/)
```

`.claude/skills/doc-standards` is a symlink to `.agents/skills/doc-standards`
for Claude Code discovery.
