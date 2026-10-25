import { IMAGES } from '../assets'
import type { DocInfo, SrcItem, DocRecord, CritRecord, ProdRecord } from './types'

export const INITIAL_DOCS: Record<string, DocInfo> = {
  '148': { title: 'Quyết định 148/QĐ-TTg', sub: 'Ban hành Bộ tiêu chí và quy trình đánh giá, phân hạng sản phẩm OCOP' },
  '26': { title: 'Quyết định 26/QĐ-BNN-VPĐP', sub: 'Hướng dẫn đánh giá, phân hạng sản phẩm OCOP' },
  'hd': { title: 'Hướng dẫn thực hiện Chương trình OCOP', sub: 'Bộ Nông nghiệp và Phát triển nông thôn' },
  'dp': { title: 'Văn bản hướng dẫn của địa phương (ví dụ)', sub: 'UBND tỉnh, Sở Nông nghiệp và PTNT' },
}

export const INITIAL_SRC: Record<string, SrcItem> = {
  S1: { doc: '148', page: 18, bbox: '[120, 340, 520, 410]', total: 42, kind: 'pdf', name: 'Quyết định 148/QĐ-TTg', sub: 'Phê duyệt Bộ tiêu chí và quy trình đánh giá, phân hạng sản phẩm OCOP' },
  S2: { doc: '26', page: 5, bbox: '[96, 212, 508, 268]', total: 18, kind: 'pdf', name: 'Quyết định 26/QĐ-BNN-VPĐP', sub: 'Hướng dẫn đánh giá, phân hạng sản phẩm OCOP' },
  S3: { doc: 'hd', page: 5, bbox: '[96, 200, 508, 260]', total: 30, kind: 'sheet', name: 'Hướng dẫn thực hiện Chương trình OCOP', sub: 'Bộ Nông nghiệp và Phát triển nông thôn' },
  S4: { doc: 'dp', page: 12, bbox: '[96, 220, 508, 280]', total: 24, kind: 'doc', name: 'Văn bản hướng dẫn của địa phương (ví dụ)', sub: 'UBND tỉnh, Sở Nông nghiệp và PTNT' },
  TT: { doc: 'TT', page: 1, bbox: '[0, 0, 0, 0]', total: 16, kind: 'doc', name: 'Thông tư 02/2024/TT-BNNPTNT', sub: 'Hướng dẫn đánh giá, phân hạng sản phẩm OCOP' },
  KH: { doc: 'KH', page: 1, bbox: '[0, 0, 0, 0]', total: 22, kind: 'doc', name: 'Kế hoạch OCOP giai đoạn 2021–2025', sub: 'UBND Tỉnh' },
}

