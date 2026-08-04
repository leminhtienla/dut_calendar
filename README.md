# DUT Calendar (Home Assistant custom integration)

<p align="center">
  <img src="custom_components/dut_calendar/brand/logo.png" alt="Logo Trường Đại học Bách khoa - Đại học Đà Nẵng" width="180">
</p>

Tích hợp tùy chỉnh cho Home Assistant, gộp dữ liệu từ Trường Đại học
Bách khoa - Đại học Đà Nẵng vào **1 component duy nhất**, chia thành
**3 loại nguồn** — mỗi loại là 1 config entry riêng, chọn qua menu khi
thêm tích hợp:

| Loại | Cần đăng nhập? | Dữ liệu |
|---|---|---|
| **`dut_lichtuan`** | Không | Lịch tuần công khai, cảnh báo theo từ khóa |
| **`dut_coithi`** | Có | Lịch coi thi đã đăng ký |
| **`dut_deadline_diem`** | Có | Hạn nộp điểm (không đụng điểm/thông tin sinh viên) |

Có thể dùng 1, 2, hoặc cả 3 loại cùng lúc — mỗi loại là 1 "thiết bị"
riêng trong Home Assistant, không phụ thuộc lẫn nhau.

## Cài đặt

1. Copy `custom_components/dut_calendar/` vào `config/custom_components/`.
2. Khởi động lại Home Assistant.
3. **Cài đặt → Thiết bị & Dịch vụ → Thêm tích hợp**, tìm "DUT Calendar".
4. Chọn 1 trong 3 nguồn ở menu hiện ra, điền form tương ứng.
5. Muốn dùng thêm nguồn khác: lặp lại bước 3-4.

## `dut_lichtuan` — Lịch tuần công khai

- Không cần đăng nhập, lấy từ `lichtuan.dut.udn.vn`.
- Cấu hình từ khóa dạng nhiều dòng, mỗi dòng 1 nhóm (gộp tên đầy đủ +
  viết tắt):
  ```
  Lê Minh Tiến: Lê Minh Tiến, LMT, Thầy Tiến
  Khoa Cơ khí Giao thông: Khoa Cơ khí Giao thông, CKGT
  Bộ môn Kỹ thuật Ô tô: Kỹ thuật Ô tô, KTOT
  ```
- Tạo 1 sensor tổng + 1 sensor riêng mỗi nhóm từ khóa, và Calendar `calendar.lich_tuan`.
- Chỉ cảnh báo mục **mới**, không lặp lại.

## Sensor đếm số sự kiện (cả 3 loại)

Mỗi loại (`dut_lichtuan`, `dut_coithi`, `dut_deadline_diem`) đều có
thêm 3 sensor đếm, tính theo giờ hệ thống của Home Assistant:

- **Hôm nay** — số sự kiện rơi đúng ngày hôm nay.
- **Ngày mai** — số sự kiện rơi đúng ngày mai.
- **Tháng này** — số sự kiện trong tháng hiện tại.

Với `dut_lichtuan`: đếm theo mục lịch tuần khớp từ khóa. Với
`dut_coithi`: đếm theo ca coi thi. Với `dut_deadline_diem`: đếm theo
mốc hạn nộp điểm (thi chung + từng lớp gộp lại).

## Calendar — tên rút gọn

- `dut_lichtuan` → Calendar **`Lịch tuần`**
- `dut_coithi` → Calendar **`Coi thi`**
- `dut_deadline_diem` → Calendar **`Nhập điểm`** *(mới)* — mỗi mốc hạn
  (giữa kỳ, thành phần, thi chung, đính chính...) hiển thị thành 1 sự
  kiện **cả ngày** trên đúng ngày hết hạn, xem trực quan trên Lovelace
  Calendar card thay vì chỉ đọc attributes của sensor.

## Đổi Options có tự cập nhật sensor không?

Có — mọi thay đổi qua Options (từ khóa, học kỳ, tài khoản...) đều làm
Home Assistant **tự reload toàn bộ entry** ngay sau khi lưu, sensor và
calendar cập nhật theo dữ liệu mới ngay trong lần tải đầu tiên sau đó,
không cần khởi động lại HA hay thao tác gì thêm.

## `dut_coithi` / `dut_deadline_diem` — quy trình cài đặt

1. **Bước 0 — Chọn tài khoản** *(chỉ hiện nếu đã có ≥1 tài khoản cấu
   hình từ trước, ở nguồn `dut_coithi` hoặc `dut_deadline_diem`
   khác)*: chọn dùng lại tài khoản đã có (khỏi gõ mật khẩu lần nữa),
   hoặc chọn "+ Tài khoản khác" để nhập tài khoản mới. Ví dụ: đã thêm
   `dut_coithi` với tài khoản A, giờ thêm `dut_deadline_diem` — có
   thể chọn lại tài khoản A ngay, không cần đăng nhập lại từ đầu.
