"use strict";

/* ── Config ───────────────────────────────────────────────────────────────────
 * Point this at your admin API Gateway base URL (no trailing slash), e.g.
 *   https://abc123.execute-api.us-east-1.amazonaws.com
 * You can also override it at runtime in the browser console with:
 *   localStorage.setItem('apiBase', 'https://...')
 */
const API_BASE = localStorage.getItem('apiBase') || 'REPLACE_WITH_ADMIN_API_BASE_URL';

const SIMPLE_FIELDS = [
  { key: 'name', label: 'Name', type: 'text',
    warn: 'The displayed name. When Subdomain is empty, the name also drives the ' +
          'URL — so changing it then moves the client to a new URL on the next publish.' },
  { key: 'subdomain', label: 'Subdomain (optional)', type: 'text',
    warn: 'Sets the URL (<value>.verifyanagent.com) independently of the displayed name. ' +
          'Leave blank to derive the URL from the name. Changing it moves the client to a ' +
          'new URL and a new storage folder on the next publish.' },
  { key: 'npn', label: 'NPN', type: 'text',
    warn: 'NPN feeds some states’ verify links. If it’s wrong, those buttons can point to the wrong record.' },
  { key: 'bio',          label: 'Bio',         type: 'textarea' },
  { key: 'agency_name',  label: 'Agency name', type: 'text' },
  { key: 'primary_color', label: 'Brand color', type: 'color' },
  { key: 'calendly_url', label: 'Calendly URL', type: 'text' },
];

const IMAGE_FIELDS = [
  { key: 'profile_pic',  label: 'Profile photo' },
  { key: 'logo_full',    label: 'Full logo' },
  { key: 'logo_icon',    label: 'Logo icon (optional)' },
  { key: 'carriers_img', label: 'Carriers image (optional)' },
];

// ── State ─────────────────────────────────────────────────────────────────────
let current = null;   // currently-open agent detail payload

// ── Token helpers ─────────────────────────────────────────────────────────────
const getToken = () => sessionStorage.getItem('adminToken');
const setToken = (t) => sessionStorage.setItem('adminToken', t);
const clearToken = () => sessionStorage.removeItem('adminToken');

// ── API wrapper ───────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const res = await fetch(API_BASE + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401) { logout(); throw new Error('Session expired — please sign in again.'); }
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(data.error || ('Request failed (' + res.status + ')'));
  return data;
}

// ── View switching ────────────────────────────────────────────────────────────
function showView(id) {
  document.querySelectorAll('.view').forEach((v) => (v.hidden = v.id !== id));
  const loggedIn = (id !== 'login-view' && id !== 'setup-view');
  document.getElementById('logout-btn').hidden = !loggedIn;
  document.getElementById('settings-btn').hidden = !loggedIn;
}

// ── Auth ──────────────────────────────────────────────────────────────────────
function logout() {
  clearToken();
  showView('login-view');
}

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = document.getElementById('login-error');
  err.hidden = true;
  try {
    const data = await api('POST', '/admin/login', {
      email: document.getElementById('email').value,
      password: document.getElementById('password').value,
    });
    setToken(data.token);
    document.getElementById('password').value = '';
    await loadAgents();
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  }
});

document.getElementById('logout-btn').addEventListener('click', logout);

// First-time password setup
document.getElementById('setup-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = document.getElementById('setup-error');
  err.hidden = true;
  const p1 = document.getElementById('setup-password').value;
  const p2 = document.getElementById('setup-password2').value;
  if (p1.length < 8) { err.textContent = 'Password must be at least 8 characters.'; err.hidden = false; return; }
  if (p1 !== p2) { err.textContent = 'Passwords do not match.'; err.hidden = false; return; }
  try {
    const data = await api('POST', '/admin/set-initial-password', {
      email: document.getElementById('setup-email').textContent,
      password: p1,
    });
    setToken(data.token);
    await loadAgents();
  } catch (ex) { err.textContent = ex.message; err.hidden = false; }
});

// Settings + change password
document.getElementById('settings-btn').addEventListener('click', () => showView('settings-view'));
document.getElementById('settings-back').addEventListener('click', () => {
  if (current) showView('detail-view'); else loadAgents();
});

