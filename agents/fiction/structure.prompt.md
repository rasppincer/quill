# Structure Agent (Fiction)

You are segmenting a {{GENRE}} {{TYPE}} in {{LANGUAGE}}.
Title: {{TITLE}}

Generate exactly {{SEGMENT_COUNT}} segment titles for this piece.
Each segment targets approximately {{SEGMENT_TARGET}} words.
Segment style: {{SEGMENT_NAME}}

The brief describes the story:
{{CONTENT}}

## Instructions

1. Generate exactly {{SEGMENT_COUNT}} segment titles
2. Use `## Segment N: Title` format (e.g., `## Segment 1: The Discovery`)
3. Titles only — no descriptions, no body content
4. Titles should follow narrative arc: setup → rising action → climax → resolution
5. Each title should evoke the emotional beat of that segment

## Output Format

Write ONLY the segment titles. No introduction, no explanation, no JSON.

Example for 5 segments:
```
## Segment 1: The Quiet Before
## Segment 2: The Discovery
## Segment 3: The Descent
## Segment 4: The Reckoning
## Segment 5: The Aftermath
```
