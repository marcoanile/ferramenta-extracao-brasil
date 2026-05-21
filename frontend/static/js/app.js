/* Nexus Extrator */
'use strict';

// ── Theme ──────────────────────────────────────────────────────────────────
function initTheme() {
  applyTheme(localStorage.getItem('nexus-theme') || 'dark');
}
function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  applyTheme(next);
  localStorage.setItem('nexus-theme', next);
}
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = theme === 'light' ? '☀' : '🌙';
}

// ── Toast ──────────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

// ── Escape HTML ────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Format period ──────────────────────────────────────────────────────────
function fmtPeriod(start, end) {
  const fmt = s => s ? s.slice(0, 10).split('-').reverse().join('/') : '?';
  if (!start && !end) return '—';
  return `${fmt(start)} → ${fmt(end)}`;
}

// ── Tabs ───────────────────────────────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(el =>
    el.classList.toggle('active', el.dataset.tab === tab));
  if (tab === 'converter') renderConverter();
  else renderConsolidar();
}

// ── Boot ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  renderConverter();
});

// ══════════════════════════════════════════════════════════════════════════
// CONVERTER TAB
// ══════════════════════════════════════════════════════════════════════════

const BANKS = [
  'Millennium BCP', 'BPI', 'CGD', 'Santander',
  'Novo Banco', 'Bankinter', 'Crédito Agrícola',
];

let converterBlob = null;
let converterFilename = 'extrato.xlsx';

function renderConverter() {
  document.getElementById('content').innerHTML = `
    <div class="converter-wrap">
      <div class="converter-hero">
        <h2>Converter extrato bancário</h2>
        <p>Arraste um ficheiro PDF, Excel ou CSV. Recebe de imediato o Excel pronto a importar no TOConline.</p>
      </div>
      <div id="converter-body"></div>
    </div>`;
  showConverterIdle();
}

function showConverterIdle() {
  document.getElementById('converter-body').innerHTML = `
    <div class="drop-zone" id="conv-drop" onclick="document.getElementById('conv-file').click()">
      <div class="dz-icon">📄</div>
      <div class="dz-title">Clique ou arraste o ficheiro aqui</div>
      <div class="dz-sub">PDF · XLSX · XLS · CSV</div>
    </div>
    <input type="file" id="conv-file" accept=".pdf,.xlsx,.xls,.csv"
           style="display:none" onchange="handleConverterFile(event)">
    <div class="bank-chips">
      ${BANKS.map(b => `<span class="chip">${esc(b)}</span>`).join('')}
    </div>`;

  const zone = document.getElementById('conv-drop');
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag');
    const f = e.dataTransfer.files[0];
    if (f) uploadConverter(f);
  });
}

function handleConverterFile(e) {
  const f = e.target.files[0];
  if (f) uploadConverter(f);
}

function showConverterProcessing(filename) {
  document.getElementById('converter-body').innerHTML = `
    <div class="progress-wrap">
      <div class="progress-label">A processar <em>${esc(filename)}</em>…</div>
      <div class="progress-bar"><div class="progress-fill"></div></div>
      <div class="progress-sub">A detectar banco e extrair movimentos…</div>
    </div>`;
}

function showConverterDone(bankName, movCount, periodStart, periodEnd) {
  const period = fmtPeriod(periodStart, periodEnd);
  const el = document.getElementById('converter-body');
  if (!el) {
    toast(`${esc(bankName || 'Extrato')} convertido — ficheiro descarregado`, 'success');
    return;
  }
  el.innerHTML = `
    <div class="result-card">
      <div class="result-icon">✅</div>
      <div class="result-title">Extrato convertido com sucesso</div>
      <div class="result-meta">
        ${esc(bankName || 'Banco detectado')}
        ${movCount ? ` · ${esc(movCount)} movimentos` : ''}
        ${period !== '—' ? `<br>${period}` : ''}
      </div>
      <div class="result-actions">
        <button class="btn btn-primary" onclick="downloadConverterFile()">⬇ Descarregar Excel</button>
        <button class="btn btn-outline" onclick="showConverterIdle()">Converter outro ficheiro</button>
      </div>
    </div>`;
}

function showConverterError(msg) {
  const el = document.getElementById('converter-body');
  if (!el) { toast(`Erro ao converter: ${msg}`, 'error'); return; }
  el.innerHTML = `
    <div class="result-card error">
      <div class="result-icon">❌</div>
      <div class="result-title">Erro ao converter</div>
      <div class="result-meta error-text">${esc(msg)}</div>
      <div class="result-actions">
        <button class="btn btn-outline" onclick="showConverterIdle()">Tentar novamente</button>
      </div>
    </div>`;
}

