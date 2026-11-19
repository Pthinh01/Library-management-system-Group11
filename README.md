# Library Management System — Group 11

Chương trình quản lý thư viện bằng Python, SQLite và giao diện web theo thiết kế Figma.

## Các tệp chính

| Tệp | Nội dung |
|---|---|
| `app.py` | Chạy chương trình, nhận yêu cầu từ giao diện |
| `Source_code.py` | Các lớp đối tượng, chức năng mượn/trả, đặt trước, gia hạn và thu phạt |
| `database.py` | Tạo bảng và xử lý dữ liệu SQLite |
| `Testing Document.xlsx` | 158 test case theo mẫu của môn học |
| `run_tests.py` | Chạy bộ kiểm thử tự động |
| `requirements.txt` | Thư viện cần cài |
| `Dockerfile` | Đóng gói và chạy bằng Docker |
| `static/` | Giao diện, hình ảnh và font chữ |
| `tests/` | Mã kiểm thử |

## Chạy chương trình

Mở Terminal tại thư mục chứa `app.py`, chạy:

```bash
python -m pip install -r requirements.txt
python app.py
```

Mở **http://127.0.0.1:8765**. Giữ Terminal đang chạy khi sử dụng.

## Đăng nhập minh họa

| Vai trò | Tên đăng nhập | Mật khẩu |
|---|---|---|
| Thủ thư | thinh.nguyen | LibraryDemo!2026 |
| Độc giả | phucthinh | LibraryDemo!2026 |
| Quản trị viên | admin | LibraryDemo!2026 |

## Chạy trên GitHub Codespaces

Chọn **Code → Codespaces**, mở Terminal rồi chạy:

```bash
python -m pip install -r requirements.txt
python app.py --host 0.0.0.0 --port 8765
```

Vào **Ports → 8765 → Open in Browser**. Nếu dùng cổng khác, thay `8765` trong lệnh và mở đúng cổng đó.

## Chạy bằng Docker

```bash
docker build -t library-group11 .
docker run -d --name library-group11 -p 127.0.0.1:8766:8765 -v library_group11_data:/app/data library-group11
```

Mở **http://127.0.0.1:8766**. Dừng bằng `docker stop library-group11`; chạy lại bằng `docker start library-group11`.

## Kiểm thử

```bash
python run_tests.py
```

Kết quả ghi trong `test-results/results.json`. Test dùng DB tạm riêng. Tài liệu kiểm thử giữ nguyên 5 cột của mẫu được cấp; test chưa chạy đầy đủ không được xem là đã đạt.

## Dữ liệu và sao lưu

Dữ liệu lưu tại `data/library.sqlite3` và được giữ sau khi tắt ứng dụng. Dữ liệu minh họa chỉ tạo khi DB chưa có tài khoản. Khôi phục một bản sao lưu đã tải từ giao diện quản trị:

```bash
python app.py --restore library-backup.lmb --destination data/restored.sqlite3
```

Chương trình hỏi mật khẩu bản sao lưu và chỉ cho khôi phục sang DB mới.
