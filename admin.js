const HEADERS = { 'X-Requested-With': 'boaba-admin' };
let data = null;
let saved = '';

const $ = (selector) => document.querySelector(selector);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value == null) continue;
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'value') node.value = value;
    else if (key === 'checked') node.checked = value;
    else node.setAttribute(key, value === true ? '' : value);
  }
  node.append(...children.filter((child) => child != null && child !== ''));
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...HEADERS, ...options.headers }, credentials: 'same-origin' });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw Object.assign(new Error(body?.error || `Eroare ${response.status}`), { status: response.status });
  return body;
}

const uid = (prefix) => `${prefix}-${Math.random().toString(36).slice(2, 10)}`;

// ---------- dirty state ----------
function setBar(state, text) {
  $('#savebar').dataset.state = state;
  $('#save-status').textContent = text;
}
function markDirty() {
  const dirty = JSON.stringify(data) !== saved;
  setBar(dirty ? 'dirty' : 'clean', dirty ? 'Ai modificări nesalvate.' : 'Totul este salvat.');
}
window.addEventListener('beforeunload', (event) => {
  if (data && JSON.stringify(data) !== saved) event.preventDefault();
});

// ---------- shared field builders ----------
function text(item, key, label, attrs = {}) {
  const tag = attrs.multiline ? 'textarea' : 'input';
  delete attrs.multiline;
  return el('label', { class: attrs.class }, label, el(tag, {
    ...attrs, class: null, value: item[key] ?? '', rows: tag === 'textarea' ? 1 : null,
    oninput: (event) => { item[key] = event.target.value; markDirty(); },
  }));
}
function toggle(item, key, label) {
  return el('label', { class: 'toggle' }, el('input', {
    type: 'checkbox', checked: Boolean(item[key]),
    onchange: (event) => { item[key] = event.target.checked; markDirty(); },
  }), label);
}
function tools(list, index, render) {
  const move = (delta) => {
    const [item] = list.splice(index, 1);
    list.splice(index + delta, 0, item);
    render(); markDirty();
  };
  return el('div', { class: 'row-tools' },
    el('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Mută mai sus', disabled: index === 0, onclick: () => move(-1) }, '↑'),
    el('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Mută mai jos', disabled: index === list.length - 1, onclick: () => move(1) }, '↓'),
    el('button', { type: 'button', class: 'icon-btn danger', 'aria-label': 'Șterge', onclick: () => {
      if (!confirm('Ștergi acest element?')) return;
      list.splice(index, 1); render(); markDirty();
    } }, '×'));
}

// ---------- panels ----------
function renderProducts() {
  const list = data.products;
  $('#categories').replaceChildren(...[...new Set(list.map((p) => p.category).filter(Boolean))].map((c) => el('option', { value: c })));
  if (!list.length) return $('#products').replaceChildren(el('p', { class: 'empty' }, 'Niciun produs încă. Adaugă primul produs.'));
  let lastCategory = null;
  const nodes = [];
  list.forEach((product, index) => {
    if (product.category !== lastCategory) {
      lastCategory = product.category;
      nodes.push(el('p', { class: 'category-head' }, product.category || 'Fără categorie'));
    }
    const price = el('label', { class: 'price-field' }, 'Preț', el('input', {
      type: 'number', min: '0', step: '0.5', inputmode: 'decimal', value: product.price ?? '', placeholder: '—',
      oninput: (event) => { product.price = event.target.value === '' ? null : Number(event.target.value); markDirty(); },
    }), el('span', {}, 'lei'));
    const category = el('label', {}, 'Categorie', el('input', {
      list: 'categories', value: product.category, required: true,
      oninput: (event) => { product.category = event.target.value; markDirty(); },
      onchange: () => renderProducts(),
    }));
    nodes.push(el('div', { class: 'card row' },
      category,
      text(product, 'name', 'Nume', { required: true, maxlength: 80 }),
      price,
      tools(list, index, renderProducts),
      text(product, 'description', 'Descriere', { class: 'desc', multiline: true, maxlength: 240 }),
      el('div', { class: 'toggles' }, toggle(product, 'available', 'Disponibil'), toggle(product, 'featured', 'Recomandat'))));
  });
  $('#products').replaceChildren(...nodes);
}

function renderOffers() {
  const list = data.offers;
  if (!list.length) return $('#offers').replaceChildren(el('p', { class: 'empty' }, 'Nicio ofertă. Secțiunea „Oferte” rămâne ascunsă pe site până adaugi una activă.'));
  $('#offers').replaceChildren(...list.map((offer, index) => el('div', { class: 'card row offer-row' },
    text(offer, 'title', 'Titlu', { required: true, maxlength: 80, placeholder: 'ex: Espresso + croissant' }),
    text(offer, 'price', 'Preț / reducere', { maxlength: 40, placeholder: 'ex: 18 lei sau −20%' }),
    text(offer, 'validUntil', 'Valabil până la', { type: 'date' }),
    tools(list, index, renderOffers),
    text(offer, 'description', 'Descriere', { class: 'desc', multiline: true, maxlength: 240 }),
    el('div', { class: 'toggles' }, toggle(offer, 'active', 'Activă')))));
}

