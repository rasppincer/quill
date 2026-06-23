Feature: Research stage
  As a writer using Quill
  I want a research stage that fetches reference material
  So that my drafts are informed by real sources

  Background:
    Given a clean Quill instance

  Scenario: Pipeline includes research stage
    When I query the pipeline info
    Then the pipeline has 10 stages
    And "research" is between "outline" and "draft" in the stage order

  Scenario: Outline routes to research (not directly to draft)
    Given the pipeline stage definitions
    Then "outline" next stage is "research"

  Scenario: Research routes to draft
    Given the pipeline stage definitions
    Then "research" next stage is "draft"

  Scenario: Research config for non-fiction
    When I load the research config for agent set "non-fiction"
    Then research is enabled
    And research is required

  Scenario: Research config for fiction
    When I load the research config for agent set "fiction"
    Then research is enabled
    And research is not required

  Scenario: Draft reads research.md as input
    Given the pipeline stage_inputs configuration
    Then "draft" stage inputs include "research.md"

  Scenario: Research reads outline and brief as input
    Given the pipeline stage_inputs configuration
    Then "research" stage inputs include "outline.md"
    And "research" stage inputs include "brief.md"

  Scenario: Research is a special stage (no mode field needed)
    Given the pipeline stage definitions
    Then "research" stage has no prompt requirement in the default agent set
