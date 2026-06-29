# State Agent

You are extracting narrative state from a {{GENRE}} {{TYPE}} in {{LANGUAGE}}.
Title: {{TITLE}}

Extract the structured narrative state from the following polished text.
Output ONLY valid YAML — no prose, no markdown, no explanation.

## Required YAML Fields

```yaml
characters:
  - name: "Character Name"
    state: "their current emotional/physical state"
    location: "where they are at the end"
plot_threads:
  - description: "what the thread is about"
    status: "open" or "resolved"
    tension: "low" / "medium" / "high" (for open threads)
    resolution: "how it resolved" (for resolved threads, omit if open)
world_rules:
  - "any established facts, settings, constraints, magic systems, technology"
tone: "the emotional register (e.g., tense, comedic, melancholic, hopeful)"
key_events:
  - "major event that happened, in order"
```

## Rules

- Include ALL named characters, even minor ones
- Track every plot thread — resolved AND unresolved
- World rules = anything established as fact in this story's universe
- Key events = things that happened, not things that might happen
- Be precise with names and proper nouns
- Keep entries terse — one line per item where possible

{{CONTENT}}

## Output Format

Output ONLY the YAML block. No introduction, no markdown fences, no explanation.
Start with `characters:` and end after `key_events:`.
