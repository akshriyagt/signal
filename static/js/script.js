// ---------------------------------------------------------------------------
// Signal — Call Recording Analyzer frontend
// ---------------------------------------------------------------------------

const dropZone     = document.getElementById('dropZone');
const fileInput    = document.getElementById('fileInput');
const queueEl      = document.getElementById('queue');
const analyzeBtn   = document.getElementById('analyzeBtn');
const resultsGrid  = document.getElementById('resultsGrid');
const emptyState   = document.getElementById('emptyState');
const clearAllBtn  = document.getElementById('clearAllBtn');
const downloadBtn  = document.getElementById('downloadJsonBtn');
const toastEl      = document.getElementById('toast');
const modelPill    = document.getElementById('modelPill');
const statTotal     = document.getElementById('statTotal');
const statSpam      = document.getElementById('statSpam');
const statImportant = document.getElementById('statImportant');
const statNormal    = document.getElementById('statNormal');

let pendingFiles = [];

// ---------- icons ----------
const ICONS = {
  spam: `<svg class="cat-icon" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8"/><path d="M9 9l6 6m0-6l-6 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`,
  important: `<svg class="cat-icon" viewBox="0 0 24 24" fill="none"><path d="M12 2l2.4 6.6L21 11l-6.6 2.4L12 20l-2.4-6.6L3 11l6.6-2.4L12 2z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" fill="currentColor" fill-opacity="0.15"/></svg>`,
  normal: `<svg class="cat-icon" viewBox="0 0 24 24" fill="none"><path d="M5 13l4 4L19 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  file: `<svg viewBox="0 0 24 24" fill="none"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" stroke="currentColor" stroke-width="1.6"/><path d="M14 2v6h6" stroke="currentColor" stroke-width="1.6"/></svg>`,
  globe: `<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.6"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.7 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.7-3.8-9S9.5 5.6 12 3z" stroke="currentColor" stroke-width="1.6"/></svg>`,
  clock: `<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.6"/><path d="M12 7v5l3 3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>`,
  trash: `<svg viewBox="0 0 24 24" fill="none"><path d="M4 7h16M9 7V4h6v3m-8 0v13a1 1 0 001 1h8a1 1 0 001-1V7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  archive: `<svg viewBox="0 0 24 24" fill="none"><rect x="3" y="4" width="18" height="4" rx="1" stroke="currentColor" stroke-width="1.8"/><path d="M5 8v11a1 1 0 001 1h12a1 1 0 001-1V8M10 13h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`,
  keep: `<svg viewBox="0 0 24 24" fill="none"><path d="M5 13l4 4L19 7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  transcript: `<svg viewBox="0 0 24 24" fill="none"><path d="M7 8h10M7 12h10M7 16h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" stroke-width="1.6"/></svg>`,
  sparkle: `<svg viewBox="0 0 24 24" fill="none"><path d="M12 3l1.6 4.9L18.5 9.5l-4.9 1.6L12 16l-1.6-4.9L5.5 9.5l4.9-1.6L12 3z" fill="currentColor"/><path d="M19 14l.7 2.1L22 17l-2.3.9L19 20l-.7-2.1L16 17l2.3-.9L19 14z" fill="currentColor"/></svg>`,
  chevron: `<svg class="chevron" viewBox="0 0 24 24" fill="none"><path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
};

const CATEGORY_LABEL = { spam: 'Spam', important: 'Important', normal: 'Normal' };

// ---------- toast ----------
let toastTimer = null;
function showToast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove('show'), 2600);
}

// ---------- upload queue ----------
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  addFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', () => addFiles(fileInput.files));

function addFiles(fileList) {
  for (const f of fileList) pendingFiles.push(f);
  renderQueue();
}

function renderQueue() {
  queueEl.innerHTML = '';
  pendingFiles.forEach((f, idx) => {
    const item = document.createElement('div');
    item.className = 'queue-item';
    item.innerHTML = `${ICONS.file}<span class="queue-name">${escapeHtml(f.name)}</span>
      <button class="queue-remove" data-idx="${idx}" title="Remove">×</button>`;
    queueEl.appendChild(item);
  });
  queueEl.querySelectorAll('.queue-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      pendingFiles.splice(Number(btn.dataset.idx), 1);
      renderQueue();
    });
  });
  analyzeBtn.disabled = pendingFiles.length === 0;
}

// ---------- analyze ----------
analyzeBtn.addEventListener('click', async () => {
  if (pendingFiles.length === 0) return;

  analyzeBtn.disabled = true;
  const originalLabel = analyzeBtn.innerHTML;
  analyzeBtn.innerHTML = `Analyzing ${pendingFiles.length} call(s)…`;

  const formData = new FormData();
  pendingFiles.forEach(f => formData.append('files', f));

  try {
    const res = await fetch('/api/analyze', { method: 'POST', body: formData });
    const data = await res.json();
    if (data.error) {
      showToast(data.error);
    } else {
      const errored = data.results.filter(r => r.error);
      if (errored.length) showToast(`${errored.length} file(s) failed — see console`);
      if (errored.length) console.warn(errored);
      showToast(`Analyzed ${data.results.length} call(s)`);
    }
    pendingFiles = [];
    renderQueue();
    await loadResults();
  } catch (err) {
    showToast('Analysis failed: ' + err.message);
  } finally {
    analyzeBtn.innerHTML = originalLabel;
    analyzeBtn.disabled = pendingFiles.length === 0;
  }
});