export const INITIAL_LIB: DocRecord[] = [
  { id: '148', code: '148/QĐ-TTg', badge: 'QĐ', col: '#e8453c', desc: 'Ban hành Bộ tiêu chí và quy trình đánh giá, phân hạng sản phẩm OCOP', org: 'Thủ tướng Chính phủ', scope: 'Toàn quốc', pages: 42, cat: 'LN', year: 2023, src: 'S1' },
  { id: '26', code: '26/QĐ-BNN-VPĐP', badge: '26', col: '#2a6fdb', desc: 'Hướng dẫn đánh giá, phân hạng sản phẩm OCOP', org: 'Bộ Nông nghiệp & PTNT', scope: 'Toàn quốc', pages: 18, cat: 'LN', year: 2023, src: 'S2' },
  { id: '1489', code: '1489/QĐ-TTg', badge: 'QĐ', col: '#e8453c', desc: 'Phê duyệt Chương trình giai đoạn 2021–2025', org: 'Thủ tướng Chính phủ', scope: 'Toàn quốc', pages: 35, cat: 'LN', year: 2021 },
  { id: '15-2018', code: '15/2018/NĐ-CP', badge: '15', col: '#8a5bd6', desc: 'Quy định chi tiết thi hành một số điều của Luật ATTP', org: 'Chính phủ', scope: 'Toàn quốc', pages: 48, cat: 'QC', year: 2018 },
  { id: '43-2017', code: '43/2017/NĐ-CP', badge: '43', col: '#8a5bd6', desc: 'Nhãn hàng hóa', org: 'Chính phủ', scope: 'Toàn quốc', pages: 32, cat: 'QC', year: 2017 },
  { id: 'attp', code: 'Luật ATTP 2010', badge: '15', col: '#13a06a', desc: 'Luật An toàn thực phẩm', org: 'Quốc hội', scope: 'Toàn quốc', pages: 64, cat: 'QC', year: 2010 },
  { id: 'htx', code: 'Luật HTX 2023', badge: '19', col: '#13a06a', desc: 'Luật Hợp tác xã', org: 'Quốc hội', scope: 'Toàn quốc', pages: 72, cat: 'LN', year: 2023 },
  { id: '525', code: 'QĐ 525/QĐ-UBND', badge: 'QĐ', col: '#f09a1a', desc: 'Công nhận sản phẩm OCOP TP. Hải Phòng', org: 'UBND TP. Hải Phòng', scope: 'TP. Hải Phòng', pages: 18, cat: 'DP', year: 2023 },
  { id: 'tt-mau', code: 'Thông tư hướng dẫn OCOP', badge: 'TT', col: '#2a6fdb', desc: 'Hướng dẫn thực hiện Chương trình OCOP (văn bản mẫu)', org: 'Bộ Nông nghiệp & PTNT', scope: 'Toàn quốc', pages: 26, cat: 'LN', year: 2022 },
  { id: 'dp-hue-1', code: 'QĐ 07/QĐ-UBND', badge: 'QĐ', col: '#f09a1a', desc: 'Quy chế đánh giá sản phẩm OCOP cấp tỉnh (văn bản mẫu)', org: 'UBND tỉnh Thừa Thiên Huế', scope: 'Thừa Thiên Huế', pages: 22, cat: 'DP', year: 2022 },
  { id: 'dp-hue-2', code: 'QĐ 12/QĐ-UBND', badge: 'QĐ', col: '#f09a1a', desc: 'Công nhận sản phẩm OCOP tỉnh Thừa Thiên Huế (văn bản mẫu)', org: 'UBND tỉnh Thừa Thiên Huế', scope: 'Thừa Thiên Huế', pages: 16, cat: 'DP', year: 2024 },
  { id: 'dp-hp-2', code: 'QĐ 31/QĐ-UBND', badge: 'QĐ', col: '#f09a1a', desc: 'Kế hoạch thực hiện OCOP TP. Hải Phòng (văn bản mẫu)', org: 'UBND TP. Hải Phòng', scope: 'TP. Hải Phòng', pages: 20, cat: 'DP', year: 2024 },
]

export const QUICK_QUESTIONS = [
  'UBND cấp huyện có quyền công nhận 4 sao không?',
  'Hồ sơ đề xuất đánh giá OCOP gồm những gì?',
  'Tiêu chuẩn an toàn thực phẩm cho OCOP 4 sao?',
  'Sản phẩm OCOP 4 sao phải đáp ứng những tiêu chí gì?',
]

export const FOLLOW_QUESTIONS: Array<[string, string]> = [
  ['Tóm tắt ngắn gọn', '<path d="M5 6h14M5 12h14M5 18h8"/>'],
  ['Giải thích chi tiết hơn', '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16v.5"/>'],
  ['So sánh thẩm quyền các cấp', '<path d="M7 7h12l-3-3M17 17H5l3 3"/>'],
  ['Tìm thêm văn bản liên quan', '<circle cx="11" cy="11" r="7"/><path d="M16 16l5 5"/>'],
]

export const REL_DOCS = [
  ['S1', 'Quyết định 148/QĐ-TTg', 'Bộ tiêu chí OCOP', '2023'],
  ['S3', 'Hướng dẫn thực hiện OCOP', 'Bộ NN&PTNT', '2023'],
  ['TT', 'Thông tư 02/2024/TT-BNNPTNT', 'Hướng dẫn đánh giá, phân hạng', '2024'],
  ['KH', 'Kế hoạch OCOP giai đoạn 2021–2025', 'UBND Tỉnh', '2022'],
]

