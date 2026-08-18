# Best practices for skill creators

Source: https://agentskills.io/skill-creation/best-practices (snapshot 2026-07)

## Start from real expertise

Generic instructions ("handle errors appropriately") produce weak skills.
Ground the skill in real, domain-specific context:

- **Extract from a hands-on task** — complete a real task with an agent, then
  capture the steps that worked, corrections you made, input/output formats,
  and context you had to supply.
- **Synthesize from existing artifacts** — runbooks, style guides, API specs,
  schemas, code review comments, version-control history, real failure cases.
  Project-specific material beats generic articles.

## Refine with real execution

Run the first draft against real tasks, then feed results back (all of them,
not just failures). Read execution traces, not just final outputs. Wasted
steps usually mean instructions are too vague, don't apply, or present too
many options without a default.

## Spend context wisely

Everything in SKILL.md competes with the rest of the agent's context window.

### Add what the agent lacks, omit what it knows

Don't explain what a PDF is or how HTTP works. Jump straight to what the agent
wouldn't know:

```markdown
<!-- Too verbose -->
PDF (Portable Document Format) files are a common file format that contains
text... To extract text from a PDF, you'll need to use a library. pdfplumber
is recommended because it handles most cases well.

<!-- Better -->
Use pdfplumber for text extraction. For scanned documents, fall back to
pdf2image with pytesseract.
```

Ask of each piece: "Would the agent get this wrong without it?" If no, cut it.

### Design coherent units

A skill should encapsulate a coherent unit of work that composes well. Too
narrow → multiple skills must load for one task. Too broad → hard to activate
precisely.

### Aim for moderate detail

Concise, stepwise guidance with a working example beats exhaustive
documentation. Don't cover every edge case in the main file.

### Structure large skills with progressive disclosure

Keep SKILL.md under 500 lines and ~5,000 tokens. Move detail to
`references/` **with explicit "when to read" triggers**: "Read
`references/api-errors.md` if the API returns a non-200 status code" — not a
generic "see references/".

## Calibrating control

### Match specificity to fragility

- **Freedom** when multiple approaches are valid and variation is tolerable.
  Explaining *why* beats rigid directives here.
- **Prescriptive** when fragile or order matters: exact command sequences,
  required flags, "do not modify."

Most skills are a mix; calibrate each part.

### Provide defaults, not menus

Pick one default and mention alternatives briefly instead of presenting them
as equal options.

### Favor procedures over declarations

Teach how to approach a class of problems, not the answer to one instance:

```markdown
<!-- Specific answer — only useful for this exact task -->
Join the `orders` table to `customers` on `customer_id`, filter where
`region = 'EMEA'`, and sum the `amount` column.

<!-- Reusable method — works for any analytical query -->
1. Read the schema from `references/schema.yaml` to find relevant tables
2. Join tables using the `_id` foreign key convention
3. Apply any filters from the user's request as WHERE clauses
4. Aggregate numeric columns as needed and format as a markdown table
```

## Patterns for effective instructions

### Gotchas sections

Environment-specific facts that defy reasonable assumptions — the highest-value
content in many skills:

```markdown
## Gotchas
- The `users` table uses soft deletes. Queries must include
  `WHERE deleted_at IS NULL` or results will include deactivated accounts.
- The user ID is `user_id` in the database, `uid` in the auth service,
  and `accountId` in the billing API.
- The `/health` endpoint returns 200 even if the database is down. Use
  `/ready` to check full service health.
```

Keep gotchas in SKILL.md (before the agent hits the situation). When the user
corrects a mistake, add the correction here.

### Templates for output format

Show a concrete template instead of describing the format in prose. Short ones
inline; long or conditional ones in `assets/`, referenced from SKILL.md.

### Checklists for multi-step workflows

Explicit checklists with dependencies/validation gates help the agent track
progress and avoid skipped steps.

### Validation loops

Do the work → run a validator (script, reference checklist, or self-check) →
fix → repeat until it passes.

### Plan-validate-execute

For batch/destructive operations: build a structured plan, validate it against
a source of truth (e.g. a script that checks field names exist), fix, then
execute. Good validator errors like "Field 'x' not found — available:
a, b, c" let the agent self-correct.

### Bundle reusable scripts

When the agent reinvents the same logic every run (charts, parsing,
validation), write it once, test it, and put it in `scripts/`.
