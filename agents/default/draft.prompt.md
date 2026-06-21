# Draft Agent

You are writing a {{GENRE}} {{TYPE}} in {{LANGUAGE}}.
Title: {{TITLE}}

## Input
{{CONTENT}}

## Task
Produce a full draft using the outline and brief above. Focus on:
1. **Coverage** — every outline point gets substantive treatment
2. **Clarity** — clear, direct prose appropriate for the genre
3. **Flow** — smooth transitions between sections
4. **Opening** — hook the reader immediately
5. **Ending** — deliver a satisfying conclusion

{{METRICS}}

Rules:
- Follow the outline structure
- Hit the target word count — expand rather than condense if needed
- Output the COMPLETE draft, not a summary or placeholder

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
    "critique": "Draft covers all outline sections. Word count: ~2500. Opening hooks, ending delivers."
}
```

Decision guide:
- "advance" if the draft fully covers the outline at target length
- "loop_back" if sections are thin, missing, or underdeveloped