2. **Bước 1 — Đăng nhập:** nhập (hoặc xác nhận) tài khoản/mật khẩu.
   Tích hợp thử đăng nhập thật ngay lúc này — sai tài khoản/mật khẩu
   báo lỗi tại đây, chưa lưu gì cả.
3. **Bước 2 — Chọn học kỳ:** sau khi đăng nhập thành công, tích hợp tự
   tải danh sách học kỳ **thật** từ cổng (vd "Học kỳ 2 năm học
   2025-2026") để bạn **chọn bằng tên**, không cần tự gõ mã số. Hiển
   thị dạng **danh sách tick chọn** (không phải dropdown chỉ chọn được
   1) — tick được nhiều học kỳ cùng lúc, kể cả các học kỳ giao thoa
   lịch nhau. Học kỳ đang là "hiện tại" trên cổng sẽ được chọn sẵn.

Muốn đổi lại danh sách học kỳ theo dõi sau này: vào Options của entry
đó — cũng đi qua đúng bước xác thực + chọn học kỳ như trên (không cần
nhớ mã số). Lưu ý: Options không có bước "chọn tài khoản có sẵn" (vì
đang sửa 1 entry cụ thể, không phải thêm mới) — để trống ô Mật khẩu
nếu không muốn đổi.

## `dut_coithi` — Lịch coi thi

- Đăng nhập 1 lần bằng tài khoản cổng `cb.dut.udn.vn`, tự đăng nhập
  lại khi phiên hết hạn (~24 giờ).
- Chọn học kỳ cần theo dõi từ danh sách thật (xem mục "quy trình cài
  đặt 2 bước" phía trên), không cần nhớ mã số.
- Tạo sensor `Lịch coi thi` + Calendar `calendar.coi_thi`.
- Chỉ cảnh báo ca thi **mới**.

## `dut_deadline_diem` — Hạn nộp điểm

- Đăng nhập riêng (độc lập với `dut_coithi`, dù cùng tài khoản — mỗi
  entry giữ phiên đăng nhập của chính nó).
- Lấy **2 loại hạn khác nhau** (khác trang, khác cơ chế):
  - **Hạn điểm cuối kỳ thi chung** — theo từng **ca thi** (tự động lấy
    "Mã ca thi" từ dữ liệu lịch coi thi nội bộ, không cần cấu hình
    thêm). Áp dụng chung cho cả ca thi đó.
  - **Hạn điểm giữa kỳ / thành phần** — theo **từng lớp học phần**
    riêng biệt (mỗi lớp có thể có hạn khác nhau, kể cả cùng môn khác
    lớp). Tự động lấy danh sách lớp phụ trách rồi tra hạn từng lớp,
    không cần cấu hình thêm.
- Tạo sensor `Hạn nộp điểm`: state = mốc hạn **gần nhất sắp tới** (gộp
  cả 2 loại trên, từ mọi lớp/học kỳ đang theo dõi); attributes có chi
  tiết đầy đủ theo từng lớp + từng học kỳ.
- Không có Calendar — đây là các mốc ngày, không phải sự kiện có giờ.
- **Không** lấy điểm số/tên/mã số sinh viên — dù response API (cả 2
  loại) có chứa bảng điểm, code chỉ đọc đúng dòng header chứa ngày
  tháng, cố tình bỏ qua phần bảng.
- Chỉ cảnh báo khi các mốc **thay đổi** so với lần quét trước.

## ⚠️ Lưu ý an toàn (`dut_coithi` / `dut_deadline_diem`)

- Mật khẩu lưu trong Config Entry của HA (không gửi cho bên thứ ba
  ngoài chính cổng `cb.dut.udn.vn`).
- Mỗi entry dùng session HTTP riêng biệt, không lẫn với tích hợp khác
  — kể cả 2 entry `dut_coithi` và `dut_deadline_diem` cùng tài khoản
  cũng có phiên đăng nhập độc lập với nhau.
- Bước cài đặt **thử đăng nhập thật** trước khi lưu — sai tài khoản/
  mật khẩu báo lỗi ngay.
- **Không** lấy dữ liệu lương/tài chính cá nhân ở bất kỳ loại nào.

## Sự kiện dùng cho automation nâng cao

- `dut_calendar_match_found` — mục lịch tuần mới khớp từ khóa.
- `dut_calendar_new_exam_duty` — ca coi thi mới.
- `dut_calendar_grade_deadline_changed` — hạn nộp điểm thay đổi.

## Ghi chú kỹ thuật

- Domain: `dut_calendar`. Ban đầu là 2 integration riêng
  (`lichtuan_dut`, `cb_dut`), sau gộp thành 1 domain 2 loại
  (`public_schedule`/`exam_login`), rồi tách lại thành **3 loại gọn**
  (`dut_lichtuan`/`dut_coithi`/`dut_deadline_diem`) để mỗi loại là 1
  thiết bị độc lập, rõ ràng hơn khi quản lý trong HA.
- Nguồn dữ liệu là các trang HTML/API nội bộ không chính thức của
  trường, có thể thay đổi nếu trường nâng cấp hệ thống.