document.getElementById('password-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const msg = document.getElementById('password-msg');
  msg.hidden = true;
  msg.className = 'error';
  const n1 = document.getElementById('new-password').value;
  const n2 = document.getElementById('new-password2').value;
  if (n1.length < 8) { msg.textContent = 'New password must be at least 8 characters.'; msg.hidden = false; return; }
  if (n1 !== n2) { msg.textContent = 'New passwords do not match.'; msg.hidden = false; return; }
  try {
    await api('POST', '/admin/change-password', {
      currentPassword: document.getElementById('cur-password').value,
      newPassword: n1,
    });
    msg.className = 'saved-flash';
    msg.textContent = 'Password updated.';
    msg.hidden = false;
    document.getElementById('password-form').reset();
  } catch (ex) { msg.textContent = ex.message; msg.hidden = false; }
});

// ── Agent list ────────────────────────────────────────────────────────────────
let allAgents = [];

async function loadAgents() {
  const data = await api('GET', '/admin/agents');
  allAgents = data.agents;
  renderAgents();
  showView('list-view');
}

function renderAgents() {
  const term = document.getElementById('agent-filter').value.toLowerCase();
  const rows = document.getElementById('agent-rows');
  rows.innerHTML = '';
  allAgents
    .filter((a) => !term || a.name.toLowerCase().includes(term) || a.email.toLowerCase().includes(term))
    .forEach((a) => {
      const tr = document.createElement('tr');
      const status = a.site_status || '—';
      const dirty = sessionStorage.getItem('dirty:' + a.id) ? ' • unpublished' : '';
      tr.innerHTML =
        '<td>' + esc(a.name) + '</td>' +
        '<td>' + esc(a.email) + '</td>' +
        '<td><span class="status-pill ' + esc(status) + '">' + esc(status) + '</span>' + dirty + '</td>' +
        '<td><button class="link-btn">Edit</button></td>';
      tr.querySelector('button').addEventListener('click', () => openAgent(a.id));
      rows.appendChild(tr);
    });
}

document.getElementById('agent-filter').addEventListener('input', renderAgents);
document.getElementById('back-btn').addEventListener('click', () => { current = null; loadAgents(); });

// ── Agent detail ──────────────────────────────────────────────────────────────
async function openAgent(id) {
  current = await api('GET', '/admin/agents/' + id);
  renderDetail();
  showView('detail-view');
}

function markDirty() {
  if (current) sessionStorage.setItem('dirty:' + current.id, '1');
  document.getElementById('unpublished-banner').hidden = false;
}

function renderHeader() {
  const r = current.read;
  const name = current.editable.name || r.name;
  document.getElementById('detail-header').innerHTML =
    '<h1>' + esc(name || '(no name)') + '</h1>' +
    '<p class="sub">' + esc(r.email || '') +
    (r.site_url ? ' · <a href="' + esc(r.site_url) + '" target="_blank" rel="noopener">' + esc(r.site_url) + '</a>' : '') +
    ' · status: ' + esc(r.site_status || '—') + '</p>';
}

function renderDetail() {
  renderHeader();
  document.getElementById('unpublished-banner').hidden = !sessionStorage.getItem('dirty:' + current.id);

  renderFields();
  renderLicensing();
  renderImages();
  document.getElementById('publish-status').textContent = '';
  document.getElementById('publish-status').className = '';
}

// Simple per-field rows with inline edit + save
function renderFields() {
  const wrap = document.getElementById('fields');
  wrap.innerHTML = '';
  SIMPLE_FIELDS.forEach((f) => {
    const value = current.editable[f.key] || '';
    const row = document.createElement('div');
    row.className = 'field-row';
    row.innerHTML =
      '<div class="field-head"><span class="field-name">' + esc(f.label) + '</span>' +
      '<button class="link-btn edit-toggle">Edit</button></div>' +
      '<div class="field-value">' + (value ? esc(value) : '<em>(empty)</em>') + '</div>' +
      '<div class="editor"></div>';

    const editor = row.querySelector('.editor');
    editor.appendChild(buildInput(f, value));
    if (f.warn) {
      const w = document.createElement('p');
      w.className = 'warn';
      w.textContent = '⚠ ' + f.warn;
      editor.appendChild(w);
    }
    const actions = document.createElement('div');
    actions.className = 'editor-actions';
    actions.innerHTML = '<button class="primary save-one">Save</button><button class="secondary cancel-one">Cancel</button>';
    editor.appendChild(actions);

    row.querySelector('.edit-toggle').addEventListener('click', () => row.classList.toggle('editing'));
    actions.querySelector('.cancel-one').addEventListener('click', () => { row.classList.remove('editing'); renderFields(); });
    actions.querySelector('.save-one').addEventListener('click', async () => {
      const input = editor.querySelector('[data-field]');
      const newVal = input.value;
      try {
        await api('PATCH', '/admin/agents/' + current.id, { [f.key]: newVal });
        current.editable[f.key] = newVal;
        markDirty();
        renderFields();
        if (f.key === 'name') renderHeader();   // title reflects the new (unpublished) name
      } catch (ex) { alert('Save failed: ' + ex.message); }
    });
    wrap.appendChild(row);
  });
}

