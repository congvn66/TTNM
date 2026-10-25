const iconPaths = {
  grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.3"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.3"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.3"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.3"/>',
  'file-search': '<path d="M13 3.5H6.5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2H12"/><path d="M13 3.5v5h5"/><path d="M13 3.5 18 8.5"/><circle cx="16.5" cy="16.5" r="3.2"/><path d="m19 19 2 2"/>',
  folder: '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/><path d="M3.5 9h17"/>',
  history: '<path d="M3 11a9 9 0 1 1 .9 5.5"/><path d="M3 4.5v6.5h6.5"/><path d="M12 7v5l3.5 2"/>',
  'life-buoy': '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.3"/><path d="m5.6 5.6 4 4M14.4 14.4l4 4M18.4 5.6l-4 4M9.6 14.4l-4 4"/>',
  'arrow-up-right': '<path d="M7 17 17 7"/><path d="M8 7h9v9"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  'chevron-down': '<path d="m6 9 6 6 6-6"/>',
  'circle-help': '<circle cx="12" cy="12" r="9"/><path d="M9.6 9a2.5 2.5 0 1 1 4.4 1.6c-.8.8-2 1.2-2 2.6"/><path d="M12 17.2h.01"/>',
  download: '<path d="M12 3.5v11"/><path d="m7.5 10 4.5 4.5 4.5-4.5"/><path d="M5 16.5v3h14v-3"/>',
  upload: '<path d="M12 15V4"/><path d="m7.5 8.5 4.5-4.5 4.5 4.5"/><path d="M5 16v4h14v-4"/>',
  'file-pdf': '<path d="M13.5 3.5H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10z"/><path d="M13.5 3.5V10H20"/><path d="M7.5 15h2a1.4 1.4 0 0 0 0-2.8h-2V18M12.5 18v-5.8h1.2c2.8 0 2.8 5.8 0 5.8zM18.5 13h-2v5M16.5 15.5h1.8"/>',
  'chevron-left': '<path d="m14.5 5-7 7 7 7"/>',
  'chevron-right': '<path d="m9.5 5 7 7-7 7"/>',
  minus: '<path d="M5 12h14"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  'external-link': '<path d="M13.5 4.5h6v6"/><path d="m19.5 4.5-9 9"/><path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/>',
  'check-circle-2': '<circle cx="12" cy="12" r="9"/><path d="m8 12.2 2.5 2.5 5.5-5.5"/>',
  'message-square-text': '<path d="M20 11.5a6.5 6.5 0 0 1-6.5 6.5H7l-3.5 2v-5A6.5 6.5 0 0 1 10 4h3.5a6.5 6.5 0 0 1 6.5 6.5z"/><path d="M8 9.5h8M8 13h5"/>',
  'file-text': '<path d="M13 3.5H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10z"/><path d="M13 3.5V10h7M8 13.5h8M8 17h8"/>',
  x: '<path d="m6 6 12 12M18 6 6 18"/>',
  sparkles: '<path d="m12 3 1.4 5.6L19 10l-5.6 1.4L12 17l-1.4-5.6L5 10l5.6-1.4z"/><path d="m19 16 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7z"/><path d="m5 2 .6 2.4L8 5l-2.4.6L5 8l-.6-2.4L2 5l2.4-.6z"/>',
  calculator: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8v3H8zM8 14h1M12 14h1M16 14h.01M8 17.5h1M12 17.5h1M16 17.5h.01"/>',
  'file-check-2': '<path d="M13 3.5H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h7"/><path d="M13 3.5V10h6.5"/><path d="M13 3.5 19.5 10"/><circle cx="17.5" cy="17.5" r="3.5"/><path d="m16 17.5 1 1 2-2"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  'corner-down-right': '<path d="M7 7v4a4 4 0 0 0 4 4h6"/><path d="m13 11 4 4-4 4"/>',
  'chart-no-axes-combined': '<path d="M3.5 20V4"/><path d="M3.5 20h17"/><path d="m6.5 15 4-4 3 2 5-6"/><path d="M15.5 7h3v3"/>',
  'corner-down-left': '<path d="M17 7v4a4 4 0 0 1-4 4H7"/><path d="m11 11-4 4 4 4"/>',
  'arrow-up': '<path d="M12 19V5"/><path d="m5.5 11.5 6.5-6.5 6.5 6.5"/>',
  'table-properties': '<rect x="3.5" y="4" width="17" height="16" rx="1.5"/><path d="M3.5 9.5h17M3.5 15h17M9.2 4v16M15 4v16"/>',
  'list-filter': '<path d="M4 6h16M7 12h10M10 18h4"/>',
  'shield-check': '<path d="M12 3 19 6v5c0 4.5-3 7.7-7 10-4-2.3-7-5.5-7-10V6z"/><path d="m8.5 12 2.2 2.2 4.8-4.8"/>',
  'file-up': '<path d="M13 3.5H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h7"/><path d="M13 3.5V10h6.5"/><path d="M13 3.5 19.5 10"/><path d="M16 19h6M19 16v6"/>',
  check: '<path d="m5 12.5 4.2 4L19 7"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4z"/>' ,
};

