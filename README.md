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
- Quét **cả bảng lịch chính lẫn bảng "PHỤ LỤC"** (2 bảng tách biệt trên
  trang) — mục nào tới từ Phụ lục sẽ có gắn cờ `phu_luc: true` trong
  attributes và tiền tố `[Phụ lục]` trong thông báo, để phân biệt.
- Tuần/năm học hiện tại được **đọc trực tiếp** từ dropdown có sẵn trên
  trang (không tự tính công thức) — an toàn trước việc trường đổi
  ranh giới năm học hoặc số tuần mỗi năm (52 hay 53 tuần) mà không
  báo trước.
- **Tiêu đề sự kiện Calendar có tiền tố `[Tên nhóm từ khóa]`** (vd
  `[Khoa Cơ khí Giao thông] Hội ý Ban Giám hiệu`) — biết ngay mục nào
  khớp theo nhóm nào khi nhìn lịch, nhất là khi cấu hình nhiều nhóm
  cùng lúc. Nếu 1 mục khớp nhiều nhóm, tiền tố liệt kê đủ (vd `[Lê
  Minh Tiến, Khoa Cơ khí Giao thông]`).
- **Chế độ cập nhật** (chọn khi cài đặt hoặc sửa qua Options):
  - **"Chỉ tuần hiện tại + tuần mới (từ cuối tuần)"** — mặc định gọn
    nhẹ nhất: mỗi lần quét chỉ tải tuần hiện tại (1 request); từ
    **Thứ 6** trở đi trong tuần mới tải thêm tuần kế tiếp (trường
    thường công bố lịch tuần sau vào khoảng cuối tuần). Bỏ qua cấu
    hình "Số tuần kiểm tra thêm" ở chế độ này.
  - **"Toàn bộ"** — hành vi như trước: luôn tải tuần hiện tại + đúng
    số tuần đã cấu hình ở "Số tuần kiểm tra thêm", bất kể ngày nào
    trong tuần.
- **Dữ liệu tuần cũ có được giữ lại không?** Có — mỗi mục khớp từ khóa
  được **gộp vào lịch sử** thay vì bị thay thế hoàn toàn mỗi lần quét.
  Khi trang chuyển sang tuần mới (không còn được quét tới nữa), mục
  của tuần cũ vẫn hiển thị trên sensor/Calendar trong **14 ngày** kể
  từ ngày diễn ra sự kiện, sau đó tự động dọn bớt để không phình to
  vô hạn. Nhờ vậy duyệt lùi lại tuần trước trên Lovelace Calendar vẫn
  thấy dữ liệu, không bị trống.
- **Nếu trường sửa lại 1 mục đã có (đổi giờ/địa điểm/chủ trì) thì
  sao?** Bản sửa sẽ **ghi đè** đúng vị trí bản cũ trong lịch sử (dựa
  trên khóa ổn định = ngày + nội dung), **không** tạo thành 2 mục hiển
  thị song song trên Calendar. Vẫn có cảnh báo báo "có thay đổi" như
  bình thường (vì nội dung chi tiết đã khác), chỉ là không bị nhân đôi
  khi hiển thị.
- **Nếu đổi từ khóa trong Options thì sao?** Toàn bộ lịch sử **bị xóa
  sạch và quét lại từ đầu** — cố ý làm vậy để tránh hiện lại mục chỉ
  khớp theo từ khóa CŨ (đã xóa/đổi), dữ liệu không còn đúng với cấu
  hình hiện tại. Đánh đổi: mất tạm phần lịch sử của các tuần không
  còn được quét lại ngay trong lần quét đó — chấp nhận được, vì hiện
  dữ liệu sai còn tệ hơn nhiều so với tạm thời thiếu vài mục cũ.
- **Xóa lịch sử thủ công:** trong Options có tick **"Xóa lịch sử cũ"**
  (mặc định **tắt**) — tick vào rồi Submit sẽ xóa sạch toàn bộ lịch sử
  đã lưu ngay lần quét kế tiếp, sau đó tick **tự tắt lại**, không cần
  tự tắt tay và không xóa lặp lại ở các lần quét sau.

## Sensor đếm số sự kiện (cả 3 loại)

Mỗi loại (`dut_lichtuan`, `dut_coithi`, `dut_deadline_diem`) đều có
thêm 5 sensor đếm, tính theo giờ hệ thống của Home Assistant:

- **Hôm nay** — số sự kiện rơi đúng ngày hôm nay.
- **Ngày mai** — số sự kiện rơi đúng ngày mai.
- **Tuần này** — số sự kiện trong tuần hiện tại (Thứ 2 → Chủ nhật).
- **Tuần sau** — số sự kiện trong tuần kế tiếp (Thứ 2 → Chủ nhật).
- **Tháng này** — số sự kiện trong tháng hiện tại.

Với `dut_lichtuan`: đếm theo mục lịch tuần khớp từ khóa. Với
`dut_coithi`: đếm theo ca coi thi. Với `dut_deadline_diem`: đếm theo
mốc hạn nộp điểm (thi chung + từng lớp gộp lại).

