# Pyragify Configuration Adjustments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exclude all development files, caches, logs, databases, and local assets from `pyragify.config` to optimize project context.

**Architecture:** Modify the yaml config keys `skip_patterns` and `skip_dirs` in `pyragify.config` directly to filter out unwanted items.

**Tech Stack:** YAML

## Global Constraints

- Exclude all folders/files not needed for understanding the design/functionality of the project.
- Skip `migrations` and `scripts` directories as requested by the user.

---

### Task 1: Update pyragify.config

**Files:**
- Modify: `pyragify.config:6-21`

**Interfaces:**
- Consumes: None
- Produces: Updated YAML structure in `pyragify.config`

- [ ] **Step 1: Write the updated pyragify.config content**

Modify `/home/bob/projects/quill/pyragify.config` to match:
```yaml
repo_path: ~/projects/quill
output_dir: /mnt/more/pyragify_out_quill
max_words: 5000
max_file_size: 100000
verbose: false
skip_patterns:
  - "*.pyc"
  - "*.png"
  - "*.jpg"
  - "*.gif"
  - "*.whl"
  - "*.lock"
  - ".git/**"
  - ".env"
  # Python compilation/coverage files
  - "*.pyo"
  - ".coverage"
  - "htmlcov/**"
  # Node/Web package locks & build outputs
  - "package-lock.json"
  - "dist/**"
  - "build/**"
  # Local databases & artifacts
  - "*.db"
  - "*.sqlite3"
  - "quill.db-shm"
  - "quill.db-wal"
  # Editor backups & OS files
  - "*.swp"
  - "*.swo"
  - "*~"
  - ".DS_Store"
  - "Thumbs.db"
skip_dirs:
  - .venv
  - .git
  - tests
  - benchmark
  - node_modules
  - __pycache__
  # Agent & environment tools
  - .agent
  - .superpowers
  - .codex
  # Build metadata & caches
  - .pytest_cache
  - .worktrees
  - quill.egg-info
  # App logs & generated outputs
  - logs
  - output
  # Development management
  - tickets
  # SQLite DB & runtime configs
  - instance
  # Project-specific non-functional folders
  - scripts
  - migrations
```

- [ ] **Step 2: Verify that pyragify.config is valid YAML**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('pyragify.config'))"
```
Expected: The command runs successfully with no output and exit code 0.

- [ ] **Step 3: Commit**

Run:
```bash
git add pyragify.config
git commit -m "chore: adjust pyragify.config skip list to exclude non-design/non-functional files"
```