// ---------- results ----------
async function loadResults() {
  const res = await fetch('/api/results');
  const data = await res.json();
  renderResults(data.results || []);
}

function renderResults(results) {
  resultsGrid.innerHTML = '';
  const visible = results.filter(r => r.status !== 'deleted');
  emptyState.style.display = visible.length ? 'none' : 'block';

  visible.forEach(r => resultsGrid.appendChild(buildCard(r)));
  updateStats(visible);
}

function updateStats(visible) {
  const counts = { spam: 0, important: 0, normal: 0 };
  visible.forEach(r => {
    if (counts.hasOwnProperty(r.category)) counts[r.category]++;
  });
  statTotal.textContent = visible.length;
  statSpam.textContent = counts.spam;
  statImportant.textContent = counts.important;
  statNormal.textContent = counts.normal;
}

function buildCard(r) {
  const card = document.createElement('div');
  card.className = `card ${r.category}`;
  card.dataset.id = r.id;

  const bars = Array.from({ length: 14 }).map((_, i) =>
    `<span style="height:${6 + (i % 5) * 4}px; animation-delay:${(i * 0.07).toFixed(2)}s"></span>`).join('');

  const statusHtml = r.status && r.status !== 'pending'
    ? `<div class="card-status">status: ${r.status}</div>`
    : '';

  card.innerHTML = `
    <div class="card-top">
      <div class="card-title">
        ${ICONS[r.category]}
        <span class="card-filename" title="${escapeHtml(r.filename)}">${escapeHtml(r.filename)}</span>
      </div>
      <span class="badge">${CATEGORY_LABEL[r.category] || r.category}</span>
    </div>

    <div class="card-meta">
      <span class="meta-chip">${ICONS.globe} ${escapeHtml((r.language || '?').toUpperCase())}</span>
      <span class="meta-chip">${ICONS.clock} ${formatDuration(r.duration_seconds)}</span>
    </div>

    <div class="waveform">${bars}</div>

    ${r.ai_summary ? `
    <div class="card-summary">
      <div class="summary-label">${ICONS.sparkle} AI Summary</div>
      <p class="summary-text">${escapeHtml(r.ai_summary)}</p>
    </div>` : ''}

    <div class="card-transcript">
      <button class="transcript-toggle" data-toggle="transcript" aria-expanded="false">
        ${ICONS.transcript} <span>Show transcript</span> ${ICONS.chevron}
      </button>
      <div class="transcript-text" hidden>${r.transcript ? escapeHtml(r.transcript) : '<em>No transcript available.</em>'}</div>
    </div>

    <div class="card-actions">
      <button class="btn act-delete" data-action="delete" title="Delete this call">${ICONS.trash} Delete</button>
      <button class="btn act-archive" data-action="archive" title="Archive this call">${ICONS.archive} Archive</button>
      <button class="btn act-keep" data-action="keep" title="Keep this call">${ICONS.keep} Keep</button>
    </div>
    ${statusHtml}
  `;

  card.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', () => performAction(r.id, btn.dataset.action, card));
  });

  const transcriptToggle = card.querySelector('[data-toggle="transcript"]');
  const transcriptText = card.querySelector('.transcript-text');
  transcriptToggle.addEventListener('click', () => {
    const isOpen = !transcriptText.hidden;
    transcriptText.hidden = isOpen;
    transcriptToggle.setAttribute('aria-expanded', String(!isOpen));
    transcriptToggle.classList.toggle('open', !isOpen);
    transcriptToggle.querySelector('span').textContent = isOpen ? 'Show transcript' : 'Hide transcript';
  });

  return card;
}

async function performAction(id, action, cardEl) {
  try {
    const res = await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, action }),
    });
    const data = await res.json();
    if (data.error) { showToast(data.error); return; }

    if (action === 'delete') {
      cardEl.style.opacity = '0';
      cardEl.style.transform = 'scale(0.96)';
      setTimeout(async () => {
        cardEl.remove();
        checkEmpty();
        await loadResults(); // resync stats bar counts after removal
      }, 150);
      showToast('Call deleted');
    } else if (action === 'archive') {
      showToast('Call archived');
      await loadResults();
    } else if (action === 'keep') {
      showToast('Call kept');
      await loadResults();
    }
  } catch (err) {
    showToast('Action failed: ' + err.message);
  }
}

function checkEmpty() {
  emptyState.style.display = resultsGrid.children.length ? 'none' : 'block';
}

// ---------- clear all ----------
clearAllBtn.addEventListener('click', async () => {
  if (!confirm('Clear all pending call results? Archived calls are kept.')) return;
  try {
    await fetch('/api/clear', { method: 'POST' });
    showToast('Cleared');
    await loadResults();
  } catch (err) {
    showToast('Clear failed: ' + err.message);
  }
});

// ---------- download json ----------
downloadBtn.addEventListener('click', () => {
  window.location.href = '/api/download-json';
});

// ---------- helpers ----------
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

function truncate(str, n) {
  return str.length > n ? str.slice(0, n).trim() + '…' : str;
}

function formatDuration(sec) {
  if (!sec && sec !== 0) return '--:--';
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

// ---------- init ----------
(async function init() {
  renderQueue();
  await loadResults();
  modelPill.textContent = 'model: faster-whisper';
})();