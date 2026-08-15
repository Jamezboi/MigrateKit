import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js';

// ==========================================
// 1. High-Performance Three.js Plexus System
// ==========================================

const canvas = document.getElementById('bg-canvas');
const isMobile = navigator.maxTouchPoints > 1 || window.innerWidth < 768;

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: !isMobile,
  alpha: false,
  powerPreference: 'high-performance'
});
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x030712); // --color-bg-base
scene.fog = new THREE.FogExp2(0x030712, 0.08);

const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.z = 8;

// --- Background Star Field (Static/Slow points) ---
const STAR_COUNT = isMobile ? 1000 : 2000;
const starsGeo = new THREE.BufferGeometry();
const starPositions = new Float32Array(STAR_COUNT * 3);

for (let i = 0; i < STAR_COUNT * 3; i++) {
  starPositions[i] = (Math.random() - 0.5) * 25;
}
starsGeo.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));

const starsMaterial = new THREE.PointsMaterial({
  color: 0x3b82f6, // Blue
  size: 0.02,
  transparent: true,
  opacity: 0.4,
  sizeAttenuation: true
});
const starField = new THREE.Points(starsGeo, starsMaterial);
scene.add(starField);

// --- Dynamic Plexus Network Nodes ---
const NODE_COUNT = isMobile ? 50 : 110;
const nodeGeo = new THREE.BufferGeometry();
const nodePositions = new Float32Array(NODE_COUNT * 3);
const velocities = [];

// Populate nodes and velocities
for (let i = 0; i < NODE_COUNT; i++) {
  nodePositions[i * 3] = (Math.random() - 0.5) * 16;
  nodePositions[i * 3 + 1] = (Math.random() - 0.5) * 10;
  nodePositions[i * 3 + 2] = (Math.random() - 0.5) * 8 - 2;
  
  velocities.push({
    x: (Math.random() - 0.5) * 0.012,
    y: (Math.random() - 0.5) * 0.012,
    z: (Math.random() - 0.5) * 0.008
  });
}
nodeGeo.setAttribute('position', new THREE.BufferAttribute(nodePositions, 3));

const nodeMaterial = new THREE.PointsMaterial({
  color: 0x06b6d4, // Cyan
  size: 0.06,
  transparent: true,
  opacity: 0.8,
  sizeAttenuation: true
});
const plexusNodes = new THREE.Points(nodeGeo, nodeMaterial);
scene.add(plexusNodes);

// --- Connection Lines for Plexus Network ---
const lineMaterial = new THREE.LineBasicMaterial({
  color: 0x06b6d4,
  transparent: true,
  opacity: 0.15
});

let lineGeometry = new THREE.BufferGeometry();
let lineMesh = new THREE.LineSegments(lineGeometry, lineMaterial);
scene.add(lineMesh);

// --- Mouse Interaction Parallax ---
let mouseX = 0, mouseY = 0;
document.addEventListener('mousemove', (event) => {
  mouseX = (event.clientX / window.innerWidth - 0.5) * 2;
  mouseY = (event.clientY / window.innerHeight - 0.5) * 2;
});

// --- Window Resizing ---
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
});

// --- Dynamic Line Drawing Logic ---
const maxDistance = 2.4;

function updatePlexusLines(positions) {
  const linePoints = [];
  
  // Look up near-neighbors to draw lines
  for (let i = 0; i < NODE_COUNT; i++) {
    const x1 = positions[i * 3];
    const y1 = positions[i * 3 + 1];
    const z1 = positions[i * 3 + 2];
    
    for (let j = i + 1; j < NODE_COUNT; j++) {
      const x2 = positions[j * 3];
      const y2 = positions[j * 3 + 1];
      const z2 = positions[j * 3 + 2];
      
      const dist = Math.sqrt((x1 - x2)**2 + (y1 - y2)**2 + (z1 - z2)**2);
      
      if (dist < maxDistance) {
        linePoints.push(x1, y1, z1);
        linePoints.push(x2, y2, z2);
      }
    }
  }
  
  lineGeometry.setAttribute('position', new THREE.Float32BufferAttribute(linePoints, 3));
}

