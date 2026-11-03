# Rule chung

Mỗi file `*.md` trong thư mục này (trừ README.md) là rule áp dụng cho **mọi task,
mọi dự án**. Ví dụ: `security.md`, `money.md`, `testing.md`.

- Viết như quy định bắt buộc, ngắn, kiểm tra được: "Tiền là số nguyên đồng,
  không dùng float", không phải "nên viết code sạch".
- Rule viết dạng *phải*/*không bao giờ* (must/never): reviewer được dặn tính vi
  phạm ít nhất là `major`, nên flow sẽ quay lại sửa.
- Rule riêng của một dự án đặt trong repo của dự án đó (`AGENTS.md`, `CLAUDE.md`
  hoặc file truyền bằng `--rules`), không đặt ở đây.

Rule được khóa (seal) vào task lúc tạo. Sửa file ở đây chỉ áp dụng cho task mới.
