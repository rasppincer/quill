# Structure Agent (Non-Fiction)

You are segmenting a {{GENRE}} {{TYPE}} in {{LANGUAGE}}.
Title: {{TITLE}}

Generate exactly {{SEGMENT_COUNT}} segment titles for this piece.
Each segment targets approximately {{SEGMENT_TARGET}} words.
Segment style: {{SEGMENT_NAME}}

The brief describes the topic and angle:
{{CONTENT}}

## Instructions

1. Generate exactly {{SEGMENT_COUNT}} segment titles
2. Use `## Segment N: Title` format (e.g., `## Segment 1: The Problem`)
3. Titles only — no descriptions, no body content
4. Titles should follow argumentative structure: thesis → evidence → analysis → conclusion
5. Each title should be SEO-friendly and descriptive

## Output Format

Write ONLY the segment titles. No introduction, no explanation, no JSON.

Example for 4 segments:
```
## Segment 1: Why This Matters Now
## Segment 2: The Evidence
## Segment 3: What the Critics Say
## Segment 4: The Path Forward
```