// --- Animation Frame ---
const clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const elapsed = clock.getElapsedTime();
  
  // Rotate background star field
  starField.rotation.y = elapsed * 0.008 + mouseX * 0.04;
  starField.rotation.x = elapsed * 0.004 + mouseY * 0.02;
  
  // Move Plexus nodes
  const positions = nodeGeo.attributes.position.array;
  for (let i = 0; i < NODE_COUNT; i++) {
    positions[i * 3] += velocities[i].x;
    positions[i * 3 + 1] += velocities[i].y;
    positions[i * 3 + 2] += velocities[i].z;
    
    // Boundary bounce checks
    if (positions[i * 3] < -8 || positions[i * 3] > 8) velocities[i].x *= -1;
    if (positions[i * 3 + 1] < -5 || positions[i * 3 + 1] > 5) velocities[i].y *= -1;
    if (positions[i * 3 + 2] < -6 || positions[i * 3 + 2] > 2) velocities[i].z *= -1;
  }
  nodeGeo.attributes.position.needsUpdate = true;
  
  // Update connection plexus
  updatePlexusLines(positions);
  
  // Apply mouse parallax rotation to plexus
  plexusNodes.rotation.y = mouseX * 0.12;
  plexusNodes.rotation.x = mouseY * 0.06;
  lineMesh.rotation.y = mouseX * 0.12;
  lineMesh.rotation.x = mouseY * 0.06;
  
  renderer.render(scene, camera);
}

animate();


// ==========================================
// 2. Interactive Windows 11 App Hero Simulation
// ==========================================

const btnSimulate = document.getElementById('btn-run-simulation');
const progressFill = document.getElementById('mock-progress-fill');
const statusText = document.getElementById('mock-status-text');
const percentageText = document.getElementById('mock-percentage');
const consoleLog = document.getElementById('mock-console-log');

const simLogs = [
  { p: 10, text: "Indexing user profile directories...", class: "log-info" },
  { p: 25, text: "Discovered: Documents (142 files), Desktop (34 files), Pictures (280 files).", class: "log-info" },
  { p: 40, text: "Scanning Google Chrome data path...", class: "log-info" },
  { p: 55, text: "Google Chrome profiles packaged. Bookmarks, history and cookies verified.", class: "log-success" },
  { p: 70, text: "Packaging Selective Application settings: AppData/Roaming folder...", class: "log-info" },
  { p: 85, text: "Exporting specified Registry keys: Environment vars...", class: "log-info" },
  { p: 95, text: "Finalizing compression format structure...", class: "log-info" },
  { p: 100, text: "SUCCESS: Archive backup completed. Saved to Desktop.", class: "log-success" }
];

btnSimulate.addEventListener('click', () => {
  btnSimulate.disabled = true;
  btnSimulate.textContent = "Simulation Running...";
  progressFill.style.width = '0%';
  percentageText.textContent = '0%';
  statusText.textContent = "Starting...";
  consoleLog.innerHTML = '<p class="log-info">[System] Starting Migration Simulation...</p>';
  
  let currentLogIdx = 0;
  let progress = 0;
  
  const timer = setInterval(() => {
    progress += 2;
    if (progress > 100) progress = 100;
    
    progressFill.style.width = `${progress}%`;
    percentageText.textContent = `${progress}%`;
    
    // Check if we need to print a log statement
    if (currentLogIdx < simLogs.length && progress >= simLogs[currentLogIdx].p) {
      statusText.textContent = simLogs[currentLogIdx].text.substring(0, 28) + "...";
      
      const newLog = document.createElement('p');
      newLog.className = simLogs[currentLogIdx].class;
      newLog.textContent = `[Engine] ${simLogs[currentLogIdx].text}`;
      consoleLog.appendChild(newLog);
      
      // Auto scroll console
      consoleLog.scrollTop = consoleLog.scrollHeight;
      currentLogIdx++;
    }
    
    if (progress >= 100) {
      clearInterval(timer);
      btnSimulate.disabled = false;
      btnSimulate.textContent = "Run Simulation Again";
      statusText.textContent = "Simulation Complete";
    }
  }, 120);
});


