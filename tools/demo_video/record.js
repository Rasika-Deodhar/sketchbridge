// Records a Sketchbridge walkthrough as JPEG frames (CDP screencast), with captions,
// a visible cursor, and sped-up waits. build.sh turns the frames into an MP4.
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = process.argv[2];
const URL = process.env.SKETCHBRIDGE_URL || 'http://127.0.0.1:8769/';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  fs.rmSync(`${OUT}/frames`, { recursive: true, force: true });
  fs.mkdirSync(`${OUT}/frames`, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1.5, colorScheme: 'light' });
  const p = await ctx.newPage();
  const errs = []; p.on('pageerror', (e) => errs.push(String(e)));
  await p.goto(URL);
  await p.waitForSelector('#demos button');

  // ---- overlay: caption banner, speed badge, cursor, title cards
  await p.addStyleTag({ content: `
    #vcap { position: fixed; top: 14px; left: 50%; transform: translateX(-50%); z-index: 50; max-width: 1100px;
            background: rgba(20,20,18,.88); color: #fff; font: 600 21px/1.35 system-ui, sans-serif; padding: 10px 20px;
            border-radius: 12px; text-align: center; transition: opacity .35s; box-shadow: 0 6px 20px rgba(0,0,0,.25); }
    #vcap small { display: block; font-weight: 400; font-size: 15px; opacity: .85; margin-top: 2px; }
    #vfast { position: fixed; top: 14px; right: 18px; z-index: 51; background: #c2410c; color: #fff;
             font: 700 15px system-ui; padding: 6px 12px; border-radius: 999px; }
    #vcur { position: fixed; z-index: 60; width: 22px; height: 22px; margin: -11px 0 0 -11px; border-radius: 50%;
            background: rgba(220,38,38,.35); border: 2px solid #dc2626; pointer-events: none;
            transition: left .7s cubic-bezier(.4,0,.2,1), top .7s cubic-bezier(.4,0,.2,1), transform .15s; left: 640px; top: 400px; }
    #vcur.click { transform: scale(.6); background: rgba(220,38,38,.7); }
    #vcard { position: fixed; inset: 0; z-index: 70; display: flex; flex-direction: column; align-items: center;
             justify-content: center; text-align: center; background: #f7f5f0; color: #1f1d1a; font-family: system-ui, sans-serif;
             transition: opacity .6s; padding: 40px; }
    #vcard h1 { font-size: 64px; margin: 0 0 8px; letter-spacing: -.02em; }
    #vcard p { font-size: 26px; margin: 6px 0; color: #4a463f; max-width: 980px; }
    #vcard .models { margin-top: 26px; font-size: 19px; color: #2f6f5e; }
  `});
  await p.evaluate(() => {
    for (const id of ['vcap', 'vfast', 'vcur']) { const d = document.createElement('div'); d.id = id; d.hidden = true; document.body.append(d); }
  });

  const caption = (title, sub = '') => p.evaluate(([t, s]) => {
    const c = document.getElementById('vcap');
    c.hidden = !t; c.innerHTML = '';
    if (t) { c.append(t); if (s) { const sm = document.createElement('small'); sm.textContent = s; c.append(sm); } }
  }, [title, sub]);
  const card = (html) => p.evaluate((h) => {
    let c = document.getElementById('vcard');
    if (!h) { if (c) { c.style.opacity = 0; setTimeout(() => c.remove(), 650); } return; }
    if (!c) { c = document.createElement('div'); c.id = 'vcard'; document.body.append(c); }
    c.innerHTML = h; c.style.opacity = 1;
  }, html);
  const fast = (on) => p.evaluate((o) => { const f = document.getElementById('vfast'); f.hidden = !o; f.textContent = '⏩ sped up'; }, on);
  async function pointAt(sel) {
    const box = await p.locator(sel).first().boundingBox();
    await p.evaluate(([x, y]) => { const c = document.getElementById('vcur'); c.hidden = false; c.style.left = x + 'px'; c.style.top = y + 'px'; },
      [box.x + box.width / 2, box.y + box.height / 2]);
    await sleep(800);
  }
  async function click(sel) {
    await p.locator(sel).first().scrollIntoViewIfNeeded();
    await pointAt(sel);
    await p.evaluate(() => document.getElementById('vcur').classList.add('click'));
    await sleep(150);
    await p.evaluate(() => document.getElementById('vcur').classList.remove('click'));
    await p.locator(sel).first().click();
  }
  async function type(sel, text) {
    await pointAt(sel);
    await p.locator(sel).first().click();
    await p.locator(sel).first().fill('');
    await p.locator(sel).first().pressSequentially(text, { delay: 45 });
  }
  const scrollTo = async (sel, block = 'start') => {
    await p.evaluate(([s, b]) => document.querySelector(s).scrollIntoView({ behavior: 'smooth', block: b }), [sel, block]);
    await sleep(1100);
  };

  // ---- start the screencast
  const cdp = await ctx.newCDPSession(p);
  const frames = []; const marks = [];
  let n = 0;
  cdp.on('Page.screencastFrame', async (f) => {
    const file = `frames/f${String(n++).padStart(5, '0')}.jpg`;
    fs.writeFileSync(`${OUT}/${file}`, Buffer.from(f.data, 'base64'));
    frames.push({ file, t: f.metadata.timestamp });
    try { await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }); } catch {}
  });
  const now = () => Date.now() / 1000;
  const speed = (factor) => marks.push({ t: now(), factor });   // from now on, play at this speed
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
  speed(1);

  // 1. Title card
  await card(`<h1>Sketchbridge</h1><p>Understand a hard idea through a picture analogy:<br>it writes it, draws it, checks its own drawing,<br>and checks that you really got it.</p>
    <p class="models">Built on Meta's Muse Spark · Muse Image · Muse Voice Transcribe</p>`);
  await sleep(4500);
  await card(null); await sleep(700);

  // 2. Ask
  await caption('Ask about any hard idea, and pick a world you know', 'Type it, or press 🎤 and say it (Muse Voice Transcribe)');
  await type('#concept', 'What is backpropagation?');
  await type('#interest', 'Restaurant');
  await sleep(500);
  await pointAt('#askBtn');
  // Show the demo's options (the ready-made example: same result as a live run, no waiting).
  await p.evaluate(() => fetch('/demos').then((r) => r.json()).then((list) => {
    const d = list[0]; state.demo = d; state.concept = d.concept; state.interest = d.interest;
    state.shownDomains = d.options.map((o) => o.domain); renderOptions(d.options, 5, d);
  }));
  await sleep(600);
  await caption('Muse Spark offers 3 analogies from that world', 'Not quite right? "Try another" gives 3 fresh ones');
  await scrollTo('#optionsCard', 'center');
  await sleep(2600);

  // 3. Pick -> picture
  await caption('Pick one: Muse Spark writes it, Muse Image draws it,', 'then Muse Spark looks at the drawing and redraws once if it doesn\'t match');
  await click('.option.cached');
  await sleep(1500);
  await scrollTo('#resultCard');
  await sleep(3000);
  await caption('Every part of the picture maps to a part of the real idea');
  await pointAt('#mapping');
  await sleep(3200);

  // 4. Connect the dots
  await caption('"Connect the dots" shows how the parts work together, in order', 'Muse Spark finds each part in the picture and walks through it');
  await click('#connectBtn');
  await sleep(1200);
  await scrollTo('#stage', 'start');
  await p.evaluate(() => { stopWalk(); showStep(0); }); await sleep(2800);
  for (let i = 1; i < 5; i++) { await click('#walkNext'); await sleep(2300); }
  await caption('…ending with the whole picture in a few sentences');
  await sleep(3500);

  // 5. Next scene (live) with the real progress bar
  await caption('"Show the next scene" zooms in on one part, in the same style', 'The bar shows the real stage as it happens');
  await scrollTo('.quick', 'center');
  await click('[data-action="next_scene"]');
  await sleep(2500);
  speed(6); await fast(true);
  await p.waitForFunction(() => document.getElementById('toast').hidden && !document.querySelector('#status.error:not([hidden])'), null, { timeout: 180000 });
  speed(1); await fast(false);
  await scrollTo('#stage', 'start');
  await caption('A close-up, linked to the scene before it', 'It joins the strip, and the walkthrough links to it');
  await sleep(3500);
  await scrollTo('#chat', 'center');
  await sleep(3500);

  // 6. Explain it back (live)
  await caption('Then the learner explains it back in their own words', 'Typed or spoken. Explaining is how it sticks.');
  await scrollTo('#teach', 'start');
  await type('#teachInput', 'You taste the soup, it is too salty, so you walk back down the line to find the cook who added salt.');
  await sleep(600);
  await click('#teachBtn');
  speed(4); await fast(true);
  await p.waitForSelector('#verdict', { state: 'visible', timeout: 120000 });
  await sleep(400);
  speed(1); await fast(false);
  await caption('Muse Spark grades every part: got it, partly, or missed', 'It flags misconceptions and offers a scene for the biggest gap');
  await scrollTo('#verdict', 'start');
  await sleep(5500);

  // 7. Simplify (ready-made)
  await caption('Still confused? "I don\'t get it" makes it simpler', 'A simpler explanation and a simpler picture, same core idea');
  await scrollTo('#resultCard', 'start');
  await click('#strip button');       // back to the first picture
  await sleep(800);
  await scrollTo('.quick', 'center');
  await click('[data-action="simplify"]');
  await sleep(800);
  await scrollTo('#resultCard', 'start');
  await sleep(4500);

  // 8. Dark mode
  await caption('Light or dark, on phone or laptop');
  await scrollTo('header', 'start');
  await click('#themeBtn');
  await sleep(2500);
  await click('#themeBtn');
  await sleep(800);
  await caption('');

  // 9. Outro
  await card(`<h1>Sketchbridge</h1><p>Explain → draw → check the drawing → connect the dots → check the learner</p>
    <p class="models">Muse Spark 1.3 · Muse Image 1.0 · Muse Voice Transcribe 1.0 — all hosted by Meta, no training</p>`);
  await sleep(4500);

  await cdp.send('Page.stopScreencast');
  marks.push({ t: now(), factor: 1, end: true });
  fs.writeFileSync(`${OUT}/frames.json`, JSON.stringify({ frames, marks }));
  console.log('frames:', frames.length, 'errors:', errs, 'spend:', await p.textContent('#spend'));
  await browser.close();
})();
