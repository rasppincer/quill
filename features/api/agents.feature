Feature: Agent pipeline
  As a writer using Quill
  I want agents to process my piece through the pipeline
  So that I get automated critique, revision, and polish

  Background:
    Given a clean Quill instance

  @slow
  Scenario: Chain run processes all stages with agent prompts
    Given a piece "chain-test" at stage "brief"
    And the piece has outline.md and draft.md content
    When I run the agent chain from "outline" with agent set "fiction"
    Then the chain runs "outline", "draft", "review", "revise", "humanize", "validate", "polish", "summary"
    And the piece reaches stage "done"

  Scenario: Polish advances to summary not done
    Given a piece "polish-next" at stage "polish"
    And the piece has content in all stages through polish
    When I set the piece trigger to "manual"
    When I advance the piece
    Then the piece is at stage "summary"

  Scenario: Summary stage has prompt in all flavors
    When I query agents for stage "summary"
    Then the response includes "default"
    And the response includes "fiction"
    And the response includes "non-fiction"

  Scenario: Brief advances to structure not outline
    Given a piece "brief-struct" at stage "brief"
    When I set the piece trigger to "manual"
    When I advance the piece
    Then the piece is at stage "structure"

  Scenario: Structure stage has prompt in all flavors
    When I query agents for stage "structure"
    Then the response includes "default"
    And the response includes "fiction"
    And the response includes "non-fiction"

  Scenario: Chain run skips stages without agent prompts
    Given a piece "chain-skip" at stage "brief"
    And the piece has outline.md and draft.md content
    When I run the agent chain from "brief" with agent set "fiction"
    Then the chain skips "brief"
    And the chain runs "outline"

  Scenario: Chain run errors when all stages lack prompts
    Given a piece "no-agent" at stage "brief"
    When I run the agent chain from "brief" with agent set "nonexistent"
    Then I get an error about no agent prompts

  Scenario: Single stage agent run
    Given a piece "single-run" at stage "review"
    And the piece has draft.md content
    When I run the agent for stage "review" with agent set "default"
    Then the review.md contains clean markdown critique
    And the review.md has no JSON code fences

  Scenario: Agent run produces output without JSON wrappers
    Given a piece "format-test" at stage "review"
    And the piece has draft.md content
    When I run the agent for stage "review" with agent set "fiction"
    Then the review.md does not contain "```json"
    And the review.md does not contain JSON decision block

  Scenario: Non-fiction flavor appears for draft stage after prompt added
    When I query agents for stage "draft"
    Then the response includes "non-fiction"
    And the response includes "fiction"
    And the response includes "default"

  Scenario: Non-fiction flavor appears for outline stage after prompt added
    When I query agents for stage "outline"
    Then the response includes "non-fiction"
    And the response includes "fiction"
    And the response includes "default"

  Scenario: For-stage returns empty for nonexistent stage
    When I query agents for stage "nonexistent-stage"
    Then the for-stage response has empty agent_sets
