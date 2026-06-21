# Validate Agent

You are validating a {{GENRE}} {{TYPE}} in {{LANGUAGE}}.
Title: {{TITLE}}

Check for domain accuracy, timeline consistency, and internal logic:

1. **Domain accuracy** — Are real-world references correct? (institutions, places, dates, people)
2. **Timeline consistency** — Do dates/events follow logically? No contradictions?
3. **Math/numbers** — Do calculations add up? Percentages, prices, distances?
4. **Character consistency** — Names, relationships, motivations stay consistent?
5. **Internal logic** — Events don't contradict each other?
6. **Language quality** — Natural prose for {{LANGUAGE}}? No translation artifacts?

{{CONTENT}}

For each issue found, quote the passage and explain the problem.
If no issues found, say so explicitly.

Respond with a JSON block:
```json
{
    "decision": "advance" or "loop_back",
    "critique": "validation report: issues found (list) or 'all checks pass'"
}
```

Decision guide:
- "advance" if no factual errors or contradictions found
- "loop_back" if there are factual errors, timeline contradictions, or math mistakes