// ==========================================
// 3. PowerShell Playground Panel
// ==========================================

const tabs = document.querySelectorAll('.playground-tab');
const btnRunScript = document.getElementById('btn-run-script');
const terminalBody = document.getElementById('playground-terminal-body');
let activeScript = 'verify';

tabs.forEach(tab => {
  tab.addEventListener('click', () => {
    tabs.forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    activeScript = tab.dataset.script;
    
    // Reset terminal placeholder
    terminalBody.innerHTML = `<p class="terminal-line text-comment"># Select script tab and click Run below to test...</p>`;
  });
});

const scriptSimulations = {
  verify: [
    { text: "PS C:\\Users\\Jamezboi\\MigrateKit> .\\verify_integrity.ps1 -BackupPath \"C:\\MigrateKit_Backup.migratekit\"", class: "text-cmd" },
    { text: "=============================================", class: "text-info" },
    { text: "   MigrateKit Integrity Verification Script  ", class: "text-info" },
    { text: "=============================================", class: "text-info" },
    { text: "Backup Path: C:\\MigrateKit_Backup.migratekit", class: "text-info" },
    { text: "Target User Root: C:\\Users\\Jamezboi", class: "text-info" },
    { text: "[+] Manifest parsed successfully. Date: 2026-08-14 20:24", class: "text-success" },
    { text: "-> Verifying category: Documents", class: "text-cmd" },
    { text: "   Directory verified (142 files matched)", class: "text-success" },
    { text: "-> Verifying category: Chrome Profile", class: "text-cmd" },
    { text: "   Directory verified (Bookmarks, History matched)", class: "text-success" },
    { text: "-> Verifying category: Registry Configurations", class: "text-cmd" },
    { text: "   Registry key verified: HKEY_CURRENT_USER\\Environment", class: "text-success" },
    { text: "Verification status: PASSED (Restored files integrity verified)", class: "text-success" }
  ],
  chrome: [
    { text: "PS C:\\Users\\Jamezboi\\MigrateKit> .\\test_chrome.ps1", class: "text-cmd" },
    { text: "=============================================", class: "text-info" },
    { text: "   MigrateKit Google Chrome Profile Validator", class: "text-info" },
    { text: "=============================================", class: "text-info" },
    { text: "[+] Chrome Default profile folder located.", class: "text-success" },
    { text: "[+] Bookmarks file: VALID JSON. Found 14 bookmark items.", class: "text-success" },
    { text: "Analyzing SQLite History database header...", class: "text-comment" },
    { text: "[+] SQLite header signature matches 'SQLite format 3'", class: "text-success" },
    { text: "Analyzing SQLite Credentials database header...", class: "text-comment" },
    { text: "[+] SQLite credentials header matches 'SQLite format 3'", class: "text-success" },
    { text: "Chrome Profile Integrity Check: PASSED", class: "text-success" }
  ],
  permissions: [
    { text: "PS C:\\Users\\Jamezboi\\MigrateKit> .\\fix_permissions.ps1 -TargetDirectory \"C:\\Users\\Jamezboi\\Documents\"", class: "text-cmd" },
    { text: "=============================================", class: "text-info" },
    { text: "   MigrateKit Permission & Lock Troubleshooter", class: "text-info" },
    { text: "=============================================", class: "text-info" },
    { text: "[1/3] Scanning for active application file locks...", class: "text-info" },
    { text: "[!] Found running process: chrome.exe. Terminating...", class: "text-error" },
    { text: "[!] Found running process: onedrive.exe. Terminating...", class: "text-error" },
    { text: "[2/3] Elevating file/folder permissions...", class: "text-info" },
    { text: "Running: takeown.exe /F C:\\Users\\Jamezboi\\Documents /R /A /D Y", class: "text-comment" },
    { text: "[+] takeown completed successfully.", class: "text-success" },
    { text: "[3/3] Granting full access control list privileges to user...", class: "text-info" },
    { text: "Running: icacls.exe \"C:\\Users\\Jamezboi\\Documents\" /grant \"JAMEZBOI-PC\\Jamezboi:(OI)(CI)F\" /T /C /Q", class: "text-comment" },
    { text: "[+] icacls completed successfully. Permissions reset complete.", class: "text-success" }
  ]
};

