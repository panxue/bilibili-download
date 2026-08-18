# Distributing and installing skills

How a skill gets from a repo to an agent's skills directory, and the repo
shape that makes that work.

## Skill distribution repo

A repo whose deliverable is the skill itself, not a project with agent config.
The skill's `SKILL.md` sits at the **repo root** — that is the artifact an
installer discovers. This is the deliberate exception to the "no free-standing
`SKILL.md`" rule (see rule 6/8 in `SKILL.md`): the root file is the entry point,
not a stray doc.

```
<repo>/
├── README.md          # human-facing intro + install instructions
├── SKILL.md           # the skill (installer entry point)
├── references/        # skill references (loaded on demand)
└── <vendored deps>/   # any content SKILL.md references, committed in-repo
```

## Installation: `npx skills add`

`npx skills add <owner/repo>` (the `skills` CLI, stewarded by Microsoft) treats
GitHub as a registry: any public repo with a root `SKILL.md` is installable —
no packaging or npm publish needed.

```shell
# Project scope: installs to ./<agent>/skills/ (committed with the project)
npx skills add panxue/doc-standards-skill

# Global scope: installs to ~/.agents/skills/ (available in every project)
npx skills add panxue/doc-standards-skill -g

# Target specific agents (e.g. claude-code, codex), non-interactively
npx skills add panxue/doc-standards-skill -g -a claude-code -a opencode -y

# List what would be installed without installing
npx skills add panxue/doc-standards-skill --list

# Verify an installation
npx skills ls -g
```

Notes:

- `-y` skips prompts (CI-safe); `--copy` copies instead of symlinking.
- The CLI auto-detects installed agents; with no detection it prompts.
- `npx` may run a cached CLI version — force latest with `npx skills@latest add ...`.

## Vendoring: submodules are not initialized

The `skills` CLI clones the source repo but does **not** initialize git
submodules. Anything `SKILL.md` references (e.g. `skill-creator/`, shared
`references/`) must therefore be committed directly into the distribution repo.
A referenced-but-empty directory is a broken skill after install.

Vendoring a submodule: `git submodule update --init`, then remove the
`.gitmodules` file and the submodule gitlink, and commit the content as plain
files. Mark the origin in the skill ("vendored from the `X` repo, single
source of truth") so the upstream stays discoverable.

## Versioning and releases

The Agent Skills spec has **no `version` frontmatter field**, so a distributed
skill records its version in three places that must agree:

1. `docs/changelog.md` — latest index entry is the source of truth (rule 7).
2. `SKILL.md` frontmatter — `metadata.version: "x.y.z"` (custom key).
3. Git tag — `v<x.y.z>` (annotated) on the release commit.

The `release` workflow (`.github/workflows/release.yml`) is the sync mechanism:
on every push to `main` it verifies the changelog version matches
`metadata.version`, creates and pushes the missing `v<x.y.z>` tag, and creates
a GitHub Release when the tag is new. Pushing a change with an updated
`docs/changelog.md` is therefore a release — no manual tagging.

The workflow gates releases: a version mismatch (changelog vs
`metadata.version`) fails the job, so a bump must update both. A manual
fallback is `git tag -a v<x.y.z> && git push origin v<x.y.z>`.

A distribution repo therefore carries `docs/` (its own changelog) plus
`.github/workflows/` alongside the skill files; none of these affect
`npx skills add` discovery, which keys off the root `SKILL.md`.

## One hub, many agents

Per the `.agents` protocol, vendor agent dirs (`.claude/skills/`, `.cursor/skills/`,
etc.) may hold **symlinks** into a single hub — conventionally `~/.agents/skills/`.
Installed once there, a skill is visible to every agent whose skills dir points
at the hub; updates land in one place.

## Audit questions

1. Is `SKILL.md` at the repo root discoverable (`npx skills add <owner/repo> --list`)?
2. Does every file `SKILL.md` references exist in-repo (no submodules, no empty dirs)?
3. Is `README.md` present with the install command, the install targets, and
   how to use the skill?
4. Do `docs/changelog.md`, `SKILL.md` `metadata.version`, and the `v<x.y.z>`
   git tag agree (the `release` workflow enforces this on push to `main`)?