function renderGallery() {
  const list = data.gallery;
  if (!list.length) return $('#gallery').replaceChildren(el('p', { class: 'empty' }, 'Nicio fotografie. Încarcă primele imagini.'));
  $('#gallery').replaceChildren(...list.map((photo, index) => el('div', { class: 'card photo' },
    el('img', { src: `/${photo.src}`, alt: '' }),
    el('div', { class: 'photo-body' },
      text(photo, 'caption', 'Titlu scurt', { maxlength: 80 }),
      text(photo, 'alt', 'Descriere pentru accesibilitate', { maxlength: 200, placeholder: 'Ce se vede în imagine' }),
      el('div', { class: 'toggles' }, toggle(photo, 'concept', 'Ilustrativă (nu e din local)')),
      tools(list, index, renderGallery)))));
}

function renderSettings() {
  document.querySelectorAll('[data-setting]').forEach((input) => {
    input.value = data.settings[input.dataset.setting] ?? '';
    input.oninput = () => { data.settings[input.dataset.setting] = input.value; markDirty(); };
  });
}

function renderAll() {
  renderProducts(); renderOffers(); renderGallery(); renderSettings(); markDirty();
}

// ---------- actions ----------
document.querySelectorAll('[data-add]').forEach((button) => button.addEventListener('click', () => {
  if (button.dataset.add === 'products') {
    const lastCategory = data.products.at(-1)?.category || 'Cafea';
    data.products.push({ id: uid('p'), category: lastCategory, name: '', description: '', price: null, available: true, featured: false });
    renderProducts();
    [...document.querySelectorAll('#products .row')].at(-1)?.querySelectorAll('input')[1]?.focus();
  } else {
    data.offers.push({ id: uid('o'), title: '', description: '', price: '', validUntil: '', active: true });
    renderOffers();
    [...document.querySelectorAll('#offers .row')].at(-1)?.querySelector('input')?.focus();
  }
  markDirty();
}));

$('#upload').addEventListener('change', async (event) => {
  const files = [...event.target.files];
  event.target.value = '';
  for (const [i, file] of files.entries()) {
    setBar('dirty', `Se încarcă ${i + 1} din ${files.length}…`);
    try {
      const { src } = await api('/api/upload', { method: 'POST', headers: { 'Content-Type': file.type }, body: file });
      data.gallery.push({ id: uid('g'), src, alt: '', caption: '', concept: false });
      renderGallery();
    } catch (error) {
      setBar('error', `${file.name}: ${error.message}`);
      return;
    }
  }
  markDirty();
});

async function save() {
  const missing = data.products.find((p) => !p.name.trim()) || data.offers.find((o) => !o.title.trim());
  if (missing) return setBar('error', 'Completează numele fiecărui produs și titlul fiecărei oferte.');
  $('#save').disabled = true;
  try {
    data = await api('/api/site', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    saved = JSON.stringify(data);
    renderAll();
    setBar('saved', 'Salvat. Site-ul este actualizat.');
    setTimeout(() => { if (JSON.stringify(data) === saved) setBar('clean', 'Totul este salvat.'); }, 2200);
  } catch (error) {
    if (error.status === 401) return showLogin('Sesiunea a expirat. Intră din nou; modificările rămân în pagină.');
    setBar('error', error.message);
  } finally {
    $('#save').disabled = false;
  }
}
$('#save').addEventListener('click', save);
document.addEventListener('keydown', (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === 's' && data) { event.preventDefault(); save(); }
});
$('#revert').addEventListener('click', () => {
  if (!confirm('Renunți la modificările nesalvate?')) return;
  data = JSON.parse(saved); renderAll();
});

document.querySelectorAll('[data-tab]').forEach((tab) => tab.addEventListener('click', () => {
  document.querySelectorAll('[data-tab]').forEach((t) => t.setAttribute('aria-selected', String(t === tab)));
  document.querySelectorAll('[data-panel]').forEach((panel) => { panel.hidden = panel.dataset.panel !== tab.dataset.tab; });
}));

// ---------- auth ----------
function showLogin(message = '') {
  $('#login').hidden = false;
  $('#login-error').textContent = message;
  $('#password').focus();
}

$('#login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await api('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: $('#password').value }) });
    $('#password').value = '';
    $('#login').hidden = true;
    if (!data) await start();
  } catch (error) {
    $('#login-error').textContent = error.message;
  }
});

$('#logout').addEventListener('click', async () => {
  await api('/api/logout', { method: 'POST' }).catch(() => {});
  location.reload();
});

async function start() {
  data = await api('/api/site');
  saved = JSON.stringify(data);
  $('#app').hidden = false;
  renderAll();
}

api('/api/me')
  .then(({ admin }) => (admin ? start() : showLogin()))
  .catch(() => showLogin('Serverul nu răspunde. Pornește-l cu: python3 server.py'));
