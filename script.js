/* ── Utilities ── */
function htmlEsc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderParas(paragraphs) {
  if (!paragraphs || !paragraphs.length) return '';
  return paragraphs
    .map(p => p.split(/\n+/).filter(l => l.trim()).map(l => `<p>${htmlEsc(l.trim())}</p>`).join(''))
    .join('');
}

/* ── Year ── */
document.addEventListener('DOMContentLoaded', () => {
  const year = document.getElementById('year');
  if (year) year.textContent = new Date().getFullYear();
});

/* ── Detail Modal ── */
function openDetailModal(card) {
  const raw = card.dataset.modal;
  if (!raw) return;
  let data;
  try { data = JSON.parse(raw); } catch (e) { return; }

  const inner = document.getElementById('modalInner');

  // Cover image
  let imageHtml = '';
  if (data.image) {
    imageHtml = `<div class="modal-cover"><img src="/Images/${htmlEsc(data.image)}" alt="${htmlEsc(data.title || '')}" /></div>`;
  }

  // Meta line
  let metaHtml = '';
  if (data.meta_line1) {
    metaHtml = `<p class="item-meta">${htmlEsc(data.meta_line1)}${data.meta_line2 ? '<br />' + htmlEsc(data.meta_line2) : ''}</p>`;
  } else if (data.year) {
    metaHtml = `<p class="item-meta">${htmlEsc(data.year)}</p>`;
  }

  // Paragraphs / description
  let contentHtml = '';
  if (data.paragraphs && data.paragraphs.length) {
    contentHtml = renderParas(data.paragraphs);
  } else if (data.description) {
    contentHtml = `<p>${htmlEsc(data.description)}</p>`;
  }

  // Details table
  let detailsHtml = '';
  if (data.details && data.details.length) {
    detailsHtml = '<div class="modal-details">' +
      data.details.map(d =>
        `<div class="detail-row"><span>${htmlEsc(d.key)}</span><span>${htmlEsc(d.value)}</span></div>`
      ).join('') +
      '</div>';
  }

  inner.innerHTML = `
    <div class="modal-layout">
      ${imageHtml}
      <div class="modal-body-text">
        <p class="item-label">${htmlEsc(data.label || '')}</p>
        <h2>${htmlEsc(data.title || '')}</h2>
        ${metaHtml}
        ${contentHtml}
        ${detailsHtml}
      </div>
    </div>`;

  document.getElementById('detailModal').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeDetailModal() {
  document.getElementById('detailModal').classList.remove('open');
  document.body.style.overflow = '';
}

function closeModalOnOverlay(e) {
  if (e.target === e.currentTarget) closeDetailModal();
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeDetailModal();
});
