# Agent Skills format spec

Source: https://agentskills.io/specification (snapshot 2026-07)

## Directory structure

```
skill-name/
├── SKILL.md          # Required: metadata + instructions
├── scripts/          # Optional: executable code
├── references/       # Optional: documentation
├── assets/           # Optional: templates, resources
└── ...               # Any additional files or directories
```

`SKILL.md` must contain YAML frontmatter followed by Markdown content.

## Frontmatter fields

| Field           | Required | Constraints |
|-----------------|----------|-------------|
| `name`          | yes      | 1–64 chars; unicode lowercase `a-z0-9` + hyphens only; no leading, trailing, or consecutive (`--`) hyphens; **must match the parent directory name** |
| `description`   | yes      | 1–1024 chars; states what it does AND when to use it; include trigger keywords |
| `license`       | no       | short license name or bundled license file reference |
| `compatibility` | no       | 1–500 chars; only if the skill has environment requirements (intended product, system packages, network access) |
| `metadata`      | no       | arbitrary string→string map; use distinctive key names to avoid conflicts |
| `allowed-tools` | no       | space-separated pre-approved tools (experimental; support varies) |

### Name validity

- `pdf-processing` ✓
- `data-analysis` ✓
- `code-review` ✓
- `PDF-Processing` ✗ (uppercase)
- `-pdf` ✗ (leading hyphen)
- `pdf--processing` ✗ (consecutive hyphens)

### Description quality

- Good: "Extracts text and tables from PDF files, fills PDF forms, and merges
  multiple PDFs. Use when working with PDF documents or when the user mentions
  PDFs, forms, or document extraction."
- Poor: "Helps with PDFs."

## Body content

No format restrictions. Recommended sections: step-by-step instructions,
examples of inputs/outputs, common edge cases. The whole file loads into
context on activation, so keep it lean and split longer content into
referenced files.

## Progressive disclosure

1. Metadata (~100 tokens): `name` + `description` loaded at startup.
2. Instructions (<5,000 tokens recommended): full SKILL.md body on activation.
3. Resources (as needed): files under `scripts/`, `references/`, `assets/`
   loaded on demand.

Keep SKILL.md under 500 lines; move detailed reference material to separate
files.

## File references

Use relative paths from the skill root, at most one level deep:

```markdown
See [the reference guide](references/REFERENCE.md) for details.

Run the extraction script:
scripts/extract.py
```

Avoid deeply nested reference chains.

## Validation

```bash
skills-ref validate ./my-skill   # github.com/agentskills/agentskills → skills-ref
```

Checks that SKILL.md frontmatter is valid and follows all naming conventions.
