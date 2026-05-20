/* Nexus Accounting Robot — Main Application JS */
'use strict';

const API = '';  // same origin

let state = {
  view: 'dashboard',
  clients: [],
  activeClient: null,
  activeYear: new Date().getFullYear(),
  authOk: false,
};

// ── Boot ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  initTheme();
  document.getElementById('upload-year').value = state.activeYear;
  await checkAuth();
  await loadClients();
  navigate('dashboard');

  // Handle drag-and-drop on upload zone
  const zone = document.getElementById('upload-zone');
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag');
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });

  // Check for auth redirect
  const params = new URLSearchParams(window.location.search);
  if (params.get('auth') === 'success') {
    toast('TOConline autenticado com sucesso!', 'success');
    await checkAuth();
    history.replaceState({}, '', '/');
  }
});

// ── Sidebar toggle (mobile) ─────────────────────────────────────────────
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('sidebar-overlay').classList.toggle('visible');
}
function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebar-overlay').classList.remove('visible');
}

// Theme toggle
function initTheme() {
  const savedTheme = localStorage.getItem('nexus-theme') || 'dark';
  applyTheme(savedTheme);
}

function toggleTheme() {
  const currentTheme = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
  const nextTheme = currentTheme === 'light' ? 'dark' : 'light';
  applyTheme(nextTheme);
  localStorage.setItem('nexus-theme', nextTheme);
}

function applyTheme(theme) {
  const isLight = theme === 'light';
  document.documentElement.dataset.theme = isLight ? 'light' : 'dark';

  const button = document.getElementById('theme-toggle');
  if (!button) return;

  button.textContent = isLight ? '☀' : '🌙';
  button.title = isLight ? 'Mudar para tema escuro' : 'Mudar para tema claro';
  button.setAttribute('aria-label', button.title);
}

// ── Navigation ─────────────────────────────────────────────────────────
function navigate(view, clientId = null) {
  closeSidebar();
  state.view = view;
  if (clientId) state.activeClient = state.clients.find(c => c.id === clientId) || state.activeClient;

  document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  document.querySelectorAll('.client-entry').forEach(el => el.classList.toggle('active', +el.dataset.id === (state.activeClient?.id)));

  const titles = { dashboard: 'Dashboard', clients: 'Clientes', settings: 'Configurações', client_detail: state.activeClient?.name || 'Cliente' };
  document.getElementById('topbar-title').textContent = titles[view] || view;

  const content = document.getElementById('content');
  switch (view) {
    case 'dashboard': renderDashboard(content); break;
    case 'clients': renderClients(content); break;
    case 'client_detail': renderClientDetail(content); break;
    case 'settings': renderSettings(content); break;
    default: content.innerHTML = `<div class="empty-state"><div class="icon">🚧</div><p>Vista não encontrada</p></div>`;
  }
}

// ── Auth ─────────────────────────────────────────────────────────────────
let authStatus = {};

async function checkAuth() {
  try {
    const r = await fetch('/api/auth/toconline/status');
    authStatus = await r.json();
    state.authOk = authStatus.authenticated;
    const badge = document.getElementById('auth-status');
    const link = document.getElementById('auth-link');
    badge.textContent = state.authOk ? 'TOConline conectado' : 'Não autenticado';
    badge.className = `auth-badge ${state.authOk ? 'ok' : 'no'}`;
    link.style.display = state.authOk ? 'none' : '';
  } catch (e) { console.error(e); }
}

function openAuthModal() {
  document.getElementById('auth-modal').style.display = 'flex';
  if (authStatus.credentials_configured) {
    showAuthLogin();
  } else {
    showCredSetup();
  }
}

function showCredSetup() {
  document.getElementById('auth-step-setup').style.display = 'block';
  document.getElementById('auth-step-login').style.display = 'none';
  // pre-fill if already saved
  if (authStatus.oauth_url) document.getElementById('cred-oauth-url').value = authStatus.oauth_url;
  if (authStatus.client_id) document.getElementById('cred-client-id').value = authStatus.client_id;
}

