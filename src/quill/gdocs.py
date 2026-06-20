"""Google Docs connector — push pieces to Google Docs.

Uses the Hermes-managed OAuth token at ~/.hermes/google_token.json.
Requires: google-api-python-client, google-auth-oauthlib, google-auth-httplib2
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

TOKEN_PATH = Path.home() / ".hermes" / "google_token.json"
SCOPES = ["https://www.googleapis.com/auth/documents"]


def _get_credentials():
    """Load OAuth2 credentials from the Hermes token file."""
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(
            f"Google token not found at {TOKEN_PATH}. "
            "Run the google-workspace setup first."
        )

    from google.oauth2.credentials import Credentials

    token_data = json.loads(TOKEN_PATH.read_text())
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes"),
    )
    return creds


def _get_docs_service():
    """Build a Google Docs API service client."""
    from googleapiclient.discovery import build

    creds = _get_credentials()
    return build("docs", "v1", credentials=creds)


def create_doc(title: str, content: str) -> dict:
    """Create a new Google Doc with the given title and content.

    Args:
        title: Document title.
        content: Markdown-ish content to write. Supports:
            - Lines starting with # → Heading 1
            - Lines starting with ## → Heading 2
            - Lines starting with ### → Heading 3
            - Blank lines → paragraph breaks
            - Everything else → body text

    Returns:
        dict with 'documentId', 'title', 'url'.
    """
    service = _get_docs_service()

    # Create the doc
    doc = service.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

    logger.info("Created Google Doc '%s' (%s)", title, doc_id)

    # Build the request body from content
    requests = _build_content_requests(content)
    if requests:
        service.documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()
        logger.info("Wrote %d formatting requests to doc %s", len(requests), doc_id)

    return {
        "documentId": doc_id,
        "title": title,
        "url": doc_url,
    }


def _build_content_requests(content: str) -> list[dict]:
    """Convert content to Google Docs API batchUpdate requests.

    Inserts text and applies heading styles for lines starting with #.
    """
    if not content or not content.strip():
        return []

    requests = []
    lines = content.split("\n")
    full_text = ""
    style_ranges = []

    for line in lines:
        start = len(full_text)

        # Detect heading lines
        heading_level = 0
        text = line
        if line.startswith("### "):
            heading_level = 3
            text = line[4:]
        elif line.startswith("## "):
            heading_level = 2
            text = line[3:]
        elif line.startswith("# "):
            heading_level = 1
            text = line[2:]

        full_text += text + "\n"
        end = len(full_text)

        if heading_level > 0:
            style_ranges.append((start, end, heading_level))

    # Insert all text at index 1 (after the doc's empty paragraph)
    requests.append(
        {
            "insertText": {
                "location": {"index": 1},
                "text": full_text,
            }
        }
    )

    # Apply heading styles
    HEADING_MAP = {
        1: "HEADING_1",
        2: "HEADING_2",
        3: "HEADING_3",
    }

    for start, end, level in style_ranges:
        # +1 offset because we insert at index 1
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": {
                        "startIndex": 1 + start,
                        "endIndex": 1 + end - 1,  # exclude trailing newline
                    },
                    "paragraphStyle": {
                        "namedStyleType": HEADING_MAP[level],
                    },
                    "fields": "namedStyleType",
                }
            }
        )

    return requests
