const $ = (id) => document.getElementById(id);

const menuBtn = $('menu-btn');
const navLinks = $('nav-links');
if (menuBtn && navLinks) {
  menuBtn.addEventListener('click', () => {
    const open = navLinks.classList.toggle('open');
    menuBtn.setAttribute('aria-expanded', String(open));
  });
  navLinks.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
    navLinks.classList.remove('open');
    menuBtn.setAttribute('aria-expanded', 'false');
  }));
}

const previewBtn = $('preview-btn');
const previewLog = $('preview-log');
const previewPercent = $('preview-percent');
if (previewBtn && previewLog && previewPercent) {
  const stages = [
    ['Indexing user folders…', 18],
    ['Checking Chrome profile…', 41],
    ['Preparing selected AppData…', 67],
    ['Archive structure ready.', 84],
    ['Backup simulation complete.', 100]
  ];
  previewBtn.addEventListener('click', () => {
    previewBtn.disabled = true;
    previewBtn.textContent = 'Running preview…';
    let i = 0;
    const timer = setInterval(() => {
      const [text, pct] = stages[i++];
      previewLog.textContent = text;
      previewPercent.textContent = `${pct}%`;
      const fill = document.querySelector('.progress > span');
      if (fill) fill.style.width = `${pct}%`;
      if (i >= stages.length) {
        clearInterval(timer);
        previewBtn.disabled = false;
        previewBtn.textContent = 'Run preview again';
      }
    }, 500);
  });
}

const diagnosticBtn = $('terminal-action');
const terminalLines = $('terminal-lines');
if (diagnosticBtn && terminalLines) {
  diagnosticBtn.addEventListener('click', () => {
    diagnosticBtn.disabled = true;
    diagnosticBtn.textContent = 'Running…';
    const rows = [
      ['10:02:16', 'Verifying archive manifest'],
      ['10:02:17', 'Checking selected categories'],
      ['10:02:18', 'Checking restore prerequisites'],
      ['10:02:19', 'Diagnostic complete — ready']
    ];
    let i = 0;
    const timer = setInterval(() => {
      const [time, text] = rows[i++];
      const row = document.createElement('div');
      const b = document.createElement('b');
      b.textContent = time;
      row.appendChild(b);
      row.append(` ${text}`);
      terminalLines.appendChild(row);
      terminalLines.scrollTop = terminalLines.scrollHeight;
      if (i >= rows.length) {
        clearInterval(timer);
        diagnosticBtn.disabled = false;
        diagnosticBtn.textContent = 'Run diagnostic preview again';
      }
    }, 450);
  });
}

const modal = $('license-modal');
const buyBtn = $('buy-btn');
const closeBtn = $('modal-close');
const simulateBuy = $('simulate-buy');
const result = $('license-result');
const licenseKey = $('license-key');
const copyKey = $('copy-key');

const closeModal = () => {
  if (!modal) return;
  modal.classList.remove('open');
  modal.setAttribute('aria-hidden', 'true');
};

if (buyBtn && modal) {
  buyBtn.addEventListener('click', () => {
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    result.hidden = true;
  });
}
if (closeBtn) closeBtn.addEventListener('click', closeModal);
if (modal) modal.addEventListener('click', (event) => {
  if (event.target.dataset.close) closeModal();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeModal();
});

async function sha256(text) {
  const buffer = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, '0')).join('').toUpperCase();
}

function randomPart(length) {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const values = new Uint32Array(length);
  crypto.getRandomValues(values);
  return [...values].map((v) => chars[v % chars.length]).join('');
}

if (simulateBuy && result && licenseKey) {
  simulateBuy.addEventListener('click', async () => {
    simulateBuy.disabled = true;
    simulateBuy.textContent = 'Generating demo license…';
    const body = randomPart(15);
    const checksum = (await sha256(`${body}MIGRATEKIT-SALT-2026`)).slice(0, 5);
    licenseKey.textContent = `${body.slice(0,5)}-${body.slice(5,10)}-${body.slice(10,15)}-${checksum}`;
    result.hidden = false;
    simulateBuy.disabled = false;
    simulateBuy.textContent = 'Generate again';
  });
}

if (copyKey && licenseKey) {
  copyKey.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(licenseKey.textContent);
      copyKey.textContent = 'Copied';
      setTimeout(() => { copyKey.textContent = 'Copy key'; }, 1800);
    } catch {
      copyKey.textContent = 'Copy failed';
    }
  });
}

// Keep the storefront intentionally dependency-free. This prevents a CDN/WebGL failure
// from taking down the product page or its core purchase/download controls.