function iconSvg(name) {
  return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${iconPaths[name] || iconPaths.info}</svg>`;
}
const iconWrapperClasses = ['footer-check', 'source-leading-icon', 'status-check', 'help-icon', 'pdf-empty-icon', 'table-icon', 'assistant-brand-icon', 'file-type-icon', 'modal-icon'];
document.querySelectorAll('[data-icon]').forEach(el => {
  const svg = iconSvg(el.dataset.icon);
  if (el.classList.contains('icon')) {
    el.innerHTML = svg;
  } else if (iconWrapperClasses.some(className => el.classList.contains(className))) {
    el.innerHTML = `<span class="icon">${svg}</span>`;
  } else {
    el.innerHTML = svg;
    el.classList.add('icon');
  }
});

const state = {
  rows: [
    { id: 'north', region: 'Miền Bắc', q1: 58, q2: 67, q3: 79, q4: 84, dataStatus: 'present', confirmation: 'confirmed', edited: false },
    { id: 'central', region: 'Miền Trung', q1: 42, q2: 49, q3: 55, q4: 61, dataStatus: 'present', confirmation: 'unconfirmed', edited: false },
    { id: 'south', region: 'Miền Nam', q1: 65, q2: 68, q3: 74, q4: 78, dataStatus: 'present', confirmation: 'confirmed', edited: false },
  ],
  filterUnconfirmed: false,
  currentPage: 3,
  totalPages: 4,
  zoom: 100,
  pdfUrl: '/sample-report.pdf',
  objectUrl: null,
  documentName: 'Báo cáo doanh thu theo khu vực.pdf',
  localDocument: false,
  contextAttached: true,
  questionsAsked: 0,
};

const byId = id => document.getElementById(id);
const fmt = n => Number(n).toLocaleString('vi-VN', { maximumFractionDigits: 2 });
const fmtPct = n => `${Number(n).toLocaleString('vi-VN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

function changePct(row) {
  if (!Number(row.q1)) return null;
  return ((Number(row.q3) - Number(row.q1)) / Number(row.q1)) * 100;
}

function confirmationChip(row) {
  if (row.confirmation === 'confirmed') return '<span class="status-pill confirmed"><i class="status-dot"></i>Đã xác nhận</span>';
  if (row.confirmation === 'edited') return '<button class="status-pill edited" data-confirm-row="' + row.id + '" title="Nhấn để xác nhận giá trị đã sửa"><i class="status-dot"></i>Đã sửa</button>';
  return '<button class="status-pill unconfirmed" data-confirm-row="' + row.id + '" title="Nhấn để xác nhận dữ liệu"><i class="status-dot"></i>Chưa xác nhận</button>';
}

function renderTable() {
  const body = byId('data-table-body');
  const rows = state.rows.filter(row => !state.filterUnconfirmed || row.confirmation !== 'confirmed');
  byId('row-count').textContent = `${rows.length} dòng`;
  const topbarCount = byId('topbar-row-count');
  if (topbarCount) topbarCount.textContent = String(state.rows.length);
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="9" class="empty-table">Tất cả số liệu đang hiển thị đã được xác nhận.</td></tr>';
    return;
  }
  body.innerHTML = rows.map(row => {
    const pct = changePct(row);
    const markClass = row.id === 'central' ? 'central' : row.id === 'south' ? 'south' : '';
    const dataStatus = row.dataStatus === 'present'
      ? '<span class="status-pill data-ok"><i class="status-dot"></i>Có giá trị</span>'
      : '<span class="status-pill data-missing"><i class="status-dot"></i>Thiếu dữ liệu</span>';
    return `<tr data-row-id="${row.id}" class="${row.edited ? 'row-edited' : ''}">
      <td><div class="region-cell"><i class="region-mark ${markClass}"></i>${esc(row.region)}</div></td>
      ${['q1','q2','q3','q4'].map(period => `<td class="value-cell"><button class="value-edit" data-edit-row="${row.id}" data-edit-period="${period}" aria-label="Sửa ${esc(row.region)}, ${period.toUpperCase()}: ${fmt(row[period])}" title="Nhấn để sửa giá trị">${fmt(row[period])}<span class="icon">${iconSvg('edit')}</span></button></td>`).join('')}
      <td>${pct === null ? '<span class="muted">Không xác định</span>' : `<span class="change-value ${pct < 0 ? 'negative' : ''}">${pct >= 0 ? '+' : ''}${fmtPct(pct)}</span>`}</td>
      <td>${dataStatus}</td><td>${confirmationChip(row)}</td>
      <td><button class="source-cell-button" data-open-page="3"><span class="icon">${iconSvg('file-text')}</span>Trang 3</button></td>
    </tr>`;
  }).join('');
}

function updatePinnedAnswer() {
  const card = document.querySelector('#chat-stream .answer-card');
  if (!card) return;
  const scored = state.rows.map(row => ({ ...row, pct: changePct(row) })).filter(row => row.pct !== null).sort((a, b) => b.pct - a.pct);
  if (!scored.length) return;
  const top = scored[0];
  const tied = scored.filter(row => Math.abs(row.pct - top.pct) < 0.00001);
  const title = tied.length > 1 ? `${tied.map(row => row.region).join(' và ')} cùng có mức tăng cao nhất.` : `${top.region} tăng nhiều nhất từ Quý 1 đến Quý 3.`;
  const pText = tied.length > 1
    ? `Mỗi khu vực tăng ${fmtPct(top.pct)} theo tỷ lệ phần trăm. Kết quả được tính từ doanh thu Quý 1 và Quý 3.`
    : `Doanh thu tăng từ ${fmt(top.q1)} lên ${fmt(top.q3)} triệu đồng, tương đương ${fmtPct(top.pct)}.`;
  const p = card.querySelector('p');
  card.querySelector('h3').textContent = title;
  p.innerHTML = tied.length > 1 ? esc(pText) : `Doanh thu tăng từ <strong>${esc(fmt(top.q1))}</strong> lên <strong>${esc(fmt(top.q3))} triệu đồng</strong>, tương đương <strong class="highlight-value">${esc(fmtPct(top.pct))}</strong>.`; 
  const formulaEl = card.querySelector('.formula');
  if (formulaEl) formulaEl.textContent = tied.length > 1 ? 'Các khu vực có tỷ lệ tăng bằng nhau' : `((${fmt(top.q3)} − ${fmt(top.q1)}) / ${fmt(top.q1)}) × 100 = ${fmtPct(top.pct)}`;
  const sourceTitle = card.querySelector('.answer-source-copy strong');
  if (sourceTitle) sourceTitle.textContent = 'Biểu đồ doanh thu theo quý';
}

function renderChatAnswer(answer) {
  const stream = byId('chat-stream');
  const row = document.createElement('div');
  row.className = 'assistant-message-row';
  const isMissing = answer.type === 'missing';
  const isClarify = answer.type === 'clarify';
  const statusText = isMissing ? 'Thiếu dữ liệu' : isClarify ? 'Cần làm rõ' : 'Có căn cứ';
  const statusIcon = isMissing ? 'info' : isClarify ? 'circle-help' : 'check';
  const facts = Array.isArray(answer.facts) && answer.facts.length
    ? `<div class="answer-facts">${answer.facts.map(fact => `<div class="answer-fact"><span>${esc(fact.label)}</span><strong>${esc(fact.value)}</strong></div>`).join('')}</div>` : '';
  const formula = answer.formula ? `<div class="calculation-block"><div class="calculation-label"><span class="icon">${iconSvg('calculator')}</span>Cách tính</div><div class="formula">${esc(answer.formula)}</div></div>` : '';
  const source = answer.sourcePage ? `<div class="answer-source-row"><span class="source-leading-icon">${iconSvg('file-check-2')}</span><div class="answer-source-copy"><strong>${esc(answer.sourceTitle || 'Nguồn trong báo cáo')}</strong><small>Trang ${Number(answer.sourcePage)} · Dữ liệu trong tài liệu</small></div><button class="source-open-button" data-open-page="${Number(answer.sourcePage)}">Xem nguồn <span class="icon">${iconSvg('arrow-up-right')}</span></button></div>` : '';
  const disclaimer = isMissing
    ? '<div class="answer-disclaimer"><span class="icon">' + iconSvg('info') + '</span>Không tự suy đoán giá trị khi báo cáo không có căn cứ.</div>'
    : isClarify
      ? '<div class="answer-disclaimer"><span class="icon">' + iconSvg('info') + '</span>Có thể bổ sung phạm vi để nhận câu trả lời chính xác hơn.</div>'
      : '<div class="answer-disclaimer"><span class="icon">' + iconSvg('info') + '</span>Số liệu đầu vào có thể được đối chiếu và hiệu chỉnh ở bảng bên dưới.</div>';
  row.innerHTML = `
    <div class="assistant-mini-avatar"><span class="icon">${iconSvg('sparkles')}</span></div>
    <div class="assistant-message-body">
      <div class="answer-meta"><span class="answer-sender">Rõ Số</span><span class="answer-status"><span class="status-check">${iconSvg(statusIcon)}</span>${statusText}</span><span class="message-time">Vừa xong</span></div>
      <div class="answer-card ${isMissing ? 'missing-card' : isClarify ? 'clarify-card' : ''}">
        <h3>${esc(answer.title || 'Kết quả tra cứu')}</h3><p>${esc(answer.text || '')}</p>${formula}${facts}${source}
      </div>${disclaimer}
    </div>`;
  stream.appendChild(row);
  stream.scrollTop = stream.scrollHeight;
}

function appendUserQuestion(question) {
  const row = document.createElement('div');
  row.className = 'user-message-row';
  const bubble = document.createElement('div');
  bubble.className = 'user-message';
  bubble.textContent = question;
  const time = document.createElement('span');
  time.className = 'message-time';
  time.textContent = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
  row.append(bubble, time);
  byId('chat-stream').appendChild(row);
}

function appendTyping() {
  const row = document.createElement('div');
  row.className = 'assistant-message-row typing-row';
  row.innerHTML = `<div class="assistant-mini-avatar"><span class="icon">${iconSvg('sparkles')}</span></div><div class="assistant-message-body"><div class="answer-meta"><span class="answer-sender">Rõ Số</span><span class="message-time">Đang kiểm tra căn cứ…</span></div><div class="answer-card"><p style="padding-top:12px;margin:0"><span class="typing-dots"><i></i><i></i><i></i></span></p></div></div>`;
  byId('chat-stream').appendChild(row);
  byId('chat-stream').scrollTop = byId('chat-stream').scrollHeight;
  return row;
}

async function askQuestion(question) {
  if (!state.contextAttached) {
    appendUserQuestion(question);
    renderChatAnswer({ type: 'missing', title: 'Chưa chọn tài liệu để hỏi đáp.', text: 'Hãy tải lên hoặc thêm một báo cáo vào phạm vi hiện tại trước khi đặt câu hỏi.', facts: [] });
    return;
  }
  appendUserQuestion(question);
  const typingRow = appendTyping();
  const sendButton = byId('send-question');
  sendButton.disabled = true;
  try {
    const response = await fetch('/api/answer', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, rows: state.rows.map(({ id, region, q1, q2, q3, q4 }) => ({ id, region, q1, q2, q3, q4 })) }),
    });
    if (!response.ok) throw new Error('Máy chủ không phản hồi đúng yêu cầu.');
    const answer = await response.json();
    typingRow.remove();
    renderChatAnswer(answer);
    state.questionsAsked += 1;
  } catch (error) {
    typingRow.remove();
    renderChatAnswer({ type: 'missing', title: 'Chưa thể xử lý câu hỏi.', text: 'Không kết nối được với dịch vụ hỏi đáp cục bộ. Hãy kiểm tra máy chủ Node.js và thử lại.', facts: [] });
  } finally {
    sendButton.disabled = false;
    byId('question-input').focus();
  }
}

