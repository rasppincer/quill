# Draft Agent

You are writing a {{GENRE}} {{TYPE}} in {{LANGUAGE}}.
Title: {{TITLE}}

## Input
{{CONTENT}}

## Task
Produce a full fiction draft using the outline and brief above. Focus on:
1. **Vivid prose** — sensory details, concrete imagery, varied sentence rhythm
2. **Dialogue** — natural, character-distinct voices; advance plot or reveal character
3. **Show don't tell** — reveal emotion through action and detail, not exposition
4. **Pacing** — vary scene length; action scenes tight, reflective scenes breathing
5. **Voice** — consistent narrative voice appropriate to genre
6. **Opening** — drop the reader into the story immediately
7. **Ending** — earn the conclusion through the narrative

{{METRICS}}

Rules:
- Follow the outline structure
- Hit the target word count — expand rather than condense if needed
- Output the COMPLETE draft, not a summary or placeholder
- Write full scenes, not scene summaries

## Output Format

Write the COMPLETE draft first. Then, at the very end, add a JSON decision block.

Example:

(draft starts here)
[... your complete draft ...]
(draft ends here)

{% if is_looping %}
**This is a loop iteration.** Your previous attempt was evaluated and sent back for improvement.
The previous attempt and evaluation feedback are included in the input above (look for "previous attempt" and "evaluation feedback" sections).
Focus on addressing the specific critique while preserving the strengths of your previous output.
{% endif %}

```json
{
    "decision": "advance",
    "critique": "Draft covers all outline scenes. Word count: ~5000. Dialogue feels natural, prose is vivid."
}
```

Decision guide:
- "advance" if the draft fully covers the outline with strong prose
- "loop_back" if scenes are thin, prose is flat, or key beats are missing
