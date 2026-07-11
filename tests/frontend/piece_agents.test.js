import { describe, it, expect, beforeEach, vi } from 'vitest';
import { JSDOM } from 'jsdom';
import fs from 'fs';
import path from 'path';

const pieceJsCode = fs.readFileSync(
  path.resolve(__dirname, '../../src/quill/static/js/piece.js'),
  'utf8'
);

describe('piece.js loadAgentsForStage tests', () => {
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
        <button id="auto-btn"></button>

        <select id="agent-select"></select>
        <button id="run-agent-btn"></button>
        
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

    global.window = dom.window;
    global.document = dom.window.document;
    global.SCRIPT_ROOT = '';
    global.PIECE_AGENT_SET = 'fiction';
    global.toast = vi.fn();
    global.fetch = vi.fn();
    dom.window.SCRIPT_ROOT = '';
    dom.window.PIECE_AGENT_SET = 'fiction';
    dom.window.toast = global.toast;
    dom.window.fetch = global.fetch;

    // Return empty mock responses for initial fetches on DOMContentLoaded to avoid errors
    global.fetch.mockResolvedValue({
      json: async () => ({})
    });

    const script = dom.window.document.createElement('script');
    script.textContent = pieceJsCode;
    dom.window.document.body.appendChild(script);
  });

  it('should populate agent selection for research stage without backend call', async () => {
    await dom.window.loadAgentsForStage('research');
    const select = dom.window.document.getElementById('agent-select');
    expect(select.innerHTML).toContain('ResearchService');
    const btn = dom.window.document.getElementById('run-agent-btn');
    expect(btn.disabled).toBe(false);
    expect(btn.textContent).toBe('🔍 Run Research');
  });

  it('should handle empty agent sets gracefully', async () => {
    global.fetch.mockResolvedValueOnce({
      json: async () => ({ agent_sets: [] })
    });
    await dom.window.loadAgentsForStage('outline');
    const select = dom.window.document.getElementById('agent-select');
    expect(select.innerHTML).toContain('No agents for this stage');
    const btn = dom.window.document.getElementById('run-agent-btn');
    expect(btn.disabled).toBe(true);
  });

  it('should populate options and auto-select active agent set', async () => {
    global.fetch.mockResolvedValueOnce({
      json: async () => ({ agent_sets: [{ name: 'default' }, { name: 'fiction' }] })
    });
    await dom.window.loadAgentsForStage('outline');
    const select = dom.window.document.getElementById('agent-select');
    expect(select.children.length).toBe(2);
    expect(select.children[0].value).toBe('default');
    expect(select.children[1].value).toBe('fiction');
    expect(select.value).toBe('fiction');
  });
});
