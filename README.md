# Che thông tin CV (bản thử nghiệm trên máy)

Công cụ này giúp nhân sự ngân hàng che thông tin cá nhân trong CV. Ứng dụng chạy
trên máy Mac hoặc Windows của người dùng nhân sự. Tệp CV ở lại trên laptop đó.
Ứng dụng không gửi CV tới dịch vụ nào trên internet.

Trên Mac, nhân sự mở ứng dụng bằng cách bấm đúp `scripts/cv-masking.command`.
Lần đầu, nếu macOS chặn tệp, bấm chuột phải rồi chọn Open.

Trên Windows, lần đầu mở PowerShell trong thư mục dự án và chạy
`powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1`.
Lệnh này không dùng GNU Make. Nó tải Python 3.12 qua uv, tạo `backend\.venv`
chỉ cho dự án này, rồi dựng giao diện. Những lần sau, bấm đúp
`scripts\cv-masking.bat`.

Ứng dụng mở tại <http://127.0.0.1:8765>.

## Cách hoạt động

**1. Nhân sự mở ứng dụng**
Trình duyệt chỉ nói chuyện với laptop này (`127.0.0.1`).
Kỹ thuật: React và TypeScript cho màn hình. Python 3.12 và FastAPI cho máy chủ.

**2. Nhân sự tải lên một lô**
Tối đa 50 tệp PDF có lớp chữ hoặc Word (`.docx`). Hỗ trợ cả tiếng Việt và tiếng
Anh. Mức lương được che theo mặc định. Nhân sự có thể tắt mục đó cho cả lô.
Nhân sự có thể kéo thả tệp, chọn tệp, hoặc chọn thư mục. Nếu CV là liên kết trên
máy chủ tệp công ty, nhân sự dán các URL đó rồi bấm **Tải các liên kết**.
Laptop này tải các tệp và thêm vào lô. Liên kết phải mở được mà không cần đăng
nhập trên trình duyệt. Liên kết trên máy chủ khác không được tải; nhân sự lưu
các tệp đó, rồi chọn thư mục hoặc kéo thả. Máy chủ không gửi CV đi nơi khác, và
không lưu liên kết.
Kỹ thuật: màn hình gửi tệp đã chọn, hoặc liên kết đã dán, tới máy chủ trên máy
này. Máy chủ chỉ tải từ máy chủ tệp công ty đó. Máy chủ kiểm tra chứng chỉ của
máy chủ tệp. Trên Mac, máy chủ cũng tin các chứng chỉ đã cài trong Keychain.
Trên Windows, máy chủ tin các chứng chỉ đã cài trong Windows.
SQLite chỉ lưu trạng thái công việc và số lượng. SQLite không lưu chữ cá nhân
hay liên kết.

**3. Mỗi tệp được kiểm tra**
Ứng dụng từ chối sai loại tệp, tệp quá lớn, tệp quá nhiều trang, PDF quét ảnh,
và tệp Word có macro. Tệp gốc không bao giờ bị sửa.
Kỹ thuật: PyMuPDF cho PDF. `defusedxml` để đọc XML của Word an toàn.

**4. Chữ được lấy ra**
PDF và Word được chuyển thành cùng một dạng chữ nội bộ, nên bước sau giống nhau
cho cả hai định dạng.
Kỹ thuật: PyMuPDF cho PDF. XML của Word cho `.docx`.

**5. Thông tin cá nhân được tìm thấy**
Ứng dụng tìm tên, số điện thoại, email, số CCCD/CMND và hộ chiếu, địa chỉ, ngày
sinh, giới tính, tình trạng hôn nhân, quốc tịch, tôn giáo, dân tộc, sức khỏe,
thông tin gia đình, và tên người tham chiếu. Mức lương được tính khi công tắc
bật. Tên công ty, trường học, chức danh, ngày tháng, và liên kết cá nhân vẫn
nằm trong tệp.
Kỹ thuật: Microsoft Presidio để khớp mẫu, cộng quy tắc nhãn và mục tiếng Việt
và tiếng Anh của dự án. Không dùng AI đám mây và không dùng mô hình ngôn ngữ.

**6. Chữ đó được gỡ khỏi tệp**
Trong PDF, chữ bị xóa và thay bằng nhãn như `[NAME]`.
Trong Word, các ký tự bị xóa khỏi tệp và thay bằng cùng loại nhãn. Nội dung ẩn
(bình luận, siêu dữ liệu, và chữ vô hình) luôn được gỡ.
Kỹ thuật: che bằng PyMuPDF cho PDF. Sửa XML trực tiếp cho Word. PDF không bao
giờ được chuyển thành Word, và Word không bao giờ được chuyển thành PDF.