function setPdfPage(page) {
  const max = state.totalPages || 40;
  state.currentPage = Math.min(max, Math.max(1, page));
  byId('page-current').textContent = state.currentPage;
  byId('page-total').textContent = state.totalPages ?? '—';
  const hash = `#page=${state.currentPage}&toolbar=0&navpanes=0&view=FitH&zoom=${state.zoom}`;
  byId('pdf-frame').src = `${state.pdfUrl}${hash}`;
  byId('source-caption').innerHTML = `Nguồn đang xem: <strong>Trang ${state.currentPage}${state.currentPage === 3 ? ' · Biểu đồ doanh thu theo quý' : ''}</strong>`;
  byId('go-to-source').disabled = false;
}

function openSource(page = 3) {
  setPdfPage(Number(page) || 3);
  byId('pdf-stage').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  toast('Đã mở căn cứ', `Trình xem tài liệu đã chuyển đến trang ${state.currentPage}.`);
}

function toast(title, message) {
  const item = document.createElement('div');
  item.className = 'toast';
  item.innerHTML = `<span class="icon">${iconSvg('check-circle-2')}</span><div><strong>${esc(title)}</strong><p>${esc(message)}</p></div>`;
  byId('toast-region').appendChild(item);
  setTimeout(() => { item.style.opacity = '0'; item.style.transform = 'translateY(5px)'; setTimeout(() => item.remove(), 220); }, 3200);
}

