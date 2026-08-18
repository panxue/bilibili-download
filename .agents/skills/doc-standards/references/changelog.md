# Changelog spec — version change records

Source: project-specific convention (`docs/changelog.md` as the index entry). Beyond Agent Skills,
this is a project documentation convention; see the "memories vs docs division" in
[dotagents.md](dotagents.md).

## Division of responsibilities (avoid duplicating design.md)

| Document | Question answered | Content |
|----------|-------------------|---------|
| `docs/requirements.md` | what we want | requirements baseline (stable) |
| `docs/design.md` | what it is now | full picture of the current architecture (living) |
| `docs/changelog.md` | what changed, when, and why | index: version → summary → link to detail docs |
| `docs/iterations/<version>.md` | details | full change details for that version |
| `.agents/memories/*.md` | currently valid decisions | distilled conclusions (frontmatter, may point to docs/) |

**Core distinction**: design.md describes the *end state* (nouns — what exists);
changelog describes *change* (verbs — from A to B) plus reasons plus an index.
changelog does **not embed details** — details go into `docs/iterations/<version>.md`,
referenced rather than copied, to avoid becoming a copy of design.md.

## changelog.md format (index entry)

```markdown
# Changelog

## 1.0.0 — 2026-08-02 — Initial release
- Fresh baseline. See docs/requirements.md (requirements), docs/design.md (design), docs/state-lifecycle.md (storage)

## 1.1.0 — 2026-xx-xx — Added xxx
- Added xxx (see docs/iterations/1.1.0.md)
```

Rules:

- Each entry: `## <version> — <date> — <change type>`. Change types: added / changed / fixed / removed.
- Body only holds a **one-line summary + link to the detail doc**, never the details themselves.
- Append-only, sorted by version (newest first).
- **Version semantics**: iteration changes bump `x.y.z` (major/minor/patch) by the size of the change.
- First release (e.g. 1.0.0) is the initial baseline — do **not** mark it "breaking change",
  since a breaking change implies a fresh start.

## iterations/<version>.md format (details)

```markdown
# Iteration 1.1.0 — Added xxx

## Changes
- Topic | Before → After | Reason
- ... (decision-level, one per line, not file-level)

## Implementation notes
- Details, trade-offs, code references

## TODO / rollback notes
- ...
```

Rules:

- Decision-level entries use one format: `Topic | Before → After | Reason`.
- **Reason (why) is mandatory** — this is the dividing line between the changelog family and design.md.
- Granularity = decision level; do not record what each file changed.

## When to add entries

- Any change to `docs/requirements.md` must also add a changelog index entry.
- Any new version release: add a changelog index entry + create `docs/iterations/<version>.md`.
- First release: changelog gets the initial entry + `docs/iterations/1.0.0.md` baseline details.

## Git tag sync (skill distribution repos)

For a repo that distributes a skill, the release version is also exposed as a
git tag `v<x.y.z>` on GitHub and as `metadata.version` in `SKILL.md`. The
changelog's latest entry is the source of truth; keep the three in step:

- Release = changelog index entry + `docs/iterations/<version>.md` +
  `SKILL.md` `metadata.version` + annotated tag `v<x.y.z>` on the release commit.
- The `release` GitHub Action (`.github/workflows/release.yml`) creates the
  missing tag and GitHub Release on push to `main`. See [distribution.md](distribution.md).
