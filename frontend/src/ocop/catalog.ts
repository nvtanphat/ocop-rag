import type { Source } from './api'

export const sourceCategory: Record<string, string> = {
  central_current: 'OCOP hiện hành', ocop_current: 'OCOP hiện hành', ocop_2026: 'OCOP hiện hành',
  central_historical: 'OCOP lịch sử', ocop_historical: 'OCOP lịch sử',
  food_safety_law: 'An toàn thực phẩm', food_safety_decree: 'An toàn thực phẩm',
  labeling_decree: 'Ghi nhãn hàng hóa', labeling_amendment: 'Ghi nhãn hàng hóa',
  cooperative_law: 'Luật hợp tác xã', recognition_decision: 'Công nhận sản phẩm',
  local_guidance: 'Hướng dẫn địa phương',
}
export function categoryOf(source?: Source | null): string {
  if (!source || !source.source_id) return 'Văn bản liên quan'
  if (source.source_id.startsWith('VN.OCOP.QD26')) return 'OCOP hiện hành'
  if (source.source_id.startsWith('VN.OCOP.QD148')) return 'OCOP lịch sử'
  return sourceCategory[source.source_kind] || 'Văn bản liên quan'
}
export function sourceTitle(source?: Source | null): string {
  if (!source || !source.source_id) return 'Bộ tiêu chí và quy trình đánh giá, phân hạng sản phẩm OCOP'
  if (source.source_id === 'VN.OCOP.QD26.2026') return 'Bộ tiêu chí và quy trình đánh giá OCOP 2026'
  if (source.source_id === 'VN.OCOP.QD148.2023') return 'Bộ tiêu chí OCOP 2023'
  if (source.source_id === 'VN.OCOP.QD1489.2025') return 'Sửa đổi bộ tiêu chí OCOP 2025'
  if (source.source_id.includes('THANHSEN')) return 'Thông tin triển khai OCOP tại Thành Sen'
  if (source.source_id.includes('HUE.QD797')) return 'Kết quả công nhận OCOP tại Huế'
  if (source.source_id.includes('HAIPHONG.QD525')) return 'Kết quả công nhận OCOP tại Hải Phòng'
  if (source.document_number) return `Văn bản số ${source.document_number}`
  return (source.filename || '').replace(/\.pdf$/i, '') || 'Văn bản OCOP'
}
export const samplePrompts = [
  { title: 'Phân loại sản phẩm', detail: 'Sản phẩm mật ong thuộc nhóm OCOP nào?', tag: 'Nhóm sản phẩm' },
  { title: 'Tra cứu bộ tiêu chí', detail: 'Tiêu chí chấm điểm rau, củ, quả, hạt tươi theo QĐ26/2026?', tag: 'Tiêu chí' },
  { title: 'Hồ sơ và biểu mẫu', detail: 'Mẫu số 01 đăng ký đánh giá OCOP cần điền thông tin gì?', tag: 'Biểu mẫu' },
  { title: 'Quy định theo thời gian', detail: 'Quy định chuyển tiếp giữa QĐ148/2023 và QĐ26/2026 là gì?', tag: 'Hiệu lực' },
]