function showModal(title, message) {
  byId('modal-title').textContent = title;
  byId('modal-copy').textContent = message;
  byId('modal-backdrop').hidden = false;
  byId('modal-ok').focus();
}
function closeModal() { byId('modal-backdrop').hidden = true; }

function downloadBlob(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = filename;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function exportCsv() {
  const headers = ['Khu vực', 'Quý 1 (triệu đồng)', 'Quý 2 (triệu đồng)', 'Quý 3 (triệu đồng)', 'Quý 4 (triệu đồng)', 'Thay đổi Q1-Q3 (%)', 'Tình trạng dữ liệu', 'Xác nhận', 'Nguồn'];
  const csvRows = [headers, ...state.rows.map(row => [row.region, row.q1, row.q2, row.q3, row.q4, changePct(row) === null ? '' : changePct(row).toFixed(1), row.dataStatus === 'present' ? 'Có giá trị' : 'Thiếu dữ liệu', row.confirmation === 'confirmed' ? 'Đã xác nhận' : row.confirmation === 'edited' ? 'Đã sửa' : 'Chưa xác nhận', 'Trang 3'])];
  const csv = '\ufeff' + csvRows.map(row => row.map(cell => `"${String(cell ?? '').replace(/"/g, '""')}"`).join(',')).join('\r\n');
  downloadBlob('ro-so-du-lieu-bao-cao.csv', csv, 'text/csv;charset=utf-8;');
  toast('Đã xuất dữ liệu', 'Tệp CSV đã được tạo từ các giá trị hiện tại.');
}

function exportReport() {
  const lines = [
    '# Rõ Số — Báo cáo kiểm tra số liệu', '',
    `Tài liệu: ${state.documentName}`,
    `Thời điểm xuất: ${new Date().toLocaleString('vi-VN')}`, '',
    '## Dữ liệu đã trích xuất', '',
    '| Khu vực | Quý 1 | Quý 2 | Quý 3 | Quý 4 | Thay đổi Q1–Q3 | Xác nhận |',
    '|---|---:|---:|---:|---:|---:|---|',
    ...state.rows.map(r => `| ${r.region} | ${r.q1} | ${r.q2} | ${r.q3} | ${r.q4} | ${changePct(r) === null ? 'Không xác định' : fmtPct(changePct(r))} | ${r.confirmation === 'confirmed' ? 'Đã xác nhận' : r.confirmation === 'edited' ? 'Đã sửa' : 'Chưa xác nhận'} |`),
    '', '## Ghi chú',
    '- Đơn vị doanh thu: triệu đồng.',
    '- Nguồn số liệu: Biểu đồ doanh thu theo quý, trang 3.',
    '- Các tỷ lệ thay đổi được tính theo công thức ((Quý 3 − Quý 1) / Quý 1) × 100.',
    '- Đây là bản xuất từ dữ liệu đang hiển thị trong phiên làm việc.',
  ];
  downloadBlob('ro-so-bao-cao-kiem-tra.md', lines.join('\n'), 'text/markdown;charset=utf-8;');
  toast('Đã xuất báo cáo', 'Tệp Markdown gồm bảng số liệu và ghi chú nguồn đã được tải xuống.');
}

function beginInlineEdit(button) {
  const row = state.rows.find(item => item.id === button.dataset.editRow);
  const period = button.dataset.editPeriod;
  if (!row || !['q1', 'q2', 'q3', 'q4'].includes(period)) return;
  const cell = button.closest('td');
  if (!cell || cell.querySelector('input')) return;
  const previous = row[period];
  cell.innerHTML = `<input class="inline-edit" type="number" min="0" max="1000000000" step="0.1" value="${esc(previous)}" aria-label="Giá trị mới cho ${esc(row.region)}, ${period.toUpperCase()}" />`;
  const input = cell.querySelector('input');
  input.focus(); input.select();
  let finished = false;
  const save = (commit) => {
    if (finished) return;
    finished = true;
    if (commit) {
      const value = Number(input.value);
      if (input.value.trim() === '' || !Number.isFinite(value) || value < 0 || value > 1e9) {
        toast('Giá trị chưa hợp lệ', 'Nhập một số không âm để lưu thay đổi.');
      } else if (value !== previous) {
        row[period] = value;
        row.confirmation = 'edited';
        row.edited = true;
        byId('table-note').textContent = `Đã cập nhật ${row.region} · ${period.toUpperCase()}; các tỷ lệ phụ thuộc đã được tính lại.`;
        toast('Đã cập nhật số liệu', `${row.region} · ${period.toUpperCase()} = ${fmt(value)} triệu đồng.`);
      }
    }
    renderTable(); updatePinnedAnswer();
  };
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); save(true); }
    if (event.key === 'Escape') { event.preventDefault(); save(false); }
  });
  input.addEventListener('blur', () => save(true));
}