export const PROD_CAROUSEL: Array<[string, string, string, string]> = [
  ['Mật ong rừng', '4.2', IMAGES.prodHoney, 'linear-gradient(160deg,#fbd98a,#e9a23b)'],
  ['Cà phê đặc sản', '4.1', IMAGES.prodCoffee, 'linear-gradient(160deg,#d9c3a5,#a77a4e)'],
  ['Combo quà tặng OCOP', '4.0', IMAGES.prodGift, 'linear-gradient(160deg,#cfe8c6,#7fb26a)'],
  ['Nước mắm Cát Hải', '4.3', '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M10 2h4v3h-1v2h1.5A1.5 1.5 0 0116 8.5V21a1 1 0 01-1 1H9a1 1 0 01-1-1V8.5A1.5 1.5 0 019.5 7H11V5h-1z"/></svg>', 'linear-gradient(160deg,#f3b86a,#d98521)'],
  ['Rau an toàn Trường Thọ', '4.0', '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M5 19C5 10 10 5 20 4c0 10-5 15-14 15z"/></svg>', 'linear-gradient(160deg,#a8dca0,#46a05a)'],
]

export const KINDS_MAP: Record<string, [string, string]> = {
  bottle: ['#f6c46a', '#d98b1f'],
  tea: ['#a8dba0', '#4a9a5a'],
  rice: ['#f3e7c2', '#cdb26a'],
  fish: ['#9fd3ea', '#3a86b4'],
  jar: ['#f2b18a', '#c4623b'],
  leaf: ['#b6e5a0', '#3f9a3f'],
  noodle: ['#f4dfb0', '#c99a4a'],
  hat: ['#e8d2a0', '#a8793a'],
  oil: ['#cfe3a0', '#6d9a2a'],
  sweet: ['#f5c6d0', '#c8607a'],
  honey: ['#ffe2a0', '#e9a82f'],
  coffee: ['#d9b58a', '#7a4a28'],
  gift: ['#e3d9f5', '#8a6bd0'],
}

// Generate base criteria list
export function generateBaseCriteria(): Record<string, CritRecord[]> {
  const BASE: Array<[string, number]> = [
    ['Có giấy chứng nhận cơ sở đủ điều kiện an toàn thực phẩm hoặc chứng chỉ tương đương (ISO, HACCP, ...)', 18],
    ['Chất lượng cảm quan, dinh dưỡng, thành phần ...', 18],
    ['Có truy xuất nguồn gốc', 18],
    ['Đáp ứng quy chuẩn, tiêu chuẩn liên quan', 18],
    ['Bảo vệ môi trường trong sản xuất', 19],
    ['Sử dụng nguyên liệu địa phương', 19],
    ['Bao bì, nhãn mác, thông tin truy xuất đầy đủ', 21],
    ['Khả năng mở rộng thị trường', 22],
    ['Có kế hoạch phát triển sản phẩm', 22],
    ['Tham gia liên kết chuỗi giá trị', 23],
  ]
  const MORE = [
    'Quy mô sản xuất và sản lượng ổn định',
    'Hồ sơ đăng ký nhãn hiệu, sở hữu trí tuệ',
    'Quy trình sản xuất được chuẩn hóa',
    'Kênh phân phối trực tuyến và truyền thông',
    'Câu chuyện sản phẩm và bản sắc địa phương',
    'Tạo việc làm cho lao động địa phương',
    'Chia sẻ lợi ích với cộng đồng',
    'Xử lý chất thải, tiết kiệm năng lượng',
    'Đào tạo, tập huấn cho thành viên',
    'Kiểm nghiệm định kỳ chất lượng',
    'Thiết kế bao bì thân thiện môi trường',
    'Hợp đồng tiêu thụ ổn định',
    'Giá bán và hiệu quả kinh tế',
    'Bảo quản và vận chuyển đảm bảo chất lượng',
    'Đăng ký mã số vùng trồng, cơ sở',
    'Tuân thủ quy định ghi nhãn dinh dưỡng',
    'Quản lý khách hàng và phản hồi',
    'Ứng dụng công nghệ số trong bán hàng',
    'Gắn kết du lịch và trải nghiệm',
    'Bảo tồn nghề truyền thống',
  ]
  const cr148: CritRecord[] = []
  for (let i = 0; i < 150; i++) {
    const t = i < 10 ? BASE[i][0] : MORE[(i - 10) % MORE.length] + ' (mục ' + (i + 1) + ')'
    const pg = i < 10 ? BASE[i][1] : Math.min(41, 24 + Math.floor((i - 10) / 8))
    cr148.push({ n: i + 1, t, doc: 'QĐ 148/QĐ-TTg', src: 'S1', page: pg })
  }
  const cr26: CritRecord[] = []
  for (let j = 0; j < 36; j++) {
    const t = (j < 4 ? BASE[j][0] : MORE[(j + 3) % MORE.length]) + (j < 4 ? '' : ' (mục ' + (j + 1) + ')')
    cr26.push({ n: j + 1, t, doc: 'QĐ 26/QĐ-BNN-VPĐP', src: 'S2', page: 3 + Math.floor(j / 3) })
  }
  return { '148': cr148, '26': cr26 }
}

