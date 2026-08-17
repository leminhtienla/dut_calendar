# Changelog

Định dạng theo [Keep a Changelog](https://keepachangelog.com/vi/1.0.0/).
Phiên bản theo [Semantic Versioning](https://semver.org/lang/vi/).

## [Unreleased]

## [1.34.0] - 2026-08-17

### Sửa lỗi nghiêm trọng — bật `mail_exclude_subjects` làm gãy cả lần quét mail
- **Nguyên nhân**: `exclude_mails_by_subject()` không có try/except, và
  `m.get("subject", "")` chỉ trả về mặc định `""` khi THIẾU key —
  không xử lý trường hợp key tồn tại nhưng **giá trị chính là `None`**
  (mail hệ thống tiêu đề hỏng/rỗng). Gặp trường hợp này,
  `unicodedata.normalize("NFC", None)` ném `TypeError`, làm gãy toàn
  bộ `_async_update_data` -> coordinator giữ nguyên **dữ liệu cache
  cũ** (giải thích đúng hiện tượng "bật exclude thì chỉ còn 1 mail cũ,
  tắt thì đầy đủ" — không phải do sai logic loại trừ, mà do crash toàn
  bộ lần quét).
- **Sửa 2 lớp phòng thủ**:
  1. `exclude_mails_by_subject()`: mỗi mail xử lý trong try/except
     riêng — 1 mail dữ liệu lạ chỉ bị bỏ qua bước loại trừ CHO RIÊNG
     NÓ (coi như không loại, vẫn giữ), không ảnh hưởng mail khác.
  2. `coordinator_mail.py`: gọi `exclude_mails_by_subject` trong
     try/except ở tầng coordinator — nếu vẫn lỗi vì lý do khác, log
     cảnh báo và dùng nguyên danh sách CHƯA lọc loại trừ, không crash
     cả lần quét.
- Log cảnh báo mới: `"Lỗi khi loại trừ mail theo tiêu đề, bỏ qua bước
  này: ..."` — nếu còn lỗi tái diễn, log này sẽ chỉ đúng nguyên nhân
  thật để vá tiếp.

### Kiểm tra
- Test lại case bình thường (không đổi kết quả so với 1.33.0) + case
  `subject: None` (mail dữ liệu lạ) — không còn crash, vẫn lọc đúng
  các mail hợp lệ khác trong cùng đợt quét.

## [1.33.0] - 2026-08-17

### Thêm mới — loại trừ mail theo tiêu đề
- **Mail "Lịch công tác tuần"** (nội dung trùng với `dut_lichtuan`, ra
  đều đặn mỗi tuần) giờ bị **bỏ qua hoàn toàn** trong `dut_mail`, không
  tính khớp với bất kỳ nhóm từ khóa nào nữa — tránh nhiễu sensor/
  Calendar mail vì loại mail này gần như tuần nào cũng dính nhiều nhóm
  (họp, hội nghị...).
- Hàm mới `parse_exclude_subjects()` + `exclude_mails_by_subject()` —
  loại trừ áp dụng TRƯỚC bước lọc từ khóa, chỉ xét TIÊU ĐỀ (khớp chuỗi
  con, không phân biệt hoa/thường, chuẩn hóa NFC), không đụng tới thân
  mail.
- **Cấu hình mới trong Options `dut_mail`**: ô `mail_exclude_subjects`
  (nhiều dòng, mỗi dòng 1 cụm) — mặc định điền sẵn `Lịch công tác
  tuần`, có thể xóa hoặc thêm cụm khác (vd tên các thông báo lặp lại
  đều đặn khác của trường).

### Kiểm tra
- Test loại đúng cả bản gốc lẫn bản `FW:` của "Lịch công tác tuần",
  giữ nguyên mail khác không khớp cụm loại trừ.

## [1.32.0] - 2026-08-17

### Thêm mới — AI hỗ trợ đọc email (chỉ khi rule-based thất bại)
- **Chỉ kích hoạt khi mail đã khớp từ khóa NHƯNG rule-based không tách
  được gì cả** (không giờ họp, không sự kiện cả ngày, không hạn, không
  khoảng ngày) — AI không bao giờ ghi đè lên kết quả rule-based đã có,
  chỉ lấp khoảng trống mà `dut_mail` vốn để trống theo đúng nguyên tắc
  "thà trống còn hơn sai".
- **Dùng entity `conversation` có sẵn trong Home Assistant** (Options
  → chọn 1 agent đã cấu hình sẵn, vd Anthropic/OpenAI/Google) — không
  tự lưu API key riêng trong `dut_calendar`, không hardcode 1 hãng cụ
  thể. Gọi qua service chuẩn `conversation.process`.
- **Prompt ép AI cùng nguyên tắc "thà trống còn hơn sai"**: yêu cầu trả
  JSON đúng khuôn, để `null`/mảng rỗng khi không chắc, không được suy
  luận hay tự bịa ngày/giờ/địa điểm.
- **Phạm vi gửi cho AI**: tiêu đề + phần thân mail MỚI NHẤT (đã cắt bỏ
  trích dẫn mail cũ — cùng phạm vi rule-based dùng), KHÔNG gửi toàn
  văn, KHÔNG lưu lại prompt/kết quả thô vào `.storage` (chỉ lưu các
  trường đã tách, giống hệt cách rule-based lưu).
- **Minh bạch nguồn gốc**: sự kiện Calendar do AI tìm ra có tiền tố
  `🤖` trong tiêu đề và ghi chú "Nguồn: AI hỗ trợ tìm — kiểm tra lại"
  trong mô tả, để phân biệt rõ với kết quả rule-based (vốn đáng tin hơn
  vì đã kiểm chứng bằng dữ liệu thật).
- **An toàn khi lỗi**: mọi lỗi gọi AI (agent lỗi, JSON hỏng, ngày sai
  định dạng...) đều bị nuốt và coi như AI cũng không tìm thấy gì — mail
  vẫn báo bình thường qua sensor, chỉ là không lên Calendar, không bao
  giờ làm crash coordinator.
- **Cấu hình mới trong Options `dut_mail`**:
  - `ai_enabled` (bật/tắt) — mặc định **BẬT**.
  - `ai_entity_id` (chọn entity `conversation`) — để trống thì tính
    năng AI không chạy dù `ai_enabled` bật.

### Kiểm tra
- Test `build_ai_prompt` / `parse_ai_response` với JSON hợp lệ, phản
  hồi rác không parse được, và ngày sai định dạng (`32/13/2026`,
  `"tuần sau"`) — đều trả kết quả rỗng an toàn, không raise lỗi.

## [1.31.0] - 2026-08-17

### Thêm mới (từ mẫu mail thông báo sinh hoạt lớp chủ nhiệm)
- **Khoảng "từ ngày X - Y" không cần nhãn "Thời gian:"**: mail liệt kê
  nhiều đợt kiểu `+ Đợt 1: từ ngày 20/04/2026 - 23/04/2026 (...)` giờ
  tách được thành sự kiện CẢ NGÀY riêng cho từng đợt (hàm mới
  `parse_date_ranges`), không còn bị bỏ sót vì thiếu khuôn "Thời gian:"
  chuẩn.
- **Hạn kế thừa giờ khi tỉnh lược**: `trước 17h00 ngày 29/04/2026 (đợt
  1) và 22/05/2026 (đợt 2)` — mốc thứ 2 (`22/05/2026`) giờ được nhận ra
  là hạn riêng, **kế thừa giờ 17:00** từ mốc đứng trước trong cùng câu,
  thay vì bị bỏ qua vì không có từ khóa báo hạn đứng ngay trước nó.

### Xác nhận không cần sửa (đối chiếu mẫu mail thật)
- Mail có dấu phẩy xen giữa giờ và "ngày" (`07h30, ngày 22/8/2026`) đã
  hoạt động đúng từ trước — `_RE_GIO` và `_RE_NGAY` tìm độc lập trong
  cùng chuỗi, không đòi hỏi 2 cụm phải liền kề nhau.
- Mail thông báo hành chính chung không có mốc ngày theo khuôn nào
  (vd "chuyển phòng học ngày 17.8.2026" — ngày viết dấu chấm) **cố ý
  không lên Calendar**, đúng nguyên tắc "thà trống còn hơn sai"; ngày
  dạng chấm không được thêm vào bộ nhận dạng vì rủi ro khớp nhầm số
  công văn/văn bản cao hơn lợi ích.

### Kiểm tra không hồi quy
- Test lại đủ khoảng ngày qua nhãn "Thời gian:" (`ngày 22–23/10/2026`),
  hạn đơn giản (`trước ngày 2026-08-06`), và mail seminar 2 NCS chung
  giờ/phòng — không đổi kết quả so với 1.30.0.

## [1.30.0] - 2026-08-09

### Thêm mới (từ mẫu mail góp ý dự thảo)
- **Hạn kèm GIỜ**: `trước 11h00 ngày 12/8/2026`. Trước đây regex đòi cụm `trước ngày` nên bỏ sót hoàn toàn dạng có giờ xen giữa. Nay `trước` đứng một mình cũng tính (vẫn an toàn vì bắt buộc có ngày trong vòng 25 ký tự).
- Hạn có giờ tạo **sự kiện đúng giờ đó (30 phút)** thay vì cả ngày — nhắc sát hạn hơn; tiêu đề dạng `Hạn 11:00: <tiêu đề mail>`.
- Kiểm chứng không nhầm **ngày công văn** (`Công văn số 3115/ĐHĐN-CTSVDNTT ngày 07/8/2026`) thành hạn.
- Test lại cả 5 mẫu mail thật (góp ý dự thảo, đăng ký đề tài, họp chi bộ, mời phản biện, hội thảo) — không hồi quy.

## [1.29.2] - 2026-08-09

### Thêm mới
- **Lớp sinh hoạt** (`lop_sinh_hoat`) cho ô chọn Sinh viên. Thông tin này không có trong bảng danh sách thường mà nằm ở chế độ xem ảnh (`AH=true`), nên khi chọn lớp sẽ gọi thêm 1 request và ghép theo mã sinh viên.
- Dữ liệu gốc ở chế độ đó còn có **ngày sinh** — cố ý KHÔNG đọc, vì chỉ cần lớp sinh hoạt để phân biệt sinh viên trùng tên.

## [1.29.1] - 2026-08-09

### Thêm mới
- **Số thứ tự sinh viên trong lớp** (`stt`): hiện ngay trong ô chọn (`12. Nguyễn Văn A (103…)`) và có trong thuộc tính entity — tiện đối chiếu với danh sách lớp in ra giấy.

## [1.29.0] - 2026-08-09

### Thêm mới
- Ô chọn **Sinh viên** có thêm thuộc tính `dien_thoai` (số của sinh viên).

### Vẫn giữ nguyên giới hạn
- **SĐT người nhà** và **địa chỉ cư trú** trong bảng gốc vẫn KHÔNG được đọc.
- Lưu ý trong tài liệu: Home Assistant không phân quyền theo entity nên mọi tài khoản HA đều xem được số điện thoại này.

## [1.28.2] - 2026-08-09

### Sửa lỗi
- **Lớp có nhóm con (hậu tố A/B) không lấy được sinh viên**: mã lớp dạng `1033910.2610.23.20A` bị hàm chuẩn hoá xoá mất chữ cái cuối thành `103391026102320`, sai với mã hệ thống yêu cầu. Nay chỉ bỏ dấu chấm/khoảng trắng, giữ nguyên hậu tố chữ.

### Chẩn đoán
- Ô chọn **Sinh viên** có thêm thuộc tính `ma_lop_da_goi` và `trang_thai` (`đang tải…` / `đã tải N sinh viên` / `tải được nhưng không đọc ra sinh viên nào` / `lỗi: …`) — xem ngay trong more-info, không phải đào log.

## [1.28.1] - 2026-08-06

### Sửa lỗi
- **Chọn lớp xong nhưng danh sách sinh viên rỗng.** Bảng lịch giảng dạy hiển thị mã lớp có dấu chấm (`1033580.2610.24.21`), trong khi endpoint danh sách sinh viên chỉ nhận dạng liền 15 chữ số (`103358026102421`) — truyền sai định dạng nên trả về rỗng. Đã chuẩn hoá mã lớp trước khi gọi.
- Thêm cảnh báo trong log khi tải được nhưng không đọc được sinh viên nào, để lần sau khoanh vùng nhanh.

### Thêm mới
- **Ảnh hiện ngay trên entity** qua `entity_picture`: bấm vào ô chọn sinh viên là thấy ảnh, không bắt buộc phải tự thêm thẻ Markdown. Vẫn chỉ là đường dẫn — HA không tải, không lưu ảnh.

## [1.28.0] - 2026-08-06

### Thêm mới
- **Xem nhanh ảnh sinh viên** cho `dut_lichgiangday`: 2 ô chọn `Lớp` → `Sinh viên`, thuộc tính `anh_url` trỏ tới ảnh trên máy chủ trường; hiển thị bằng thẻ Markdown trên dashboard.
- `parse_student_list()` + `anh_sinh_vien_url()` (mã SV có 2 số năm ở vị trí 4-5, trùng tên thư mục ảnh: `103230219` -> `/ImageSV/23/`).

### Về dữ liệu cá nhân (chủ ý thiết kế)
- **Không tải, không lưu ảnh**: chỉ dựng đường dẫn, trình duyệt tải thẳng từ máy chủ trường. Tránh việc tạo kho ảnh sinh viên trong Home Assistant, đặc biệt tránh `/config/www/` vốn được phục vụ công khai không cần đăng nhập.
- **Chỉ đọc mã số + họ tên**. Bảng gốc còn có số điện thoại sinh viên, số điện thoại người nhà và địa chỉ cư trú — các cột này không được đọc.
- Danh sách chỉ nằm trong bộ nhớ, chỉ tải khi người dùng chủ động chọn lớp.

## [1.27.3] - 2026-08-06

### Thêm mới (từ mẫu mail thông báo đăng ký đề tài)
- **Nhận dạng hạn có chữ đệm**: `Hạn nộp chậm nhất ngày 9/8/2026` — regex cũ đòi ngày phải đứng sát từ khóa nên trượt. Bổ sung cả từ khóa `chậm nhất`, `hạn đăng ký`, `hạn gửi`.
- **Chỉ đọc phần MỚI NHẤT của mail chuyển tiếp** (cắt tại dòng `Từ:`/`From:` hoặc đường kẻ ngang) khi tìm mốc hạn. Cần thiết vì đơn vị trung gian thường đặt hạn sớm hơn hạn gốc: Khoa yêu cầu nộp trước **9/8**, thông báo gốc của Phòng ghi **10/8** — hạn áp dụng cho người nhận là 9/8. Trước đây tạo cả 2 sự kiện. Nếu phần mới không có mốc nào thì mới quét toàn bộ.
- Kiểm chứng không nhầm **ngày văn bản** thành hạn: `Thông báo số 3641/TB-ĐHBK ngày 13/7/2026` bị bỏ qua đúng.
- Test lại cả 4 mẫu mail thật (thông báo, họp có giờ, mời phản biện, hội thảo) — đều tách đúng, không hồi quy.

## [1.27.2] - 2026-08-06

### Riêng tư
- **Xóa toàn bộ thông tin cá nhân khỏi dữ liệu mẫu và tài liệu.** Trước đây form cấu hình điền sẵn tên người thật và nhãn ô tài khoản ghi ví dụ là tài khoản/email thật — những thứ này hiện ngay trên giao diện nên dễ lọt vào ảnh chụp màn hình khi báo lỗi, và tài liệu thì công khai trên GitHub.
  - Gợi ý ô từ khóa: đổi thành `Tên nhóm 1: từ khóa, từ viết tắt`.
  - Nhãn ô tài khoản: bỏ ví dụ, chỉ còn `Tài khoản cổng cb.dut.udn.vn` / `Địa chỉ email`.
  - README, CHANGELOG, docstring: thay tên người/địa chỉ email thật bằng tên giả (`Nguyễn Văn A`, `user@dut.udn.vn`...).

## [1.27.1] - 2026-08-06

### Sửa lỗi
- **Sự kiện cả ngày lọt sang ngày kế tiếp** (hạn phản biện 06/08 hiện cả ở danh sách 07/08). Nguyên nhân: cả **5 Calendar** đều lọc bằng `event.end >= start_date and event.start <= end_date`, trong khi Home Assistant đặt `end` của sự kiện cả ngày là **00:00 ngày hôm sau (không bao gồm)** — đúng bằng mốc bắt đầu của khoảng ngày kế tiếp, nên bị tính là "có giao nhau".
- Đã đổi sang đúng quy ước `event.start < end_date and event.end > start_date` cho toàn bộ Calendar (Lịch tuần, Coi thi, Nhập điểm, Lịch dạy, Email). Calendar `Nhập điểm` còn được sửa thêm: trước đó so sánh trực tiếp `date` với `datetime` thay vì qua hàm chuyển đổi.

## [1.27.0] - 2026-08-06

### Thêm mới (từ 2 mẫu mail thật của người dùng)
- **Nhận ngày kiểu ISO** `2026-07-26` (mail hệ thống tạp chí tự sinh) bên cạnh `4/8/2026`.
- **Mốc hạn trong câu văn**: `trước ngày X`, `hạn chót`, `hạn nộp`, `hạn cuối` — mail mời phản biện không có dòng `Thời gian:` nên trước đây không lên lịch được gì. Mỗi mốc thành 1 sự kiện cả ngày, mô tả kèm câu chứa mốc để biết hạn đó là hạn gì.
- **Danh sách mốc dạng `Nhãn: ngày`** (mail thông báo hội thảo liệt kê `Mời gửi bài: 01/7/2026`, `Hạn nộp tóm tắt (Abstract): 31/8/2026`...) — tiêu đề sự kiện lấy đúng nhãn.
- **Sự kiện cả ngày / nhiều ngày**: `Thời gian: ngày 22–23/10/2026` (hội thảo không nêu giờ) → sự kiện cả ngày trải đúng 2 ngày, thay vì bỏ qua như trước.
- Nhận `Địa điểm tổ chức:` (trước chỉ nhận đúng `Địa điểm:`) và các dòng có dấu đầu mục `•`.

### Kiểm chứng
- Test lại cả 3 mẫu mail thật: họp chi bộ (có giờ), mời phản biện (2 mốc hạn ISO), hội thảo ISAT-25 (khoảng ngày + 5 mốc) — đều tách đúng, không hồi quy mẫu cũ.

## [1.26.0] - 2026-08-05

### Thay đổi
- **Đổi định dạng tiêu đề sự kiện `Lịch dạy`**: `[Tên] dạy môn: <môn>, phòng: <phòng>, tiết <n> (x tiết)` — rõ nghĩa hơn kiểu ngăn cách bằng dấu `·` trước đây.
- **Tên giảng viên luôn hiện**, kể cả khi không theo dõi ai khác (trước đây chỉ hiện khi có bật theo dõi giảng viên khác nên lịch của chính mình bị trống tên).
- Tên được **suy luận 1 lần rồi nhớ lại** trong bộ nhớ coordinator — tránh tải lại danh sách lớp cả khoa (~170KB) ở mỗi chu kỳ quét.

## [1.25.3] - 2026-08-05

### Sửa lỗi (tìm ra nguyên nhân gốc nhờ HAR năm học 2026-2027)
- **HTML biểu đồ năm học của trường bị lệch**: tổng `colspan` hàng THÁNG = **51** trong khi có **52 ô ngày**. Parser trước đòi khớp tuyệt đối nên trả về rỗng (lịch dạy trống hẳn); bản 1.25.2 cắt bớt cho khớp thì tháng **trôi lệch dần** về sau — vẫn sai.
- Đã bỏ hoàn toàn việc dựa vào `colspan`: chỉ lấy **tháng đầu tiên** làm mốc rồi duyệt dãy NGÀY — hễ số ngày nhỏ hơn ngày trước là sang tháng mới. Cách này tự sửa được mọi sai lệch colspan của trường.
- **Năm được theo dõi trực tiếp** (tăng khi tháng vòng 12→1) thay vì suy từ tháng: năm học kéo dài quay lại tháng 8 nên tuần cuối (02/08) thuộc năm SAU — suy theo tháng cho ra sai năm.
- Kiểm chứng cả 2 năm học: mỗi năm 52 tuần, **mọi tuần cách nhau đúng 7 ngày**, HK 2520 tuần 1 = 04/08/2025, HK 2610 tuần 1 = 10/08/2026, tuần cuối = 02/08/2027. Lịch dạy HK1 26-27 dựng được **48 buổi**, trong đó **3 buổi ngày 18/08/2026** — đúng như trên trang trường.

## [1.25.2] - 2026-08-05

### Sửa lỗi (log người dùng chỉ đúng nguyên nhân)
- **Không parse được biểu đồ năm học của học kỳ mới** (`HK 2610: đọc biểu đồ năm học nhưng KHÔNG parse được tuần nào`). Parser cũ đọc hàng tháng/ngày **theo vị trí ô** và bắt buộc số ô tháng phải bằng số ô ngày; bảng của học kỳ khác có thêm/bớt ô nhãn nên lệch, và khi lệch thì **trả về rỗng toàn bộ**. Nay lọc theo **nội dung ô** (ô tháng chứa chữ "Tháng", ô ngày chỉ gồm chữ số) và nếu vẫn lệch thì ghép theo số nhỏ hơn thay vì bỏ trắng. Có log rõ số ô đọc được khi thất bại.
- **Nguồn dự phòng bị dùng sai năm học** — hậu quả nặng hơn: `lichtuan` chỉ có tuần của **năm học hiện tại**, nhưng vẫn bị áp cho HK1 2026-2027 → sinh **48 buổi dạy lệch nguyên 1 năm** (05/08/**2025**). Nay chỉ dùng dự phòng khi **đúng năm học**; khác năm thì bỏ qua và ghi lỗi rõ ràng — thà trống còn hơn hiện dữ liệu sai.

## [1.25.1] - 2026-08-05

### Chẩn đoán
- Sensor đếm buổi dạy có thêm thuộc tính chẩn đoán: `hoc_ky_theo_doi`, `hoc_ky_lay_duoc_du_lieu`, `so_lop_co_tkb`, `tong_so_buoi_day`, `buoi_dau_tien`, `buoi_cuoi_cung` — xem trực tiếp trong Developer Tools để biết lịch trống là do chưa chọn học kỳ, không lấy được dữ liệu, hay không dựng được buổi.
- Thêm log: số tuần đọc được và ngày của tuần 1 theo từng học kỳ; cảnh báo rõ khi có lớp nhưng không dựng được buổi dạy nào.

## [1.25.0] - 2026-08-05

### Sửa lỗi / Thêm mới (từ phản hồi thực tế)
- **Trùng sự kiện cuộc họp**: cùng một cuộc họp tạo ra 3 sự kiện (forward 2 lần + 1 bản giờ cũ đã bị đính chính). Nay gom theo tiêu đề đã bỏ tiền tố `Fw:`/`Re:`, chỉ giữ bản của mail **nhận gần nhất** — forward nhiều lần chỉ còn 1 sự kiện, mail đính chính tự thay giờ cũ.
- **Người gửi sai với mail chuyển tiếp**: header `From` là người *chuyển tiếp* (chính bạn), không phải người gửi thật. Nay lấy người gửi **gốc** từ dòng `Từ:`/`From:` trong phần trích dẫn, mô tả hiện cả hai.
- **Thêm tiền tố `[Nhóm từ khóa]`** vào tiêu đề sự kiện email, giống lịch tuần — phân biệt khi dùng nhiều nhóm từ khóa khác nhau. Tiêu đề cũng bỏ `Fw:`/`Re:` cho gọn.

### Ghi chú
- Nhóm từ khóa của email dùng **chung định dạng và chung cơ chế so khớp** với `dut_lichtuan` (mỗi dòng `Nhãn: biến thể 1, biến thể 2`) — cùng dùng `parse_keyword_groups`.

## [1.24.0] - 2026-08-05

### Thêm mới
- **Calendar `Email`: tự tạo sự kiện cuộc họp từ mail** — tách `Thời gian` / `Địa điểm` / `Thành phần` bằng **quy tắc (regex), không dùng AI**, nên không gửi nội dung mail ra dịch vụ ngoài và không tốn quota.
  - Nhận nhiều khuôn giờ: `14h30`, `8h`, `14:00`, `9 giờ 30`; ngày `4/8/2026`, `05/09/2026`.
  - **Xử lý đúng mail đính chính**: mail trả lời trích lại mail cũ bên dưới với giờ CŨ (vd bản mới 14h30 nhưng bản trích ghi 15h00) — parser chỉ lấy lần xuất hiện ĐẦU TIÊN (phần trên cùng = nội dung mới nhất). Test bằng mail thật của người dùng: ra đúng 14:30.
  - Mail không tách được đủ ngày+giờ thì không lên lịch, vẫn báo bình thường — tránh đặt sai giờ.
  - Sự kiện mặc định dài 60 phút (mail mời họp hầu như không ghi giờ kết thúc).
  - Chỉ lưu phần đã tách vào `.storage`, không lưu toàn văn nội dung mail.

## [1.23.1] - 2026-08-05

### Tài liệu
- Làm rõ: "Chỉ quét email chưa đọc" và "Số mail gần nhất" hoạt động theo kiểu **VÀ** — bật tick + để 50 nghĩa là quét **50 mail chưa đọc mới nhất** (lọc `UNSEEN` trước, cắt 50 mail mới nhất sau). Bước lọc chỉ lấy danh sách ID nên hộp thư nhiều nghìn mail chưa đọc không làm lần quét nặng thêm.

## [1.23.0] - 2026-08-05

### Thêm mới
- **Tùy chọn "Chỉ quét email chưa đọc"** cho `dut_mail` (mặc định tắt). Bật thì dùng cờ IMAP `UNSEEN` — nhẹ hơn nhiều với hộp thư lớn, nhưng mail mở ở nơi khác trước khi HA quét sẽ bị bỏ sót; tắt thì quét N mail gần nhất rồi khử trùng theo `Message-ID` (an toàn, không bỏ sót). Cả 2 chế độ đều không đánh dấu đã đọc và không xóa mail.
- (Ô "Số mail gần nhất quét mỗi lần", mặc định 50, đã có sẵn trong form từ 1.22.0.)

## [1.22.2] - 2026-08-05

### Sửa lỗi
- **Lần quét email đầu tiên bắn thông báo hàng loạt cho mail cũ**: lịch sử còn rỗng nên mọi mail khớp từ khóa trong cửa sổ quét đều bị coi là "mới". Nay lần quét đầu chỉ **nạp nền** (ghi vào lịch sử, hiện trên sensor) và **không gửi thông báo**; từ lần quét thứ hai trở đi mới cảnh báo mail mới.

## [1.22.1] - 2026-08-05

### Sửa lỗi (người dùng phát hiện: chọn HK1 26-27 nhưng không thấy buổi dạy nào)
- **Bảng quy đổi tuần học bị dùng chung cho mọi học kỳ.** Code cũ chỉ dựng bảng từ **học kỳ đầu tiên** đọc được rồi áp cho tất cả. Khi chọn nhiều học kỳ khác **năm học** (vd HK2 2025-2026 + HK1 2026-2027), lớp của năm sau bị quy ra ngày của năm trước — **lệch đúng 1 năm** (tuần 2 của HK 2610 là 11/08/**2026** nhưng bị tính thành 11/08/**2025**), nên không có buổi nào rơi vào tuần hiện tại/tuần sau.
- Đã sửa: dựng bảng quy đổi **riêng cho từng học kỳ**; áp dụng cho cả lịch của mình lẫn lịch giảng viên khác. Học kỳ nào không đọc được biểu đồ thì ghi cảnh báo rõ ràng thay vì âm thầm dùng bảng sai; nguồn dự phòng `lichtuan` chỉ dùng khi thiếu và có cảnh báo (vì chỉ đúng cho năm học hiện tại).

## [1.22.0] - 2026-08-05

### Thêm mới
- **Loại nguồn thứ 5: `dut_mail` — đọc & lọc email qua IMAP**, dùng lại nguyên cơ chế so khớp từ khóa của `dut_lichtuan` (biến thể viết tắt/chuỗi con, chuẩn hóa Unicode NFC).
  - Giải mã header MIME trước khi lọc — tiêu đề tiếng Việt thường ở dạng `=?UTF-8?B?...?=`, không giải mã thì lọc luôn trượt.
  - Kết nối **chỉ đọc**: không đánh dấu đã đọc, không xóa, không di chuyển mail.
  - **Không dùng cờ `UNSEEN`**: nếu mở mail trên điện thoại trước thì mail thành "đã đọc" và bị bỏ sót; thay vào đó quét N mail gần nhất rồi khử trùng theo `Message-ID`.
  - Chỉ báo mail mới, lưu lịch sử 30 ngày, đổi từ khóa thì quét lại từ đầu.
  - Sensor: tổng + theo từng nhóm từ khóa + đếm Hôm nay/Tuần này/Tháng này.
- Module `mail_client.py` thuần Python (test độc lập không cần HA) và `coordinator_mail.py`.

### Lưu ý
- Gmail cần bật Xác minh 2 bước rồi tạo **App Password**; HA lưu mật khẩu trong `.storage` nên dùng App Password (thu hồi riêng được), đừng dùng mật khẩu Gmail chính.

## [1.21.0] - 2026-08-05

### Thêm mới
- **Tiêu đề sự kiện `Lịch dạy` có thứ tự tiết và số lượng tiết**: `Điều khiển tự động trên động cơ · H108 · tiết 9-10 (2 tiết)`. Trước đây thông tin tiết chỉ nằm trong phần mô tả, phải bấm vào mới thấy.
- Mỗi buổi dạy có thêm trường `so_tiet` (buổi thường tính từ khoảng tiết; buổi dạy bù lấy đúng số tiết đã đăng ký). Kiểm chứng dữ liệu thật: 0 buổi thiếu trường này.

## [1.20.3] - 2026-08-05

### Sửa lỗi
- **Calendar `Lịch dạy` không hiện icon** (ô trống trong danh sách lịch). Nguyên nhân: dùng `mdi:teach`, nhưng Material Design Icons đã **đổi tên icon này thành `human-male-board`** nên tên cũ không còn tồn tại và HA không vẽ được gì. Đã bỏ icon tùy chỉnh để dùng **icon mặc định chuẩn của Home Assistant** cho entity calendar.
- Rà soát toàn bộ icon MDI đang dùng, đối chiếu danh sách icon đã bị đổi tên/gỡ bỏ của MDI: không còn tên lỗi thời nào khác.

## [1.20.2] - 2026-08-05

### Sửa lỗi
- **Buổi dạy của chính mình không có tên** trong khi buổi của người khác có `[Tên]`, nhìn lịch dễ tưởng là "không rõ của ai". Nay khi có theo dõi thêm người khác, buổi của bạn cũng được gắn tên cho nhất quán (không theo dõi ai thì vẫn không hiện tiền tố, tránh thừa).
- Thêm `infer_self_name_from_khoa()`: suy luận tên hiển thị của tài khoản bằng cách đối chiếu mã lớp mình dạy (từ `ctrLichGiangDay`, chỉ có mã lớp) với danh sách lớp của khoa (`LopHPKH`, có tên giảng viên). Khoa của mình lấy từ 3 số đầu tài khoản theo quy ước mã của trường. Test dữ liệu thật: suy ra đúng "Nguyễn Văn A" từ 10 lớp.
- Thêm cache theo (học kỳ, khoa) để không tải trùng danh sách lớp khoa (~170KB/lần).

## [1.20.1] - 2026-08-05

### Sửa lỗi
- **Danh sách lịch hiện tên lặp** (`DUT Calendar - Lịch giảng dạy Lịch dạy`, `DUT Calendar - Coi thi Coi thi`...). Bản sửa cũ (1.5.1) đặt `has_entity_name = False` chỉ có tác dụng ở trang thiết bị, danh sách Calendar vẫn ghép "tên thiết bị + tên entity". Nay đặt `has_entity_name = True` + `name = None` để entity **lấy thẳng tên thiết bị**, hiển thị đúng 1 lần.
- Đổi tên thiết bị cho gọn/đúng: `DUT Calendar - Hạn nộp điểm` -> **`DUT Calendar - Nhập điểm`**, `DUT Calendar - Lịch giảng dạy` -> **`DUT Calendar - Lịch dạy`**. Tên thiết bị trong `sensor.py` và `calendar.py` đã đối chiếu khớp nhau (nếu lệch, HA sẽ tạo 2 thiết bị trùng).

## [1.20.0] - 2026-08-05

### Thay đổi (làm rõ 2 loại hạn dễ nhầm)
- **Phân biệt rõ "hạn NHẬP điểm" và "hạn NỘP BẢN IN bảng điểm"** — hai việc khác hẳn nhau (nhập trên web vs in giấy nộp về Phòng Đào tạo) nhưng nhãn cũ gọi chung chung ("Hạn điểm giữa kỳ", "Nộp bảng điểm giữa kỳ") gây hiểu nhầm.
  - Nhãn mới ghi rõ: `Hạn nhập điểm ...`, `Hạn đính chính điểm ...`, `Hạn nộp bản in bảng điểm ...`.
  - Mỗi mốc hạn có thêm trường **`loai_han`**: `nhap_diem` | `dinh_chinh` | `nop_ban_in`.
  - Sensor `Cần nhập điểm` có thêm 3 danh sách tách riêng: `can_nhap_diem`, `can_dinh_chinh`, `can_nop_ban_in`.
- Kiểm chứng dữ liệu thật HK2 2025-2026: 18 mốc nhập điểm, 17 mốc đính chính, 1 mốc nộp bản in (các ô "Chưa đặt hạn" được bỏ qua đúng vì không phải ngày).

## [1.19.3] - 2026-08-05

### Thay đổi
- **Ẩn các ô cấu hình không dùng tới ở từng loại nguồn** (trước đây cả 3 loại dùng chung 1 form nên hiện thừa):
  - **Thời lượng ca thi**: chỉ còn ở `dut_coithi` — dùng để tính giờ kết thúc ca thi vì trang trường chỉ cho giờ bắt đầu. Hai loại kia không dùng.
  - **Notify service**: chỉ còn ở `dut_coithi` (báo ca thi mới) và `dut_deadline_diem` (báo hạn thay đổi); `dut_lichgiangday` không gửi thông báo nên đã bỏ.

## [1.19.2] - 2026-08-05

### Sửa lỗi
- **`TypeError: apply_bao_nghi() takes 2 positional arguments but 4 were given`** khiến entry `dut_lichgiangday` không nạp được. Nguyên nhân: khi thêm import `apply_bao_nghi`, chuỗi tìm-thay `"    build_teaching_events,"` khớp trúng cả **phần cuối của dòng gọi hàm** (vốn thụt sâu hơn), nên tên hàm bị chèn nhầm vào lời gọi. Đã khôi phục lời gọi đúng.
- Bổ sung kiểm tra tự động bằng AST: đối chiếu số tham số của **mọi** lời gọi `async_add_executor_job(fn, ...)` với chữ ký hàm thật trong `parser_exam`/`parser_public` — hiện 0 lời gọi sai. Cùng với đó quét toàn bộ file tìm dòng bị chèn sai thụt lề.

## [1.19.1] - 2026-08-05

### Sửa lỗi (bản 1.19.0 KHÔNG dùng được, hãy cập nhật ngay)
- **Entry `dut_lichgiangday` không khởi tạo được** — `__init__.py` chưa nhận loại thứ 4 nên báo `Loại config entry không hợp lệ` và entry lỗi ngay khi thêm.
- **Config flow lỗi ở bước chọn khoa** — khối phương thức dành cho OptionsFlow bị chèn nhầm vào ConfigFlow (dòng neo trùng ở cả 2 class), khiến ConfigFlow gọi `self._config_entry` vốn không tồn tại. Đã tách đúng: ConfigFlow dùng `_pending_data`, OptionsFlow dùng `_config_entry`; kiểm tra bằng AST xác nhận không còn phương thức trùng tên trong cùng class.

## [1.19.0] - 2026-08-05

### Thêm mới
- **Theo dõi lịch dạy của giảng viên khác** cho `dut_lichgiangday` — trước đây không làm được vì `ctrLichGiangDay` chỉ trả lớp của chính tài khoản. Nay dùng **danh sách lớp học phần của cả khoa** (`E=LopHPKH&HK=<hk>&KHOA=<mã khoa>`), có đủ giảng viên + thời khóa biểu. Kiểm chứng: lọc chính tài khoản từ nguồn khoa ra **đúng 10 lớp**, khớp hoàn toàn endpoint cá nhân.
- UI giống lịch coi thi: tick bật ở bước đăng nhập → chọn **Khoa** (dropdown thật, 40 khoa) → chọn **tên** (nhiều người, gõ tìm). Có lựa chọn "Giữ nguyên"/"Xóa hết" tách bạch như bên coi thi.
- Sự kiện của người khác hiện tiền tố `[Tên giảng viên]` trong tiêu đề và dòng "Giảng viên" trong mô tả.

### Hạn chế đã biết (do nguồn dữ liệu)
- Lịch của người khác **không có báo nghỉ/dạy bù** và **không loại được tuần thi** (nguồn khoa không có 2 thông tin này) — chỉ là thời khóa biểu gốc. Lịch của chính bạn vẫn đầy đủ cả 2.

## [1.18.2] - 2026-08-05

### Thay đổi
- Đổi tên Calendar `Giảng dạy` -> **`Lịch dạy`** cho gọn.
- Tiêu đề sự kiện hỗ trợ tiền tố `[Tên giảng viên]` để phân biệt khi theo dõi thêm người khác (hiện chưa hiện vì tính năng theo dõi giảng viên khác cho lịch dạy còn chờ endpoint — xem ghi chú bên dưới); mô tả sự kiện cũng hiện dòng "Giảng viên" tương ứng.

### Chưa làm được (cần thêm dữ liệu)
- **Theo dõi lịch dạy của giảng viên khác**: endpoint `ctrLichGiangDay` chỉ trả về lớp của chính tài khoản đăng nhập, không có tham số lấy người khác (khác với lịch coi thi vốn có endpoint trả toàn bộ ca thi mọi cán bộ). Theo tài liệu, chức năng này nằm ở *[Đào tạo] → [Kế hoạch, thời khóa biểu] → [In thời khóa biểu]* (mục 2.2.7) hoặc *[Biểu đồ TKB Giảng viên]* (mục 2.2.8) và **cần phân quyền cán bộ quản lý**. Cần HAR của trang đó để triển khai.

## [1.18.1] - 2026-08-05

### Thay đổi
- **Rút gọn tiêu đề sự kiện Calendar `Giảng dạy`**: `Tên lớp · Phòng` (trước: `🚫 [Đã báo nghỉ] Tên lớp — P.Phòng`). Trạng thái nghỉ/bù chỉ còn icon `🚫`/`🔁` ở đầu; chữ mô tả đầy đủ chuyển hết vào phần mô tả sự kiện.

## [1.18.0] - 2026-08-05

### Thay đổi lớn
- **Tách lịch giảng dạy thành loại nguồn THỨ 4 riêng biệt: `dut_lichgiangday`** (trước đây nằm chung thiết bị với `dut_deadline_diem`). Có thiết bị riêng, Calendar `Giảng dạy` riêng, và 5 sensor đếm buổi lên lớp riêng. Hai loại giờ độc lập hoàn toàn: chọn loại nào thì chỉ tải dữ liệu của loại đó (loại lịch giảng dạy không tải danh sách ca coi thi, không tính hạn nộp điểm).

### Thêm mới
- **Áp dụng báo nghỉ / dạy bù vào lịch giảng dạy** (`E=ctrBaoNghi_GVList&HK=<mã HK>`). Tài liệu chính thức của trường có cảnh báo thời khóa biểu "không tuyệt đối chính xác" khi có thay đổi ngắn hạn — đây chính là dữ liệu bù đắp: buổi đã báo nghỉ hiện `🚫 [Đã báo nghỉ]` (giữ lại thay vì im lặng biến mất), buổi dạy bù được thêm đúng ngày/giờ/phòng với `🔁 [Dạy bù]`; bản ghi đã hủy báo nghỉ thì bỏ qua.
- `parse_bao_nghi()` + `apply_bao_nghi()` (parser_exam), test với dữ liệu thật: 7 bản ghi (3 nghỉ + 4 bù) của HK2 2024-2025.
- Sensor đếm buổi lên lớp không tính buổi đã báo nghỉ, có tính buổi dạy bù.

## [1.17.1] - 2026-08-05

### Sửa lỗi (phát hiện qua kiểm chứng chéo với biểu đồ thời gian giảng)
- **Calendar `Giảng dạy` sinh buổi dạy "ma" vào tuần thi giữa kỳ.** Chuỗi tuần trong thời khóa biểu BAO GỒM CẢ tuần thi (vd `22-27;31-40` — tuần 33 là tuần thi), nhưng tuần đó không lên lớp. Đối chiếu với tab *"Biểu đồ thời gian giảng ở năm học"*: tuần thi được đánh dấu `K` và không có số tiết. Lỗi ảnh hưởng **8/8 lớp** có thời khóa biểu (mỗi lớp 1 buổi ma).
- Đã sửa: loại tuần thi khỏi lịch dạy, lấy từ cột "Tuần thi" của bảng hạn nhập điểm (khớp đúng ô `K` trên biểu đồ). Kết quả: 123 → **115 buổi dạy**, khớp biểu đồ thực tế **8/8 lớp**.

## [1.17.0] - 2026-08-05

### Thay đổi (dựa trên tài liệu chính thức của Phòng Đào tạo)
- **Quy tắc mã học kỳ nay theo tài liệu chính thức** (*Hướng dẫn sử dụng website Hệ thống tác nghiệp*, mục 3.1 "Quy ước Mã"): `YY` = 2 số cuối năm đầu của năm học, `S` = học kỳ (1/2), `K` = kỳ **chính** (0) hay kỳ **phụ** (1). Trước đây suy luận từ dropdown nên chỉ xử lý được kỳ Hè (`S=2,K=1`); giờ xử lý đúng cả kỳ phụ của HK1 (`2511` → "Học kỳ 1 (phụ)"). Vẫn khớp 14/14 nhãn thật.
- **Bảng quy đổi tuần học → ngày nay lấy từ chính `cb.dut.udn.vn`** (tab *"Biểu đồ thời gian giảng ở năm học"*, `E=ctrLGD_KeHoach&SKH=<mã HK>`) thay vì phụ thuộc trang ngoài — cùng nguồn với thời khóa biểu nên chắc chắn khớp cách đánh số tuần. Vẫn giữ `lichtuan.dut.udn.vn` làm **dự phòng**. Đối chiếu 2 nguồn: **khớp 52/52 tuần**.

## [1.16.0] - 2026-08-05

### Thêm mới
- **Calendar `Giảng dạy`** — dựng các buổi lên lớp cụ thể (ngày + giờ + phòng) từ thời khóa biểu học kỳ. Test với dữ liệu thật: 8 lớp có TKB → **123 buổi dạy**, thứ/ngày khớp chính xác.
- `parse_all_weeks()` (parser_public): đọc ánh xạ **số tuần học → ngày Thứ Hai** từ dropdown công khai của `lichtuan.dut.udn.vn` (không cần đăng nhập). Chính xác hơn tự cộng 7 ngày từ tuần 1 vì năm học có **tuần ngắt quãng** (tuần 22 = 29/12/2025, tuần 28-30 nghỉ Tết, tuần 31 = 02/03/2026).
- `parse_tuan_hoc()` / `parse_tkb_slots()` / `build_teaching_events()` (parser_exam): phân tích chuỗi TKB dạng `22-27;31-40` và `T3,6-7,F109` (hỗ trợ nhiều buổi/tuần, cả Chủ nhật).
- Bảng giờ tiết học `TIET_START` trong `const.py` — trường không công bố dữ liệu chính thức dạng máy đọc, bảng theo quy ước thực tế, sửa được ở một chỗ nếu trường đổi giờ.

## [1.15.0] - 2026-08-05

### Thay đổi lớn
- **Đổi nguồn dữ liệu hạn nộp điểm sang trang "Kế hoạch giảng dạy & thi"** (`E=ctrLichGiangDay&SKH=<mã HK>`): **1 request cho cả học kỳ** thay vì ≈11 request (`ctrlLopHP` + `ctrlListHP` từng lớp). Nhanh hơn nhiều và nhiều dữ liệu hơn hẳn. Có **fallback tự động** về cách cũ nếu endpoint mới lỗi.
- **Biết được đã nhập điểm xong hay chưa** (cột "xác nhận lúc"/"đã xác nhận"): sensor `Cần nhập điểm` giờ **loại bỏ các mốc đã hoàn thành**, chỉ liệt kê việc còn phải làm — trước đây liệt kê cả mốc đã nhập xong nên không dùng để nhắc việc được. Calendar `Nhập điểm` đánh dấu `✓` cho mốc đã xong.
- **Theo dõi thêm loại hạn hoàn toàn mới: hạn NỘP BẢNG IN ĐIỂM** (giữa kỳ / thành phần / cuối kỳ / tổng hợp) — khác với hạn *nhập* điểm, trước đây integration không hề biết tới.
- Bổ sung hạn **đính chính điểm cuối kỳ**, tuần thi, gia hạn, trễ hạn.

### Kỹ thuật
- `parse_lich_giang_day()` đọc đủ 4 bảng của trang (lịch giảng dạy + hạn nhập điểm + nộp bảng điểm + thi chung), `lgd_to_grade_deadlines()` chuyển sang cấu trúc cũ để tương thích ngược.
- Xử lý đúng các cột dấu ✓ **rỗng về text** — trạng thái nằm ở class CSS `GridCellCenterCheck` / `GridCellDisable`; đọc theo text sẽ sai toàn bộ.

## [1.14.2] - 2026-08-05

### Thay đổi
- **Calendar `Nhập điểm`: đưa loại điểm lên trước tên môn** — `Hạn điểm giữa kỳ: Cảm biến & Kỹ thuật đo` thay vì `Cảm biến & Kỹ thuật đo: Hạn điểm giữa kỳ`, dễ quét mắt hơn khi nhiều mốc cùng ngày.
- **Thêm số nhóm lớp để phân biệt các lớp cùng tên môn.** Trước đây 2 nhóm khác nhau của cùng học phần (mã `...2419` và `...2420`) hiện thành 2 dòng trùng hệt nhau trên lịch, không biết đâu là lớp nào. Giờ hiện `(nhóm 24.19)` / `(nhóm 24.20)`, lấy từ 4 chữ số cuối của mã lớp 15 số. Sensor `Cần nhập điểm` cũng có thêm attribute `nhom`.

## [1.14.1] - 2026-08-05

### Thêm mới
- **Hiển thị tên học kỳ thay vì mã số.** Thêm `parser_exam.format_hoc_ky()`: mã `YYSK` → tên đọc được (`2521` → "Học kỳ Hè năm học 2025-2026"). Quy tắc suy ra từ dropdown thật của trường và **đối chiếu khớp 14/14 mã có thật** (`YY`=năm bắt đầu, `S`=1/2 học kỳ, `K`=0 kỳ chính / 1 kỳ Hè). Mã không khớp định dạng được giữ nguyên thay vì đoán sai.
- Áp dụng cho: attribute `hoc_ky_ten` của sensor `Cần nhập điểm`, attribute `hoc_ky` của sensor `Lịch coi thi`, và mô tả sự kiện của cả 2 Calendar `Coi thi`/`Nhập điểm`.

## [1.14.0] - 2026-08-05

### Thêm mới
- **Sensor `Cần nhập điểm`** cho `dut_deadline_diem` — phẳng hóa dữ liệu gốc (vốn lồng nhau theo học kỳ → lớp → từng loại điểm) thành **danh sách việc cần làm** dùng được ngay trong automation/template: state = số mốc chưa quá hạn (gộp cả 3 học kỳ đang theo dõi), kèm attributes `gan_nhat`, `hom_nay`, `trong_7_ngay`, `danh_sach` — mỗi mục có `mon`, `loai`, `ngay`, `con_lai_ngay`, `hoc_ky`, `ma_lop`.
- `build_deadline_events()` bổ sung `ten_lop`, `loai`, `ma_lop` vào mỗi mốc hạn (trước đây chỉ có chuỗi `summary` gộp sẵn, không tách được môn/loại điểm khi dùng trong template).
- README thêm ví dụ automation nhắc mỗi sáng khi có mốc hết hạn trong 7 ngày tới.

## [1.13.2] - 2026-08-05

### Thêm mới
- **Sensor `Hạn nộp điểm` có attributes giải thích khi state hiện `Unknown`.** Vì sensor này là `device_class: date` (state chỉ có thể là 1 ngày hoặc rỗng, không dùng được số 0), nên khi không còn mốc hạn nào sắp tới thì HA hiện `Unknown` — trước đây không phân biệt được với lỗi chưa lấy được dữ liệu. Giờ có attribute `trang_thai` với 3 giá trị rõ ràng: `con_han_sap_toi`, `da_qua_het_han` (mọi mốc đã qua), `chua_co_du_lieu`. Kèm `so_moc_sap_toi`, `so_moc_da_qua`, `han_gan_nhat_da_qua`.

## [1.13.1] - 2026-08-04

### Thêm mới
- **Tự động xóa sensor cũ không còn dùng khi đổi Options.** Trước đây `dut_lichtuan` tạo sensor theo từng nhóm từ khóa, nên khi xóa/đổi tên nhóm trong Options thì sensor của nhóm cũ nằm lại vĩnh viễn ở trạng thái "không khả dụng" (restored), gây rác trong danh sách entity. Giờ mỗi lần nạp lại entry sẽ tự gỡ khỏi entity registry các sensor không còn được tạo nữa. Áp dụng cho cả 3 loại; chỉ đụng tới entity domain `sensor` của đúng entry đó nên không ảnh hưởng Calendar hay entry khác.
- Việc dọn chạy TRƯỚC khi thêm sensor mới, để `entity_id` cũ được giải phóng — tránh trường hợp đổi tên nhóm rồi HA tự thêm hậu tố `_2` vào entity_id mới.

## [1.13.0] - 2026-08-04

### Thay đổi
- **`dut_coithi` — tiêu đề sự kiện Calendar giờ luôn có tên + vai trò (GT1/GT2) + phòng thi**, áp dụng cho CẢ ca của chính bạn lẫn ca của giảng viên khác (trước đây chỉ ca giảng viên khác mới có tên trong tiêu đề). Vd `[103-Nguyễn Văn A · GT1] Coi thi: Kỹ thuật điện - điện tử — Phòng F108`.
- Thêm `parser_exam.infer_self_name()`: suy luận tên hiển thị của tài khoản đăng nhập từ danh sách ca thi của chính mình — phát hiện quan trọng qua dữ liệu thật: cột "Cán bộ 1"/"Cán bộ 2" **không cố định vị trí** (có ca mình là CB1, có ca là CB2, tùy ai đăng ký trước), nên không thể giả định vị trí cố định như trước. Suy luận dựa trên tên duy nhất xuất hiện ở mọi ca — test đúng 100% với dữ liệu thật (11/11 ca).
- Thêm `parser_exam.duty_role()`: xác định 1 người là Cán bộ 1 hay 2 trong 1 ca cụ thể — dùng chung cho cả ca của chính mình lẫn ca giảng viên khác (xác định đúng người nào trong danh sách nhiều người theo dõi khớp với từng dòng, thay vì lấy tên đầu tiên bất kỳ).
- Sensor `Lịch coi thi` thêm attributes `ten`/`giam_thi_so`; thông báo ca thi mới cũng đồng bộ hiện tên+vai trò.

## [1.12.1] - 2026-08-04

### Sửa lỗi (UX gây nhầm lẫn, người dùng phát hiện)
- **Bước "chọn khoa" khi sửa Options có 2 cách "bỏ qua" trông giống nhau nhưng hệ quả khác hẳn** — dễ xóa nhầm danh sách đang theo dõi. Cụ thể trước đây: bỏ tick "Theo dõi thêm giảng viên khác?" ngay từ đầu thì GIỮ NGUYÊN dữ liệu, nhưng nếu đã vào bước chọn khoa rồi mới chọn "Không theo dõi thêm ai" thì lại XÓA HẲN — cùng ý định "không muốn đổi" nhưng 1 chỗ an toàn, 1 chỗ phá dữ liệu.
- Đã tách biệt rõ ràng thành **2 lựa chọn riêng** trong bước chọn khoa (chỉ hiện khi entry đã có sẵn người đang theo dõi): **"↩️ Giữ nguyên N người đang theo dõi, không đổi gì"** (an toàn, mặc định chọn sẵn) và **"🗑️ Xóa hết, không theo dõi ai"** (rõ ràng là hành động xóa). Không còn 1 lựa chọn duy nhất gánh 2 ý nghĩa khác nhau.

## [1.12.0] - 2026-08-04

### Thêm mới
- **`dut_coithi` — tick bật/tắt tính năng theo dõi giảng viên khác ngay ở bước đăng nhập gốc**: mặc định tắt, không tải gì thêm, không tốn thời gian. Chỉ khi tick bật mới đi qua các bước chọn khoa/tên (tải dữ liệu ~1MB). Khi sửa qua Options, nếu entry đã có sẵn giảng viên đang theo dõi thì tick tự mặc định bật; bỏ tick đi thì giữ nguyên lựa chọn hiện tại, không xóa.
- **`dut_lichtuan` — tiêu đề sự kiện Calendar có tiền tố `[Tên nhóm từ khóa]`** (vd `[Khoa Cơ khí Giao thông] Hội ý Ban Giám hiệu`), tương tự cách hiện `[Tên giảng viên]` bên `dut_coithi` — biết ngay mục nào khớp theo nhóm nào khi nhìn lịch.

### Sửa lỗi
- **Dọn code chết/lỗi từ phiên bản trước**: `async_step_hoi_theo_doi_gv` bị gọi nhưng chưa từng được định nghĩa (sót lại từ 1 lần chỉnh sửa dở dang) — sẽ gây lỗi crash khi cấu hình `dut_coithi` mới hoàn toàn qua ConfigFlow (không phải Options). Đã xóa code chết và thay bằng cơ chế tick hoàn chỉnh nêu trên.

## [1.11.2] - 2026-08-04

### Sửa lỗi (nguyên nhân thật của "danh sách khoa/tên không ổn định, lúc thiếu")
- **Tìm ra nguyên nhân chính xác** qua ảnh chụp thật của người dùng: danh sách khoa bị **thiếu hẳn khoa 103** (khoa của chính tài khoản đang cấu hình). Không phải do timeout (đã loại trừ ở 1.11.1) — mà do code chỉ lấy dữ liệu từ **1 học kỳ đầu tiên** trong số các học kỳ đã chọn (`selected[0]`), trong khi học kỳ đó có thể chưa có đủ dữ liệu coi thi cho mọi khoa (vd học kỳ mới chưa xếp lịch hết).
- Đã sửa: `_fetch_lecturer_directory()` giờ nhận **danh sách** học kỳ, tải và **gộp** dữ liệu từ TẤT CẢ học kỳ đã chọn (không chỉ 1) — khoa/tên xuất hiện ở BẤT KỲ học kỳ nào cũng sẽ có trong danh sách cuối cùng. Test mô phỏng xác nhận: học kỳ đơn lẻ thiếu khoa 103, gộp nhiều học kỳ thì đầy đủ 18 người khoa 103.
- Nếu 1 số học kỳ lỗi khi tải (mạng/timeout) nhưng học kỳ khác thành công, vẫn trả về danh sách gộp từ các học kỳ tải được — chỉ báo lỗi hẳn (None) khi TẤT CẢ học kỳ đều lỗi.

## [1.11.1] - 2026-08-04

### Sửa lỗi
- **Tải danh sách khoa/giảng viên (bước cấu hình `dut_coithi`) không ổn định**, lúc được lúc mất dữ liệu. Nguyên nhân: timeout 30s không đủ cho response ~1MB (`NCB=true&DDK=false&KHOA=ALL`) dưới mạng chậm/server tải, và khi lỗi thì code cũ **âm thầm bỏ qua** tính năng luôn (không cho biết lý do, không cho thử lại ngay). Đã sửa:
  - Tăng timeout riêng cho API này lên **90s** (các API khác trong file vẫn giữ 30s).
  - Tự động **thử lại 2 lần** trước khi báo lỗi hẳn, có log rõ nguyên nhân từng lần thử để chẩn đoán được qua HA logs.
  - Khi vẫn lỗi sau 2 lần thử: UI hiện rõ thông báo lỗi + nút **"🔄 Thử tải lại"** ngay tại chỗ (không phải thoát ra làm lại từ đầu), bên cạnh lựa chọn "Không theo dõi thêm ai" để bỏ qua nếu muốn.

## [1.11.0] - 2026-08-04

### Thay đổi
- **`dut_coithi` — chọn giảng viên khác qua UI thay vì gõ tay**: thêm 2 bước mới sau khi chọn học kỳ — chọn **Khoa** (rút gọn danh sách, hoặc bỏ qua/chọn tất cả) rồi chọn **tên** (nhiều lựa chọn, gõ để tìm kiếm). Tên lấy trực tiếp từ dữ liệu thật (`mã khoa-Tên`, vd `103-Nguyễn Văn A`), khớp **chính xác** thay vì kiểu chuỗi con như trước — tránh sai chính tả/khớp nhầm. Áp dụng cho cả khi thêm mới lẫn sửa qua Options. Vẫn đọc tương thích ngược cấu hình cũ (1 tên gõ tay) nếu entry chưa cấu hình lại theo cách mới.
- `parser_exam.py`: thêm `build_lecturer_directory()` (gom tên theo mã khoa từ dữ liệu thật) và `filter_exam_duty_by_lecturers()` (lọc theo danh sách, khớp chính xác) — test bằng dữ liệu thật (724 ca, 265 tên, 32 khoa).

## [1.10.0] - 2026-08-04

### Thêm mới
- **2 khoảng đếm mới: "Tuần này" và "Tuần sau"** (Thứ 2 → Chủ nhật) — áp dụng cho cả 3 loại (`dut_lichtuan`, `dut_coithi`, `dut_deadline_diem`), nâng tổng số khoảng đếm từ 3 lên 5 (Hôm nay/Ngày mai/Tuần này/Tuần sau/Tháng này).
- **`dut_lichtuan` — bộ sensor đếm riêng cho TỪNG NHÓM từ khóa**: trước đây chỉ có 1 bộ đếm TỔNG (gộp mọi nhóm); giờ mỗi nhóm từ khóa có thêm 5 sensor đếm riêng (vd "Nguyễn Văn A: Hôm nay"), bên cạnh bộ tổng vẫn giữ nguyên.

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

[Unreleased]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/compare/v1.30.0...HEAD
[1.30.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.30.0
[1.29.2]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.29.2
[1.29.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.29.1
[1.29.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.29.0
[1.28.2]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.28.2
[1.28.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.28.1
[1.28.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.28.0
[1.27.3]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.27.3
[1.27.2]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.27.2
[1.27.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.27.1
[1.27.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.27.0
[1.26.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.26.0
[1.25.3]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.25.3
[1.25.2]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.25.2
[1.25.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.25.1
[1.25.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.25.0
[1.24.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.24.0
[1.23.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.23.1
[1.23.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.23.0
[1.22.2]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.22.2
[1.22.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.22.1
[1.22.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.22.0
[1.21.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.21.0
[1.20.3]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.20.3
[1.20.2]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.20.2
[1.20.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.20.1
[1.20.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.20.0
[1.19.3]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.19.3
[1.19.2]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.19.2
[1.19.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.19.1
[1.19.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.19.0
[1.18.2]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.18.2
[1.18.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.18.1
[1.18.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.18.0
[1.17.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.17.1
[1.17.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.17.0
[1.16.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.16.0
[1.15.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.15.0
[1.14.2]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.14.2
[1.14.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.14.1
[1.14.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.14.0
[1.13.2]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.13.2
[1.13.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.13.1
[1.13.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.13.0
[1.12.1]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.12.1
[1.12.0]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.12.0
[1.11.2]: https://github.com/YOUR_GITHUB_USERNAME/dut_calendar/releases/tag/v1.11.2
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
