import { describe, it, expect, beforeEach, vi } from 'vitest';
import { JSDOM, VirtualConsole } from 'jsdom';
import fs from 'fs';
import path from 'path';

const pieceJsCode = fs.readFileSync(
  path.resolve(__dirname, '../../src/quill/static/js/piece.js'),
  'utf8'
);

describe('piece.js EventSource / SSE handlers tests', () => {
  let dom;

  function buildDom() {
    // Suppress JSDOM "Not implemented: navigation" stderr noise
    const virtualConsole = new VirtualConsole();
    virtualConsole.sendTo(console, { omitJSDOMErrors: true });

    return new JSDOM(`
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
        <div id="trigger-display"></div>
        <button id="auto-btn"></button>
        <button id="interrupt-btn" style="display: none;"></button>
        <button id="execute-btn"></button>
        <button id="advance-btn"></button>
        <button id="save-content-btn"></button>
        <button id="delete-piece-btn"></button>
        <textarea id="prompt-editor"></textarea>
        <textarea id="content-editor"></textarea>
        <pre id="raw-json-content"></pre>
        <div id="execute-status"></div>
        <div id="run-log-panel"></div>
        <div id="run-log-entries"></div>
        <div id="run-log-toggle"></div>
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
    `, { runScripts: "dangerously", virtualConsole });
  }

  function setupDom() {
    dom = buildDom();

    dom.window.eventSources = [];
    const domRef = dom;

    class BoundMockEventSource {
      constructor(url) {
        this.url = url;
        this.listeners = {};
        this.readyState = 0; // CONNECTING
        domRef.window.eventSources.push(this);
      }
      addEventListener(event, callback) {
        this.listeners[event] = this.listeners[event] || [];
        this.listeners[event].push(callback);
      }
      close() {
        this.readyState = 2; // CLOSED
      }
      emit(event, data) {
        if (this.listeners[event]) {
          this.listeners[event].forEach(cb => cb({ data: JSON.stringify(data) }));
        }
      }
    }
    BoundMockEventSource.CLOSED = 2;
    dom.window.EventSource = BoundMockEventSource;
    global.EventSource = BoundMockEventSource;

    const fetchMock = vi.fn().mockResolvedValue({ json: async () => ({}) });
    dom.window.fetch = fetchMock;
    dom.window.toast = vi.fn();
    dom.window.locationReloadMock = vi.fn();
    dom.window.SCRIPT_ROOT = '';

    global.window = dom.window;
    global.document = dom.window.document;
    global.fetch = fetchMock;
    global.toast = dom.window.toast;

    const script = dom.window.document.createElement('script');
    script.textContent = `const location = { reload: () => window.locationReloadMock() };\n` + pieceJsCode;
    dom.window.document.body.appendChild(script);

    return fetchMock;
  }

  beforeEach(() => {
    setupDom();
  });

  it('connectAutoSSE chain_stage_complete event should refresh stage tabs', () => {
    dom.window.refreshStageTabs = vi.fn();
    dom.window.connectAutoSSE('run-123');
    const es = dom.window.eventSources[0];
    es.emit('chain_stage_complete', { stage: 'draft' });
    expect(dom.window.refreshStageTabs).toHaveBeenCalled();
  });

  it('connectAutoSSE chain_complete event should close and show success toast and reload', () => {
    dom.window.connectAutoSSE('run-123');
    const es = dom.window.eventSources[0];
    const closeSpy = vi.spyOn(es, 'close');

    es.emit('chain_complete', {});

    expect(closeSpy).toHaveBeenCalled();
    expect(dom.window.toast).toHaveBeenCalledWith('Auto pipeline complete!', 'success');
    expect(dom.window.locationReloadMock).toHaveBeenCalled();
  });

  it('connectAutoSSE chain_interrupted event should close and show info toast and reload', () => {
    dom.window.connectAutoSSE('run-123');
    const es = dom.window.eventSources[0];
    const closeSpy = vi.spyOn(es, 'close');

    es.emit('chain_interrupted', {});

    expect(closeSpy).toHaveBeenCalled();
    expect(dom.window.toast).toHaveBeenCalledWith('Pipeline interrupted', 'info');
    expect(dom.window.locationReloadMock).toHaveBeenCalled();
  });

  it('connectAutoSSE error event in CLOSED readyState resets auto buttons', () => {
    dom.window.connectAutoSSE('run-123');
    const es = dom.window.eventSources[0];
    es.readyState = 2; // CLOSED

    es.listeners['error'].forEach(cb => cb({}));

    const autoBtn = dom.window.document.getElementById('auto-btn');
    expect(autoBtn.disabled).toBe(false);
    expect(autoBtn.textContent).toBe('▶ Auto Pipeline');
  });

  it('executeStage SSE flow should append log and update status on completion', async () => {
    dom.window.fetch = vi.fn().mockResolvedValueOnce({
      json: async () => ({ run_id: 'run-456' })
    });
    dom.window.navigateToStage = vi.fn();
    dom.window.loadRunLog = vi.fn();

    await dom.window.executeStage();

    const es = dom.window.eventSources[0];
    expect(es.url).toContain('/runs/run-456/events');

    es.emit('stage_start', { stage: 'draft' });
    expect(dom.window.document.getElementById('run-log-entries').innerHTML).toContain('Stage start:');

    es.emit('stage_complete', {});
    expect(dom.window.document.getElementById('run-log-entries').innerHTML).toContain('Stage complete');

    const closeSpy = vi.spyOn(es, 'close');
    es.emit('run_complete', {});

    expect(closeSpy).toHaveBeenCalled();
    expect(dom.window.document.getElementById('execute-status').textContent).toBe('Complete');
    expect(dom.window.toast).toHaveBeenCalledWith('Execution complete', 'success');
    expect(dom.window.navigateToStage).toHaveBeenCalled();
    expect(dom.window.loadRunLog).toHaveBeenCalled();
  });
});