function showAuthLogin() {
  document.getElementById('auth-step-setup').style.display = 'none';
  document.getElementById('auth-step-login').style.display = 'block';
  document.getElementById('redirect-uri-display').textContent =
    window.location.origin + '/api/auth/toconline/callback';
}

function closeAuthModal() { document.getElementById('auth-modal').style.display = 'none'; }

async function saveCredentials() {
  const oauth_url = document.getElementById('cred-oauth-url').value.trim();
  const client_id = document.getElementById('cred-client-id').value.trim();
  const client_secret = document.getElementById('cred-client-secret').value.trim();
  const api_url = document.getElementById('cred-api-url').value.trim();

  if (!oauth_url || !client_id || !client_secret) {
    toast('Preencha todos os campos obrigatórios', 'error');
    return;
  }

  try {
    const r = await fetch('/api/auth/toconline/configure', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ oauth_url, client_id, client_secret, api_url }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    authStatus.credentials_configured = true;
    authStatus.oauth_url = oauth_url;
    authStatus.client_id = client_id;
    toast('Credenciais guardadas', 'success');
    showAuthLogin();
  } catch (e) { toast(e.message, 'error'); }
}

async function startAuth() {
  const r = await fetch('/api/auth/toconline/start');
  const d = await r.json();
  if (d.auth_url) {
    window.open(d.auth_url, '_blank');
    closeAuthModal();
    toast('Janela de autorização aberta. Após autorizar no TOConline, a página será atualizada.', 'info');
  } else if (d.error) {
    toast(d.error, 'error');
  }
}

// ── Clients ─────────────────────────────────────────────────────────────
async function loadClients() {
  try {
    const r = await fetch('/api/clients');
    const d = await r.json();
    state.clients = d.data || [];
    renderSidebarClients();
  } catch (e) { console.error(e); }
}

function renderSidebarClients() {
  const el = document.getElementById('sidebar-clients');
  if (!state.clients.length) {
    el.innerHTML = '<div class="client-entry text-sm" style="opacity:.5">Sem clientes</div>';
    return;
  }
  el.innerHTML = state.clients.slice(0, 15).map(c => `
    <div class="client-entry ${state.activeClient?.id === c.id ? 'active' : ''}" data-id="${c.id}"
         onclick="openClient(${c.id})">
      <span class="dot"></span>
      <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.name)}</span>
    </div>
  `).join('');
}

async function syncClients() {
  if (!state.authOk) { openAuthModal(); return; }
  toast('A sincronizar clientes do TOConline…', 'info');
  try {
    const r = await fetch('/api/clients/sync', { method: 'POST' });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    await loadClients();
    toast(d.message, 'success');
    navigate(state.view);
  } catch (e) { toast(e.message, 'error'); }
}

async function openClient(id) {
  const client = state.clients.find(c => c.id === id);
  state.activeClient = client;
  navigate('client_detail', id);
}