btnRunScript.addEventListener('click', () => {
  btnRunScript.disabled = true;
  btnRunScript.textContent = "Executing Script...";
  terminalBody.innerHTML = '';
  
  const lines = scriptSimulations[activeScript];
  let lineIdx = 0;
  
  const timer = setInterval(() => {
    if (lineIdx < lines.length) {
      const newLine = document.createElement('p');
      newLine.className = `terminal-line ${lines[lineIdx].class}`;
      newLine.textContent = lines[lineIdx].text;
      terminalBody.appendChild(newLine);
      
      terminalBody.scrollTop = terminalBody.scrollHeight;
      lineIdx++;
    } else {
      clearInterval(timer);
      btnRunScript.disabled = false;
      btnRunScript.textContent = "Run Script Simulation";
    }
  }, 180);
});


// ==========================================
// 4. Billing Toggler & Price Updates
// ==========================================

const toggleBtn = document.getElementById('billing-toggle');
const labelSingle = document.getElementById('label-single');
const labelFamily = document.getElementById('label-family');
const licenseTitle = document.getElementById('license-tier-title');
const licensePrice = document.getElementById('license-price');
const licensePC = document.getElementById('license-pc-count');

const productModalName = document.getElementById('modal-product-name');
const productModalPrice = document.getElementById('modal-product-price');
const productModalTotal = document.getElementById('modal-product-total');

let isFamilyPack = false;

const updatePricingDisplay = () => {
  if (isFamilyPack) {
    toggleBtn.classList.add('active');
    labelSingle.classList.remove('active');
    labelFamily.classList.add('active');
    licenseTitle.textContent = "Family Bundle";
    licensePrice.textContent = "49.99";
    licensePC.textContent = "Five (5)";
    
    // Modal updates
    productModalName.textContent = "MigrateKit Family License (5 PCs)";
    productModalPrice.textContent = "$49.99 USD";
    productModalTotal.textContent = "$49.99 USD";
  } else {
    toggleBtn.classList.remove('active');
    labelSingle.classList.add('active');
    labelFamily.classList.remove('active');
    licenseTitle.textContent = "Premium License";
    licensePrice.textContent = "29.99";
    licensePC.textContent = "Single (1)";
    
    // Modal updates
    productModalName.textContent = "MigrateKit Premium License (1 PC)";
    productModalPrice.textContent = "$29.99 USD";
    productModalTotal.textContent = "$29.99 USD";
  }
};

toggleBtn.addEventListener('click', () => {
  isFamilyPack = !isFamilyPack;
  updatePricingDisplay();
});

labelSingle.addEventListener('click', () => {
  isFamilyPack = false;
  updatePricingDisplay();
});

labelFamily.addEventListener('click', () => {
  isFamilyPack = true;
  updatePricingDisplay();
});


// ==========================================
// 5. FAQ Accordion Controls
// ==========================================

const faqItems = document.querySelectorAll('.faq-item');

