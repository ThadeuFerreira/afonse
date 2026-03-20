/* =========================================================
   Music Teacher AI – app.js
   Native browser APIs only. No frameworks. < 10 KB
   ========================================================= */

// ── Helpers ──────────────────────────────────────────────────────────────────

function qs(sel, ctx) { return (ctx || document).querySelector(sel); }
function el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([k, v]) => {
    if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  });
  children.forEach(c => c && e.append(typeof c === 'string' ? c : c));
  return e;
}
function spinner() { return el('div', { class: 'spinner' }); }
function alert(msg, type) {
  return el('div', { class: `alert alert-${type || 'info'}`, html: msg });
}
function clearEl(node) { while (node.firstChild) node.removeChild(node.firstChild); }

// ── LocalStorage helpers ──────────────────────────────────────────────────────

const RECENT_KEY = 'mtai_recent';
function getRecent() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); }
  catch { return []; }
}
function addRecent(q) {
  if (!q.trim()) return;
  const list = [q, ...getRecent().filter(x => x !== q)].slice(0, 8);
  localStorage.setItem(RECENT_KEY, JSON.stringify(list));
}

// ── Playlist cart (sessionStorage) ───────────────────────────────────────────

const CART_KEY = 'mtai_cart';
function getCart() {
  try { return JSON.parse(sessionStorage.getItem(CART_KEY) || '[]'); }
  catch { return []; }
}
function addToCart(song) {
  const cart = getCart();
  if (!cart.find(s => s.song_id === song.song_id)) cart.push(song);
  sessionStorage.setItem(CART_KEY, JSON.stringify(cart));
}
function removeFromCart(song_id) {
  sessionStorage.setItem(CART_KEY, JSON.stringify(getCart().filter(s => s.song_id !== song_id)));
}
function cartCount() { return getCart().length; }

// ── API calls ─────────────────────────────────────────────────────────────────

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Song result card ──────────────────────────────────────────────────────────

function songCard(song) {
  const id   = song.song_id || song.id;
  const year = song.year || song.release_year || '';
  const div  = el('li', { class: 'result-item' });

  div.append(
    el('div', { class: 'title' }, song.title),
    el('div', { class: 'meta' }, `${song.artist_name || song.artist || ''} ${year ? '· ' + year : ''}`),
  );

  const actions = el('div', { class: 'actions' });

  if (id) {
    actions.append(
      el('a', { class: 'btn btn-secondary btn-sm', href: `lyrics.html?id=${id}` }, 'Lyrics'),
      el('a', { class: 'btn btn-secondary btn-sm', href: `exercise.html?id=${id}` }, 'Exercise'),
    );
    const addBtn = el('button', { class: 'btn btn-primary btn-sm', onclick: () => {
      addToCart({ song_id: id, title: song.title, artist: song.artist_name || song.artist || '', year });
      addBtn.textContent = 'Added ✓';
      addBtn.disabled = true;
    }}, '+ Playlist');
    if (getCart().find(s => s.song_id === id)) { addBtn.textContent = 'Added ✓'; addBtn.disabled = true; }
    actions.append(addBtn);
  }

  div.append(actions);
  return div;
}

// ── HOME PAGE ─────────────────────────────────────────────────────────────────

function initHome() {
  const form    = qs('#home-form');
  const input   = qs('#home-q');
  const chips   = qs('#recent-chips');

  function renderChips() {
    clearEl(chips);
    getRecent().forEach(q => {
      chips.append(el('button', { class: 'chip', onclick: () => {
        window.location.href = `search.html?q=${encodeURIComponent(q)}`;
      }}, q));
    });
  }
  renderChips();

  form && form.addEventListener('submit', e => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) return;
    addRecent(q);
    window.location.href = `search.html?q=${encodeURIComponent(q)}`;
  });

  const cnt = qs('#cart-count');
  if (cnt) cnt.textContent = cartCount() || '';
}

// ── SEARCH PAGE ───────────────────────────────────────────────────────────────

function initSearch() {
  const params  = new URLSearchParams(location.search);
  const input   = qs('#search-q');
  const results = qs('#search-results');
  const form    = qs('#search-form');

  if (input && params.get('q')) input.value = params.get('q');

  async function doSearch(q) {
    clearEl(results);
    results.append(spinner());
    addRecent(q);
    try {
      const semantic = qs('#mode-semantic') && qs('#mode-semantic').checked;
      let data;
      if (semantic) {
        data = await api('/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: q, top_k: 20 }),
        });
        data = { results: data.results || data };
      } else {
        data = await api(`/search?word=${encodeURIComponent(q)}&limit=30`);
      }
      clearEl(results);
      const items = data.results || data;
      if (!items.length) {
        results.append(alert('No songs found.', 'info'));
        return;
      }
      const ul = el('ul', { class: 'result-list' });
      items.forEach(s => ul.append(songCard(s)));
      results.append(ul);
    } catch (err) {
      clearEl(results);
      results.append(alert(err.message, 'error'));
    }
  }

  form && form.addEventListener('submit', e => {
    e.preventDefault();
    const q = input.value.trim();
    if (q) doSearch(q);
  });

  if (params.get('q')) doSearch(params.get('q'));
}

// ── LYRICS PAGE ───────────────────────────────────────────────────────────────

