import { describe, it, expect, beforeEach, vi } from 'vitest';
import { JSDOM } from 'jsdom';
import fs from 'fs';
import path from 'path';

const dashboardViewJsCode = fs.readFileSync(
  path.resolve(__dirname, '../../src/quill/static/js/dashboard_view.js'),
  'utf8'
);

describe('dashboard_view.js createPiece', () => {
  let dom;

  beforeEach(() => {
    dom = new JSDOM(`
      <!DOCTYPE html>
      <html>
      <body>
        <div id="stats"></div>
        <table><tbody id="pieces-table"></tbody></table>
        <div id="create-modal">
          <form id="create-form">
            <input type="text" id="f-title" value="Test title">
            <select id="f-genre"><option value="fiction">Fiction</option></select>
            <select id="f-type"><option value="story">Story</option></select>
            <input type="text" id="f-audience" value="gamers">
            <input type="text" id="f-tone" value="casual">
            <select id="f-language"><option value="en">English</option></select>
            <input type="text" id="f-length" value="1000 words">
            <textarea id="f-body">This is the brief.</textarea>
            <input type="radio" name="trigger" value="on_advance" checked>
          </form>
        </div>
      </body>
      </html>
    `, { runScripts: "dangerously" });

    global.window = dom.window;
    global.document = dom.window.document;
    global.toast = vi.fn();
    
    // api mock handles both POST creation and GET listing
    global.api = vi.fn().mockImplementation((path, opts) => {
      if (path === '/api/pieces' && opts?.method === 'POST') {
        return Promise.resolve({ id: 'test-id', title: 'Test title' });
      }
      return Promise.resolve({ count: 0, pieces: [] });
    });
    global.closeModal = vi.fn();

    // Bind to window to simulate scripts loading in same window context
    dom.window.toast = global.toast;
    dom.window.api = global.api;
    dom.window.closeModal = global.closeModal;

    // Load dashboard_view.js
    const script = dom.window.document.createElement('script');
    script.textContent = dashboardViewJsCode;
    dom.window.document.body.appendChild(script);
  });

  it('collects f-body brief content and sends it to the API, then resets form', async () => {
    const event = { preventDefault: vi.fn() };
    
    // Spy on form reset
    const form = dom.window.document.getElementById('create-form');
    const resetSpy = vi.spyOn(form, 'reset');
    
    await dom.window.createPiece(event);

    expect(global.api).toHaveBeenCalledWith('/api/pieces', {
      method: 'POST',
      body: JSON.stringify({
        title: 'Test title',
        genre: 'fiction',
        type: 'story',
        audience: 'gamers',
        tone: 'casual',
        language: 'en',
        target_length: '1000 words',
        body: 'This is the brief.',
        trigger: 'on_advance',
      })
    });
    
    expect(resetSpy).toHaveBeenCalled();
  });
});
