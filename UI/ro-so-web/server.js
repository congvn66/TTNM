const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { URL } = require('node:url');

const ROOT = __dirname;
const PUBLIC = path.join(ROOT, 'public');
const PORT = Number(process.env.PORT || 3000);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.pdf': 'application/pdf',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

function sendJson(res, status, payload) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(payload));
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => {
      body += chunk;
      if (body.length > 1024 * 1024) {
        reject(new Error('Request body too large'));
        req.destroy();
      }
    });
    req.on('end', () => {
      try { resolve(body ? JSON.parse(body) : {}); }
      catch { reject(new Error('Invalid JSON')); }
    });
    req.on('error', reject);
  });
}

function normalizeRows(rows) {
  const fallback = [
    { id: 'north', region: 'Miền Bắc', q1: 58, q2: 67, q3: 79, q4: 84 },
    { id: 'central', region: 'Miền Trung', q1: 42, q2: 49, q3: 55, q4: 61 },
    { id: 'south', region: 'Miền Nam', q1: 65, q2: 68, q3: 74, q4: 78 },
  ];
  if (!Array.isArray(rows)) return fallback;
  return fallback.map(base => {
    const row = rows.find(item => item && item.id === base.id) || {};
    const next = { ...base };
    for (const key of ['q1', 'q2', 'q3', 'q4']) {
      const n = Number(row[key]);
      if (Number.isFinite(n) && n >= 0 && n <= 1e9) next[key] = n;
    }
    return next;
  });
}

function buildAnswer(question, rawRows) {
  const rows = normalizeRows(rawRows);
  const q = String(question || '').trim().toLocaleLowerCase('vi-VN');
  if (!q) {
    return { type: 'clarify', title: 'Bạn muốn kiểm tra số liệu nào?', text: 'Hãy nêu khu vực, kỳ báo cáo hoặc phép so sánh cần thực hiện.', sourcePage: null, facts: [] };
  }

  if (/(lợi nhuận|lãi ròng|profit)/i.test(q)) {
    return {
      type: 'missing', title: 'Báo cáo chưa có số liệu này.',
      text: 'Tài liệu đang mở chỉ cung cấp doanh thu theo khu vực và quý, chưa có dữ liệu về lợi nhuận. Không thể suy ra lợi nhuận từ doanh thu.',
      sourcePage: null, facts: [],
    };
  }

  if (/(quý\s*4|q4)/i.test(q) && /(cao nhất|lớn nhất|nhiều nhất|đứng đầu|max)/i.test(q)) {
    const sorted = [...rows].sort((a, b) => b.q4 - a.q4);
    const top = sorted[0];
    return {
      type: 'answer', title: `${top.region} có doanh thu Quý 4 cao nhất.`,
      text: `Doanh thu của khu vực này là ${fmt(top.q4)} triệu đồng.`,
      formula: null, sourcePage: 3, sourceTitle: 'Biểu đồ doanh thu theo quý',
      facts: [{ label: `${top.region} · Quý 4`, value: `${fmt(top.q4)} triệu đồng` }],
    };
  }

  if (/(quý\s*2|q2)/i.test(q) && /(miền bắc|phía bắc|khu vực bắc)/i.test(q)) {
    const north = rows.find(r => r.id === 'north') || rows[0];
    return {
      type: 'answer', title: `Doanh thu Quý 2 của ${north.region} là ${fmt(north.q2)} triệu đồng.`,
      text: 'Giá trị được lấy từ chuỗi doanh thu của khu vực Miền Bắc trong báo cáo.',
      formula: null, sourcePage: 3, sourceTitle: 'Biểu đồ doanh thu theo quý',
      facts: [{ label: 'Quý 2', value: `${fmt(north.q2)} triệu đồng` }],
    };
  }

  if (/(tăng|thay đổi|so sánh|nhiều nhất|cao nhất|phần trăm|tỷ lệ|%)/i.test(q)) {
    const scored = rows.map(row => ({
      ...row,
      change: row.q1 === 0 ? null : ((row.q3 - row.q1) / row.q1) * 100,
    })).filter(r => r.change !== null).sort((a, b) => b.change - a.change);
    const top = scored[0];
    const tied = scored.filter(r => Math.abs(r.change - top.change) < 0.00001);
    const pct = `${top.change.toLocaleString('vi-VN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
    const title = tied.length > 1
      ? `${tied.map(r => r.region).join(' và ')} cùng có mức tăng cao nhất.`
      : `${top.region} tăng nhiều nhất từ Quý 1 đến Quý 3.`;
    return {
      type: 'answer', title,
      text: tied.length > 1
        ? `Mỗi khu vực tăng ${pct} theo tỷ lệ phần trăm. Kết quả được tính từ doanh thu Quý 1 và Quý 3.`
        : `Doanh thu tăng từ ${fmt(top.q1)} lên ${fmt(top.q3)} triệu đồng, tương đương ${pct}.`,
      formula: tied.length > 1 ? null : `((${fmt(top.q3)} − ${fmt(top.q1)}) / ${fmt(top.q1)}) × 100 = ${pct}`,
      sourcePage: 3, sourceTitle: 'Biểu đồ doanh thu theo quý',
      facts: tied.length > 1 ? tied.map(r => ({ label: r.region, value: pct })) : [
        { label: 'Quý 1', value: `${fmt(top.q1)} triệu đồng` },
        { label: 'Quý 3', value: `${fmt(top.q3)} triệu đồng` },
      ],
    };
  }

  return {
    type: 'clarify', title: 'Cần làm rõ phạm vi câu hỏi.',
    text: 'Báo cáo hiện có doanh thu của ba khu vực theo bốn quý. Hãy nêu khu vực, kỳ báo cáo hoặc cách so sánh cụ thể để tránh chọn nhầm số liệu.',
    sourcePage: 3, sourceTitle: 'Biểu đồ doanh thu theo quý', facts: [],
  };
}

function fmt(n) {
  return Number(n).toLocaleString('vi-VN', { maximumFractionDigits: 2 });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  if (req.method === 'GET' && url.pathname === '/api/health') {
    return sendJson(res, 200, { ok: true, app: 'Ro So' });
  }
  if (req.method === 'POST' && url.pathname === '/api/answer') {
    try {
      const body = await readJson(req);
      return sendJson(res, 200, buildAnswer(body.question, body.rows));
    } catch (error) {
      return sendJson(res, 400, { type: 'error', title: 'Không thể xử lý yêu cầu.', text: error.message, facts: [] });
    }
  }

  const requestedPath = url.pathname === '/' ? '/index.html' : decodeURIComponent(url.pathname);
  const fullPath = path.resolve(PUBLIC, `.${requestedPath}`);
  if (!fullPath.startsWith(PUBLIC + path.sep) && fullPath !== path.join(PUBLIC, 'index.html')) {
    res.writeHead(403); return res.end('Forbidden');
  }

  fs.stat(fullPath, (err, stat) => {
    if (err || !stat.isFile()) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      return res.end('Not found');
    }
    res.writeHead(200, {
      'Content-Type': MIME[path.extname(fullPath).toLowerCase()] || 'application/octet-stream',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'same-origin',
    });
    fs.createReadStream(fullPath).pipe(res);
  });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Rõ Số đang chạy tại http://localhost:${PORT}`);
});