function handleUpload(file) {
  if (!file) return;
  const looksPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
  if (!looksPdf) {
    showModal('Định dạng chưa được hỗ trợ', 'Rõ Số hiện chỉ nhận báo cáo PDF. Hãy chọn một tệp có đuôi .pdf.');
    return;
  }
  if (file.size > 35 * 1024 * 1024) {
    showModal('Tệp PDF quá lớn', 'Ở bản dựng hiện tại, vui lòng chọn tệp nhỏ hơn 35 MB để xem trong trình duyệt.');
    return;
  }
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.objectUrl = URL.createObjectURL(file);
  state.pdfUrl = state.objectUrl;
  state.documentName = file.name;
  state.localDocument = true;
  state.currentPage = 1;
  state.totalPages = null;
  state.contextAttached = true;
  byId('document-name').textContent = file.name;
  byId('sidebar-document-name').textContent = file.name.replace(/\.pdf$/i, '');
  byId('document-meta').textContent = `PDF · ${(file.size / (1024 * 1024)).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} MB · Tệp cục bộ`;
  byId('context-filename').textContent = file.name.replace(/\.pdf$/i, '');
  byId('context-filename').title = file.name;
  byId('context-file').style.display = 'flex';
  byId('chat-context-strip').style.background = '';
  byId('chat-context-strip').style.opacity = '1';
  byId('pdf-frame').hidden = false;
  byId('pdf-empty').hidden = true;
  byId('page-total').textContent = '—';
  setPdfPage(1);
  toast('Đã mở báo cáo', `${file.name} sẵn sàng để xem trong trình duyệt.`);
}

