import { describe, it, expect, beforeEach, vi } from 'vitest';
import { JSDOM } from 'jsdom';
import fs from 'fs';
import path from 'path';

const pieceJsCode = fs.readFileSync(
  path.resolve(__dirname, '../../src/quill/static/js/piece.js'),
  'utf8'
);

describe('piece.js tests', () => {
  let dom;

  beforeEach(() => {
    dom = new JSDOM(`
      <!DOCTYPE html>
      <html>
      <body>
        <script id="piece-data" type="application/json">
        {
          "piece_id": "test-id",
          "current_stage": "outline",
          "piece_agent_set": "fiction",
          "pipeline_order": ["brief", "outline", "draft"]
        }
        </script>
        <select id="trigger-select">
          <option value="manual">Manual</option>
          <option value="on_advance">On Advance</option>
          <option value="auto">Auto</option>
        </select>
        <textarea id="prompt-editor"></textarea>
        <textarea id="content-editor"></textarea>
        <pre id="raw-json-content"></pre>
        <button id="execute-btn"></button>
        <button id="save-content-btn"></button>
        <button id="advance-btn"></button>
        <button id="interrupt-btn" style="display: none;"></button>
        <button id="delete-piece-btn"></button>

        <!-- Mock initialization elements to prevent DOMContentLoaded errors -->
        <div id="viewing-stage-display"></div>
        <div id="content-heading"></div>
        <div id="chapter-breakdown"></div>
        <div id="stage-state-badge"></div>
        <div id="stage-metrics"></div>
        <div id="stage-metrics-grid"></div>
        <div id="audio-section"></div>
        <div id="audio-files"></div>
      </body>
      </html>
    `, { runScripts: "dangerously" });

    // Set globals for tests to point to the current JSDOM instance
    global.window = dom.window;
    global.document = dom.window.document;
    global.SCRIPT_ROOT = '';
    global.toast = vi.fn();
    global.fetch = vi.fn();
    dom.window.SCRIPT_ROOT = '';
    dom.window.toast = global.toast;
    dom.window.fetch = global.fetch;

    // Load piece.js in this JSDOM context
    const script = dom.window.document.createElement('script');
    script.textContent = pieceJsCode;
    dom.window.document.body.appendChild(script);
  });

  it('should disable execute and advance buttons when auto trigger and interrupt is visible', () => {
    dom.window.document.getElementById('trigger-select').value = 'auto';
    dom.window.document.getElementById('interrupt-btn').style.display = 'block';
    
    dom.window.updateButtonStates();

    expect(dom.window.document.getElementById('execute-btn').disabled).toBe(true);
    expect(dom.window.document.getElementById('advance-btn').disabled).toBe(true);
  });

  it('should enable execute and advance buttons when trigger is manual', () => {
    dom.window.document.getElementById('trigger-select').value = 'manual';
    dom.window.updateButtonStates();

    expect(dom.window.document.getElementById('execute-btn').disabled).toBe(false);
    expect(dom.window.document.getElementById('advance-btn').disabled).toBe(false);
  });

  it('should toggle element disabled states during setLockState', () => {
    dom.window.setLockState(true);
    expect(dom.window.document.getElementById('prompt-editor').disabled).toBe(true);
    expect(dom.window.document.getElementById('content-editor').disabled).toBe(true);
    expect(dom.window.document.getElementById('execute-btn').disabled).toBe(true);
    expect(dom.window.document.getElementById('save-content-btn').disabled).toBe(true);

    dom.window.setLockState(false);
    expect(dom.window.document.getElementById('prompt-editor').disabled).toBe(false);
    expect(dom.window.document.getElementById('content-editor').disabled).toBe(false);
    expect(dom.window.document.getElementById('execute-btn').disabled).toBe(false);
    expect(dom.window.document.getElementById('save-content-btn').disabled).toBe(false);
  });
});