**Riêng `dut_lichtuan`: có thêm 1 bộ 5 sensor đếm này cho TỪNG NHÓM từ
khóa** (vd "Lê Minh Tiến: Hôm nay", "Lê Minh Tiến: Tuần này"...), bên
cạnh bộ đếm TỔNG (gộp mọi nhóm) đã có sẵn — tổng cộng `5 × (1 + số
nhóm từ khóa)` sensor đếm cho riêng `dut_lichtuan`.

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
- **Tiêu đề sự kiện Calendar luôn có tên + vai trò + phòng thi**, áp
  dụng cho **cả ca của chính bạn lẫn ca của giảng viên khác đang theo
  dõi** (trước đây chỉ ca giảng viên khác mới có tên, ca của chính
  mình không hiện gì): vd `[103-Lê Minh Tiến · GT1] Coi thi: Kỹ thuật
  điện - điện tử — Phòng F108`. `GT1`/`GT2` = Giám thị 1/2 (tức đang
  là Cán bộ 1 hay Cán bộ 2 trong ca đó).
  - Tên của **chính bạn** được **suy luận tự động**: vì cột "Cán bộ
    1"/"Cán bộ 2" trên hệ thống trường **không cố định vị trí** (có ca
    bạn là Cán bộ 1, có ca là Cán bộ 2, tùy ai đăng ký trước) — không
    thể giả định vị trí cố định. Suy luận dựa trên: tên của bạn là tên
    **duy nhất xuất hiện ở MỌI ca trong danh sách của chính bạn** (vì
    mọi ca đó chắc chắn có bạn tham gia, chỉ người cùng coi thi đổi
    khác nhau tuỳ ca).
- **Ý nghĩa số đếm sensor `Lịch coi thi`:** tổng số ca coi thi **sắp
  tới** (chưa diễn ra) trong các học kỳ đang theo dõi — khác với các
  sensor "Hôm nay"/"Tuần này"... chỉ đếm theo 1 khoảng ngày cụ thể.
  Khi không còn ca nào sắp tới, giá trị đúng là `0`; nếu thấy
  `unknown`, đó là dấu hiệu sensor **chưa từng lấy được dữ liệu lần
  nào** (coordinator lỗi/chưa cập nhật xong), không phải nghĩa là
  "hết ca thi".
- Chỉ cảnh báo ca thi **mới**.
- **Theo dõi thêm giảng viên khác** (tùy chọn, tick bật ngay ở bước
  đăng nhập — cả khi thêm mới lẫn sửa qua Options): mặc định **tắt**,
  không tải gì thêm, không tốn thời gian. Chỉ khi **tick bật** mới đi
  tiếp qua 3 bước:
  1. Chọn học kỳ (như cũ)
  2. Chọn **Khoa** (dropdown, kèm số người mỗi khoa) để rút gọn danh
     sách. Khi sửa qua Options mà đã có sẵn người đang theo dõi, có
     **2 lựa chọn tách biệt rõ ràng** (tránh nhầm lẫn hệ quả):
     - **↩️ "Giữ nguyên N người đang theo dõi, không đổi gì"** — chỉ
       bỏ qua lần chỉnh sửa này, KHÔNG xóa ai (mặc định chọn sẵn).
     - **🗑️ "Xóa hết, không theo dõi ai"** — xóa hẳn toàn bộ danh
       sách đang theo dõi, đặt về rỗng.
     - Hoặc chọn **"— Tất cả các khoa —"** / 1 khoa cụ thể để đi tiếp
       bước chọn tên.
  3. Chọn **tên** (nhiều lựa chọn cùng lúc, gõ để tìm kiếm nếu danh
     sách dài) — tên lấy trực tiếp từ dữ liệu thật trên hệ thống
     (dạng `mã khoa-Tên`, vd `103-Lê Minh Tiến`), không gõ tay nên
     không lo sai chính tả/không khớp.

  Danh sách khoa/tên được **gộp từ TẤT CẢ học kỳ** đã chọn ở bước
  trước (không chỉ học kỳ đầu tiên) — vì 1 học kỳ đơn lẻ có thể chưa
  có đủ dữ liệu coi thi cho mọi khoa (vd học kỳ mới chưa xếp lịch hết,
  hoặc khoa của chính bạn tình cờ chưa có ca nào trong học kỳ đó),
  khiến danh sách bị thiếu nếu chỉ dựa vào 1 học kỳ.

  *Khi sửa qua Options: nếu entry đã có sẵn giảng viên đang theo dõi,
  tick này tự mặc định BẬT (để tiện chỉnh sửa). Có 2 chỗ "bỏ qua"
  tách biệt rõ ràng để không nhầm lẫn hệ quả:*
  - *Bỏ tick ngay từ đầu (chưa vào bước chọn khoa) → GIỮ NGUYÊN, không
    đổi gì, không tải dữ liệu.*
  - *Đã vào bước chọn khoa → có 2 lựa chọn tách biệt: "↩️ Giữ nguyên"
    (không đổi gì, như trên) hoặc "🗑️ Xóa hết" (xóa hẳn danh sách).*

  Khi có chọn, mỗi lần quét sẽ tải thêm danh sách **toàn bộ ca thi**
  (không giới hạn theo tài khoản đăng nhập, response lớn hơn — chỉ
  tải khi thực sự có chọn ai) rồi lọc theo đúng (các) tên đã chọn
  (khớp **chính xác**, không phải chuỗi con như trước). Ca thi tìm
  được gắn cờ `giang_vien_khac: true` trong attributes, có tiền tố
  `[Tên]` trong tiêu đề sự kiện Calendar và trong thông báo. Nếu
  giảng viên đó vốn đã là "Cán bộ 2" cùng coi thi với bạn, ca đó chỉ
  tính 1 lần (không hiện trùng lặp).

  *Nếu không tải được danh sách khoa/tên lúc cấu hình (lỗi mạng...),
  vẫn tạo/lưu entry bình thường — chỉ là bỏ qua tính năng này lần đó,
  có thể vào lại Options để thử chọn lại sau.*