async function uploadConverter(file) {
  showConverterProcessing(file.name);
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch('/convert', { method: 'POST', body: fd });
    if (!r.ok) {
      const d = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
      showConverterError(d.error || 'Erro desconhecido');
      return;
    }
    const bankName  = r.headers.get('X-Bank-Name') || '';
    const movCount  = r.headers.get('X-Movement-Count') || '';
    const periodStart = r.headers.get('X-Period-Start') || '';
    const periodEnd   = r.headers.get('X-Period-End') || '';

    const cd = r.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename[^;=\n]*=["']?([^"';\n]+)/);
    converterFilename = match ? match[1] : 'extrato.xlsx';
    converterBlob = await r.blob();

    showConverterDone(bankName, movCount, periodStart, periodEnd);
    downloadConverterFile();
  } catch (e) {
    showConverterError(e.message);
  }
}

function downloadConverterFile() {
  if (!converterBlob) return;
  const url = URL.createObjectURL(converterBlob);
  const a = Object.assign(document.createElement('a'), { href: url, download: converterFilename });
  a.click();
  URL.revokeObjectURL(url);
}

// ══════════════════════════════════════════════════════════════════════════
// CONSOLIDAR TAB
// ══════════════════════════════════════════════════════════════════════════

let groups = [];
let activeGroupId = null;
let groupExtracts = [];

async function renderConsolidar() {
  await loadGroups();
  document.getElementById('content').innerHTML = `
    <div class="consolidar-hero">
      <h2>Consolidar extratos bancários</h2>
      <p>Agrupe extratos mensais e gere um Excel unificado pronto a importar.</p>
    </div>
    <div class="consolidar-wrap">
      <div class="groups-panel">
        <div class="groups-panel-header">
          <span>Grupos</span>
          <button class="btn btn-sm btn-outline" onclick="showNewGroupForm()">+ Novo</button>
        </div>
        <div id="groups-list" class="groups-list"></div>
      </div>
      <div class="group-workspace" id="group-workspace">
        <div class="empty-state">
          <div class="es-icon">📂</div>
          <p>Selecione um grupo ou crie um novo<br>para começar a consolidar extratos.</p>
        </div>
      </div>
    </div>`;
  renderGroupsList();
  if (activeGroupId) await loadGroupWorkspace(activeGroupId);
}

async function loadGroups() {
  try {
    const r = await fetch('/api/groups');
    const d = await r.json();
    groups = d.data || [];
  } catch (e) {
    groups = [];
  }
}

function renderGroupsList() {
  const el = document.getElementById('groups-list');
  if (!el) return;
  if (!groups.length) {
    el.innerHTML = '<div class="empty-state" style="padding:20px 14px"><p>Sem grupos ainda</p></div>';
    return;
  }
  el.innerHTML = groups.map(g => `
    <div class="group-item ${g.id === activeGroupId ? 'active' : ''}"
         onclick="selectGroup(${g.id})">
      <div class="group-item-name">${esc(g.name)}</div>
      <div class="group-item-meta">${g.extract_count} extrato${g.extract_count !== 1 ? 's' : ''}</div>
    </div>`).join('');
}

function showNewGroupForm() {
  const list = document.getElementById('groups-list');
  if (!list || document.getElementById('new-group-input')) return;
  const form = document.createElement('div');
  form.className = 'new-group-form';
  form.innerHTML = `
    <input type="text" id="new-group-input" placeholder="Nome do grupo" maxlength="80">
    <button class="btn btn-sm btn-primary" onclick="confirmNewGroup()">✓</button>`;
  list.prepend(form);
  const input = document.getElementById('new-group-input');
  input.focus();
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') confirmNewGroup();
    if (e.key === 'Escape') form.remove();
  });
}

