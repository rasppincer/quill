Feature: Pipeline navigation and stage lifecycle
  As a writer using Quill
  I want to navigate freely across explored stages and control how agents run
  So that I can review, re-run, and manage my writing pipeline intuitively

  # Stage state is tracked explicitly in meta.yaml:
  #   stage_states:
  #     brief: ready
  #     outline: ready
  #     draft: superseded
  #     review: empty
  #
  # States: empty | generating | ready | superseded
  # - empty: stage not yet reached or content cleared
  # - generating: agent is currently running (runtime-only, reverts to empty on crash)
  # - ready: agent completed, content available
  # - superseded: a later stage was re-run, this stage's content is stale
  #
  # Navigation: user can view any stage whose state is NOT "empty".
  # Frontier: piece.current_stage = last stage that was advanced to.

  Background:
    Given a clean Quill instance

  # ── Stage states ─────────────────────────────────────────────────

  Scenario: New piece has only brief stage ready
    When I create a piece with title "Nav Test" and genre "fiction"
    Then the piece is at stage "brief"
    And stage "brief" has state "ready"
    And stage "outline" has state "empty"
    And stage "draft" has state "empty"

  Scenario: Advancing creates next stage in empty state
    Given a piece "adv-test" at stage "brief"
    When I advance the piece
    Then the piece is at stage "outline"
    And stage "outline" has state "empty"

  Scenario: Running agent transitions stage through generating to ready
    Given a piece "gen-test" at stage "outline"
    And the piece has brief.md content
    When I run the agent for stage "outline" with agent set "default"
    Then stage "outline" has state "ready"
    And the outline.md file has content
    And the run log records state "generating" for stage "outline"

  # ── Free navigation within explored territory ────────────────────

  Scenario: Navigate to earlier stage and back to current
    Given a piece "nav-test" at stage "draft"
    And the piece has content in brief and outline stages
    When I navigate to stage "brief"
    Then the stage content for "brief" is returned
    And the stage metrics for "brief" are returned
    When I navigate to stage "draft"
    Then the stage content for "draft" is returned

  Scenario: Cannot navigate beyond frontier
    Given a piece "nav-lock" at stage "outline"
    When I navigate to stage "draft"
    Then I get an error containing "not yet reached"

  Scenario: Cannot navigate to stage far beyond frontier
    Given a piece "nav-far" at stage "brief"
    When I navigate to stage "humanize"
    Then I get an error containing "not yet reached"

  # ── Running agent on earlier stage supersedes later stages ───────

  Scenario: Re-running outline supersedes draft and review
    Given a piece "super-test" at stage "review"
    And the piece has content in brief, outline, and draft stages
    When I run the agent for stage "outline" with agent set "default"
    Then stage "outline" has state "ready"
    And stage "draft" has state "superseded"
    And stage "review" has state "superseded"
    And the piece is at stage "outline"

  Scenario: Re-running brief supersedes everything after it
    Given a piece "super-all" at stage "polish"
    And the piece has content in all stages through polish
    When I run the agent for stage "brief" with agent set "default"
    Then stage "brief" has state "ready"
    And stage "outline" has state "superseded"
    And stage "draft" has state "superseded"
    And stage "review" has state "superseded"
    And the piece is at stage "brief"

  Scenario: Superseded stages lose their content
    Given a piece "super-content" at stage "draft"
    And the piece has outline.md and draft.md content
    When I run the agent for stage "outline" with agent set "default"
    Then stage "draft" has state "superseded"
    And the draft.md file is empty or missing

  # ── Trigger mode: manual ────────────────────────────────────────

  Scenario: Piece defaults to on_advance trigger
    When I create a piece with title "Trigger Default" and genre "fiction"
    Then the piece trigger is "on_advance"

  Scenario: Set trigger to manual
    Given a piece "man-trigger" at stage "brief"
    When I set the piece trigger to "manual"
    Then the piece trigger is "manual"

  Scenario: Manual trigger — advance lands on empty stage, agent does not run
    Given a piece "man-adv" at stage "brief" with trigger "manual"
    And the piece has brief.md content
    When I advance the piece
    Then the piece is at stage "outline"
    And stage "outline" has state "empty"
    And no agent output exists for stage "outline"

  Scenario: Manual trigger — user must click run agent explicitly
    Given a piece "man-run" at stage "outline" with trigger "manual"
    And the piece has brief.md content
    When I run the agent for stage "outline" with agent set "default"
    Then stage "outline" has state "ready"
    And the outline.md file has content

  Scenario: Manual trigger — re-running agent replaces output
    Given a piece "man-rerun" at stage "outline" with trigger "manual"
    And the piece has brief.md content
    When I run the agent for stage "outline" with agent set "default"
    Then the outline.md file has content
    When I run the agent for stage "outline" with agent set "default"
    Then stage "outline" has state "ready"
    And the outline.md file has content

  # ── Trigger mode: on_advance ────────────────────────────────────

  Scenario: On_advance trigger — agent runs automatically on advance
    Given a piece "oa-adv" at stage "brief" with trigger "on_advance"
    And the piece has brief.md content
    When I advance the piece
    Then the piece is at stage "outline"
    And stage "outline" has state "ready"
    And the outline.md file has content

  Scenario: On_advance trigger — user can re-run agent after auto-generation
    Given a piece "oa-rerun" at stage "outline" with trigger "on_advance"
    And the piece has brief.md content
    And the outline.md has auto-generated content
    When I run the agent for stage "outline" with agent set "default"
    Then stage "outline" has state "ready"
    And the outline.md file has content

  Scenario: On_advance trigger — advancing again moves to next stage
    Given a piece "oa-next" at stage "outline" with trigger "on_advance"
    And the piece has brief.md and outline.md content
    When I advance the piece
    Then the piece is at stage "research"
    And stage "research" has state "ready"

  # ── Trigger mode: auto ──────────────────────────────────────────

  Scenario: Auto trigger — full pipeline runs without user intervention
    Given a piece "auto-full" at stage "brief" with trigger "auto"
    And the piece has brief.md content
    When I start the auto pipeline
    Then the piece reaches stage "done"
    And all content stages have state "ready"

  Scenario: Auto trigger — user can navigate to any reached stage while running
    Given a piece "auto-nav" at stage "brief" with trigger "auto"
    And the piece has brief.md content
    When I start the auto pipeline
    And I wait until the piece reaches stage "draft"
    And I navigate to stage "outline"
    Then the stage content for "outline" is returned

  Scenario: Auto trigger — run agent button is disabled while running
    Given a piece "auto-disabled" at stage "brief" with trigger "auto"
    And the piece has brief.md content
    When I start the auto pipeline
    And I wait until the piece reaches stage "outline"
    And I attempt to run the agent for stage "outline"
    Then I get an error containing "auto mode"

  Scenario: Auto trigger — advance button is disabled while running
    Given a piece "auto-noadv" at stage "brief" with trigger "auto"
    And the piece has brief.md content
    When I start the auto pipeline
    And I wait until the piece reaches stage "outline"
    And I attempt to advance the piece
    Then I get an error containing "auto mode"

  Scenario: Auto trigger — interrupt downgrades to on_advance
    Given a piece "auto-int" at stage "brief" with trigger "auto"
    And the piece has brief.md content
    When I start the auto pipeline
    And I wait until the piece reaches stage "outline"
    And I interrupt the auto pipeline
    Then the piece trigger is "on_advance"
    And the pipeline stops after the current stage completes

  # ── Trigger is per-piece ────────────────────────────────────────

  Scenario: Different pieces can have different triggers
    Given a piece "piece-manual" at stage "brief" with trigger "manual"
    And a piece "piece-auto" at stage "brief" with trigger "auto"
    Then piece "piece-manual" trigger is "manual"
    And piece "piece-auto" trigger is "auto"

  Scenario: Changing trigger on one piece does not affect others
    Given a piece "trig-a" at stage "brief" with trigger "manual"
    And a piece "trig-b" at stage "brief" with trigger "on_advance"
    When I set piece "trig-a" trigger to "auto"
    Then piece "trig-a" trigger is "auto"
    And piece "trig-b" trigger is "on_advance"

  # ── Inner generate-evaluate loop ────────────────────────────────

  Scenario: Agent loop-back is invisible to user
    Given a piece "loop-inner" at stage "draft" with trigger "on_advance"
    And the piece has outline.md and research.md content
    When I run the agent for stage "draft" with agent set "fiction"
    Then stage "draft" has state "ready"
    And the draft.md file has content
    # The agent may have looped internally — user only sees the final result

  Scenario: Agent max_loops is respected
    Given a piece "loop-max" at stage "draft" with trigger "on_advance"
    And the piece has outline.md and research.md content
    And the agent flavor has max_loops 1
    When I run the agent for stage "draft" with agent set "fiction"
    Then stage "draft" has state "ready"
    # Even if evaluate says loop_back, max_loops=1 means only 1 attempt
