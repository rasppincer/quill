# Design Spec: Deleting Pieces in Quill

Date: 2026-07-05
Author: Antigravity

## Goal
Provide a clean mechanism to permanently delete pieces/projects in Quill from both the SQLite database and the filesystem (`output/` directory), accessible via API and the web UI (Dashboard and Piece View).

## Requirements
1. **Database Cleanup**: Delete SQL records for `Project` and `DocumentNode` by ID. Associated records in `stage_states`, `metrics`, and `agent_logs` must be automatically deleted via cascading foreign keys (`ondelete="CASCADE"`, `cascade="all, delete-orphan"`).
2. **Filesystem Cleanup**: Delete the piece's directory under `output/<piece_id>` or a standalone legacy file `output/<piece_id>.md`.
3. **Safety Guard**: Prevent deletion if the piece currently has a running agent job (checked via `RunManager().is_piece_running(piece_id)`).
4. **UI Integration**:
   - **Dashboard**: Row-level "Delete" button inside the pieces list table.
   - **Piece View**: A "Delete" button in the top action bar.
   - **Confirmation**: Prompts the user with a confirmation dialog before deleting.

## Architecture & Data Flow
1. User clicks the Delete button in the UI.
2. The UI shows a confirmation dialog.
3. If confirmed, the UI sends a `DELETE /api/pieces/<piece_id>` request.
4. The server validates that no active runs are executing for this piece.
5. The server deletes DB records, commits the transaction, and deletes the corresponding filesystem assets.
6. The server returns a JSON success response.
7. The UI displays a toast notification and either refreshes the dashboard list or redirects the user back to the dashboard.

## Proposed Changes

### Backend Blueprint
Modify `src/quill/blueprints/pieces.py` to add the `DELETE /api/pieces/<piece_id>` endpoint.

### Dashboard Template
Modify `src/quill/templates/dashboard.html` to add the Delete button in the actions column and the `deletePiece()` JavaScript function.

### Piece Template
Modify `src/quill/templates/piece.html` to add the `🗑 Delete` button to the action bar and the `deleteCurrentPiece()` JavaScript function.
