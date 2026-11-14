/* Public site behaviour.  Every section is its own page with its own
   address — /books, /theatre, /books/<id> … — all served from this one
   file, so moving between them is instant. */
(function () {
  var root = document.documentElement;
  var navLinks = document.getElementById('navLinks');
  var navToggle = document.getElementById('navToggle');
  var baseTitle = document.title;
  var scrollMemory = {};          // address -> scroll position, for Back / Forward

  /* ── Black / white design switch (remembered on this device) ── */
  document.getElementById('themeToggle').addEventListener('click', function () {
    var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch (e) { /* private mode */ }
  });

  /* ── Mobile menu ── */
  function setMenu(open) {
    navLinks.classList.toggle('open', open);
    navToggle.setAttribute('aria-expanded', String(open));
    navToggle.firstElementChild.textContent = open ? 'Close' : 'Menu';
  }
  navToggle.addEventListener('click', function () {
    setMenu(!navLinks.classList.contains('open'));
  });

  /* ── Which page does this address show? ── */
  function resolve(pathname) {
    var parts = pathname.replace(/^\/+|\/+$/g, '').split('/');
    var section = parts[0] && document.getElementById(parts[0]);
    if (!section || !section.classList.contains('page') || parts[0] === 'home') {
      return { view: 'home', section: '', title: '' };
    }
    if (parts[1]) {
      var detail = document.getElementById('detail-' + decodeURIComponent(parts[1]));
      if (detail) return { view: 'detail', section: parts[0], detail: detail, title: detail.dataset.title };
    }
    return { view: parts[0], section: parts[0], title: section.dataset.title };
  }

  function show(pathname) {
    var page = resolve(pathname);
    root.setAttribute('data-view', page.view);
    document.querySelectorAll('.detail').forEach(function (el) { el.hidden = el !== page.detail; });
    navLinks.querySelectorAll('a[data-section]').forEach(function (a) {
      var on = a.dataset.section === page.section;
      a.classList.toggle('active', on);
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    document.title = page.title ? page.title + ' — ' + baseTitle : baseTitle;
    setMenu(false);
  }

  function go(pathname) {
    if (pathname === location.pathname) { window.scrollTo(0, 0); return; }
    scrollMemory[location.pathname] = window.scrollY;
    history.pushState(null, '', pathname);
    show(pathname);
    window.scrollTo(0, 0);
  }

  /* Links inside the site switch pages without reloading. */
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest('a[href]');
    if (!a || a.target || a.origin !== location.origin) return;
    if (/^\/(Images|admin|api)(\/|$)/.test(a.pathname) || a.hash) return;
    e.preventDefault();
    go(a.pathname);
  });

  window.addEventListener('popstate', function () {
    show(location.pathname);
    window.scrollTo(0, scrollMemory[location.pathname] || 0);
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    setMenu(false);
    var page = resolve(location.pathname);
    if (page.view === 'detail') go('/' + page.section);
  });

  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';

  /* Old links (#books, #/couriers-tales) keep working. */
  var old = location.hash.replace(/^#\/?/, '');
  if (old && location.pathname === '/') {
    var detail = document.getElementById('detail-' + decodeURIComponent(old));
    var target = detail ? '/' + detail.dataset.section + '/' + old : (document.getElementById(old) ? '/' + old : null);
    if (target && old !== 'home') history.replaceState(null, '', target);
  }
  show(location.pathname);
})();
