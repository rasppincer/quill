Feature: Concurrency and edge cases
  As a writer using Quill
  I want the system to handle concurrent operations safely
  So that my pieces don't get corrupted by race conditions

  Background:
    Given a clean Quill instance

  Scenario: Can start runs on different pieces concurrently
    Given a piece "concurrent-a" at stage "review"
    And the piece has draft.md content
    Given a piece "concurrent-b" at stage "review"
    And the piece has draft.md content
    When I start an async run on piece "concurrent-a" for stage "review" with agent set "default"
    Then the response has status 200
    When I start an async run on piece "concurrent-b" for stage "review" with agent set "default"
    Then the response has status 200
    And the response contains a run_id

  Scenario: Run log appends across multiple runs
    Given a piece "log-append-test" at stage "review"
    And the piece has draft.md content
    When I run the agent for stage "review" with agent set "default"
    Then the response has status 200
    When I run the agent for stage "review" with agent set "default"
    Then the response has status 200
    When I fetch the run log for piece "log-append-test"
    Then the run log has at least 2 entries

  Scenario: Content cleaning removes em dashes from output
    Given a piece "clean-test" at stage "review"
    And the piece has draft.md content with em dashes
    When I run the agent for stage "review" with agent set "default"
    Then the review.md file does not contain em dashes