function buildInput(f, value) {
  let el;
  if (f.type === 'textarea') {
    el = document.createElement('textarea');
    el.value = value;
  } else if (f.type === 'color') {
    el = document.createElement('input');
    el.type = 'text';
    el.placeholder = '#1a3a5c';
    el.value = value;
  } else {
    el = document.createElement('input');
    el.type = 'text';
    el.value = value;
  }
  el.setAttribute('data-field', f.key);
  return el;
}

// Licensing: states checklist + per-state license number & verify link
function renderLicensing() {
  const wrap = document.getElementById('licensing');
  wrap.innerHTML = '';

  const selected = new Set((current.editable.states || []).map((s) => s.toUpperCase()));
  const licenseNums = parseKV(current.editable.license_numbers_override);
  const verifyUrls = parseKV(current.editable.verify_url_override);

  // State membership checkboxes
  const picker = document.createElement('details');
  picker.innerHTML = '<summary>Licensed states (' + selected.size + ' selected)</summary>';
  const grid = document.createElement('div');
  grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:4px;margin:10px 0;';
  current.all_states.forEach((s) => {
    const id = 'st-' + s.abbrev;
    const lbl = document.createElement('label');
    lbl.style.cssText = 'flex-direction:row;align-items:center;gap:6px;color:#1d2939;';
    lbl.innerHTML = '<input type="checkbox" value="' + s.abbrev + '" ' + (selected.has(s.abbrev) ? 'checked' : '') +
      ' style="width:auto"> ' + esc(s.abbrev) + ' — ' + esc(s.name);
    lbl.querySelector('input').addEventListener('change', () => { captureLicensing(); renderLicensing(); });
    grid.appendChild(lbl);
  });
  picker.appendChild(grid);
  wrap.appendChild(picker);

  // Per-state rows for selected states
  const head = document.createElement('div');
  head.className = 'lic-grid';
  head.innerHTML = '<span class="head">State</span><span class="head">License #</span><span class="head">Custom verify link</span>';
  wrap.appendChild(head);

  Array.from(selected).sort().forEach((ab) => {
    const grid2 = document.createElement('div');
    grid2.className = 'lic-grid';
    grid2.innerHTML =
      '<span class="state-abbrev">' + esc(ab) + '</span>' +
      '<input type="text" data-lic="' + ab + '" value="' + esc(licenseNums[ab] || '') + '" placeholder="(none)">' +
      '<input type="url" data-url="' + ab + '" value="' + esc(verifyUrls[ab] || '') + '" placeholder="https://… (for FL-type states)">';
    wrap.appendChild(grid2);
  });
}

// Pull current licensing inputs back into `current.editable` (so a re-render keeps them)
function captureLicensing() {
  const checked = Array.from(document.querySelectorAll('#licensing input[type=checkbox]:checked')).map((c) => c.value);
  const nums = {}, urls = {};
  document.querySelectorAll('#licensing input[data-lic]').forEach((i) => { if (i.value.trim()) nums[i.dataset.lic] = i.value.trim(); });
  document.querySelectorAll('#licensing input[data-url]').forEach((i) => { if (i.value.trim()) urls[i.dataset.url] = i.value.trim(); });
  current.editable.states = checked;
  current.editable.license_numbers_override = serializeKV(nums);
  current.editable.verify_url_override = serializeKV(urls);
}

