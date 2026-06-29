Feature: Orchestrator
  As a writer using Quill
  I want my long-form piece to be processed chapter by chapter
  So that each chapter gets proper context from its neighbors

  Background:
    Given a clean Quill instance

  @slow
  Scenario: Chaptered piece shows children after orchestrator runs
    Given a piece "orch-test" at stage "draft"
    And the piece has structure with 3 segments
    And the piece has outline and brief content
    When I run the orchestrator for stage "draft" with agent set "default"
    Then the piece "orch-test" has 3 children
    And each child has a parent field pointing to "orch-test"

  Scenario: Non-chaptered piece has no children
    Given a piece "single-piece" at stage "draft"
    And the piece has outline.md and draft.md content
    When I set the piece trigger to "manual"
    When I advance the piece
    Then the piece "single-piece" has 0 children
