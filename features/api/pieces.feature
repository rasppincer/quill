Feature: Piece lifecycle
  As a writer using Quill
  I want to create, advance, rename, and manage pieces
  So that I can track my writing through the pipeline

  Background:
    Given a clean Quill instance

  Scenario: Create a new piece
    When I create a piece with title "Test Story" and genre "fiction"
    Then the piece "test-story" exists
    And the piece is at stage "brief"
    And the piece title is "Test Story"

  Scenario: Advance through stages
    Given a piece "my-story" at stage "brief"
    When I advance the piece
    Then the piece is at stage "outline"
    When I advance the piece
    Then the piece is at stage "draft"

  Scenario: Rename does not change stage
    Given a piece "test-piece" at stage "humanize"
    When I rename the piece to "Renamed Piece"
    Then the piece title is "Renamed Piece"
    And the piece is still at stage "humanize"
    And the meta.yaml has current_stage "humanize"
    And the stage file content is preserved

  Scenario: Rename does not overwrite stage file with frontmatter
    Given a piece "runner-piece" at stage "review"
    And the review.md has runner-style content without frontmatter
    When I rename the piece to "Runner Test"
    Then the review.md still has no frontmatter
    And the meta.yaml has the new title "Runner Test"

  Scenario: Reject to previous stage
    Given a piece "reject-piece" at stage "revise"
    When I reject the piece to stage "draft"
    Then the piece is at stage "draft"

  Scenario: Body length is non-zero when stage files exist
    Given a piece "body-test" with content in stage files
    When I fetch the piece detail
    Then the body_length is greater than 0
    And the body is not empty

  Scenario: Cannot advance past done
    Given a piece "done-piece" at stage "done"
    When I advance the piece
    Then I get an error containing "final stage"

  Scenario: Duplicate piece creation fails
    Given a piece "dupe-test" exists
    When I create a piece with title "Dupe Test" and genre "fiction"
    Then I get an error containing "already exists"
