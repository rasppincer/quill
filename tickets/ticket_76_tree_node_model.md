# Ticket 76: Implement Hierarchical Tree-Node Document Model

## Description
Implement a hierarchical tree-node document model to natively represent long-form pieces (Volumes, Chapters, Scenes, etc.).

## Background
Quill currently struggles with multi-chapter content, requiring either flat draft generation or programmatically creating sibling directories under parent-child string patterns. A tree-node architecture treats each section as a nested database node.

## Tasks
- [ ] Create `src/quill/structure.py` or modify document models to include `parent_node_id` and `node_type` (Project, Chapter, Scene).
- [ ] Implement recursive node traversal, section concatenation, and node order management.
- [ ] Update frontend Piece detail views to show tree-structure nodes.

## Success Criteria
- [ ] A Project can have arbitrary nested child chapters/sections.
- [ ] Parent node automatically updates its metrics/content when child nodes change.

## Priority
High

---
**Next Expected Ticket Number**: 77