// ── Dashboard ─────────────────────────────────────────────────────────
function renderDashboard(el) {
  const total = state.clients.length;
  el.innerHTML = `
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Clientes</div>
        <div class="stat-value">${total}</div>
        <div class="stat-sub">na base de dados local</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">TOConline</div>
        <div class="stat-value">${state.authOk ? '✓' : '—'}</div>
        <div class="stat-sub">${state.authOk ? 'Conectado' : 'Não autenticado'}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Ano Activo</div>
        <div class="stat-value">${state.activeYear}</div>
        <div class="stat-sub">exercício corrente</div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">🚀 Início Rápido</div>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <button class="btn btn-primary" onclick="syncClients()">🔄 Sincronizar Clientes TOConline</button>
        <button class="btn btn-outline" onclick="navigate('clients')">🏢 Ver Todos os Clientes</button>
        ${!state.authOk ? `<button class="btn btn-accent" onclick="openAuthModal()">🔐 Autenticar TOConline</button>` : ''}
      </div>
    </div>

    <div class="card">
      <div class="card-title">🏢 Clientes Recentes</div>
      ${state.clients.length ? `
        <div class="table-wrap">
          <table>
            <thead><tr><th>Nome</th><th>NIF</th><th>Plataforma</th><th>Acções</th></tr></thead>
            <tbody>
              ${state.clients.slice(0, 8).map(c => `
                <tr>
                  <td><strong>${esc(c.name)}</strong></td>
                  <td>${esc(c.nif || '—')}</td>
                  <td><span class="badge badge-info">${esc(c.platform)}</span></td>
                  <td><button class="btn btn-sm btn-outline" onclick="openClient(${c.id})">Abrir</button></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      ` : `<div class="empty-state"><div class="icon">🏢</div><p>Sem clientes. Sincronize com o TOConline ou adicione manualmente.</p></div>`}
    </div>
  `;
}

// ── Clients view ─────────────────────────────────────────────────────────
function renderClients(el) {
  el.innerHTML = `
    <div class="flex-between" style="margin-bottom:20px">
      <h3 style="font-size:18px;font-weight:700">Todos os Clientes</h3>
      <div style="display:flex;gap:8px">
        <button class="btn btn-outline btn-sm" onclick="syncClients()">🔄 Sincronizar TOConline</button>
        <button class="btn btn-primary btn-sm" onclick="showAddClientModal()">+ Adicionar Cliente</button>
      </div>
    </div>
    <div class="card">
      <div class="table-wrap">
        ${state.clients.length ? `
          <table>
            <thead><tr><th>Nome</th><th>NIF</th><th>Plataforma</th><th>ID TOConline</th><th>Acções</th></tr></thead>
            <tbody>
              ${state.clients.map(c => `
                <tr>
                  <td><strong>${esc(c.name)}</strong></td>
                  <td>${esc(c.nif || '—')}</td>
                  <td><span class="badge badge-info">${esc(c.platform)}</span></td>
                  <td class="text-muted text-sm">${esc(c.toconline_id || '—')}</td>
                  <td><button class="btn btn-sm btn-outline" onclick="openClient(${c.id})">Abrir</button></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        ` : `<div class="empty-state"><div class="icon">🏢</div><p>Sem clientes.</p></div>`}
      </div>
    </div>
  `;
}

// ── Client Detail ─────────────────────────────────────────────────────────
let clientDetail = null;

async function renderClientDetail(el) {
  if (!state.activeClient) { navigate('clients'); return; }
  const id = state.activeClient.id;

  el.innerHTML = `<div class="loading">A carregar dados do cliente…</div>`;
  try {
    const r = await fetch(`/api/clients/${id}`);
    const d = await r.json();
    clientDetail = d;
    renderSidebarClients();
    _drawClientDetail(el, d);
  } catch (e) {
    el.innerHTML = `<div class="empty-state"><div class="icon">❌</div><p>${e.message}</p></div>`;
  }
}

function _drawClientDetail(el, d) {
  const c = d.data;
  const stmts = d.statements || [];
  const recon = d.reconciliation || {};
  const matchedPct = recon.matched_pct || 0;

  el.innerHTML = `
    <!-- Header -->
    <div class="flex-between" style="margin-bottom:20px">
      <div>
        <h3 style="font-size:20px;font-weight:700">${esc(c.name)}</h3>
        <span class="text-muted text-sm">NIF: ${esc(c.nif || '—')} &nbsp;|&nbsp; ID: ${esc(c.toconline_id || '—')}</span>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <select id="year-select" style="width:100px" onchange="changeYear(this.value)">
          ${[2023,2024,2025,2026].map(y => `<option ${y===state.activeYear?'selected':''}>${y}</option>`).join('')}
        </select>
        <button class="btn btn-primary btn-sm" onclick="openUploadModal()">📤 Carregar Extrato</button>
        <button class="btn btn-outline btn-sm" onclick="runReconciliation(${c.id})">🔁 Reconciliar</button>
      </div>
    </div>

    <!-- Stats -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Extratos</div>
        <div class="stat-value">${stmts.length}</div>
        <div class="stat-sub">carregados</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Movimentos</div>
        <div class="stat-value">${recon.total || 0}</div>
        <div class="stat-sub">total de linhas</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Reconciliados</div>
        <div class="stat-value" style="color:var(--success)">${recon.matched || 0}</div>
        <div class="stat-sub">${matchedPct}% do total</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Por Rever</div>
        <div class="stat-value" style="color:var(--warning)">${recon.review || 0}</div>
        <div class="stat-sub">requer atenção</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Por Reconciliar</div>
        <div class="stat-value" style="color:var(--danger)">${recon.unmatched || 0}</div>
        <div class="stat-sub">sem correspondência</div>
      </div>
    </div>

    <!-- Reconciliation progress -->
    ${recon.total ? `
    <div class="card">
      <div class="card-title">📊 Estado da Reconciliação</div>
      <div class="recon-bars">
        <div class="recon-bar-row">
          <span class="recon-bar-label">Reconciliado</span>
          <div class="recon-bar-track"><div class="recon-bar-fill matched" style="width:${(recon.matched||0)/recon.total*100}%;background:var(--success)"></div></div>
          <span class="recon-bar-count" style="color:var(--success)">${recon.matched||0}</span>
        </div>
        <div class="recon-bar-row">
          <span class="recon-bar-label">Rever</span>
          <div class="recon-bar-track"><div class="recon-bar-fill" style="width:${(recon.review||0)/recon.total*100}%;background:var(--warning)"></div></div>
          <span class="recon-bar-count" style="color:var(--warning)">${recon.review||0}</span>
        </div>
        <div class="recon-bar-row">
          <span class="recon-bar-label">Por reconciliar</span>
          <div class="recon-bar-track"><div class="recon-bar-fill" style="width:${(recon.unmatched||0)/recon.total*100}%;background:var(--danger)"></div></div>
          <span class="recon-bar-count" style="color:var(--danger)">${recon.unmatched||0}</span>
        </div>
      </div>
    </div>
    ` : ''}

    <!-- Statements -->
    <div class="card">
      <div class="card-title">📁 Extratos Bancários</div>
      ${stmts.length ? `
        <div class="table-wrap">
          <table>
            <thead><tr><th>Ficheiro</th><th>Banco</th><th>Período</th><th>Movimentos</th><th>Estado</th><th>Acções</th></tr></thead>
            <tbody>
              ${stmts.map(s => `
                <tr>
                  <td>${esc(s.filename)}</td>
                  <td>${esc(s.bank_name || '—')}</td>
                  <td class="text-sm text-muted">${s.period_start || ''}${s.period_end ? ' → '+s.period_end : ''}</td>
                  <td>${s.movement_count || 0}</td>
                  <td>${statusBadge(s.status)}</td>
                  <td>
                    ${s.converted_path ? `<button class="btn btn-sm btn-success" onclick="downloadConverted(${c.id},${s.id})">⬇ Excel</button>` : ''}
                    <button class="btn btn-sm btn-outline" onclick="viewMovements(${c.id},${s.id})">Ver</button>
                    <button class="btn btn-sm btn-outline" onclick="addToConsolidatedModal(${c.id},${s.id})" title="Adicionar a extrato consolidado">＋</button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      ` : `<div class="empty-state"><div class="icon">📂</div><p>Sem extratos. Carregue um ficheiro para começar.</p></div>`}
    </div>

    <!-- Consolidated Extracts -->
    <div class="card" id="consolidated-section">
      <div class="flex-between" style="margin-bottom:12px">
        <div class="card-title" style="margin:0">📂 Extratos Consolidados</div>
        <button class="btn btn-sm btn-primary" onclick="createConsolidatedModal(${c.id})">+ Novo</button>
      </div>
      <div id="consolidated-list">A carregar...</div>
    </div>

    <!-- Movements table -->
    <div class="card" id="movements-section" style="display:none">
      <div class="flex-between" style="margin-bottom:12px">
        <div class="card-title" style="margin:0">📋 Movimentos</div>
        <div style="display:flex;gap:8px">
          <select id="status-filter" onchange="filterMovements(${c.id})">
            <option value="">Todos</option>
            <option value="matched">Reconciliados</option>
            <option value="review">Rever</option>
            <option value="unmatched">Não reconciliados</option>
          </select>
        </div>
      </div>
      <div id="movements-table">A carregar…</div>
    </div>
  `;
  // Load consolidated extracts asynchronously after HTML is rendered
  loadConsolidated(c.id);
}

async function viewMovements(clientId, stmtId) {
  const section = document.getElementById('movements-section');
  section.style.display = 'block';
  section.scrollIntoView({ behavior: 'smooth' });
  await loadMovements(clientId, stmtId);
}

async function loadMovements(clientId, stmtId = null, status = null) {
  const el = document.getElementById('movements-table');
  if (!el) return;
  el.innerHTML = '<div class="loading">A carregar movimentos…</div>';

  let url = `/api/clients/${clientId}/movements?year=${state.activeYear}`;
  if (stmtId) url += `&statement_id=${stmtId}`;
  if (status) url += `&status=${status}`;

  const r = await fetch(url);
  const d = await r.json();
  const movs = d.data || [];

  if (!movs.length) {
    el.innerHTML = '<div class="empty-state"><div class="icon">🔍</div><p>Sem movimentos.</p></div>';
    return;
  }

  el.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Data</th><th>Descrição</th><th>Débito</th><th>Crédito</th><th>Saldo</th><th>Estado</th><th></th></tr></thead>
        <tbody>
          ${movs.map(m => {
            const isDebit = m.amount < 0;
            return `<tr>
              <td style="white-space:nowrap">${m.date}</td>
              <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(m.description)}">${esc(m.description || '')}</td>
              <td class="amount debit">${isDebit ? fmt(Math.abs(m.amount)) : ''}</td>
              <td class="amount credit">${!isDebit ? fmt(m.amount) : ''}</td>
              <td class="amount">${m.balance != null ? fmt(m.balance) : ''}</td>
              <td>${reconBadge(m.reconciliation_status)}</td>
              <td>
                ${m.reconciliation_status !== 'matched' ? `
                  <button class="btn btn-sm btn-outline" onclick="markMatched(${clientId},${m.id})">✓</button>
                ` : ''}
              </td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>
    <p class="text-sm text-muted mt-8">${movs.length} movimentos</p>
  `;
}

async function filterMovements(clientId) {
  const status = document.getElementById('status-filter')?.value;
  await loadMovements(clientId, null, status || null);
}

async function markMatched(clientId, movId) {
  await fetch(`/api/clients/${clientId}/movements/${movId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reconciliation_status: 'matched' }),
  });
  toast('Marcado como reconciliado', 'success');
  await loadMovements(clientId);
}