async function initLyrics() {
  const params = new URLSearchParams(location.search);
  const id     = params.get('id');
  const title  = qs('#song-title');
  const block  = qs('#lyrics-block');
  const exLink = qs('#exercise-link');

  if (!id) { block && (block.textContent = 'No song selected.'); return; }

  try {
    const [song, lyr] = await Promise.all([
      api(`/songs/${id}`),
      api(`/lyrics/${id}`),
    ]);
    if (title) title.textContent = `${song.title} – ${song.artist_name || ''}`;
    if (block) block.textContent = lyr.lyrics_text || '(no lyrics)';
    if (exLink) exLink.href = `exercise.html?id=${id}`;

    const addBtn = qs('#add-playlist');
    if (addBtn) {
      addBtn.addEventListener('click', () => {
        addToCart({ song_id: +id, title: song.title, artist: song.artist_name || '', year: song.release_year });
        addBtn.textContent = 'Added ✓';
        addBtn.disabled = true;
      });
      if (getCart().find(s => s.song_id === +id)) { addBtn.textContent = 'Added ✓'; addBtn.disabled = true; }
    }
  } catch (err) {
    if (block) block.textContent = err.message;
  }
}

// ── PLAYLIST PAGE ─────────────────────────────────────────────────────────────

function initPlaylist() {
  const list    = qs('#pl-list');
  const nameIn  = qs('#pl-name');
  const saveBtn = qs('#pl-save');
  const expBtn  = qs('#pl-export');

  function render() {
    clearEl(list);
    const cart = getCart();
    if (!cart.length) {
      list.append(el('p', { class: 'empty' }, 'No songs added yet. Search for songs to add them.'));
      return;
    }
    cart.forEach(s => {
      const item = el('div', { class: 'pl-item' });
      item.append(
        el('div', { class: 'info', html: `<strong>${s.title}</strong><br><small>${s.artist} ${s.year ? '· ' + s.year : ''}</small>` }),
        el('button', { class: 'pl-remove', onclick: () => { removeFromCart(s.song_id); render(); } }, '✕'),
      );
      list.append(item);
    });
  }
  render();

  saveBtn && saveBtn.addEventListener('click', async () => {
    const name = nameIn && nameIn.value.trim();
    if (!name) { nameIn && nameIn.focus(); return; }
    const cart  = getCart();
    const songs = cart.map(s => ({ song_id: s.song_id, title: s.title, artist: s.artist, year: s.year }));
    try {
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving…';
      const pl = await api('/playlists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, query: {} }),
      });
      const msg = qs('#pl-msg');
      if (msg) { clearEl(msg); msg.append(alert(`Playlist "${pl.name}" saved!`, 'success')); }
    } catch (err) {
      const msg = qs('#pl-msg');
      if (msg) { clearEl(msg); msg.append(alert(err.message, 'error')); }
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save playlist';
    }
  });

  expBtn && expBtn.addEventListener('click', async () => {
    const cart = getCart();
    if (!cart.length) return;
    const lines = ['#EXTM3U', ...cart.flatMap(s => [
      `#EXTINF:-1,${s.artist} - ${s.title}`,
      `${s.artist} - ${s.title}`,
    ])];
    const blob = new Blob([lines.join('\n')], { type: 'audio/x-mpegurl' });
    const url  = URL.createObjectURL(blob);
    const a    = el('a', { href: url, download: 'playlist.m3u' });
    document.body.append(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  });
}

// ── EXERCISE PAGE ─────────────────────────────────────────────────────────────

async function initExercise() {
  const params   = new URLSearchParams(location.search);
  const id       = params.get('id');
  const songInfo = qs('#ex-song-info');
  const output   = qs('#ex-output');
  const genBtn   = qs('#ex-generate');
  const dlBtn    = qs('#ex-download');
  const pills    = document.querySelectorAll('.pill');

  let level = 20;
  pills.forEach(p => {
    p.addEventListener('click', () => {
      pills.forEach(x => x.classList.remove('active'));
      p.classList.add('active');
      level = +p.dataset.level;
    });
  });
  pills[0] && pills[0].classList.add('active');

  if (id) {
    try {
      const song = await api(`/songs/${id}`);
      if (songInfo) songInfo.textContent = `${song.title} – ${song.artist_name || ''}`;
    } catch { /* ignore */ }
  }

  genBtn && genBtn.addEventListener('click', async () => {
    const sid = id || (qs('#ex-song-id') && qs('#ex-song-id').value.trim());
    if (!sid) { output && (output.textContent = 'Enter a song ID.'); return; }

    clearEl(output);
    output && output.append(spinner());
    genBtn.disabled = true;

    try {
      const data = await api('/exercise/gap', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ song_id: +sid, mode: 'random', level }),
      });
      clearEl(output);
      // Also fetch the actual exercise text from education endpoint
      const ex = await api(`/education/exercise/${sid}?num_blanks=${Math.round(level / 5)}`);
      output && (output.textContent = ex.text_with_blanks || data.file);

      if (dlBtn) {
        dlBtn.style.display = 'block';
        dlBtn.onclick = () => {
          const blob = new Blob([ex.text_with_blanks || ''], { type: 'text/plain' });
          const url  = URL.createObjectURL(blob);
          const a    = el('a', { href: url, download: `exercise-${sid}.txt` });
          document.body.append(a); a.click(); a.remove();
          URL.revokeObjectURL(url);
        };
      }
    } catch (err) {
      clearEl(output);
      output && output.append(alert(err.message, 'error'));
    } finally {
      genBtn.disabled = false;
    }
  });
}

// ── Router ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  const page = location.pathname.split('/').pop().replace('.html', '') || 'index';
  const map  = {
    index:    initHome,
    '':       initHome,
    search:   initSearch,
    lyrics:   initLyrics,
    playlist: initPlaylist,
    exercise: initExercise,
  };
  (map[page] || (() => {}))();
});