// Generate base products list
export function generateBaseProducts(): ProdRecord[] {
  const BASEP: Array<[string, string, string, number, string]> = [
    ['Nước mắm Cát Hải', 'HTX Nước mắm Cát Hải', 'Hải Phòng', 4, 'bottle'],
    ['Trà sen Huế', 'HTX Trà sen Huế', 'Thừa Thiên Huế', 4, 'tea'],
    ['Gạo nếp cải hoa vàng', 'Hộ kinh doanh Nguyễn Văn A', 'Hải Phòng', 3, 'rice'],
    ['Chả cá Thu', 'Cơ sở sản xuất Bích Ngọc', 'Hải Phòng', 4, 'fish'],
    ['Mật ong rừng Cát Bà', 'HTX Ong mật Cát Bà', 'Hải Phòng', 5, 'honey'],
    ['Mắm tôm chua Huế', 'Cơ sở sản xuất Tâm Đức', 'Thừa Thiên Huế', 3, 'jar'],
    ['Rau an toàn Trường Thọ', 'HTX Nông nghiệp Trường Thọ', 'Thừa Thiên Huế', 3, 'leaf'],
    ['Bánh đa cua Hải Phòng', 'Cơ sở sản xuất Hương Việt', 'Hải Phòng', 3, 'noodle'],
    ['Cà phê rang xay Hải Vân', 'Công ty TNHH Hải Vân', 'Thừa Thiên Huế', 4, 'coffee'],
    ['Tinh dầu tràm Huế', 'HTX Tinh dầu Huế', 'Thừa Thiên Huế', 4, 'oil'],
    ['Nón lá Huế', 'Làng nghề Phú Cam', 'Thừa Thiên Huế', 4, 'hat'],
    ['Mè xửng Huế', 'Cơ sở Thanh Hà', 'Thừa Thiên Huế', 3, 'sweet'],
    ['Cá cơm khô Cát Hải', 'HTX Thủy sản Cát Hải', 'Hải Phòng', 3, 'fish'],
    ['Hộp quà đặc sản Hải Phòng', 'Công ty Đặc sản Biển', 'Hải Phòng', 5, 'gift'],
    ['Ruốc Huế', 'Cơ sở Hương Giang', 'Thừa Thiên Huế', 4, 'jar'],
    ['Bột sắn dây Thủy Phù', 'HTX Sắn dây Thủy Phù', 'Thừa Thiên Huế', 5, 'rice'],
  ]
  const SUF = ['', ' loại đặc biệt', ' loại 1', ' gói 500g', ' hộp quà', ' loại thượng hạng', ' bản tiêu chuẩn', ' bản nhỏ']
  const prods: ProdRecord[] = []
  for (let k = 0; k < 120; k++) {
    const b = BASEP[k % 16]
    const r = Math.floor(k / 16)
    const stars = r === 0 ? b[3] : Math.max(3, Math.min(5, b[3] + ((k % 3) - 1)))
    prods.push({
      id: k + 1,
      name: b[0] + SUF[r % 8],
      owner: b[1],
      loc: b[2],
      stars,
      kind: b[4],
      code: 'QĐ ' + (500 + ((k * 37) % 900)) + '/QĐ-UBND',
    })
  }
  return prods
}
