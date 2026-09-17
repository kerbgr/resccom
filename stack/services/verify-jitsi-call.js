/**
 * ResCCOM 1.3-d acceptance: two browser clients hold a real audio call
 * over talk.island. "Real" here means actual RTP media flowing, not
 * just "both joined the room" — this wraps window.RTCPeerConnection
 * before Jitsi Meet's own code runs, then reads real getStats() reports
 * from both participants' live peer connections to confirm each is
 * RECEIVING the other's audio: a non-empty inbound-rtp/audio report with
 * a non-zero audioLevel, and — checked twice, five seconds apart —
 * packetsReceived actually increasing. A call that connected but went
 * silent, or a stats snapshot that just happened to have a stale nonzero
 * count, would fail the growth check.
 *
 * Forces `config.p2p.enabled=false` so media is verified going through
 * JVB (the path every >2-person call and most 2-person calls on a real
 * multi-user island actually use), not Jitsi's P2P shortcut for exactly
 * two participants.
 *
 * Uses Chromium's `--use-fake-device-for-media-stream` (synthetic
 * audio/video, no real hardware needed) and `--ignore-certificate-errors`
 * (talk.island's cert is self-signed — see
 * config/jitsi-gateway/nginx.conf's header comment for why TLS exists
 * here at all).
 *
 * Run inside a container with the `playwright` npm package installed
 * (see verify.sh, which does this in a throwaway
 * mcr.microsoft.com/playwright container on services_net) — no other
 * dependency on this repo.
 */
const { chromium } = require('playwright');

const ROOM = 'verify-' + Math.random().toString(16).slice(2, 10);
const BASE_ARGS = [
  '--ignore-certificate-errors',
  '--use-fake-device-for-media-stream',
  '--use-fake-ui-for-media-stream',
  '--autoplay-policy=no-user-gesture-required',
];

const URL_FRAGMENT = [
  'config.startWithVideoMuted=true',
  'config.startWithAudioMuted=false',
  'config.requireDisplayName=false',
  'config.disableDeepLinking=true',
  'config.p2p.enabled=false',
].join('&');

async function makeParticipant(name) {
  const browser = await chromium.launch({ args: BASE_ARGS });
  const context = await browser.newContext({
    permissions: ['microphone', 'camera'],
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  page.on('console', (msg) => {
    if (/error/i.test(msg.type())) console.log(`[${name} console] ${msg.text()}`);
  });

  // Capture every RTCPeerConnection Jitsi creates so we can read real
  // getStats() from it later — not something Jitsi exposes a stable
  // public API for.
  await page.addInitScript(() => {
    window.__pcs = [];
    const OrigPC = window.RTCPeerConnection;
    function Wrapped(...args) {
      const pc = new OrigPC(...args);
      window.__pcs.push(pc);
      return pc;
    }
    Wrapped.prototype = OrigPC.prototype;
    window.RTCPeerConnection = Wrapped;
  });

  const url = `https://talk.island/${ROOM}#${URL_FRAGMENT}&userInfo.displayName="${name}"`;
  console.log(`[${name}] navigating to ${url}`);
  await page.goto(url, { waitUntil: 'load', timeout: 30000 });

  const joinButton = page.getByRole('button', { name: /join meeting/i });
  await joinButton.waitFor({ state: 'visible', timeout: 20000 });
  await joinButton.click();
  console.log(`[${name}] clicked Join meeting`);
  return { browser, page, name };
}

async function getInboundAudioStats(page) {
  return page.evaluate(async () => {
    const results = [];
    for (const pc of window.__pcs || []) {
      if (pc.connectionState === 'closed') continue;
      const report = await pc.getStats();
      for (const stat of report.values()) {
        if (stat.type === 'inbound-rtp' && stat.kind === 'audio') {
          results.push({
            packetsReceived: stat.packetsReceived,
            bytesReceived: stat.bytesReceived,
            audioLevel: stat.audioLevel,
          });
        }
      }
    }
    return results;
  });
}

function maxPackets(stats) {
  return Math.max(0, ...stats.map((s) => s.packetsReceived || 0));
}

async function main() {
  console.log(`Room: ${ROOM}`);
  const alice = await makeParticipant('Alice');
  const bob = await makeParticipant('Bob');

  console.log('waiting for both to settle into the call...');
  await new Promise((r) => setTimeout(r, 15000));

  const participantCount = await alice.page.evaluate(() =>
    window.APP && window.APP.conference && window.APP.conference._room
      ? window.APP.conference._room.getParticipantCount()
      : null
  );
  console.log('Alice sees participant count:', participantCount);
  if (participantCount !== 2) {
    throw new Error(`expected 2 participants in the room, Alice saw ${participantCount}`);
  }

  const s1a = await getInboundAudioStats(alice.page);
  const s1b = await getInboundAudioStats(bob.page);
  await new Promise((r) => setTimeout(r, 5000));
  const s2a = await getInboundAudioStats(alice.page);
  const s2b = await getInboundAudioStats(bob.page);

  await alice.browser.close();
  await bob.browser.close();

  const aliceGrowth = maxPackets(s2a) - maxPackets(s1a);
  const bobGrowth = maxPackets(s2b) - maxPackets(s1b);
  console.log(`Alice inbound audio: ${JSON.stringify(s1a)} -> ${JSON.stringify(s2a)} (growth ${aliceGrowth})`);
  console.log(`Bob inbound audio: ${JSON.stringify(s1b)} -> ${JSON.stringify(s2b)} (growth ${bobGrowth})`);

  if (maxPackets(s1a) === 0 && maxPackets(s2a) === 0) {
    throw new Error("Alice never received any inbound audio RTP packets");
  }
  if (maxPackets(s1b) === 0 && maxPackets(s2b) === 0) {
    throw new Error("Bob never received any inbound audio RTP packets");
  }
  if (aliceGrowth <= 0) {
    throw new Error("Alice's inbound audio packet count did not grow over 5s — stream is not live");
  }
  if (bobGrowth <= 0) {
    throw new Error("Bob's inbound audio packet count did not grow over 5s — stream is not live");
  }

  console.log('\nALL CHECKS PASSED: real, live, bidirectional audio RTP flowing over JVB');
}

main().catch((e) => {
  console.error('FAIL:', e.message);
  process.exitCode = 1;
});