// Actions: keep all interface interactions local and predictable.
byId('question-form').addEventListener('submit', async event => {
  event.preventDefault();
  const input = byId('question-input');
  const question = input.value.trim();
  if (!question) { input.focus(); return; }
  input.value = ''; input.style.height = 'auto';
  await askQuestion(question);
});
byId('question-input').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault(); byId('question-form').requestSubmit();
  }
});
byId('question-input').addEventListener('input', event => {
  event.target.style.height = 'auto';
  event.target.style.height = `${Math.min(event.target.scrollHeight, 105)}px`;
});
byId('suggestion-row').addEventListener('click', event => {
  const button = event.target.closest('[data-question]');
  if (!button) return;
  byId('question-input').value = button.dataset.question;
  byId('question-form').requestSubmit();
});
byId('chat-stream').addEventListener('click', event => {
  const button = event.target.closest('[data-open-page]');
  if (button) openSource(button.dataset.openPage);
});
byId('data-table-body').addEventListener('click', event => {
  const editButton = event.target.closest('[data-edit-row]');
  if (editButton) { beginInlineEdit(editButton); return; }
  const confirmButton = event.target.closest('[data-confirm-row]');
  if (confirmButton) {
    const row = state.rows.find(item => item.id === confirmButton.dataset.confirmRow);
    if (!row) return;
    row.confirmation = row.confirmation === 'confirmed' ? 'unconfirmed' : 'confirmed';
    renderTable();
    toast(row.confirmation === 'confirmed' ? 'Đã xác nhận dữ liệu' : 'Đã chuyển về chưa xác nhận', row.region);
  }
  const sourceButton = event.target.closest('[data-open-page]');
  if (sourceButton) openSource(sourceButton.dataset.openPage);
});
byId('upload-button').addEventListener('click', () => byId('pdf-input').click());
byId('topbar-upload').addEventListener('click', () => byId('pdf-input').click());
byId('empty-upload').addEventListener('click', () => byId('pdf-input').click());
byId('pdf-input').addEventListener('change', event => {
  handleUpload(event.target.files?.[0]); event.target.value = '';
});
byId('prev-page').addEventListener('click', () => setPdfPage(state.currentPage - 1));
byId('next-page').addEventListener('click', () => setPdfPage(state.currentPage + 1));
byId('zoom-in').addEventListener('click', () => { state.zoom = Math.min(150, state.zoom + 10); byId('zoom-label').textContent = `${state.zoom}%`; setPdfPage(state.currentPage); });
byId('zoom-out').addEventListener('click', () => { state.zoom = Math.max(70, state.zoom - 10); byId('zoom-label').textContent = `${state.zoom}%`; setPdfPage(state.currentPage); });
byId('open-pdf').addEventListener('click', () => window.open(`${state.pdfUrl}#page=${state.currentPage}`, '_blank', 'noopener,noreferrer'));
byId('go-to-source').addEventListener('click', () => openSource(state.currentPage === 3 ? 3 : state.currentPage));
byId('filter-unconfirmed').addEventListener('click', () => {
  state.filterUnconfirmed = !state.filterUnconfirmed;
  byId('filter-unconfirmed').classList.toggle('filter-active', state.filterUnconfirmed);
  byId('filter-unconfirmed').innerHTML = `<span class="icon">${iconSvg('list-filter')}</span>${state.filterUnconfirmed ? 'Hiện tất cả' : 'Chỉ hiện cần kiểm tra'}`;
  renderTable();
});
byId('export-csv').addEventListener('click', exportCsv);
byId('export-report').addEventListener('click', exportReport);
function setDataPanelOpen(open) {
  const panel = byId('data-panel');
  const scrim = byId('drawer-scrim');
  const toggle = byId('toggle-data-panel');
  panel.hidden = !open;
  scrim.hidden = !open;
  toggle.setAttribute('aria-expanded', String(open));
  if (open) byId('close-data-panel').focus();
}
byId('toggle-data-panel').addEventListener('click', () => setDataPanelOpen(byId('data-panel').hidden));
byId('close-data-panel').addEventListener('click', () => setDataPanelOpen(false));
byId('drawer-scrim').addEventListener('click', () => setDataPanelOpen(false));
byId('open-table-from-answer').addEventListener('click', () => setDataPanelOpen(true));
byId('context-button').addEventListener('click', () => showModal('Phạm vi hỏi đáp', `Các câu hỏi hiện được đối chiếu với tài liệu “${state.documentName}”. Bảng dữ liệu phía dưới dùng các số liệu mẫu trong phiên làm việc; việc tải PDF mới thay đổi bản xem tài liệu, chưa tự động trích xuất lại bảng số liệu.`));
byId('clear-context').addEventListener('click', () => {
  state.contextAttached = false;
  byId('context-filename').textContent = 'Chưa chọn tài liệu';
  byId('chat-context-strip').style.background = '#fbf4e8';
  toast('Đã gỡ tài liệu khỏi phạm vi', 'Tải lên hoặc chọn lại tài liệu để tiếp tục hỏi đáp.');
});
byId('help-button').addEventListener('click', () => showModal('Cách sử dụng Rõ Số', 'Đặt câu hỏi về số liệu trong báo cáo. Mỗi câu trả lời có thể liên kết tới trang nguồn và nêu cách tính. Trong bảng dữ liệu, nhấp vào một số để sửa; các tỷ lệ phụ thuộc sẽ được tính lại. Đây là bản dựng giao diện với dữ liệu mẫu, chưa tích hợp OCR hoặc mô hình hỏi đáp thực tế.'));
byId('document-menu').addEventListener('click', () => showModal('Tài liệu hiện tại', `${state.documentName}\n\nBạn có thể tải báo cáo khác bằng nút “Tải báo cáo PDF”. Tài liệu đã chọn được hiển thị trong trình xem của trình duyệt.`));
byId('modal-close').addEventListener('click', closeModal);
byId('modal-ok').addEventListener('click', closeModal);
byId('modal-backdrop').addEventListener('click', event => { if (event.target === byId('modal-backdrop')) closeModal(); });
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeModal(); });
document.querySelectorAll('[data-nav]').forEach(link => {
  link.addEventListener('click', event => {
    if (link.dataset.nav === 'workspace') return;
    event.preventDefault();
    showModal(link.textContent.trim(), 'Khu vực này sẽ hiển thị tài liệu và lịch sử tương ứng khi phần quản lý không gian được tích hợp.');
  });
});

byId('pdf-frame').addEventListener('load', () => {
  byId('pdf-loader').classList.add('hidden');
});
byId('pdf-frame').addEventListener('error', () => {
  byId('pdf-loader').classList.add('hidden');
  toast('Không thể xem tệp PDF', 'Thử mở tệp trong tab mới hoặc chọn một tệp khác.');
});

// First render of the sample workspace.
renderTable();
updatePinnedAnswer();
setTimeout(() => byId('pdf-loader').classList.add('hidden'), 1700);