function changeYear(y) {
  state.activeYear = +y;
  navigate('client_detail');
}

// ── Upload ─────────────────────────────────────────────────────────────
let uploadClientId = null;

function openUploadModal() {
  if (!state.activeClient) { toast('Seleccione um cliente primeiro', 'error'); return; }
  uploadClientId = state.activeClient.id;
  document.getElementById('upload-modal').style.display = 'flex';
}

function closeUploadModal() {
  document.getElementById('upload-modal').style.display = 'none';
  document.getElementById('upload-progress').style.display = 'none';
  document.getElementById('upload-bar').style.width = '0%';
}

function handleFileSelect(e) {
  const file = e.target.files[0];
  if (file) uploadFile(file);
}

async function uploadFile(file) {
  const bankHint = document.getElementById('upload-bank-hint').value;
  const year = document.getElementById('upload-year').value;

  const progress = document.getElementById('upload-progress');
  const bar = document.getElementById('upload-bar');
  const status = document.getElementById('upload-status');

  progress.style.display = 'block';
  bar.style.width = '30%';
  status.textContent = 'A enviar ficheiro…';

  const form = new FormData();
  form.append('file', file);
  form.append('bank_hint', bankHint);
  form.append('year', year);

  try {
    bar.style.width = '60%';
    status.textContent = 'A processar extrato…';

    const r = await fetch(`/api/clients/${uploadClientId}/statements/upload`, { method: 'POST', body: form });
    const d = await r.json();

    bar.style.width = '100%';

    if (d.error) throw new Error(d.error);

    status.textContent = `✓ ${d.movements} movimentos importados (${d.inserted} novos, ${d.duplicates_skipped} duplicados ignorados)`;
    toast(`Extrato processado: ${d.movements} movimentos — Banco: ${d.bank_name}`, 'success');

    if (d.warnings?.length) d.warnings.forEach(w => toast(w, 'info'));

    setTimeout(() => {
      closeUploadModal();
      navigate('client_detail');
    }, 2000);
  } catch (e) {
    bar.style.width = '0%';
    status.textContent = `Erro: ${e.message}`;
    toast(e.message, 'error');
  }
}

