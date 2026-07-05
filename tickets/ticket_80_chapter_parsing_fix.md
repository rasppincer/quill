# Ticket 80: Fix LLMCaller Chapter Parsing in Draft Loop Backs

## Description
Modify `LLMCaller.run_content_stage` in `src/quill/stage_runner.py` to parse chapters from the piece's source files on disk instead of the concatenated `sc.input_content`.

## Background
During draft stage loops, `sc.input_content` contains the previous draft attempt, which itself has chapter headings. `LLMCaller` parses chapters from the entire `sc.input_content`, causing chapter headings to double and generating duplicate chapters (the story generated twice).

## Tasks
- [ ] Modify `LLMCaller.run_content_stage` to check the outline/structure/brief files on disk directly for chapter headings rather than using `sc.input_content`.
- [ ] Extract headings from the outline file first, then fall back to structure file, then brief file.

## Success Criteria
- [ ] Draft stage loop backs do not duplicate chapter generation.
- [ ] All unit and integration tests pass.

## Priority
High

---
**Next Expected Ticket Number**: 81

