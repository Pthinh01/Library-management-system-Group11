# Library Management System — Group 11

Bản hiện tại chạy bằng một tệp Source_code.py, dùng SQLite và giao diện web theo thiết kế Figma. Không cần MySQL.

## Chạy chương trình

    python Source_code.py

Mở [http://127.0.0.1:8765](http://127.0.0.1:8765). Giữ Terminal đang chạy; nhấn Ctrl+C để dừng.

Nếu sử dụng chức năng sao lưu mã hóa, cài thêm:

    python -m pip install cryptography

Tài khoản minh họa: thinh.nguyen, phucthinh hoặc admin; mật khẩu LibraryDemo!2026.

## Dữ liệu

Chương trình tự tạo library.sqlite3 cạnh mã nguồn. Giữ tệp này để dùng lại dữ liệu sau khi tắt hoặc chuyển máy. Tệp dữ liệu đang sử dụng không được đưa lên kho mã nguồn. Giao diện, ảnh và font đã nhúng trong Source_code.py.

## Codespaces

Chọn Code → Codespaces, mở Terminal và chạy:

    python Source_code.py --host 0.0.0.0 --port 8765

Mở cổng 8765 trong mục Ports. Có thể thay số cổng nếu cổng cũ đang được dùng.

## Docker

    docker build -t library-group11 .
    docker run -d --name library-group11 -p 127.0.0.1:8766:8765 library-group11

Mở [http://127.0.0.1:8766](http://127.0.0.1:8766). Tạm dừng bằng docker stop library-group11, chạy lại bằng docker start library-group11. Khi chạy Docker, SQLite nằm trong container.

## Các tệp bài nộp

- Source_code.py: toàn bộ mã Python, cơ sở dữ liệu và giao diện.
- Testing Document.xlsx: tài liệu kiểm thử rút gọn, 40 test case theo 5 cột mẫu.
- Dockerfile: cấu hình đóng gói.
- task assignment.docx: phân công công việc của nhóm.
- containing evidence of tool usage.docx: tài liệu minh chứng công cụ.

Các tệp hỗ trợ từ phiên bản trước vẫn còn trong lịch sử và kho; điểm khởi chạy của bản hiện tại là Source_code.py.
