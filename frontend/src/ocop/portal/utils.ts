// Helper: Escape HTML
export function esc(s: unknown): string {
  return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] || c))
}

// Helper: Normalize Vietnamese text for search
export function norm(s: unknown): string {
  return String(s ?? '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
}

// Helper: Format Current Time HH:MM
export function nowTime(): string {
  const d = new Date()
  return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2)
}

// Format Markdown to styled HTML
export function formatMd(text: string): string {
  if (!text) return ''
  let s = esc(text)
  s = s.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
  s = s.replace(/\*(.*?)\*/g, '<i>$1</i>')
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
  const paras = s.split(/\n\s*\n/)
  const res: string[] = []
  for (const para of paras) {
    const lines = para.trim().split('\n')
    if (!lines.length || !lines[0]) continue
    if (lines.every((l) => /^\d+\.\s+/.test(l.trim()))) {
      const ol = lines
        .map((l) => {
          const m = l.trim().match(/^(\d+)\.\s+(.*)$/)
          return m ? `<li><span class="n">${m[1]}.</span><div>${m[2]}</div></li>` : `<li>${l}</li>`
        })
        .join('')
      res.push(`<ol>${ol}</ol>`)
    } else if (lines.every((l) => /^[-*•]\s+/.test(l.trim()))) {
      const ul = lines.map((l) => `<li>${l.trim().replace(/^[-*•]\s+/, '')}</li>`).join('')
      res.push(`<ul>${ul}</ul>`)
    } else {
      res.push(`<p>${lines.join('<br>')}</p>`)
    }
  }
  return res.join('')
}

export const CHECK_SVG =
  '<svg width="14" height="14" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="#18a56e"/><path d="M7 12.5l3.2 3L17 9" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/></svg>'

export const PAGE18_HTML = `<div class="c"><h5>Phụ lục I</h5><h5>BỘ TIÊU CHÍ ĐÁNH GIÁ, PHÂN HẠNG SẢN PHẨM OCOP</h5><p class="it">(Kèm theo Quyết định số 148/QĐ-TTg ngày 24 tháng 02 năm 2023<br>của Thủ tướng Chính phủ)</p></div><h6>I. Nhóm tiêu chí chất lượng sản phẩm (40 điểm)</h6><div class="tblw" id="tblw"><table class="tbl"><thead><tr><th style="width:11%">STT</th><th>Tiêu chí thành phần</th><th style="width:22%">Chuẩn yêu cầu</th><th style="width:15%">Điểm tối đa</th></tr></thead><tbody><tr class="hit"><td>1.1</td><td>Có giấy chứng nhận cơ sở đủ điều kiện an toàn thực phẩm hoặc chứng chỉ tương đương (ISO, HACCP, ...)</td><td>Có</td><td>10</td></tr><tr><td>1.2</td><td>Chất lượng cảm quan, dinh dưỡng, thành phần ...</td><td>Đạt yêu cầu</td><td>10</td></tr><tr><td>1.3</td><td>Có truy xuất nguồn gốc</td><td>Có</td><td>5</td></tr><tr><td>1.4</td><td>Đáp ứng quy chuẩn, tiêu chuẩn liên quan</td><td>Đạt yêu cầu</td><td>5</td></tr><tr><td>1.5</td><td>Bảo vệ môi trường trong sản xuất</td><td>Đạt yêu cầu</td><td>5</td></tr><tr><td>1.6</td><td>Sử dụng nguyên liệu địa phương</td><td>Ưu tiên</td><td>5</td></tr></tbody></table></div>`
