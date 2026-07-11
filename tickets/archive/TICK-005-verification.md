# TICK-005: Verification & Testing

## Goal
Ensure the new loopback system is robust and preserves files correctly through automated and manual tests.

## Tasks
- [ ] **Automated Tests**: 
    - Verify transition resolution for simple and decision-based next stages in `tests/test_pipeline.py`.
    - Verify dynamic context input assembly with different loop counts in `tests/test_runner.py`.
    - Verify decision-stage parsing and loop count boundaries in `tests/test_async.py`.

- [ ] **Manual Verification**: 
    - Start a non-fiction piece run in `auto` mode.
    - Check `run-log.jsonl` to confirm loop execution and incrementing counts.
    - Confirm output files on disk are correctly suffixed (`.L1.md`, `.L2.md`, etc.).
    - Verify execution proceeds to the end of the pipeline after successful decisions.

## Acceptance Criteria
- All related unit tests pass.
- Manual run confirms that versioned files are preserved and the loop terminates correctly.
