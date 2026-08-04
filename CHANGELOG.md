# Changelog

Định dạng theo [Keep a Changelog](https://keepachangelog.com/vi/1.0.0/).
Phiên bản theo [Semantic Versioning](https://semver.org/lang/vi/).

## [Unreleased]

## [1.11.1] - 2026-08-04

### Sửa lỗi
- **Tải danh sách khoa/giảng viên (bước cấu hình `dut_coithi`) không ổn định**, lúc được lúc mất dữ liệu. Nguyên nhân: timeout 30s không đủ cho response ~1MB (`NCB=true&DDK=false&KHOA=ALL`) dưới mạng chậm/server tải, và khi lỗi thì code cũ **âm thầm bỏ qua** tính năng luôn (không cho biết lý do, không cho thử lại ngay). Đã sửa:
  - Tăng timeout riêng cho API này lên **90s** (các API khác trong file vẫn giữ 30s).
  - Tự động **thử lại 2 lần** trước khi báo lỗi hẳn, có log rõ nguyên nhân từng lần thử để chẩn đoán được qua HA logs.
  - Khi vẫn lỗi sau 2 lần thử: UI hiện rõ thông báo lỗi + nút **"🔄 Thử tải lại"** ngay tại chỗ (không phải thoát ra làm lại từ đầu), bên cạnh lựa chọn "Không theo dõi thêm ai" để bỏ qua nếu muốn.

## [1.11.0] - 2026-08-04

### Thay đổi
- **`dut_coithi` — chọn giảng viên khác qua UI thay vì gõ tay**: thêm 2 bước mới sau khi chọn học kỳ — chọn **Khoa** (rút gọn danh sách, hoặc bỏ qua/chọn tất cả) rồi chọn **tên** (nhiều lựa chọn, gõ để tìm kiếm). Tên lấy trực tiếp từ dữ liệu thật (`mã khoa-Tên`, vd `103-Lê Minh Tiến`), khớp **chính xác** thay vì kiểu chuỗi con như trước — tránh sai chính tả/khớp nhầm. Áp dụng cho cả khi thêm mới lẫn sửa qua Options. Vẫn đọc tương thích ngược cấu hình cũ (1 tên gõ tay) nếu entry chưa cấu hình lại theo cách mới.
- `parser_exam.py`: thêm `build_lecturer_directory()` (gom tên theo mã khoa từ dữ liệu thật) và `filter_exam_duty_by_lecturers()` (lọc theo danh sách, khớp chính xác) — test bằng dữ liệu thật (724 ca, 265 tên, 32 khoa).

## [1.10.0] - 2026-08-04

### Thêm mới
- **2 khoảng đếm mới: "Tuần này" và "Tuần sau"** (Thứ 2 → Chủ nhật) — áp dụng cho cả 3 loại (`dut_lichtuan`, `dut_coithi`, `dut_deadline_diem`), nâng tổng số khoảng đếm từ 3 lên 5 (Hôm nay/Ngày mai/Tuần này/Tuần sau/Tháng này).
- **`dut_lichtuan` — bộ sensor đếm riêng cho TỪNG NHÓM từ khóa**: trước đây chỉ có 1 bộ đếm TỔNG (gộp mọi nhóm); giờ mỗi nhóm từ khóa có thêm 5 sensor đếm riêng (vd "Lê Minh Tiến: Hôm nay"), bên cạnh bộ tổng vẫn giữ nguyên.

## [1.9.0] - 2026-08-04

### Thêm mới
- **`dut_lichtuan` — tick "Xóa lịch sử cũ" trong Options** (mặc định tắt). Tick vào rồi Submit sẽ xóa sạch toàn bộ lịch sử đã lưu (kể cả các mục vẫn còn khớp đúng) ngay lần quét kế tiếp, tự tắt lại ngay sau đó — không cần tự tắt tay, không xóa lặp lại các lần quét sau. Hữu ích khi muốn dọn sạch thủ công mà không cần đổi từ khóa (vốn đã tự động xóa lịch sử từ v1.8.2).

## [1.8.2] - 2026-08-04

### Sửa lỗi (phát hiện qua đối chiếu attributes thật của người dùng: đổi "Hiệu trưởng" → "Giám đốc", 13/16 mục cũ không liên quan vẫn còn nguyên)
- **Đổi từ khóa trong Options không xóa các mục chỉ khớp theo từ khóa CŨ.** Cơ chế giữ lịch sử (thêm ở 1.8.0) chỉ cộng dồn/ghi đè mục còn khớp, không bao giờ chủ động gỡ mục khi từ khóa đổi — khiến dữ liệu sai (theo tiêu chí không còn áp dụng) hiển thị lẫn với dữ liệu đúng, tới 14 ngày sau mới tự hết hạn. Đã sửa: lưu thêm "chữ ký" cấu hình từ khóa; phát hiện từ khóa vừa đổi (khác chữ ký lần quét trước) sẽ **xóa sạch lịch sử cũ**, quét lại từ đầu — đảm bảo không bao giờ hiện dữ liệu không còn đúng với cấu hình hiện tại.

### Đánh đổi có chủ đích
- Sau khi đổi từ khóa, lịch sử của các tuần không nằm trong phạm vi quét lần đó sẽ tạm thời trống cho tới lần quét kế tiếp bao gồm chúng — chấp nhận được, vì ưu tiên "không hiện sai" hơn "không thiếu tạm thời".

## [1.8.1] - 2026-08-04

### Sửa lỗi
- **Sửa 1 mục đã có (đổi giờ/địa điểm/chủ trì) tạo ra 2 bản hiển thị song song** trên Calendar/sensor (bug mới phát sinh từ cơ chế giữ lịch sử ở 1.8.0 — vì khóa lưu trữ trước đó dựa trên mã băm CHI TIẾT, đổi bất kỳ trường nào cũng ra khóa khác, bản cũ + bản mới cùng tồn tại tới khi bản cũ hết hạn 14 ngày). Đã đổi khóa lưu trữ lịch sử sang **khóa ổn định** (chỉ dựa ngày + nội dung) — bản sửa giờ ghi đè đúng vị trí bản cũ, không nhân đôi. Vẫn giữ nguyên việc báo "có thay đổi" khi chi tiết khác (dùng mã băm chi tiết riêng cho việc này, tách khỏi khóa lưu trữ).

## [1.8.0] - 2026-08-04

### Thay đổi
- **`dut_lichtuan` giờ giữ lại lịch sử mục đã khớp qua nhiều lần quét**, thay vì dựng lại hoàn toàn từ đầu mỗi lần (trước đây: khi trang chuyển sang tuần mới, dữ liệu tuần cũ biến mất ngay khỏi sensor/Calendar vì mỗi lần quét chỉ lấy đúng tuần đang quét). Giờ mỗi mục khớp được gộp vào lịch sử, giữ lại **14 ngày** kể từ ngày diễn ra sự kiện rồi mới tự dọn — Calendar duyệt lùi lại tuần trước vẫn còn dữ liệu.
- Sửa lỗi sắp xếp ngày kiểu chuỗi (`dd/mm/yyyy` so sánh trực tiếp bằng string cho kết quả sai khi khác tháng/năm, vd "01/09" bị coi nhỏ hơn "15/08") — giờ sắp xếp theo ngày thật.

## [1.7.1] - 2026-08-04

### Sửa lỗi (2 lỗi thật, phát hiện qua đối chiếu attributes sensor thật của người dùng)
- **Bỏ sót từ khóa khớp do lệch chuẩn Unicode (nguyên nhân chính gây "thiếu dữ liệu" khi lọc theo "Hiệu trưởng"):** trang nguồn (và cổng `cb.dut.udn.vn`) trộn lẫn 2 cách encode dấu tiếng Việt — NFC (dựng sẵn) và NFD (tổ hợp) — tùy người nhập liệu. Hai chuỗi **nhìn giống hệt nhau** nhưng khác byte, khiến so khớp kiểu chuỗi con (`in`) âm thầm trả về `False`. Đã chuẩn hóa **NFC** cho toàn bộ text trích từ trang (`_clean_text` ở `parser_public.py`, trích cột bảng ở `parser_exam.py`) VÀ cho từ khóa/tên giảng viên người dùng nhập (`parse_keyword_groups`, `filter_exam_duty_by_lecturer`) — đảm bảo luôn so sánh cùng 1 chuẩn.
- **Lỗi tách "Thứ/Ngày" khi dính liền** (vd `Thứ tư05/08/2026` không tách được thành `Thứ tư` + `05/08/2026`, ngày bị để trống): trang nguồn không đồng nhất khoảng trắng giữa tên Thứ và ngày (một số thứ tách đúng qua `\n`, một số dính liền thành 1 chuỗi). Đã đổi sang tách bằng **regex theo đúng định dạng `dd/mm/yyyy`**, không phụ thuộc khoảng trắng/newline nguồn — hoạt động đúng với cả 2 kiểu.

### Kỹ thuật
- Cả 2 lỗi test bằng dữ liệu `attributes` sensor thật do người dùng cung cấp (không phải dữ liệu giả lập), đã xác nhận sửa đúng và không hồi quy trên toàn bộ test case cũ.

## [1.7.0] - 2026-08-04

### Thêm mới
- **`dut_lichtuan` — Chế độ cập nhật:** thêm lựa chọn "Chỉ tuần hiện tại + tuần mới (từ cuối tuần)" bên cạnh chế độ "Toàn bộ" cũ. Chế độ mới mặc định gọn nhẹ hơn: chỉ 1 request/lần quét (tuần hiện tại), tự tải thêm tuần kế tiếp từ Thứ 6 trở đi trong tuần (thời điểm trường thường công bố lịch tuần sau).
- **`dut_coithi` — Theo dõi thêm 1 giảng viên khác:** tùy chọn nhập tên giảng viên (ngoài tài khoản đang đăng nhập) để lọc và cảnh báo thêm ca thi của người đó. Tải danh sách toàn bộ ca thi (không giới hạn theo tài khoản), lọc cục bộ theo tên, khử trùng nếu trùng với ca của chính mình. Gắn cờ `giang_vien_khac`/tiền tố `[Tên]` để phân biệt trong sensor, Calendar, và thông báo.

### Kỹ thuật
- `parser_exam.filter_exam_duty_by_lecturer()` mới, test độc lập bằng dữ liệu thật (lọc đúng 4/11 ca thi mẫu).
- `api_exam.fetch_exam_duty_all_html()` mới (dùng `NCB=true&DDK=false`).
- Field "Tên giảng viên khác" chỉ hiện ở form của `dut_coithi`, không hiện ở `dut_deadline_diem`.

## [1.6.0] - 2026-08-04

### Sửa lỗi (quan trọng — người dùng phát hiện qua kiểm tra thực tế)
- **`dut_lichtuan` bỏ sót gần 1/4 dữ liệu**: trang `lichtuan.dut.udn.vn` đã được viết lại (kiến trúc mới, đăng nhập qua Microsoft OAuth cho admin, PDF export riêng...) và giờ có thêm **bảng "PHỤ LỤC"** tách biệt hoàn toàn với bảng lịch chính — parser cũ chỉ đọc bảng đầu tiên (`soup.find`), bỏ sót toàn bộ Phụ lục. Đã sửa đọc **tất cả bảng** (`soup.find_all`), phân biệt bảng chính/phụ lục qua heading `<h*>` đứng trước, gắn cờ `phu_luc` vào từng mục. Test thực tế: từ 26 mục (chỉ bảng chính) lên 35 mục (cả 2 bảng) cho cùng 1 tuần.
- **Công thức tính năm học sai, khiến `weeks_ahead` (quét thêm tuần tới) không hoạt động đúng**: công thức cũ giả định năm học bắt đầu cố định ngày 1/9, nhưng thực tế trường không dùng ranh giới cố định (năm học có thể 52 hoặc 53 tuần, bắt đầu lệch ngày tuỳ năm). Đã bỏ hoàn toàn công thức tự tính — giờ **đọc trực tiếp** dropdown "Tuần"/"Năm học" có sẵn trên chính trang (`parse_current_week_info()`) để lấy tuần/năm học hiện tại chính xác 100%, chỉ chuyển sang năm học kế tiếp khi tuần cần quét thực sự vượt quá tuần cuối cùng đã biết.
- Thêm cờ `[Phụ lục]` trong thông báo cảnh báo và trường `phu_luc` trong attributes/mô tả Calendar để phân biệt nguồn.

### Ghi chú
- Không phát hiện thay đổi cấu trúc bảng chính (class `week` cho ô ngày, thứ tự cột) — logic đọc dòng/cột không đổi, chỉ mở rộng phạm vi bảng được đọc.

## [1.5.1] - 2026-08-04

### Sửa lỗi
- **Tên Calendar bị lặp chữ trong giao diện Lovelace** (vd "DUT Calendar - Coi thi Coi thi") do Home Assistant tự ghép "tên thiết bị + tên entity" khi cả hai đều chứa cùng nội dung. Đã tắt `has_entity_name` riêng cho 3 Calendar entity — giờ hiển thị gọn đúng: `Lịch tuần`, `Coi thi`, `Nhập điểm`. Sensor không đổi (vẫn ghép tên thiết bị, vì ở đó không bị trùng và ghép tên giúp dễ phân biệt hơn, vd "DUT Calendar - Coi thi Hôm nay").

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

[Unreleased]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/compare/v1.11.1...HEAD
[1.11.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.11.1
[1.11.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.11.0
[1.10.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.10.0
[1.9.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.9.0
[1.8.2]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.8.2
[1.8.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.8.1
[1.8.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.8.0
[1.7.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.7.1
[1.7.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.7.0
[1.6.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.6.0
[1.5.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.5.1
[1.5.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.5.0
[1.4.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.4.0
[1.3.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.3.0
[1.2.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.2.0
[1.1.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.1.0
[1.0.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.0.0
