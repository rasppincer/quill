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
        <button id="run-agent-btn"></button>
        <button id="advance-btn"></button>
        <button id="interrupt-btn" style="display: none;"></button>
        <select id="agent-select"></select>

        <!-- Mock initialization elements to prevent DOMContentLoaded errors -->
        <div id="viewing-stage-display"></div>
        <div id="content-heading"></div>
        <div id="stage-content"></div>
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

  it('should disable run and advance buttons when auto trigger and interrupt is visible', () => {
    dom.window.document.getElementById('trigger-select').value = 'auto';
    dom.window.document.getElementById('interrupt-btn').style.display = 'block';
    
    dom.window.updateButtonStates();

    expect(dom.window.document.getElementById('run-agent-btn').disabled).toBe(true);
    expect(dom.window.document.getElementById('advance-btn').disabled).toBe(true);
  });

  it('should enable run and advance buttons when trigger is manual', () => {
    dom.window.document.getElementById('trigger-select').value = 'manual';
    dom.window.updateButtonStates();

    expect(dom.window.document.getElementById('run-agent-btn').disabled).toBe(false);
    expect(dom.window.document.getElementById('advance-btn').disabled).toBe(false);
  });

  it('should populate agent selection for research stage without backend call', async () => {
    await dom.window.loadAgentsForStage('research');
    const select = dom.window.document.getElementById('agent-select');
    expect(select.innerHTML).toContain('ResearchService');
  });
});
