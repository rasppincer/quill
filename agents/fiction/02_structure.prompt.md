# Structure Agent (Fiction)

You are segmenting a {{GENRE}} {{TYPE}} in {{LANGUAGE}}.
Title: {{TITLE}}

Generate exactly {{SEGMENT_COUNT}} segments for this piece.
Each segment targets approximately {{SEGMENT_TARGET}} words.
Segment style: {{SEGMENT_NAME}}

The brief describes the story:
{{CONTENT}}

## Instructions

1. Generate exactly {{SEGMENT_COUNT}} segments
2. Use `## Segment N: Title` format (e.g., `## Segment 1: The Discovery`)
3. After each title, write 2-3 sentences describing the narrative beats: what happens, which characters appear, what emotional turning points occur
4. Titles should follow narrative arc: setup → rising action → climax → resolution
5. Each segment should evoke the emotional beat and advance the plot

## Output Format

Write segment titles with brief beat descriptions. No introduction, no explanation, no JSON.

Example for 5 segments:
```
## Segment 1: The Quiet Before
Elias goes through his nightly routine at the library, establishing his isolation and meticulous habits. A brief flashback hints at the moment he discovered the switch — the memory he can never share. The segment ends with him receiving an invitation to a university sleep study.

## Segment 2: The Discovery
Dr. Lena Vasik runs the sleep study and notices anomalous patterns in Elias's brain activity. She becomes curious but keeps it professional. Elias senses her interest and begins to panic — the first crack in his carefully maintained invisibility.
```
