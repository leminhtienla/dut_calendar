# Changelog

Định dạng theo [Keep a Changelog](https://keepachangelog.com/vi/1.0.0/).
Phiên bản theo [Semantic Versioning](https://semver.org/lang/vi/).

## [Unreleased]

## [1.5.0] - 2026-08-04

### Thêm mới
- **Sensor đếm sự kiện** — mỗi loại (`dut_lichtuan`, `dut_coithi`, `dut_deadline_diem`) đều có thêm 3 sensor: `Hôm nay`, `Ngày mai`, `Tháng này`.
- **Calendar `Nhập điểm`** cho `dut_deadline_diem` (trước đây loại này không có Calendar) — mỗi mốc hạn (giữa kỳ, thành phần, thi chung, đính chính) thành 1 sự kiện cả ngày, xem trực quan trên Lovelace.
- Hàm `build_deadline_events()` mới trong `parser_exam.py` (thuần Python, test độc lập được), gộp phẳng mọi mốc hạn thành danh sách sự kiện có ngày cụ thể — dùng chung cho Calendar mới và các sensor đếm.

### Xác nhận hành vi
- Tên Calendar đã rút gọn đúng theo yêu cầu: `Lịch tuần`, `Coi thi`, `Nhập điểm`.
- Đổi Options vẫn tự `async_reload` toàn bộ entry như trước — sensor/calendar tự cập nhật ngay, không cần thao tác thêm.

## [1.4.0] - 2026-08-04

### Thêm mới
- **Dùng chung tài khoản giữa `dut_coithi` và `dut_deadline_diem`.** Khi thêm entry thứ 2 (loại còn lại) và đã có ≥1 tài khoản cấu hình sẵn, config flow cho chọn dùng lại tài khoản đó (bước mới trước bước đăng nhập) thay vì bắt gõ lại mật khẩu — mỗi entry vẫn giữ phiên đăng nhập độc lập với nhau như trước, chỉ là khỏi phải nhập lại thông tin.
- Xác nhận: **sửa lại học kỳ sau khi đã thêm entry** vẫn làm được qua Options — đã có từ v1.3.0, không đổi gì thêm ở bản này.

## [1.3.0] - 2026-08-04

### Thêm mới
- **Chọn học kỳ bằng tên thật thay vì gõ mã số.** `dut_coithi`/`dut_deadline_diem` giờ cài đặt qua 2 bước:
  1. Đăng nhập (xác thực thật).
  2. Chọn học kỳ từ danh sách lấy trực tiếp từ dropdown thật của cổng (vd "Học kỳ 2 năm học 2025-2026"), hỗ trợ chọn nhiều học kỳ cùng lúc, học kỳ hiện tại được chọn sẵn.
- Áp dụng tương tự cho Options Flow khi sửa cấu hình sau này.
- `parse_hoc_ky_options()` mới trong `parser_exam.py`, đọc dropdown `#DKCT_cboHocKy` có sẵn trên `PageCNDKCoiThi.aspx`.

## [1.2.0] - 2026-08-04

### Sửa lỗi
- **Phát hiện quan trọng (nhờ người dùng đối chiếu ảnh chụp thật):** hạn điểm giữa kỳ/thành phần thực ra **khác nhau theo từng lớp học phần**, không phải chung cho cả học kỳ như bản 1.1.0 giả định. Hạn điểm cuối kỳ thi chung (theo ca thi) thì vẫn đúng như cũ.

### Thêm mới
- `dut_deadline_diem` giờ lấy **2 loại hạn riêng biệt**:
  - Hạn điểm cuối kỳ thi chung — theo ca thi (giữ nguyên cơ chế cũ).
  - Hạn điểm giữa kỳ/thành phần — theo **từng lớp học phần** (mới): tự động lấy danh sách lớp phụ trách (`ctrlLopHP`), tra hạn riêng từng lớp (`ctrlListHP`), không cần cấu hình thêm.
- Sensor `Hạn nộp điểm`: state giờ là mốc gần nhất sắp tới trong TẤT CẢ các loại hạn (thi chung + từng lớp), attributes chi tiết đầy đủ theo từng lớp.
- Vẫn giữ nguyên cam kết an toàn: chỉ đọc phần header ngày tháng, không đụng bảng điểm/tên/mã số sinh viên ở bất kỳ API nào.

## [1.1.0] - 2026-08-03

### Thay đổi
- **Tách "Lịch coi thi & hạn nộp điểm" (loại `exam_login`) thành 2 loại riêng biệt**, đổi tên gọn 3 loại nguồn:
  - `public_schedule` → **`dut_lichtuan`**
  - `exam_login` (gộp) → tách thành **`dut_coithi`** (chỉ lịch coi thi) và **`dut_deadline_diem`** (chỉ hạn nộp điểm)
- Mỗi loại giờ là 1 thiết bị (device) riêng, tên rõ ràng: "DUT Calendar - Coi thi" vs "DUT Calendar - Hạn nộp điểm" (trước đây gộp chung 1 thiết bị).
- `dut_coithi` không còn gọi API hạn nộp điểm (giảm request thừa); `dut_deadline_diem` không tạo Calendar (hạn nộp điểm là mốc ngày, không phải sự kiện có giờ).
- Menu chọn nguồn khi thêm tích hợp giờ có **3 lựa chọn** thay vì 2.
- Config entry cũ dạng `exam_login` (nếu có) không tự chuyển đổi — cần xoá và thêm lại theo loại mới.

## [1.0.0] - 2026-08-03

### Thay đổi
- **Gộp 2 integration riêng biệt** (`lichtuan_dut` v1.4.0 và `cb_dut`
  v1.1.0) thành 1 component duy nhất: **`dut_calendar`**.
- Mỗi nguồn dữ liệu (Lịch tuần công khai / Lịch coi thi & hạn nộp
  điểm) giờ là 1 config entry riêng bên trong cùng 1 integration,
  chọn qua menu khi thêm tích hợp — có thể dùng 1 hoặc cả 2.
- Toàn bộ tính năng của 2 bản cũ được giữ nguyên không đổi: cảnh báo
  từ khóa (kèm biến thể/viết tắt), Calendar cho lịch tuần, đăng nhập
  tự động + tự làm mới phiên cho cổng cán bộ, lịch coi thi, hạn nộp
  điểm (không đụng điểm/thông tin sinh viên).
- Đổi tên sự kiện cho nhất quán với domain mới: `lichtuan_dut_match_found`
  → `dut_calendar_match_found`, `cb_dut_new_exam_duty` →
  `dut_calendar_new_exam_duty`, `cb_dut_grade_deadline_changed` →
  `dut_calendar_grade_deadline_changed`.

[Unreleased]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.5.0
[1.4.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.4.0
[1.3.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.3.0
[1.2.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.2.0
[1.1.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.1.0
[1.0.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.0.0