**7. Kết quả được kiểm tra lại**
Ứng dụng đọc tệp mới và tìm thông tin cá nhân lần thứ hai.
Nếu vẫn còn, nhân sự không tải tệp đó như bản hoàn tất.
Kỹ thuật: cùng bộ phát hiện, chạy lại độc lập.

**8. Nhân sự xem các tệp chưa chắc**
Tệp rõ thì sẵn sàng. Tệp chưa chắc thì chờ. Nhân sự xem PDF đã che trong ứng
dụng (Word chỉ tải xuống) rồi giữ hoặc xóa.
Kỹ thuật: một tiến trình nền trên máy, một tài liệu mỗi lần. Màn hình hiện
trạng thái và số lượng, không hiện chữ cá nhân gốc.

**9. Nhân sự tải kết quả**
PDF có thể xem trước. Word chỉ tải xuống. Một tệp, hoặc mọi tệp tải được dưới
dạng `output.zip` (kể cả dòng vẫn đang **Cần xem**), hoặc chỉ các bản đã che
trong một thư mục (`masked.zip`). Tệp không gỡ được nội dung ẩn bị bỏ ra.
`output.zip`: mỗi thư mục đặt theo tên tệp và chứa tệp gốc cùng `masked_`.
`masked.zip`: một thư mục, chỉ các tệp `masked_`. CV chọn, kéo thả, hoặc tải
từ liên kết trong tab này đều có tệp gốc trong `output.zip`. Chỉ chia sẻ các
bản `masked_` đã kiểm. Tên gốc ở lại trong tab trình duyệt này; chúng không
được lưu trên máy chủ.

**10. Nhân sự xóa kết quả khi xong**
Tệp ở trên laptop cho đến khi nhân sự thoát ứng dụng và xóa thư mục `data/`.
Tệp làm việc tạm được gỡ sau mỗi công việc.

## Giới hạn

- Kết quả đã được che. Tên công ty, trường học, chức danh, ngày tháng, và liên
  kết cá nhân vẫn còn, nên người đọc vẫn có thể nhận ra người đó. Đây không phải
  ẩn danh hoàn toàn.
- Ảnh, và mọi chữ trong ảnh, vẫn nằm trong tệp.
- Ứng dụng chỉ nhận PDF có lớp chữ và `.docx`. CV quét ảnh, tệp `.doc` cũ, và
  tệp Word có macro bị từ chối.
- Ứng dụng không bảo vệ laptop khỏi phần mềm độc hại, tiện ích trình duyệt, hoặc
  bản sao lưu. Dán CV vào công cụ AI như Cursor sẽ gửi chữ đó ra khỏi laptop.
- Trên Windows, thư mục `data/` nên nằm trong hồ sơ người dùng. Windows không
  có cùng kiểu khóa quyền thư mục như Mac. Ứng dụng vẫn từ chối symlink và
  junction.

## Phát triển (macOS)

Cần [uv](https://docs.astral.sh/uv/) từ 0.10.6 trở lên, Node.js từ 24 trở lên
kèm npm, và GNU Make. Không cần cài Python cho cả máy. `make install` tải
Python 3.12 qua uv và tạo `backend/.venv` chỉ cho dự án này.

```bash
make setup               # lần đầu trên laptop: venv, thư viện, rồi giao diện bản chạy
make install             # tạo backend/.venv, khóa phiên bản thư viện, Playwright Chromium, file guard
make build               # giao diện bản chạy vào gói Python
make dev                 # backend 127.0.0.1:8765, frontend 127.0.0.1:5173
make check               # file guard + lint + kiểm tra kiểu + build giao diện + kiểm thử
make eval                # số liệu tổng hợp chỉ siêu dữ liệu (không dùng CV thật)
```

Mở <http://127.0.0.1:5173> khi đang phát triển. Trình khởi chạy `.command` phục
vụ màn hình từ <http://127.0.0.1:8765> và không khởi động Node.

Cả hai máy chủ chỉ lắng nghe trên `127.0.0.1`. Đặt `CV_MASKING_PORT` để đổi
cổng backend (proxy của Vite kỳ vọng 8765).

Windows không dùng Makefile. Cài và chạy bằng hai tệp trong `scripts/`:
`setup-windows.ps1` một lần, rồi `cv-masking.bat`. Cần uv từ 0.10.6 và Node.js
từ 24, không cần GNU Make và không cần cài Python cho cả máy.
