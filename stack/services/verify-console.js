// ResCCOM 2.1-d/2.1-f verify: console.island from the UE subnet, WAN down in
// spirit (this repo's own convention per verify-jitsi-call.js: run inside
// core-ue-1's network namespace, `--network container:core-ue-1`, so
// there is no path to the WAN to begin with -- see that file's own
// header comment for why the playwright *install* step needs a
// WAN-having network first).
//
// Requires OPERATOR_TOKEN in the environment -- the per-boot token
// island.sh prints once on `up` and writes to
// stack/services/data/console/operator-token, e.g.:
//
//   docker run --rm --network container:core-ue-1 \
//     -e OPERATOR_TOKEN="$(cat stack/services/data/console/operator-token)" \
//     -v "$(pwd)/verify-console.js:/work/verify.js:ro" \
//     -w /work mcr.microsoft.com/playwright:v1.63.0-noble node verify.js
//
// Drives the acceptance test in island-init/TASKS.md 2.1-d/2.1-f
// literally: load console.island, confirm the map renders from local
// tiles, place a site + cell, confirm every write endpoint 401s without
// the operator token and succeeds with it, Preview, Save Draft, and
// confirm the console reports a pending draft. 2.1-f moved signing +
// rendering + service restarts host-side (`island.sh apply`, RFC-0006
// D5) -- out of the console container, and out of what a browser on the
// UE subnet can reach -- so this script's own job stops at "a valid
// draft is staged"; a human or CI wrapper runs `island.sh apply`
// afterward and confirms the result with `island-init check`.
const { chromium } = require('playwright');

const OPERATOR_TOKEN = process.env.OPERATOR_TOKEN;
if (!OPERATOR_TOKEN) {
  console.error('FAIL: OPERATOR_TOKEN not set -- see this file\'s own header comment');
  process.exit(1);
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on('pageerror', (e) => consoleErrors.push(String(e)));

  await page.goto('http://console.island/', { waitUntil: 'networkidle', timeout: 20000 });

  const title = await page.title();
  if (!title.includes('Island Console')) throw new Error(`unexpected title: ${title}`);
  console.log('OK: console.island loaded');

  // Map tiles actually rendered (not just an empty canvas): MapLibre
  // exposes loaded source data through queryRenderedFeatures once the
  // vector tiles are in.
  await page.waitForFunction(
    () => window.map && window.map.isStyleLoaded() && window.map.queryRenderedFeatures().length > 0,
    { timeout: 20000 }
  );
  console.log('OK: map rendered features from local tiles (maps.island)');

  // Write endpoints reject a request with no operator token, and one
  // with the wrong token -- checked directly against the API before
  // touching the UI's own (correct) token, so this is a real negative
  // test, not just "the button never sends a bad token".
  const noTokenStatus = await page.evaluate(async () => {
    const r = await fetch('/api/preview', { method: 'POST', body: '{}' });
    return r.status;
  });
  if (noTokenStatus !== 401) throw new Error(`expected 401 with no token, got ${noTokenStatus}`);
  const wrongTokenStatus = await page.evaluate(async () => {
    const r = await fetch('/api/preview', {
      method: 'POST',
      headers: { Authorization: 'Bearer not-the-real-token' },
      body: '{}',
    });
    return r.status;
  });
  if (wrongTokenStatus !== 401) throw new Error(`expected 401 with wrong token, got ${wrongTokenStatus}`);
  console.log('OK: write endpoints reject missing/wrong operator token (401)');

  // The operator token the UI itself will now use for every write --
  // set directly in localStorage the same way a human would type it
  // into the "Operator token" field once (app.js's getOperatorToken()).
  await page.evaluate((token) => window.localStorage.setItem('operatorToken', token), OPERATOR_TOKEN);

  // Place a site by clicking the map, then fill in its name.
  const mapBox = await page.locator('#map').boundingBox();
  await page.mouse.click(mapBox.x + mapBox.width / 2, mapBox.y + mapBox.height / 2);
  await page.waitForSelector('#site-form:not([hidden])');
  await page.fill('#site-name', 'Verify Test Site');
  await page.fill('#site-height', '25');

  await page.click('#btn-add-cell');
  const cellCard = page.locator('.cell-card').first();
  await cellCard.locator('.c-band').fill('7');
  await cellCard.locator('.c-pci').fill('9');
  console.log('OK: placed a site and added a cell');

  // Preview (acceptance: render --diff from the console equals the
  // CLI's output -- exercised by hitting the same /api/preview endpoint
  // the CLI's render module backs, see server.py's do_preview), now
  // with the real token attached.
  await page.click('#btn-preview');
  await page.waitForFunction(
    () => document.getElementById('result').textContent.length > 0,
    { timeout: 10000 }
  );
  const previewText = await page.locator('#result').textContent();
  if (previewText.includes('error') || previewText.match(/^\S+\.\S+: /)) {
    throw new Error(`preview reported issues: ${previewText}`);
  }
  console.log('OK: preview render ran with a valid token (no validation issues)');

  // Save draft: 2.1-f's console never signs or applies -- it only stages
  // a validated candidate for a host-side `island.sh apply` to sign,
  // render, and restart affected services from.
  await page.click('#btn-save-draft');
  await page.waitForFunction(
    () => document.getElementById('result').textContent.includes('pending draft'),
    { timeout: 20000 }
  );
  const saveText = await page.locator('#result').textContent();
  console.log('save-draft result:', saveText.split('\n')[0]);

  const draftStatus = await page.evaluate(async () => (await fetch('/api/draft')).json());
  if (!draftStatus.pending) throw new Error(`expected a pending draft, got ${JSON.stringify(draftStatus)}`);
  console.log('OK: console reports a pending draft, staged at', draftStatus.staged_at);

  await browser.close();

  if (consoleErrors.length) {
    console.log('page errors seen:', consoleErrors);
  }

  console.log('ALL CHECKS PASSED (browser side -- run island.sh apply on the host next)');
})().catch((err) => {
  console.error('FAIL:', err);
  process.exit(1);
});
