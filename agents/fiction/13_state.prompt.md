# State Agent (Fiction)

You are extracting narrative state from a {{GENRE}} {{TYPE}} in {{LANGUAGE}}.
Title: {{TITLE}}

Extract the structured narrative state from the following polished text.
Output ONLY valid YAML — no prose, no markdown, no explanation.

## Required YAML Fields

```yaml
characters:
  - name: "Character Name"
    state: "emotional arc, where they ended up"
    location: "physical location at end of text"
    relationships: "key relationships and their current state"
plot_threads:
  - description: "the thread"
    status: "open" or "resolved"
    tension: "low" / "medium" / "high" (open threads)
    foreshadowing: "any hints planted" (if applicable)
world_rules:
  - "established facts: magic systems, technology, geography, social structures"
tone: "the emotional register (dark, comedic, tense, bittersweet, etc.)"
key_events:
  - "what happened, in causal order"
stakes:
  - character: "name"
    stands_to: "gain or lose what"
```

## Rules

- Include ALL named characters — even minor ones who might return
- Track EVERY plot thread — resolved, unresolved, and foreshadowed
- World rules = anything a reader would expect to remain true
- Key events = causal chain, not chronological list
- Preserve character names exactly as written
- Note cliffhangers and unresolved tension explicitly

{{CONTENT}}

## Output Format

Output ONLY the YAML block. No introduction, no markdown fences, no explanation.
Start with `characters:` and end after `stakes:`.
