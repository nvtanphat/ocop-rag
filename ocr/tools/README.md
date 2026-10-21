# Công cụ hỗ trợ OCR OCOP

Thư mục này chứa các script chẩn đoán và kiểm chứng độc lập cho pipeline OCR:

1. `run_sequential_check.py`: Kiểm chứng tính tất định giữa chạy 1 worker tuần tự và 3 worker song song trên 5 trang chuẩn.
2. `evaluate_connected_rules.py`: Chẩn đoán cấu trúc raster bảng và ranh ngang/dọc trên các trang biểu mẫu điểm.

Sử dụng môi trường OCR độc lập từ repo:
```powershell
python -m ocr.tools.run_sequential_check
```