faqItems.forEach(item => {
  const trigger = item.querySelector('.faq-trigger');
  const content = item.querySelector('.faq-content');
  
  trigger.addEventListener('click', () => {
    const isOpen = item.classList.contains('active');
    
    // Close other open FAQ panels
    faqItems.forEach(otherItem => {
      otherItem.classList.remove('active');
      otherItem.querySelector('.faq-content').style.maxHeight = null;
    });
    
    if (!isOpen) {
      item.classList.add('active');
      // Set panel max-height dynamically to fit text beautifully
      content.style.maxHeight = content.scrollHeight + "px";
    }
  });
});


// ==========================================
// 6. Checkout Modal & Licensing Logic
// ==========================================

const modal = document.getElementById('checkout-modal');
const btnBuy = document.getElementById('btn-buy');
const btnClose = document.getElementById('modal-close');
const btnPaypalSimulate = document.getElementById('btn-paypal-simulate');
const btnDevSimulate = document.getElementById('btn-dev-simulate');
const btnFinish = document.getElementById('btn-finish');
const btnCopyKey = document.getElementById('btn-copy-key');

const stepPayment = document.getElementById('checkout-step-payment');
const stepSuccess = document.getElementById('checkout-step-success');
const licenseText = document.getElementById('license-key-text');
const copySuccessMsg = document.getElementById('copy-success-msg');

btnBuy.addEventListener('click', () => {
  stepPayment.classList.remove('hidden');
  stepSuccess.classList.add('hidden');
  copySuccessMsg.style.display = 'none';
  modal.classList.add('active');
});

const closeModal = () => {
  modal.classList.remove('active');
};
btnClose.addEventListener('click', closeModal);
btnFinish.addEventListener('click', () => {
  closeModal();
  window.location.href = "https://github.com/Jamezboi/MigrateKit/releases/latest";
});

modal.addEventListener('click', (e) => {
  if (e.target === modal) {
    closeModal();
  }
});

// Cryptographically valid key generator
async function generateLicenseKey() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let first_15 = '';
  
  for (let i = 0; i < 15; i++) {
    first_15 += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  
  const salt = "MIGRATEKIT-SALT-2026";
  const rawInput = first_15 + salt;
  const msgBuffer = new TextEncoder().encode(rawInput);
  const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
  
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('').toUpperCase();
  
  const last_5 = hashHex.substring(0, 5);
  const fullKey = first_15 + last_5;
  
  return fullKey.match(/.{1,5}/g).join('-');
}

async function triggerSuccessFlow() {
  const licenseKey = await generateLicenseKey();
  stepPayment.classList.add('hidden');
  stepSuccess.classList.remove('hidden');
  licenseText.textContent = licenseKey;
}

btnPaypalSimulate.addEventListener('click', () => {
  btnPaypalSimulate.disabled = true;
  btnPaypalSimulate.textContent = "Processing PayPal Sandbox Authorization...";
  
  setTimeout(() => {
    btnPaypalSimulate.disabled = false;
    btnPaypalSimulate.innerHTML = '<span class="paypal-logo"><i>Pay</i><i>Pal</i></span><span class="paypal-text">Simulate Checkout</span>';
    triggerSuccessFlow();
  }, 1500);
});

btnDevSimulate.addEventListener('click', triggerSuccessFlow);

btnCopyKey.addEventListener('click', () => {
  const key = licenseText.textContent;
  navigator.clipboard.writeText(key).then(() => {
    copySuccessMsg.style.display = 'block';
    setTimeout(() => {
      copySuccessMsg.style.display = 'none';
    }, 3000);
  });
});


// ==========================================
// 7. Scroll Reveal Trigger
// ==========================================

const revealElements = document.querySelectorAll('.fade-in');
const observerOptions = {
  root: null,
  threshold: 0.15,
  rootMargin: "0px"
};

const observer = new IntersectionObserver((entries, observer) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      observer.unobserve(entry.target);
    }
  });
}, observerOptions);

revealElements.forEach(element => {
  observer.observe(element);
});
