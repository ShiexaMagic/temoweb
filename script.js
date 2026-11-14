/* Public page behaviour: mobile menu, active nav link, and the detail
   pages for books / plays / films (opened at  #/<id>  so they can be linked). */
(function () {
  var view = document.getElementById('detailView');
  var navLinks = document.getElementById('navLinks');
  var navToggle = document.getElementById('navToggle');
  var baseTitle = document.title;
  var pageScroll = 0;
  var openedHere = false;   // true when the detail was opened by a click on this page

  /* ── Mobile menu ── */
  function setMenu(open) {
    navLinks.classList.toggle('open', open);
    navToggle.setAttribute('aria-expanded', String(open));
    navToggle.firstElementChild.textContent = open ? 'Close' : 'Menu';
  }
  navToggle.addEventListener('click', function () {
    setMenu(!navLinks.classList.contains('open'));
  });
  navLinks.addEventListener('click', function (e) {
    if (e.target.closest('a')) setMenu(false);
  });

  /* ── Detail pages ── */
  function currentDetail() {
    var m = location.hash.match(/^#\/(.+)$/);
    return m ? document.getElementById('detail-' + decodeURIComponent(m[1])) : null;
  }

  function sync() {
    var target = currentDetail();
    var wasOpen = !view.hidden;
    view.querySelectorAll('.detail').forEach(function (el) { el.hidden = el !== target; });

    if (target) {
      if (!wasOpen) pageScroll = window.scrollY;
      view.hidden = false;
      view.scrollTop = 0;
      document.body.classList.add('detail-open');
      document.title = target.dataset.title + ' — ' + baseTitle;
      return;
    }
    if (wasOpen) {
      view.hidden = true;
      document.body.classList.remove('detail-open');
      document.title = baseTitle;
      // Closed with Back: return to where the reader was. A link to a
      // section (#books) scrolls there by itself.
      if (location.hash.length < 2) window.scrollTo(0, pageScroll);
    }
  }

  function closeDetail() {
    if (view.hidden) return;
    if (openedHere) { history.back(); return; }
    var back = currentDetail() && currentDetail().querySelector('.back-link');
    location.hash = back ? back.getAttribute('href') : '#home';
  }

  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[href^="#"]');
    if (!a) return;
    if (a.getAttribute('href').indexOf('#/') === 0) { openedHere = true; return; }
    // "Back to …" returns to the exact spot the reader left.
    if (a.classList.contains('back-link') && openedHere) {
      e.preventDefault();
      history.back();
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { setMenu(false); closeDetail(); }
  });
  window.addEventListener('hashchange', function () {
    if (!currentDetail()) openedHere = false;
    sync();
  });
  sync();

  /* ── Highlight the section being read ── */
  var links = {};
  navLinks.querySelectorAll('a[data-section]').forEach(function (a) { links[a.dataset.section] = a; });
  if ('IntersectionObserver' in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var link = links[entry.target.id];
        if (link) link.classList.toggle('active', entry.isIntersecting);
      });
    }, { rootMargin: '-45% 0px -50% 0px' });
    Object.keys(links).forEach(function (id) {
      var section = document.getElementById(id);
      if (section) observer.observe(section);
    });
  }
})();
