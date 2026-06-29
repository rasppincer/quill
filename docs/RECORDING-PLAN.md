# Quill Demo Recording Plan

**Purpose:** Record a desktop demo of Quill generating ABQTester content, using authority-chain for claim verification. For the Nous/NVIDIA/Stripe hackathon submission.

**Date:** TBD (blocked on LAN LLM at 192.168.0.3:1234 being up)

## Technical Setup

- **Display:** 1536×864 (HDMI-A-2 native). Record at native res, upscale to 1080p in post.
  - 1080p profile exists on `lease-HDMI-A-2` but is disconnected — plug into that output if available.
- **Recording:** VLC, no audio (add narration in post)
  ```bash
  timeout <seconds> cvlc screen:// --screen-fps=15 --no-audio \
    --sout '#transcode{vcodec=h264,vb=4096}:std{access=file,mux=mp4,dst=/mnt/usb/quill-demo-YYYYMMDD.mp4}'
  ```
- **Output:** `/mnt/usb/` (USB700, 656GB free, exFAT, no sudo needed)
- **Post-process:** ffmpeg upscale
  ```bash
  ffmpeg -i /mnt/usb/quill-demo-raw.mp4 -vf scale=1920:1080 -c:v libx264 -crf 18 \
    /mnt/usb/quill-demo-1080p.mp4
  ```

## Pre-flight Checklist

- [ ] LAN LLM up at 192.168.0.3:1234 (test: `curl -s http://192.168.0.3:1234/v1/models`)
- [ ] Quill service running (`systemctl --user status quill`)
- [ ] Authority-chain service running (`systemctl --user status authority-chain`)
- [ ] Browser full-screen (F11)
- [ ] Browser bookmarks bar hidden
- [ ] Close unnecessary tabs / notifications
- [ ] Test VLC capture with a 5s dry run

## Scenes

### Scene 1 — Quill Dashboard (~30s)
- Open `http://localhost:8325/dashboard`
- Show existing pieces — highlight completed ones (gold-collapse, seo-practices, TaskForge)
- Show pipeline progress bars

### Scene 2 — Create New Piece (~30s)
- Create piece: "ABQTester: Async Standups Landing Page"
- Metadata: genre=non-fiction, type=article, audience=developers
- Land on brief stage

### Scene 3 — Write Brief + Run Pipeline (~2-3 min)
- Write a brief describing ABQTester landing page content
- Save brief → advance
- Walk through stages: outline → research → draft → review → revise
- At each stage: show agent result (decision + critique)
- Highlight the two-call flow: generate → evaluate → advance/loop

### Scene 4 — Authority Chain Verification (~30s)
- Terminal: curl authority-chain API
- Verify a claim from the generated text
- Show tree output (Wikipedia → DOI → PubMed = high score)
- Optionally contrast with a zeitgeist claim (low score)

### Scene 5 — Final Piece (~30s)
- Navigate back to piece
- Show polished content in stage viewer
- Show run log (all stage transitions)
- Show text metrics (Flesch, word count, grade level, passive voice)

## ABQTester Context

- Project: `~/projects/ABQTester/`
- Existing content: `content/syncgrid_article_standups.md`, `content/flowpulse_article_standups.md`
- Strategy: A/B conversion campaign — two product variants, Quill generates content for the treatment variant
- TODO.md has Phase 5 completed (baseline articles generated)

## Notes

- If 1080p HDMI output is available, switch display to it before recording for native quality
- Keep browser zoom at 100% for consistent text rendering
- The demo should feel like a real workflow, not a rehearsed script
- Authority-chain demo works now (no LLM dependency) — can record that scene independently
