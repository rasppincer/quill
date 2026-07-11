# Design Spec: pyragify.config adjustments

## Goal
Adjust the configuration in `pyragify.config` to skip all folders/files that are not needed for understanding the design/functionality of the project, optimizing context packaging.

## Background
The Quill project contains several directories and files that do not define its core architecture, features, or design. These include:
- Agent/environment configurations and caches (`.agent`, `.superpowers`, `.codex`)
- Virtual environments (`.venv`)
- Lock files, package lock files, build artifacts (`package-lock.json`, `dist/`, `build/`, `*.egg-info`)
- Local development helper scripts and database migrations (`scripts/`, `migrations/`)
- Log files and runtime outputs (`logs/`, `output/`)
- Local database files (`*.db`, `instance/`)
- Editor and OS metadata (`.DS_Store`, `*.swp`)

Excluding these files speeds up processing and minimizes noise when using retrieval-augmented tools.

## Proposed Configuration Changes

We will modify [pyragify.config](file:///home/bob/projects/quill/pyragify.config) by adding these groups of file patterns and directory names to `skip_patterns` and `skip_dirs`.

### [pyragify.config](file:///home/bob/projects/quill/pyragify.config)

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

## Verification Plan

1. Verify that `pyragify.config` parses as valid YAML.
2. Confirm the exact file content match.
