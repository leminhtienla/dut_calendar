"""Hằng số cho tích hợp DUT Calendar (gộp Lịch tuần công khai + Lịch coi thi/hạn nộp điểm)."""
from __future__ import annotations

DOMAIN = "dut_calendar"

# ---- Loại nguồn dữ liệu (mỗi config entry chọn đúng 1 loại) ----
CONF_TYPE = "type"
TYPE_LICHTUAN = "dut_lichtuan"  # lichtuan.dut.udn.vn - công khai, theo từ khóa
TYPE_COITHI = "dut_coithi"  # cb.dut.udn.vn - cần đăng nhập, lịch coi thi
TYPE_DEADLINE_DIEM = "dut_deadline_diem"  # cb.dut.udn.vn - cần đăng nhập, hạn nộp điểm

# =====================================================================
# Nguồn 1: Lịch tuần công khai (lichtuan.dut.udn.vn)
# =====================================================================
CONF_KEYWORDS = "keywords"
CONF_SCAN_INTERVAL = "scan_interval"  # phút
CONF_WEEKS_AHEAD = "weeks_ahead"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_UPDATE_MODE = "update_mode"
CONF_CLEAR_HISTORY = "clear_history"  # tick 1 lần để xóa sạch lịch sử đã lưu, tự tắt lại sau khi xóa

UPDATE_MODE_SMART = "smart"  # chỉ tuần hiện tại + tuần mới (từ thứ 6 trở đi)
UPDATE_MODE_FULL = "full"  # tuần hiện tại + weeks_ahead, mỗi lần quét
DEFAULT_UPDATE_MODE = UPDATE_MODE_FULL
# Từ thứ mấy trong tuần (0=Thứ 2 ... 6=Chủ nhật) thì bắt đầu coi là
# "cuối tuần" và quét thêm tuần kế tiếp ở chế độ smart. Thứ 6 = 4.
SMART_MODE_WEEKDAY_THRESHOLD = 4

DEFAULT_SCAN_INTERVAL_PUBLIC = 60
DEFAULT_WEEKS_AHEAD = 0
MIN_SCAN_INTERVAL_PUBLIC = 15
MAX_SCAN_INTERVAL_PUBLIC = 1440
MAX_WEEKS_AHEAD = 3

LICHTUAN_BASE_URL = "https://lichtuan.dut.udn.vn/home"
EVENT_MATCH_FOUND = f"{DOMAIN}_match_found"
MAX_STORED_HASHES_PUBLIC = 1000
# Giữ lại mục lịch tuần đã khớp bao nhiêu ngày SAU ngày diễn ra sự kiện,
# để Calendar/sensor vẫn còn dữ liệu khi duyệt lùi lại tuần trước, thay
# vì mất ngay khi trang chuyển sang tuần mới. Không giữ vô hạn để tránh
# phình to theo thời gian.
PUBLIC_HISTORY_RETENTION_DAYS = 14

# =====================================================================
# Nguồn 2: Lịch coi thi & hạn nộp điểm (cb.dut.udn.vn - cần đăng nhập)
# =====================================================================
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_HOC_KY = "hoc_ky"
CONF_EXAM_DURATION = "exam_duration"
CONF_EXTRA_LECTURER = "extra_lecturer"  # (cũ, giữ để đọc tương thích ngược) 1 tên dạng text tự do
CONF_EXTRA_LECTURERS = "extra_lecturers"  # danh sách tên đã chọn qua UI khoa/tên (chỉ dut_coithi)
CONF_CONFIGURE_EXTRA_LECTURER = "configure_extra_lecturer"  # tick bật/tắt bước chọn khoa/tên (transient, không dùng để lọc)

DEFAULT_SCAN_INTERVAL_EXAM = 120
DEFAULT_EXAM_DURATION = 90
MIN_SCAN_INTERVAL_EXAM = 30
MAX_SCAN_INTERVAL_EXAM = 1440

CB_BASE_URL = "https://cb.dut.udn.vn"
CB_LOGIN_URL = f"{CB_BASE_URL}/default.aspx"
CB_EXAM_AJAX_URL = f"{CB_BASE_URL}/WebAjax/evHocPhanBrowse.aspx"
CB_PAGE_COITHI_URL = f"{CB_BASE_URL}/PageCNDKCoiThi.aspx"
CB_GRADE_DEADLINE_AJAX_URL = f"{CB_BASE_URL}/WebAjax/evLopHP_Load.aspx"
CB_PAGE_LTDIEM_URL = f"{CB_BASE_URL}/PageLTDiem.aspx"
CB_PAGE_DIEMHP_URL = f"{CB_BASE_URL}/PageDiemHP.aspx"

LOGIN_FIELD_BUTTON = "_ctl0:Main_panLogin:Login_btnLogin"
LOGIN_BUTTON_VALUE = " Đăng nhập "

EVENT_NEW_EXAM_DUTY = f"{DOMAIN}_new_exam_duty"
EVENT_GRADE_DEADLINE_CHANGED = f"{DOMAIN}_grade_deadline_changed"
MAX_STORED_HASHES_EXAM = 500

# =====================================================================
# Chung
# =====================================================================
STORAGE_VERSION = 1
STORAGE_KEY_TEMPLATE = f"{DOMAIN}_{{entry_id}}_seen"