## `dut_deadline_diem` — Hạn nộp điểm

**Sensor `Hạn nộp điểm` hiện `Unknown` nghĩa là gì?** Sensor này có
`device_class: date` nên state chỉ có thể là 1 ngày cụ thể hoặc rỗng
(không dùng được số 0 như các sensor đếm). State = mốc hạn **gần nhất
còn sắp tới**; nếu không còn mốc nào, state rỗng → HA hiện `Unknown`.
Xem attribute **`trang_thai`** để biết chính xác lý do:

| `trang_thai` | Ý nghĩa |
|---|---|
| `con_han_sap_toi` | Còn hạn sắp tới, state là ngày gần nhất |
| `da_qua_het_han` | Có dữ liệu nhưng mọi mốc đều đã qua (xem `han_gan_nhat_da_qua`) |
| `chua_co_du_lieu` | Chưa lấy được dữ liệu, hoặc trường chưa công bố hạn |

Kèm theo: `so_moc_sap_toi`, `so_moc_da_qua`, `han_gan_nhat_da_qua`.

### Mã học kỳ

Trường dùng mã 4 chữ số `YYSK`, integration tự chuyển sang tên đọc
được (attribute `hoc_ky_ten`, và trong mô tả sự kiện Calendar):

| Thành phần | Ý nghĩa |
|---|---|
| `YY` | Năm bắt đầu năm học (`25` → 2025-2026) |
| `S` | `1` = Học kỳ 1, `2` = Học kỳ 2 |
| `K` | `0` = kỳ chính, `1` = kỳ **Hè** (chỉ đi kèm `S=2`) |

Ví dụ: `2510` → HK1 2025-2026, `2520` → HK2 2025-2026, `2521` → **Hè**
2025-2026. Quy tắc này được đối chiếu khớp 14/14 mã có thật trên hệ
thống trường. Mã không khớp định dạng sẽ được giữ nguyên thay vì đoán
sai (phòng khi trường đổi quy ước).

### Sensor `Cần nhập điểm` — trả lời "hôm nay cần nhập môn gì, hạn khi nào"



Dữ liệu gốc của trường lồng nhau theo học kỳ → lớp → từng loại điểm,
khó dùng trực tiếp. Sensor này **phẳng hóa thành danh sách việc cần
làm**, gộp cả 3 học kỳ (HK1, HK2, hè) đang theo dõi, bỏ các mốc đã
quá hạn, sắp xếp gần → xa:

- **State** = tổng số mốc chưa quá hạn.
- `gan_nhat` — mốc sắp tới gần nhất.
- `hom_nay` — các mốc hết hạn **đúng hôm nay**.
- `trong_7_ngay` — các mốc còn ≤ 7 ngày (để nhắc sớm).
- `danh_sach` — toàn bộ, mỗi mục gồm: `mon`, `loai` (giữa kỳ / thành
  phần / cuối kỳ / đính chính...), `ngay`, `con_lai_ngay`, `hoc_ky`,
  `ma_lop`.

Ví dụ automation nhắc mỗi sáng 7h khi có mốc trong 7 ngày tới:

```yaml
automation:
  - alias: Nhắc hạn nhập điểm
    trigger:
      - platform: time
        at: "07:00:00"
    condition:
      - condition: template
        value_template: >
          {{ state_attr('sensor.dut_calendar_han_nop_diem_can_nhap_diem',
                        'trong_7_ngay') | count > 0 }}
    action:
      - service: notify.mobile_app_cua_ban
        data:
          title: Sắp hết hạn nhập điểm
          message: >
            {% for x in state_attr('sensor.dut_calendar_han_nop_diem_can_nhap_diem',
                                   'trong_7_ngay') %}
            • {{ x.mon }} — {{ x.loai }}: còn {{ x.con_lai_ngay }} ngày
              (hạn {{ x.ngay }})
            {% endfor %}
```

*Thay `sensor.dut_calendar_han_nop_diem_can_nhap_diem` bằng entity_id
thật (xem trong Developer Tools → States) và `notify.mobile_app_cua_ban`
bằng notify service của bạn.*

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