async function confirmNewGroup() {
  const input = document.getElementById('new-group-input');
  if (!input) return;
  const name = input.value.trim();
  if (!name) return;
  try {
    const r = await fetch('/api/groups', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const d = await r.json();
    if (d.error) { toast(d.error, 'error'); return; }
    activeGroupId = d.id;
    await renderConsolidar();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function selectGroup(id) {
  activeGroupId = id;
  renderGroupsList();
  await loadGroupWorkspace(id);
}

async function loadGroupWorkspace(id) {
  const group = groups.find(g => g.id === id);
  if (!group) return;
  try {
    const r = await fetch(`/api/groups/${id}/extracts`);
    const d = await r.json();
    groupExtracts = d.data || [];
  } catch (e) {
    groupExtracts = [];
  }
  renderWorkspace(group);
}

function renderWorkspace(group) {
  const ws = document.getElementById('group-workspace');
  if (!ws) return;
  ws.innerHTML = `
    <div class="workspace-header">
      <span class="workspace-title">${esc(group.name)}</span>
      <div class="workspace-actions">
        <button class="btn btn-primary btn-sm" onclick="generateGroup(${group.id})">
          ⬇ Gerar Excel Consolidado
        </button>
        <button class="btn-icon" title="Eliminar grupo" onclick="confirmDeleteGroup(${group.id})">🗑</button>
      </div>
    </div>
    <div class="workspace-body">
      <div class="workspace-drop" id="ws-drop"
           onclick="document.getElementById('ws-file').click()">
        <p>📥 Arraste um extrato para adicionar ao grupo</p>
        <p>PDF · XLSX · XLS · CSV</p>
      </div>
      <input type="file" id="ws-file" accept=".pdf,.xlsx,.xls,.csv" style="display:none"
             onchange="handleWorkspaceFile(event, ${group.id})">
      <div id="extracts-table">${renderExtractsTable(group.id)}</div>
    </div>`;

  const drop = document.getElementById('ws-drop');
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
  drop.addEventListener('drop', e => {
    e.preventDefault();
    drop.classList.remove('drag');
    const f = e.dataTransfer.files[0];
    if (f) uploadToGroup(group.id, f);
  });
}

function renderExtractsTable(groupId) {
  if (!groupExtracts.length) {
    return `<div class="empty-state">
      <div class="es-icon">📭</div>
      <p>Ainda sem extratos.<br>Arraste um ficheiro para começar.</p>
    </div>`;
  }
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Banco</th><th>Período</th><th>Movimentos</th><th></th></tr>
        </thead>
        <tbody>
          ${groupExtracts.map(e => `
            <tr>
              <td>${esc(e.bank_name || '—')}</td>
              <td class="text-muted">${esc(fmtPeriod(e.period_start, e.period_end))}</td>
              <td>${esc(e.movement_count ?? '—')}</td>
              <td>
                <button class="btn-icon" title="Remover extrato"
                        onclick="removeExtract(${groupId}, ${e.id})">🗑</button>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

function handleWorkspaceFile(e, groupId) {
  const f = e.target.files[0];
  if (f) uploadToGroup(groupId, f);
}

async function uploadToGroup(groupId, file) {
  toast(`A processar ${file.name}…`, 'info');
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch(`/api/groups/${groupId}/upload`, { method: 'POST', body: fd });
    const d = await r.json();
    if (d.error) { toast(d.error, 'error'); return; }
    toast(
      `${d.bank_name || 'Extrato'} adicionado` +
      (d.movement_count ? ` (${d.movement_count} movimentos)` : ''),
      'success'
    );
    await loadGroups();
    renderGroupsList();
    await loadGroupWorkspace(groupId);
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function removeExtract(groupId, extractId) {
  try {
    await fetch(`/api/groups/${groupId}/extracts/${extractId}`, { method: 'DELETE' });
    await loadGroups();
    renderGroupsList();
    await loadGroupWorkspace(groupId);
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function confirmDeleteGroup(groupId) {
  if (!confirm('Eliminar este grupo e todos os seus extratos? Esta acção não pode ser desfeita.')) return;
  try {
    await fetch(`/api/groups/${groupId}`, { method: 'DELETE' });
    activeGroupId = null;
    await renderConsolidar();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function generateGroup(groupId) {
  toast('A gerar Excel consolidado…', 'info');
  try {
    const r = await fetch(`/api/groups/${groupId}/generate`);
    if (!r.ok) {
      const d = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
      toast(d.error || 'Erro ao gerar Excel', 'error');
      return;
    }
    const blob = await r.blob();
    const cd = r.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename[^;=\n]*=["']?([^"';\n]+)/);
    const filename = match ? match[1] : 'consolidado.xlsx';
    const url = URL.createObjectURL(blob);
    Object.assign(document.createElement('a'), { href: url, download: filename }).click();
    URL.revokeObjectURL(url);
    toast('Excel consolidado descarregado!', 'success');
  } catch (e) {
    toast(e.message, 'error');
  }
}