// ── Reconciliation ────────────────────────────────────────────────────────
async function runReconciliation(clientId) {
  toast('A executar reconciliação…', 'info');
  try {
    const r = await fetch(`/api/clients/${clientId}/reconciliation/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ year: state.activeYear }),
    });
    const d = await r.json();
    toast(`Reconciliação: ${d.matched} correspondências, ${d.unmatched} por reconciliar`, 'success');
    navigate('client_detail');
  } catch (e) { toast(e.message, 'error'); }
}

// ── Consolidated Extracts ────────────────────────────────────────────────

async function loadConsolidated(clientId) {
  const el = document.getElementById('consolidated-list');
  if (!el) return;
  try {
    const r = await fetch(`/api/clients/${clientId}/consolidated`);
    const d = await r.json();
    const items = d.data || [];
    if (!items.length) {
      el.innerHTML = `<div class="empty-state" style="padding:16px 0"><p style="margin:0;color:var(--text-muted)">Nenhum extrato consolidado. Clique em <strong>+ Novo</strong> para criar um.</p></div>`;
      return;
    }
    el.innerHTML = items.map(ce => {
      const stmts = ce.statements || [];
      const periods = stmts.map(s => s.period_start ? s.period_start.slice(0,7) : '?').join(', ');
      return `
        <div style="border:1px solid var(--border);border-radius:8px;padding:14px 16px;margin-bottom:12px">
          <div class="flex-between" style="margin-bottom:8px">
            <div>
              <strong>${esc(ce.name)}</strong>
              ${ce.bank_name ? `<span class="text-muted text-sm" style="margin-left:8px">${esc(ce.bank_name)}</span>` : ''}
            </div>
            <div style="display:flex;gap:6px">
              <button class="btn btn-sm btn-primary" onclick="generateConsolidated(${clientId},${ce.id})">⚙ Gerar</button>
              ${ce.output_path ? `<button class="btn btn-sm btn-success" onclick="downloadConsolidated(${clientId},${ce.id})">⬇ Download</button>` : ''}
              <button class="btn btn-sm btn-outline" style="color:var(--danger)" onclick="deleteConsolidated(${clientId},${ce.id})">🗑</button>
            </div>
          </div>
          <div class="text-sm text-muted" style="margin-bottom:8px">
            ${stmts.length} extrato(s) incluído(s)${periods ? ': ' + periods : ''}
          </div>
          ${stmts.length ? `
            <div style="display:flex;flex-wrap:wrap;gap:6px">
              ${stmts.map(s => `
                <span style="background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:3px 8px;font-size:12px;display:flex;align-items:center;gap:6px">
                  ${esc(s.filename)}
                  <span onclick="removeFromConsolidated(${clientId},${ce.id},${s.id})" style="cursor:pointer;color:var(--text-muted);font-size:14px" title="Remover">×</span>
                </span>
              `).join('')}
            </div>
          ` : ''}
        </div>
      `;
    }).join('');
  } catch(e) {
    el.innerHTML = `<p class="text-sm" style="color:var(--danger)">${e.message}</p>`;
  }
}

function createConsolidatedModal(clientId) {
  const name = prompt('Nome do extrato consolidado (ex: Novo Banco 2025):');
  if (!name || !name.trim()) return;
  const bank = prompt('Banco (opcional, pode deixar em branco):') || '';
  fetch(`/api/clients/${clientId}/consolidated`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name.trim(), bank_name: bank.trim() || null }),
  }).then(r => r.json()).then(() => {
    toast('Extrato consolidado criado', 'success');
    loadConsolidated(clientId);
  }).catch(e => toast(e.message, 'error'));
}

async function addToConsolidatedModal(clientId, stmtId) {
  // Fetch existing consolidated extracts to let user pick one
  const r = await fetch(`/api/clients/${clientId}/consolidated`);
  const d = await r.json();
  const items = d.data || [];
  if (!items.length) {
    const create = confirm('Ainda não tem extratos consolidados. Criar um agora?');
    if (create) createConsolidatedModal(clientId);
    return;
  }
  const options = items.map((ce, i) => `${i + 1}. ${ce.name}`).join('\n');
  const pick = prompt(`Escolha o extrato consolidado (introduza o número):\n${options}`);
  if (!pick) return;
  const idx = parseInt(pick) - 1;
  if (isNaN(idx) || idx < 0 || idx >= items.length) { toast('Opção inválida', 'error'); return; }
  const ce = items[idx];
  fetch(`/api/clients/${clientId}/consolidated/${ce.id}/statements`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ statement_id: stmtId }),
  }).then(() => {
    toast(`Adicionado a "${ce.name}"`, 'success');
    loadConsolidated(clientId);
  }).catch(e => toast(e.message, 'error'));
}

async function removeFromConsolidated(clientId, consId, stmtId) {
  await fetch(`/api/clients/${clientId}/consolidated/${consId}/statements/${stmtId}`, { method: 'DELETE' });
  toast('Extrato removido', 'success');
  loadConsolidated(clientId);
}

async function generateConsolidated(clientId, consId) {
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = '⏳ A gerar…';
  try {
    const r = await fetch(`/api/clients/${clientId}/consolidated/${consId}/generate`, { method: 'POST' });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Erro ao gerar');
    toast(`Excel gerado — ${d.movements} movimentos`, 'success');
    loadConsolidated(clientId);
  } catch(e) {
    toast(e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '⚙ Gerar';
  }
}

function downloadConsolidated(clientId, consId) {
  window.open(`/api/clients/${clientId}/consolidated/${consId}/download`, '_blank');
}

async function deleteConsolidated(clientId, consId) {
  if (!confirm('Apagar este extrato consolidado?')) return;
  await fetch(`/api/clients/${clientId}/consolidated/${consId}`, { method: 'DELETE' });
  toast('Extrato consolidado apagado', 'success');
  loadConsolidated(clientId);
}

// ── Download ────────────────────────────────────────────────────────────
function downloadConverted(clientId, stmtId) {
  window.open(`/api/clients/${clientId}/statements/${stmtId}/download`, '_blank');
}

// ── Settings ────────────────────────────────────────────────────────────
function renderSettings(el) {
  el.innerHTML = `
    <div class="card">
      <div class="card-title">🔐 Credenciais TOConline</div>
      <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:6px;padding:12px 16px;margin-bottom:16px;font-size:13px;line-height:1.7">
        <strong>Como obter as credenciais:</strong><br>
        1. Aceda ao TOConline → <strong>Empresa → Configurações → Dados API</strong><br>
        2. Introduza nome e email do integrador → será enviado um e-mail com link de 72h<br>
        3. O link dá acesso ao <strong>Client ID</strong>, <strong>Client Secret</strong> e <strong>OAUTH_URL</strong> únicos desta empresa<br>
        4. Copie esses valores para os campos abaixo
      </div>
      <div class="form-group">
        <label>OAUTH URL <span style="color:var(--danger)">*</span></label>
        <input type="text" id="s-oauth-url" placeholder="URL único fornecido pelo TOConline (ex: https://xxxxx.toconline.pt)">
      </div>
      <div class="form-group">
        <label>Client ID <span style="color:var(--danger)">*</span></label>
        <input type="text" id="s-client-id" placeholder="OAUTH_CLIENT_ID">
      </div>
      <div class="form-group">
        <label>Client Secret <span style="color:var(--danger)">*</span></label>
        <input type="text" id="s-client-secret" placeholder="OAUTH_CLIENT_SECRET">
      </div>
      <div class="form-group">
        <label>API URL</label>
        <input type="text" id="s-api-url" value="https://apiv1.toconline.com">
      </div>
      <div style="margin-top:4px;margin-bottom:16px">
        <strong>Redirect URI a registar no TOConline:</strong><br>
        <code style="font-size:12px;background:#f1f5f9;padding:4px 8px;border-radius:4px;display:inline-block;margin-top:4px">${window.location.origin}/api/auth/toconline/callback</code>
      </div>
      <button class="btn btn-primary" onclick="saveSettingsCredentials()">💾 Guardar Credenciais</button>
      <button class="btn btn-accent" style="margin-left:8px" onclick="startAuthFromSettings()">🔐 Autenticar com TOConline</button>
    </div>
    <div class="card">
      <div class="card-title">🏥 Estado do Sistema</div>
      <div id="health-info" class="loading">A verificar…</div>
    </div>
  `;

  // Pre-fill saved values
  if (authStatus.oauth_url) document.getElementById('s-oauth-url').value = authStatus.oauth_url;
  if (authStatus.client_id) document.getElementById('s-client-id').value = authStatus.client_id;

  fetch('/api/health').then(r => r.json()).then(d => {
    document.getElementById('health-info').innerHTML = `
      <table>
        <tr><td><strong>Versão</strong></td><td>${d.version}</td></tr>
        <tr><td><strong>TOConline</strong></td><td>${d.toconline_authenticated ? '<span class="badge badge-success">Autenticado</span>' : '<span class="badge badge-danger">Não autenticado</span>'}</td></tr>
        <tr><td><strong>Base de dados</strong></td><td><code>${esc(d.db)}</code></td></tr>
      </table>
    `;
  });
}

async function saveSettingsCredentials() {
  const oauth_url = document.getElementById('s-oauth-url').value.trim();
  const client_id = document.getElementById('s-client-id').value.trim();
  const client_secret = document.getElementById('s-client-secret').value.trim();
  const api_url = document.getElementById('s-api-url').value.trim();
  if (!oauth_url || !client_id || !client_secret) { toast('Preencha todos os campos obrigatórios', 'error'); return; }
  try {
    const r = await fetch('/api/auth/toconline/configure', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ oauth_url, client_id, client_secret, api_url }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    authStatus.credentials_configured = true;
    authStatus.oauth_url = oauth_url;
    authStatus.client_id = client_id;
    toast('Credenciais guardadas com sucesso', 'success');
  } catch (e) { toast(e.message, 'error'); }
}

async function startAuthFromSettings() {
  const r = await fetch('/api/auth/toconline/start');
  const d = await r.json();
  if (d.error) { toast(d.error, 'error'); return; }
  if (d.auth_url) {
    window.open(d.auth_url, '_blank');
    toast('Janela de autorização aberta. Após autorizar, volte aqui.', 'info');
  }
}

// ── Add Client Modal (simple inline) ─────────────────────────────────────
function showAddClientModal() {
  const name = prompt('Nome do cliente:');
  if (!name) return;
  const nif = prompt('NIF (opcional):');
  fetch('/api/clients', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, nif }),
  }).then(r => r.json()).then(async d => {
    await loadClients();
    toast(`Cliente "${name}" criado (ID ${d.id})`, 'success');
    navigate('clients');
  });
}

// ── Helpers ─────────────────────────────────────────────────────────────
function esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmt(n) {
  if (n == null) return '';
  return Number(n).toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function statusBadge(s) {
  const map = {
    pending: ['badge-gray', 'Pendente'],
    processing: ['badge-info', 'A processar'],
    processed: ['badge-success', 'Processado'],
    error: ['badge-danger', 'Erro'],
  };
  const [cls, label] = map[s] || ['badge-gray', s];
  return `<span class="badge ${cls}">${label}</span>`;
}

function reconBadge(s) {
  const map = {
    matched: ['badge-success', '✓ Reconciliado'],
    review: ['badge-purple', '⚠ Rever'],
    unmatched: ['badge-danger', '✗ Pendente'],
  };
  const [cls, label] = map[s] || ['badge-gray', s || '—'];
  return `<span class="badge ${cls}">${label}</span>`;
}

function toast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}