document.getElementById('save-licensing').addEventListener('click', async () => {
  captureLicensing();
  try {
    await api('PATCH', '/admin/agents/' + current.id, {
      states: current.editable.states,
      license_numbers_override: current.editable.license_numbers_override,
      verify_url_override: current.editable.verify_url_override,
    });
    markDirty();
    flash('save-licensing', 'Saved');
  } catch (ex) { alert('Save failed: ' + ex.message); }
});

// Images
function renderImages() {
  const wrap = document.getElementById('images');
  wrap.innerHTML = '';
  IMAGE_FIELDS.forEach((f) => {
    const url = current.images[f.key];
    const row = document.createElement('div');
    row.className = 'img-row';
    row.innerHTML =
      '<img class="thumb" alt="" src="' + (url || '') + '">' +
      '<div class="img-meta"><div class="img-name">' + esc(f.label) + '</div>' +
      '<div class="img-state">' + (url ? 'Uploaded' : 'Not set') + '</div></div>' +
      '<input type="file" accept="image/*">';
    const fileInput = row.querySelector('input[type=file]');
    fileInput.addEventListener('change', async () => {
      const file = fileInput.files[0];
      if (!file) return;
      const meta = row.querySelector('.img-state');
      meta.textContent = 'Uploading…';
      try {
        await uploadImage(f.key, file);
        row.querySelector('.thumb').src = URL.createObjectURL(file);
        meta.textContent = 'Uploaded (unpublished)';
        markDirty();
      } catch (ex) { meta.textContent = 'Upload failed'; alert('Upload failed: ' + ex.message); }
    });
    wrap.appendChild(row);
  });
}

async function uploadImage(field, file) {
  const ct = file.type || 'application/octet-stream';
  const pre = await api('POST', '/admin/agents/' + current.id + '/image-url', {
    field, filename: file.name, contentType: ct,
  });
  const put = await fetch(pre.uploadUrl, { method: 'PUT', headers: { 'Content-Type': pre.contentType }, body: file });
  if (!put.ok) throw new Error('S3 upload failed (' + put.status + ')');
  await api('POST', '/admin/agents/' + current.id + '/image', {
    field, key: pre.key, filename: file.name,
  });
}

// Publish
document.getElementById('publish-btn').addEventListener('click', async () => {
  const btn = document.getElementById('publish-btn');
  const status = document.getElementById('publish-status');
  btn.disabled = true;
  status.className = '';
  status.textContent = 'Publishing… (this can take up to a minute)';
  try {
    const res = await api('POST', '/admin/agents/' + current.id + '/publish', {});
    sessionStorage.removeItem('dirty:' + current.id);
    document.getElementById('unpublished-banner').hidden = true;
    status.className = res.ok ? 'ok' : 'err';
    status.textContent = (res.ok ? 'Published → ' + res.site_url : 'Build failed') +
      (res.warning_count ? ('  (' + res.warning_count + ' warning(s): ' + res.warnings.join(' | ') + ')') : '');
  } catch (ex) {
    status.className = 'err';
    status.textContent = 'Publish failed: ' + ex.message;
  } finally {
    btn.disabled = false;
  }
});

// ── Small helpers ─────────────────────────────────────────────────────────────
function parseKV(text) {
  const out = {};
  (text || '').split('\n').forEach((line) => {
    const i = line.indexOf(':');
    if (i === -1) return;
    const k = line.slice(0, i).trim().toUpperCase();
    const v = line.slice(i + 1).trim();
    if (k && v) out[k] = v;
  });
  return out;
}

function serializeKV(obj) {
  return Object.keys(obj).sort().map((k) => k + ': ' + obj[k]).join('\n');
}

function flash(btnId, msg) {
  const btn = document.getElementById(btnId);
  const span = document.createElement('span');
  span.className = 'saved-flash';
  span.textContent = '  ' + msg;
  btn.after(span);
  setTimeout(() => span.remove(), 1800);
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Boot ──────────────────────────────────────────────────────────────────────
async function boot() {
  if (getToken()) {
    try { await loadAgents(); return; } catch (e) { /* token expired — fall through */ }
  }
  try {
    const st = await api('GET', '/admin/status');
    if (st.email) {
      document.getElementById('email').value = st.email;
      document.getElementById('setup-email').textContent = st.email;
      document.getElementById('settings-email').textContent = st.email;
    }
    showView(st.initialized ? 'login-view' : 'setup-view');
  } catch (e) {
    showView('login-view');
  }
}
boot();
