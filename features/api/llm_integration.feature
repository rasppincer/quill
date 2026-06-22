Feature: LLM integration
  As a writer using Quill
  I want agents to actually call the LLM and return results
  So that the pipeline produces real content

  Background:
    Given a clean Quill instance

  Scenario: Models endpoint returns available models from LAN LLM
    When I request the available models
    Then the response has status 200
    And the response contains a non-empty models list

  Scenario: Review agent produces a decision via real LLM call
    Given a piece "llm-review-test" at stage "review"
    And the piece has draft.md content
    When I run the agent for stage "review" with agent set "default"
    Then the response has status 200
    And the response contains a decision
    And the response contains a critique
    And the review.md file exists and has content

  Scenario: Async run returns run_id and completes
    Given a piece "llm-async-test" at stage "review"
    And the piece has draft.md content
    When I start an async agent run for stage "review" with agent set "default"
    Then the response has status 200
    And the response contains a run_id
    When I wait for the async run to complete
    Then the run log contains entries

  Scenario: Draft agent (two-call) produces content and decision
    Given a piece "llm-draft-test" at stage "draft"
    And the piece has outline.md and draft.md content
    When I run the agent for stage "draft" with agent set "fiction"
    Then the response has status 200
    And the response contains a decision
    And the response contains a critique
    And the draft.md file has content longer than 100 chars
