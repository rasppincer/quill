# Design Spec: Brief Input on New Piece Modal

## Goal
To allow users to input a Brief / Prompt at the time of creating a new piece from the Quill dashboard modal. This eliminates the awkward extra step of requesting the brief after the piece has already been initialized, facilitating a one-click automated execution.

## Proposed Changes

### Frontend Template
Modify [dashboard.html](file:///home/bob/projects/quill/src/quill/templates/dashboard.html):
- Add a `<label>Brief / Prompt</label>` and `<textarea id="f-body" placeholder="Outline the main goals, characters, plot points, or requirements..."></textarea>` before the Trigger Mode radio buttons selection.

### Frontend Logic
Modify [dashboard_view.js](file:///home/bob/projects/quill/src/quill/static/js/dashboard_view.js):
- In the `createPiece(e)` function, capture the value of the brief textarea using `document.getElementById('f-body').value`.
- Send this value in the JSON payload of the POST request to `/api/pieces` under the key `"body"`.
- Clear/reset the modal form elements after a successful piece creation (or when closing/opening the modal) to ensure a clean state.

### Backend Tests
Modify [test_app.py](file:///home/bob/projects/quill/tests/test_app.py):
- Add a new test `test_create_piece_with_brief` to verify that passing `body` during piece creation correctly persists the brief content to the `01_brief.md` file.

## Verification Plan

### Automated Tests
- Run `pytest` to verify the backend creation API changes.
- Run frontend tests using `npm run test` (vitest).

### Manual Verification
- Launch the Quill application, click "+ New Piece", enter details along with a Brief, and verify the piece is created with the brief content pre-populated in the Brief stage.
