import { describe, it, expect, beforeEach, vi } from 'vitest';
import { JSDOM } from 'jsdom';
import fs from 'fs';
import path from 'path';

const dashboardJsCode = fs.readFileSync(
  path.resolve(__dirname, '../../src/quill/static/js/dashboard.js'),
  'utf8'
);

describe('dashboard.js modal interactions', () => {
  let dom;

  beforeEach(() => {
    dom = new JSDOM(`
      <!DOCTYPE html>
      <html>
      <body>
        <div class="modal-overlay">
          <div class="modal-content">Create Piece Form</div>
        </div>
      </body>
      </html>
    `, { runScripts: "dangerously" });

    // Set globals for tests
    global.window = dom.window;
    global.document = dom.window.document;
    global.location = dom.window.location;

    // Load dashboard.js
    const script = dom.window.document.createElement('script');
    script.textContent = dashboardJsCode;
    dom.window.document.body.appendChild(script);
  });

  it('closes modal on Escape key down', () => {
    const event = new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
    dom.window.document.dispatchEvent(event);
    expect(dom.window.document.querySelector('.modal-overlay')).toBeNull();
  });

  it('closes modal on click-outside (overlay click)', () => {
    const overlay = dom.window.document.querySelector('.modal-overlay');
    overlay.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
    expect(dom.window.document.querySelector('.modal-overlay')).toBeNull();
  });
});
