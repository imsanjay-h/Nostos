(() => {
  'use strict';
  const root = document.documentElement;
  const palette = [
    ['#ff684b','#171914','#d5ef65'], ['#d5ef65','#171914','#2855f5'],
    ['#d7d4ff','#171914','#ff684b'], ['#f3c8a9','#171914','#2855f5'],
    ['#2855f5','#fffdf7','#ff684b'], ['#e6d6a5','#171914','#8ba7ff']
  ];
  const tierNames = {
    immortals: '01 · THE IMMORTALS', 'works-of-art': '02 · WORKS OF ART',
    'stayed-with-me': '03 · STAYED WITH ME', 'a-good-time': '04 · A GOOD TIME',
    'didnt-connect': "05 · DIDN'T CONNECT"
  };
  const byId = id => document.getElementById(id);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  async function readJSON(path, fallback = {}) {
    try { const response = await fetch(path, {cache:'no-store'}); if (!response.ok) throw new Error('Could not load ' + path); return await response.json(); }
    catch (error) { console.warn(error.message); return fallback; }
  }
  function setText(id, text) { const element = byId(id); if (element && text !== undefined && text !== null) element.textContent = text; }
  function getTitle(item) { return item.title || item.name || 'Untitled entry'; }
  function getPalette(item, index = 0) { return palette[(Number.isFinite(item.palette) ? item.palette : index) % palette.length]; }
  function cardArt(item, index = 0) {
    const [bg, ink, shape] = getPalette(item, index);
    const title = safe(getTitle(item));
    const year = safe(item.year || item.releaseYear || item.startDate?.year || 'NOSTOS');
    const kind = safe(item.kindLabel || item.type || 'COLLECTED');
    const style = `--card-bg:${safe(item.color || bg)};--card-ink:${safe(item.ink || ink)};--card-shape:${safe(item.shape || shape)}`;
    const image = item.posterUrl || item.coverImage || item.image || item.coverUrl || '';
    return `<div class="poster-art${image ? ' has-image' : ''}" style="${style}">${image ? `<img class="poster-image" src="${safe(image)}" alt="" loading="lazy">` : ''}<span class="poster-mark">${kind}</span><span class="poster-year">${year}</span></div>`;
  }
  function createPoster(item, index = 0, collection = 'entry') {
    const button = document.createElement('button');
    button.className = 'poster-card'; button.type = 'button'; button.setAttribute('aria-label', `Open details for ${getTitle(item)}`);
    button._nostosItem = item; button._nostosCollection = collection; button._nostosIndex = index;
    button.innerHTML = `${cardArt(item,index)}<span class="poster-caption"><span class="poster-caption-title" title="${safe(getTitle(item))}">${safe(getTitle(item))}</span><span class="poster-caption-year">${safe(item.year || item.releaseYear || item.startDate?.year || '')}</span></span>`;
    button.addEventListener('click', () => openModal(item, collection, index));
    return button;
  }
  function placeholder(label, compact = false) {
    const div = document.createElement('div'); div.className = 'empty-card';
    div.textContent = label; if (compact) div.style.minWidth = '100px';
    return div;
  }
  function fillPosterRow(element, items, collection, emptyLabel = 'YOUR NEXT ENTRY\nWILL LIVE HERE', limit = 0) {
    if (!element) return;
    element.innerHTML = '';
    const shown = limit ? items.slice(0, limit) : items;
    if (!shown.length) { element.appendChild(placeholder(emptyLabel, element.classList.contains('mini-row'))); return; }
    shown.forEach((item, index) => element.appendChild(createPoster(item, index, collection)));
    setupPosterInteraction(element);
    setupAutoMotion(element);
  }
  // Gentle continuous horizontal movement for overflowing poster rows.
  // Uses scrollLeft (not transforms) so touch scrolling and accessibility remain native.
  function setupAutoMotion(row) {
    const viewport = row && row.closest('.marquee-window');
    if (!row || !viewport || row.dataset.autoMotion === 'true') return;
    row.dataset.autoMotion = 'true';
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    let frame = 0, lastTime = 0, pausedUntil = 0, direction = 1;
    const speed = 18; // pixels per second: deliberately slow and calm
    const maxScroll = () => Math.max(0, viewport.scrollWidth - viewport.clientWidth);
    const pause = (ms = 1400) => { pausedUntil = performance.now() + ms; };
    const tick = now => {
      if (!document.hidden) {
        const max = maxScroll();
        if (max > 8 && now >= pausedUntil && !row.matches(':hover') && !viewport.matches(':active')) {
          if (lastTime) viewport.scrollLeft += direction * speed * Math.min((now - lastTime) / 1000, .05);
          if (viewport.scrollLeft >= max - 1) { viewport.scrollLeft = max; direction = -1; pause(450); }
          else if (viewport.scrollLeft <= 1 && direction < 0) { viewport.scrollLeft = 0; direction = 1; pause(450); }
        }
      }
      lastTime = now;
      frame = requestAnimationFrame(tick);
    };
    viewport.addEventListener('pointerenter', () => pause(1800));
    viewport.addEventListener('pointerdown', () => pause(5000), {passive:true});
    viewport.addEventListener('touchstart', () => pause(5000), {passive:true});
    viewport.addEventListener('wheel', () => pause(2500), {passive:true});
    viewport.addEventListener('scroll', () => pause(1800), {passive:true});
    document.addEventListener('visibilitychange', () => { lastTime = 0; });
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => { if (maxScroll() <= 8) viewport.scrollLeft = 0; }).observe(viewport);
    frame = requestAnimationFrame(tick);
  }
  function setupPosterInteraction(row) {
    if (!row || row.dataset.posterInteraction === 'true') return;
    row.dataset.posterInteraction = 'true';
    const cards = () => Array.from(row.querySelectorAll('.poster-card'));
    const clearLift = () => cards().forEach(card => card.style.setProperty('--poster-lift', '0px'));
    row.addEventListener('pointermove', event => {
      if (event.pointerType !== 'mouse' || !window.matchMedia('(hover: hover) and (pointer: fine)').matches) return;
      const list = cards();
      const hovered = event.target.closest('.poster-card');
      if (!hovered) { clearLift(); return; }
      const focusIndex = list.indexOf(hovered);
      list.forEach((card, index) => {
        const distance = Math.abs(index - focusIndex);
        const lift = distance === 0 ? 13 : distance === 1 ? 6 : distance === 2 ? 2.5 : 0;
        card.style.setProperty('--poster-lift', `${lift}px`);
      });
    });
    row.addEventListener('pointerleave', clearLift);
  }
  function openModal(item, collection, index = 0) {
    const backdrop = byId('detail-modal'); if (!backdrop) return;
    const [bg, ink, shape] = getPalette(item, index);
    const art = byId('modal-art');
    art.style.setProperty('--card-bg', item.color || bg); art.style.setProperty('--card-ink', item.ink || ink); art.style.setProperty('--card-shape', item.shape || shape);
    const modalImage = item.posterUrl || item.coverImage || item.image || item.coverUrl || '';
    art.innerHTML = `${modalImage ? `<img class="modal-image" src="${safe(modalImage)}" alt="" loading="lazy">` : ''}<span>${safe(getTitle(item))}</span>`;
    setText('modal-title', getTitle(item));
    let kicker = collection === 'films' ? 'FROM THE FILM ARCHIVE' : collection === 'anime' ? 'FROM THE ANIME ARCHIVE' : collection === 'books' ? 'FROM THE BOOKSHELF' : 'A CURRENT FAVOURITE';
    setText('modal-kicker', kicker);
    const tier = item.tier ? (tierNames[item.tier] || item.tier) : '';
    const status = item.status || (collection === 'films' && item.watchlist ? 'Watchlist' : collection === 'anime' && item.watchlist ? 'Watchlist' : '');
    const author = item.author ? ` · ${item.author}` : '';
    const year = item.year || item.releaseYear || item.startDate?.year || '';
    setText('modal-meta', [tier || status, year, author.replace(/^ · /,'')].filter(Boolean).join('  /  '));
    setText('modal-note', item.note || item.review || item.description || '');
    const source = byId('modal-source');
    if (item.url || item.link) { source.href = item.url || item.link; source.hidden = false; source.textContent = 'Open source ↗'; }
    else { source.hidden = true; source.removeAttribute('href'); }
    backdrop.classList.add('open'); backdrop.setAttribute('aria-hidden','false'); document.body.style.overflow = 'hidden';
    const close = backdrop.querySelector('.modal-close'); if (close) close.focus();
  }
  function closeModal() { const backdrop = byId('detail-modal'); if (!backdrop) return; backdrop.classList.remove('open'); backdrop.setAttribute('aria-hidden','true'); document.body.style.overflow = ''; }
  function renderFilmTiers(data) {
    const container = byId('film-tiers'); if (!container) return;
    const items = data.items || [];
    setText('film-count', items.length.toLocaleString()); container.innerHTML = '';
    const tiers = data.tiers || [];
    tiers.forEach((tier, tierIndex) => {
      const section = document.createElement('section'); section.className = 'tier-block';
      const group = items.filter(item => item.tier === tier.id);
      section.innerHTML = `<div class="tier-heading"><span class="tier-number">${safe(tier.number || String(tierIndex + 1).padStart(2,'0'))}</span><h2>${safe(tier.name)}</h2><p>${safe(tier.description || '')}</p></div><div class="marquee-window"><div class="poster-row"></div></div>`;
      const row = section.querySelector('.poster-row');
      fillPosterRow(row, group, 'films', 'NO FILMS IN THIS TIER YET'); container.appendChild(section);
    });
    const placedTierIds = new Set(tiers.map(tier => tier.id));
    const unplaced = items.filter(item => !item.tier || !placedTierIds.has(item.tier));
    const unsorted = document.createElement('section'); unsorted.className = 'tier-block';
    unsorted.innerHTML = `<div class="tier-heading"><span class="tier-number">↳</span><h2>JUST LOGGED / NOT YET PLACED</h2><p>New imports land here until you decide where they belong. Nothing gets lost.</p></div><div class="marquee-window"><div class="poster-row"></div></div>`;
    fillPosterRow(unsorted.querySelector('.poster-row'), unplaced, 'films', 'NEW FILMS WILL APPEAR HERE AFTER SYNC');
    container.appendChild(unsorted);
  }
  function renderBooks(data) {
    const grid = byId('book-grid'); const waiting = byId('book-watchlist'); const current = byId('book-current');
    const books = data.read || []; const inProgress = data.currentlyReading || []; const watch = data.wantToRead || [];
    setText('book-count', (books.length + (data.currentlyReading || []).length + watch.length).toLocaleString());
    const draw = (target, items, emptyText) => {
      if (!target) return; target.innerHTML = '';
      if (!items.length) { const empty = document.createElement('div'); empty.className = 'book-empty'; empty.textContent = emptyText; target.appendChild(empty); return; }
      items.forEach((book, index) => {
        const [bg, ink, shape] = getPalette(book, index); const button = document.createElement('button'); button.type='button'; button.className='book-card'; button.style.setProperty('--cover',book.color || bg); button.style.setProperty('--cover-ink',book.ink || ink);
        button.innerHTML = `<div class="book-cover"><span class="book-cover-title">${safe(getTitle(book))}</span><span class="book-cover-author">${safe(book.author || 'A BOOK ON THE SHELF')}</span></div><span class="book-card-caption"><strong>${safe(getTitle(book))}</strong><span>${safe(book.author || '')}</span></span>`;
        button.addEventListener('click', () => openModal(book,'books',index)); target.appendChild(button);
      });
    };
    draw(grid, books, 'Your read books will live here. Import your Goodreads shelf when you are ready.');
    draw(current, inProgress, 'Books you are currently reading will appear here when your shelf is imported.');
    draw(waiting, watch, 'Your to-read list will have its own shelf here.');
  }
  function renderConnect(profile) {
    const list = byId('social-links'); if (!list) return; list.innerHTML = '';
    (profile.socials || []).forEach((social, index) => {
      const row = document.createElement(social.url ? 'a' : 'div'); row.className = 'social-link';
      if (social.url) { row.href = social.url; row.target = '_blank'; row.rel = 'noreferrer'; }
      row.innerHTML = `<span class="social-index">${safe(social.number || String(index+1).padStart(2,'0'))}</span><span class="social-title">${safe(social.label)}</span><span class="social-detail">${safe(social.detail || '')}</span><span class="social-arrow">↗</span>`;
      list.appendChild(row);
    });
  }
  function renderBooksPreview(data) {
    const target = byId('home-books'); if (!target) return;
    target.innerHTML = '';
    const books = (data.read || []).slice(0,4);
    if (!books.length) { ['A BOOK TO REMEMBER','SOMETHING TO DISCOVER','A NEW PERSPECTIVE'].forEach((title,i) => { const el=document.createElement('div');el.className='book-spine';el.textContent=title;el.style.setProperty('--spine',palette[i][0]);target.appendChild(el); }); return; }
    books.forEach((book,i) => { const el=document.createElement('button');el.className='book-spine';el.type='button';el.textContent=getTitle(book);el.style.setProperty('--spine',book.color || palette[i%palette.length][0]);el.addEventListener('click',()=>openModal(book,'books',i));target.appendChild(el); });
  }
  function renderAnime(data) {
    setText('anime-count', (data.watched || []).length.toLocaleString());
    const watchedTarget = byId('anime-watched');
    if (watchedTarget) {
      watchedTarget.innerHTML = '';
      const section = document.createElement('section'); section.className='tier-block';
      section.innerHTML = `<div class="tier-heading"><span class="tier-number">01</span><h2>WATCHED / VISITED</h2><p>Stories and worlds you've spent time in. Notes appear only when you want them to.</p></div><div class="marquee-window"><div class="poster-row"></div></div>`;
      fillPosterRow(section.querySelector('.poster-row'), data.watched || [], 'anime', 'YOUR FIRST WORLD WILL LIVE HERE'); watchedTarget.appendChild(section);
    }
    fillPosterRow(byId('anime-watchlist'), data.watchlist || [], 'anime', 'THE NEXT WORLD IS WAITING');
  }
  async function init() {
    const [films, anime, books, profile] = await Promise.all([
      readJSON('data/films.json',{items:[],watchlist:[],tiers:[]}), readJSON('data/anime.json',{watched:[],watchlist:[]}),
      readJSON('data/books.json',{read:[],currentlyReading:[],wantToRead:[]}), readJSON('data/profile.json',{})
    ]);
    setText('year', new Date().getFullYear());
    const date = byId('live-date'); if (date) date.textContent = new Date().toLocaleDateString(undefined,{month:'short',year:'numeric'}).toUpperCase() + ' / ALWAYS IN PROGRESS';
    setText('now-music', profile.currentlyListening); setText('now-reading', (books.currentlyReading || []).length ? `${getTitle(books.currentlyReading[0])}${books.currentlyReading[0].author ? ' · ' + books.currentlyReading[0].author : ''}` : profile.currentlyReading); setText('now-thought', profile.currentThought);
    const page = document.body.dataset.page;
    if (page === 'home') {
      setText('profile-intro', profile.intro);
      fillPosterRow(byId('home-films'), films.items || [], 'films', 'YOUR NEXT FILM WILL LIVE HERE', 8);
      fillPosterRow(byId('home-anime'), anime.watched || [], 'anime', 'A WORLD TO DISCOVER', 3);
      renderBooksPreview(books);
    }
    if (page === 'films') { renderFilmTiers(films); fillPosterRow(byId('film-watchlist'), films.watchlist || [], 'films', 'SAVE A FILM FOR LATER'); }
    if (page === 'anime') renderAnime(anime);
    if (page === 'books') renderBooks(books);
    if (page === 'connect') renderConnect(profile);
    document.querySelectorAll('.modal-close').forEach(button => button.addEventListener('click', closeModal));
    const backdrop = byId('detail-modal'); if (backdrop) backdrop.addEventListener('click', event => { if (event.target === backdrop) closeModal(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') closeModal(); });
    const toggle = document.querySelector('.menu-toggle'); const nav = document.querySelector('.main-nav');
    if (toggle && nav) toggle.addEventListener('click', () => { const open = nav.classList.toggle('open'); toggle.setAttribute('aria-expanded', String(open)); toggle.textContent = open ? '×' : '☰'; });
  }
  document.addEventListener('DOMContentLoaded', init);
})();
