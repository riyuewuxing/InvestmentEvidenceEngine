// Independent public visual transport smoke test. No private checkout or arbitrary URLs.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');
const assert = require('node:assert/strict');

async function main() {
  const output = process.argv[2];
  assert.ok(output, 'output directory required');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const [name, viewport] of [
      ['browser-desktop', { width: 1200, height: 760 }],
      ['browser-mobile', { width: 390, height: 844 }],
    ]) {
      const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
      const errors = [];
      page.on('pageerror', (err) => errors.push(err.message));
      await page.route('**/*', route => {
        if (route.request().url().startsWith('file:')) return route.continue();
        return route.abort();
      });
      await page.goto(pathToFileURL(path.join(__dirname, 'fixture.html')).href);
      await page.getByRole('button', { name: 'Run UI check' }).click();
      assert.equal(await page.getByRole('status').textContent(), 'Interaction passed');
      const layout = await page.evaluate(() => ({
        width: document.documentElement.scrollWidth,
        viewport: window.innerWidth,
        columns: getComputedStyle(document.querySelector('.grid')).gridTemplateColumns.split(' ').length,
        visible: !!document.querySelector('.chart').getBoundingClientRect().width,
      }));
      assert.equal(layout.width, layout.viewport, 'horizontal overflow');
      assert.equal(layout.columns, name === 'browser-mobile' ? 1 : 2);
      assert.equal(layout.visible, true);
      assert.deepEqual(errors, []);
      await page.screenshot({ path: path.join(output, name + '.png'), animations: 'disabled' });
      console.log('VISUAL_LAYOUT ' + JSON.stringify({ name, viewport, ...layout }));
      await page.close();
    }
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
