# Prompt Templates — Versioning & Management

Prompt templates are the instructions each agent stage uses to process your content. They live as plain markdown files, versioned by git alongside the rest of the codebase.

## File Layout

```
agents/
├── model.yaml                    # Global model config (API base, model)
├── default/                      # Default agent set (fiction + general)
│   ├── config.yaml               # Set-level config (temp, loops, trigger)
│   ├── review.prompt.md          # Review stage prompt
│   ├── revise.prompt.md          # Revise stage prompt
│   ├── humanize.prompt.md        # Humanize stage prompt
│   ├── validate.prompt.md        # Validate stage prompt
│   └── polish.prompt.md          # Polish stage prompt
└── non-fiction/                  # Non-fiction agent set (blog, essay)
    ├── config.yaml
    ├── review.prompt.md
    ├── revise.prompt.md
    ├── humanize.prompt.md
    ├── validate.prompt.md
    └── polish.prompt.md
```

Each agent set has its own directory under `agents/`. A piece references its agent set via `agent_set` in `meta.yaml`.

## Template Variables

Prompts use `{{VARIABLE}}` placeholders, replaced at runtime:

| Variable | Description | Example |
|----------|-------------|---------|
| `{{CONTENT}}` | Input text (from previous stage files) | The draft or revised text |
| `{{STAGE}}` | Current stage name | `review`, `revise` |
| `{{PIECE_ID}}` | Piece identifier | `gold-collapse` |
| `{{TITLE}}` | Piece title | `Gold Collapse` |
| `{{GENRE}}` | Genre from meta.yaml | `fiction`, `non-fiction` |
| `{{LANGUAGE}}` | Language from meta.yaml | `en`, `bg` |
| `{{METRICS}}` | Readability scores from input stages | Flesch, word count, etc. |

## Viewing Prompts

### Dashboard (recommended)
Navigate to **⚙ Agents** → click an agent set → click a prompt to view/edit.

### API
```bash
# Get a prompt
curl http://localhost:8325/api/agents/default/review/prompt

# List all prompts in a set
curl http://localhost:8325/api/agents/default
```

### File
```bash
cat ~/projects/quill/agents/default/review.prompt.md
```

## Editing Prompts

### Dashboard
Click a prompt → edit in the textarea → **Save**.

### API
```bash
curl -X PUT http://localhost:8325/api/agents/default/review/prompt \
  -H 'Content-Type: application/json' \
  -d '{"content": "# New prompt content here..."}'
```

### File (direct edit)
```bash
$EDITOR ~/projects/quill/agents/default/review.prompt.md
# Restart quill to pick up changes
systemctl --user restart quill
```

## Git History

All prompt changes are tracked by git. Use standard git commands to inspect history.

### View commit history for a specific prompt
```bash
cd ~/projects/quill
git log --oneline agents/default/review.prompt.md
```

Output:
```
a8fa736 restore review prompt, fix hardcoded agent paths
c2dda88 Agentic pipeline + dashboard + updated docs
```

### View what changed in each commit
```bash
git log -p agents/default/review.prompt.md
```

### Diff between two versions
```bash
# Compare current vs previous version
git diff HEAD~1 -- agents/default/review.prompt.md

# Compare current vs a specific commit
git diff c2dda88 -- agents/default/review.prompt.md

# Compare two specific commits
git diff c2dda88..a8fa736 -- agents/default/review.prompt.md
```

### Show a specific version
```bash
# Show the file at a specific commit
git show c2dda88:agents/default/review.prompt.md

# Show the file 2 commits ago
git show HEAD~2:agents/default/review.prompt.md
```

## Rolling Back

### Restore a prompt to a previous version
```bash
cd ~/projects/quill

# Restore from a specific commit
git checkout c2dda88 -- agents/default/review.prompt.md

# Or restore from 1 commit ago
git checkout HEAD~1 -- agents/default/review.prompt.md
```

Then commit the rollback:
```bash
git commit -m "restore review.prompt.md to c2dda88 version"
git push
```

Restart the service to pick up the change:
```bash
systemctl --user restart quill
```

### Undo the last prompt edit (if not yet committed)
```bash
git checkout -- agents/default/review.prompt.md
```

## Adding a New Agent Set

1. Create the directory:
```bash
mkdir ~/projects/quill/agents/my-set
```

2. Create `config.yaml`:
```yaml
description: "My custom agent set"
temperature: 0.7
max_tokens: 4096
max_loops: 3
trigger: "on_advance"

stages:
  review:
    name: "Review Agent"
    temperature: 0.5
  revise:
    name: "Revise Agent"
    temperature: 0.6
```

3. Create prompt templates (at minimum, one for each stage you want agents to handle):
```bash
# Copy from an existing set as a starting point
cp agents/default/review.prompt.md agents/my-set/review.prompt.md
# Edit to taste
$EDITOR agents/my-set/review.prompt.md
```

4. The new set appears automatically in the dashboard Agents tab and piece detail dropdown.

## Tips

- **Prompt changes are instant** — the dashboard saves via API, no restart needed. File edits need a service restart.
- **Use `{{METRICS}}`** — include it in review/validate prompts so agents see readability scores from input stages.
- **Test with a small piece first** — create a test piece, run the agent, check the output before committing prompt changes.
- **Commit meaningful changes** — `git commit -m "tune review prompt for pacing analysis"` is better than `git commit -m "update prompt"`.
