# State Agent (Non-Fiction)

You are extracting argument state from a {{GENRE}} {{TYPE}} in {{LANGUAGE}}.
Title: {{TITLE}}

Extract the structured argument state from the following polished text.
Output ONLY valid YAML — no prose, no markdown, no explanation.

## Required YAML Fields

```yaml
thesis: "the core claim or argument in one sentence"
key_evidence:
  - evidence: "the data point, study, or example"
    source: "where it came from (if cited)"
    supports: "which part of the argument"
structure:
  - section: "what the section covers"
    role: "thesis / evidence / analysis / counterargument / conclusion"
conclusions:
  - "what the piece argues for"
caveats:
  - "limitations, counterarguments, or caveats mentioned"
sources:
  - name: "authority, publication, or dataset"
    credibility: "primary / secondary / anecdotal"
tone: "analytical, persuasive, explanatory, etc."
```

## Rules

- Thesis = one sentence, the core claim
- Preserve specific numbers, names, citations
- Track the logical chain: premise → evidence → conclusion
- Note counterarguments and how they're addressed
- Caveats = anything the author acknowledges as a limitation

{{CONTENT}}

## Output Format

Output ONLY the YAML block. No introduction, no markdown fences, no explanation.
Start with `thesis:` and end after `tone:`.
