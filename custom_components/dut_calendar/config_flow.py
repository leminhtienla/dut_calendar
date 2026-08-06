"""Config flow cho DUT Calendar — menu 3 loại, 2 bước cho loại cần đăng nhập
(bước 1: xác thực tài khoản, bước 2: chọn học kỳ từ danh sách thật)."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api_exam import CBDutAuthError, CBDutClient
from .const import (
    CONF_CLEAR_HISTORY,
    CONF_CONFIGURE_EXTRA_LECTURER,
    CONF_EXAM_DURATION,
    CONF_EXTRA_LECTURER,
    CONF_EXTRA_LECTURERS,
    CONF_HOC_KY,
    CONF_KEYWORDS,
    CONF_MAIL_FOLDER,
    CONF_MAIL_HOST,
    CONF_MAIL_LIMIT,
    CONF_MAIL_PORT,
    CONF_MAIL_UNSEEN_ONLY,
    CONF_NOTIFY_SERVICE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TYPE,
    CONF_UPDATE_MODE,
    CONF_USERNAME,
    CONF_WEEKS_AHEAD,
    DEFAULT_EXAM_DURATION,
    DEFAULT_SCAN_INTERVAL_EXAM,
    DEFAULT_SCAN_INTERVAL_PUBLIC,
    DEFAULT_MAIL_FOLDER,
    DEFAULT_MAIL_HOST,
    DEFAULT_MAIL_LIMIT,
    DEFAULT_MAIL_PORT,
    DEFAULT_MAIL_UNSEEN_ONLY,
    DEFAULT_SCAN_INTERVAL_MAIL,
    MAX_SCAN_INTERVAL_MAIL,
    MIN_SCAN_INTERVAL_MAIL,
    DEFAULT_UPDATE_MODE,
    DEFAULT_WEEKS_AHEAD,
    DOMAIN,
    MAX_SCAN_INTERVAL_EXAM,
    MAX_SCAN_INTERVAL_PUBLIC,
    MAX_WEEKS_AHEAD,
    MIN_SCAN_INTERVAL_EXAM,
    MIN_SCAN_INTERVAL_PUBLIC,
    TYPE_COITHI,
    TYPE_DEADLINE_DIEM,
    TYPE_LICHGIANGDAY,
    TYPE_LICHTUAN,
    TYPE_MAIL,
    UPDATE_MODE_FULL,
    UPDATE_MODE_SMART,
)
from .parser_exam import (
    build_lecturer_directory,
    lecturers_from_lop_hp_khoa,
    parse_exam_duty,
    parse_hoc_ky_options,
    parse_khoa_options,
    parse_lop_hp_khoa,
)
from .parser_public import parse_keyword_groups

_LOGGER = logging.getLogger(__name__)

# Gợi ý điền sẵn ô từ khóa. CHỦ Ý dùng chỗ trống chung chung, không
# nhúng tên người/đơn vị thật — form này hiển thị trên giao diện và có
# thể lọt vào ảnh chụp màn hình khi báo lỗi.
KEYWORDS_EXAMPLE = (
    "Tên nhóm 1: từ khóa, từ viết tắt\n"
    "Tên nhóm 2: từ khóa khác, biến thể khác"
)

ACCOUNT_NEW_SENTINEL = "__new_account__"


def _existing_accounts(hass: Any) -> dict[str, str]:
    """Trả về {tài khoản: mật khẩu} từ các entry dut_coithi/dut_deadline_diem
    đã cấu hình — để entry mới cùng loại dùng chung tài khoản, không phải
    gõ lại mật khẩu.
    """
    accounts: dict[str, str] = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_TYPE) in (TYPE_COITHI, TYPE_DEADLINE_DIEM):
            username = entry.data.get(CONF_USERNAME)
            if not username or username in accounts:
                continue
            password = entry.options.get(CONF_PASSWORD, entry.data.get(CONF_PASSWORD, ""))
            accounts[username] = password
    return accounts


def _schema_account_choice(accounts: dict[str, str]) -> vol.Schema:
    options = [SelectOptionDict(value=u, label=u) for u in accounts] + [
        SelectOptionDict(value=ACCOUNT_NEW_SENTINEL, label="+ Tài khoản khác (nhập mới)")
    ]
    return vol.Schema(
        {
            vol.Required("existing_account", default=next(iter(accounts))): SelectSelector(
                SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
            ),
        }
    )


# =====================================================================
# Schema builders
# =====================================================================
def _schema_lichtuan(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_KEYWORDS, default=defaults.get(CONF_KEYWORDS, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_PUBLIC),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL_PUBLIC,
                    max=MAX_SCAN_INTERVAL_PUBLIC,
                    step=5,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="phút",
                )
            ),
            vol.Required(
                CONF_UPDATE_MODE,
                default=defaults.get(CONF_UPDATE_MODE, DEFAULT_UPDATE_MODE),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(
                            value=UPDATE_MODE_SMART,
                            label="Chỉ tuần hiện tại + tuần mới (từ cuối tuần)",
                        ),
                        SelectOptionDict(
                            value=UPDATE_MODE_FULL,
                            label="Toàn bộ (tuần hiện tại + số tuần quét thêm bên dưới)",
                        ),
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_WEEKS_AHEAD, default=defaults.get(CONF_WEEKS_AHEAD, DEFAULT_WEEKS_AHEAD)
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=MAX_WEEKS_AHEAD, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_NOTIFY_SERVICE, default=defaults.get(CONF_NOTIFY_SERVICE, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Optional(
                CONF_CLEAR_HISTORY, default=defaults.get(CONF_CLEAR_HISTORY, False)
            ): BooleanSelector(),
        }
    )


def _schema_login_credentials(
    defaults: dict[str, Any],
    require_password: bool,
    show_lecturer_toggle: bool = False,
    show_exam_duration: bool = False,
    show_notify: bool = True,
) -> vol.Schema:
    """Bước 1: tài khoản/mật khẩu + các tuỳ chọn khác (KHÔNG có học kỳ).

    Tính năng "theo dõi thêm giảng viên khác" (chỉ dut_coithi) được
    cấu hình ở 2 bước RIÊNG sau bước chọn học kỳ (xem
    _schema_chon_khoa/_schema_chon_giang_vien) — CHỈ đi qua các bước
    đó (và tải dữ liệu ~1MB để dựng danh sách) nếu tick bật ở đây.
    Bỏ tick thì bỏ qua hoàn toàn, tiết kiệm thời gian khi không cần.
    """
    pw_key = (
        vol.Required(CONF_PASSWORD)
        if require_password
        else vol.Optional(CONF_PASSWORD, default="")
    )
    schema_dict: dict[Any, Any] = {
        vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        pw_key: TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
        vol.Required(
            CONF_SCAN_INTERVAL,
            default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_EXAM),
        ): NumberSelector(
            NumberSelectorConfig(
                min=MIN_SCAN_INTERVAL_EXAM,
                max=MAX_SCAN_INTERVAL_EXAM,
                step=5,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="phút",
            )
        ),
    }

    # Chỉ dùng cho dut_coithi: trang trường không cho giờ KẾT THÚC ca
    # thi, nên end = start + số phút này. Các loại khác không dùng tới.
    if show_exam_duration:
        schema_dict[
            vol.Optional(
                CONF_EXAM_DURATION,
                default=defaults.get(CONF_EXAM_DURATION, DEFAULT_EXAM_DURATION),
            )
        ] = NumberSelector(
            NumberSelectorConfig(
                min=15, max=240, step=5, mode=NumberSelectorMode.BOX, unit_of_measurement="phút"
            )
        )

    # Chỉ dut_coithi (ca thi mới) và dut_deadline_diem (hạn thay đổi)
    # mới gửi thông báo; dut_lichgiangday không dùng.
    if show_notify:
        schema_dict[
            vol.Optional(CONF_NOTIFY_SERVICE, default=defaults.get(CONF_NOTIFY_SERVICE, ""))
        ] = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))

    if show_lecturer_toggle:
        schema_dict[
            vol.Optional(
                CONF_CONFIGURE_EXTRA_LECTURER,
                default=defaults.get(CONF_CONFIGURE_EXTRA_LECTURER, False),
            )
        ] = BooleanSelector()

    return vol.Schema(schema_dict)


def _schema_mail(defaults: dict[str, Any], require_password: bool) -> vol.Schema:
    """Cấu hình đọc & lọc email qua IMAP.

    Với Gmail phải dùng App Password (mật khẩu ứng dụng 16 ký tự) —
    Google không cho đăng nhập IMAP bằng mật khẩu tài khoản thường.
    """
    pw_key = (
        vol.Required(CONF_PASSWORD)
        if require_password
        else vol.Optional(CONF_PASSWORD, default="")
    )
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            pw_key: TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            vol.Required(
                CONF_KEYWORDS, default=defaults.get(CONF_KEYWORDS, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)),
            vol.Required(
                CONF_MAIL_HOST, default=defaults.get(CONF_MAIL_HOST, DEFAULT_MAIL_HOST)
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Required(
                CONF_MAIL_PORT, default=defaults.get(CONF_MAIL_PORT, DEFAULT_MAIL_PORT)
            ): NumberSelector(NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)),
            vol.Required(
                CONF_MAIL_FOLDER, default=defaults.get(CONF_MAIL_FOLDER, DEFAULT_MAIL_FOLDER)
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MAIL),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL_MAIL,
                    max=MAX_SCAN_INTERVAL_MAIL,
                    step=5,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="phút",
                )
            ),
            vol.Optional(
                CONF_MAIL_LIMIT, default=defaults.get(CONF_MAIL_LIMIT, DEFAULT_MAIL_LIMIT)
            ): NumberSelector(NumberSelectorConfig(min=10, max=500, step=10, mode=NumberSelectorMode.BOX)),
            vol.Optional(
                CONF_MAIL_UNSEEN_ONLY,
                default=defaults.get(CONF_MAIL_UNSEEN_ONLY, DEFAULT_MAIL_UNSEEN_ONLY),
            ): BooleanSelector(),
            vol.Optional(
                CONF_NOTIFY_SERVICE, default=defaults.get(CONF_NOTIFY_SERVICE, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        }
    )


# Giá trị đặc biệt cho bước chọn khoa
KHOA_NONE_SENTINEL = "__none__"  # XÓA HẾT, không theo dõi ai
KHOA_KEEP_SENTINEL = "__keep__"  # GIỮ NGUYÊN lựa chọn hiện tại, không đổi gì (chỉ OptionsFlow)
KHOA_ALL_SENTINEL = "__all__"  # gộp tất cả khoa vào 1 danh sách để chọn
KHOA_RETRY_SENTINEL = "__retry__"  # tải danh sách lỗi -> thử lại


def _schema_chon_khoa(
    khoa_counts: dict[str, int],
    default: str,
    failed: bool = False,
    current_count: int = 0,
) -> vol.Schema:
    """Bước chọn khoa (để rút gọn danh sách tên ở bước sau).

    Khi `failed=True` (tải danh sách lỗi), chỉ hiện lựa chọn giữ
    nguyên/xóa hết + thử tải lại — không hiện danh sách khoa (vì
    không có dữ liệu thật để hiện).

    `current_count > 0` (chỉ xảy ra khi sửa qua Options, entry đã có
    sẵn người đang theo dõi) -> hiện thêm lựa chọn "Giữ nguyên", TÁCH
    BIỆT rõ với "Xóa hết" — tránh nhầm giữa 2 hành động khác hệ quả.
    """
    options: list[SelectOptionDict] = []
    if current_count > 0:
        options.append(
            SelectOptionDict(
                value=KHOA_KEEP_SENTINEL,
                label=f"↩️ Giữ nguyên {current_count} người đang theo dõi, không đổi gì",
            )
        )
    options.append(
        SelectOptionDict(value=KHOA_NONE_SENTINEL, label="🗑️ Xóa hết, không theo dõi ai")
    )
    if failed:
        options.append(SelectOptionDict(value=KHOA_RETRY_SENTINEL, label="🔄 Thử tải lại"))
    else:
        options.append(SelectOptionDict(value=KHOA_ALL_SENTINEL, label="— Tất cả các khoa —"))
        for code in sorted(khoa_counts):
            options.append(
                SelectOptionDict(value=code, label=f"Khoa {code} ({khoa_counts[code]} người)")
            )
    return vol.Schema(
        {
            vol.Required("khoa", default=default): SelectSelector(
                SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
            ),
        }
    )


def _schema_chon_giang_vien(names: list[str], defaults: list[str]) -> vol.Schema:
    """Bước chọn tên giảng viên (nhiều lựa chọn, gõ để tìm kiếm khi
    danh sách dài — SelectSelector dạng dropdown của HA tự hỗ trợ gõ
    lọc khi có nhiều option).
    """
    options = [SelectOptionDict(value=n, label=n) for n in names]
    return vol.Schema(
        {
            vol.Optional(CONF_EXTRA_LECTURERS, default=defaults): SelectSelector(
                SelectSelectorConfig(
                    options=options, multiple=True, mode=SelectSelectorMode.DROPDOWN
                )
            ),
        }
    )


def _schema_hocky(
    options: list[dict[str, Any]], default_selected: list[str]
) -> vol.Schema:
    """Bước 2: chọn học kỳ bằng TÊN THẬT (từ dropdown lấy được sau khi đăng nhập)."""
    select_options = [
        SelectOptionDict(value=o["value"], label=o["label"]) for o in options
    ]
    return vol.Schema(
        {
            vol.Required(CONF_HOC_KY, default=default_selected): SelectSelector(
                SelectSelectorConfig(
                    options=select_options,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            ),
        }
    )


async def _try_login_and_fetch_hocky(
    username: str, password: str
) -> tuple[str | None, list[dict[str, Any]]]:
    """Đăng nhập thật + lấy luôn danh sách học kỳ trong 1 phiên, rồi đóng.

    Trả về (mã_lỗi | None, danh_sách_học_kỳ).
    """
    session = aiohttp.ClientSession()
    try:
        client = CBDutClient(session, username, password)
        await client.ensure_logged_in()
        html = await client.fetch_hocky_options_html()
        options = parse_hoc_ky_options(html)
        return None, options
    except CBDutAuthError:
        return "invalid_auth", []
    except Exception:  # noqa: BLE001
        return "cannot_connect", []
    finally:
        await session.close()


async def _fetch_khoa_options(username: str, password: str) -> list[dict[str, str]]:
    """Danh sách Khoa (từ dropdown thật của trang Lớp học phần khoa)."""
    session = aiohttp.ClientSession()
    try:
        client = CBDutClient(session, username, password)
        await client.ensure_logged_in()
        return parse_khoa_options(await client.fetch_lop_hp_khoa_page_html())
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Không lấy được danh sách khoa: %s", err)
        return []
    finally:
        await session.close()


async def _fetch_lecturers_of_khoa(
    username: str, password: str, hoc_ky: str, khoa: str
) -> list[str]:
    """Danh sách giảng viên của 1 khoa trong 1 học kỳ."""
    session = aiohttp.ClientSession()
    try:
        client = CBDutClient(session, username, password)
        await client.ensure_logged_in()
        rows = parse_lop_hp_khoa(await client.fetch_lop_hp_khoa_html(hoc_ky, khoa))
        return lecturers_from_lop_hp_khoa(rows)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Không lấy được giảng viên khoa %s: %s", khoa, err)
        return []
    finally:
        await session.close()


async def _fetch_lecturer_directory(
    username: str, password: str, hoc_ky_list: list[str]
) -> dict[str, list[str]] | None:
    """Đăng nhập + tải TOÀN BỘ ca thi của MỌI học kỳ đang chọn (không
    chỉ 1 học kỳ đầu tiên), gộp danh sách tên giảng viên duy nhất theo
    mã khoa — dùng để hiển thị UI chọn khoa rồi chọn tên.

    QUAN TRỌNG: chỉ dùng 1 học kỳ có thể bỏ sót khoa/tên nếu học kỳ đó
    chưa có đủ dữ liệu coi thi cho khoa đó (vd học kỳ mới, lịch coi
    thi chưa xếp hết) — gộp nhiều học kỳ giúp danh sách đầy đủ hơn.

    Mỗi học kỳ response có thể tới ~1MB nên đôi khi timeout/lỗi tạm
    thời (mạng chậm, server tải) — mỗi học kỳ tự thử lại tối đa 2 lần.
    Trả về None nếu TẤT CẢ học kỳ đều lỗi — khi đó UI vẫn cho phép bỏ
    qua tính năng theo dõi giảng viên khác (không chặn cài đặt), nhưng
    có nút "Thử lại" riêng để không phải làm lại từ đầu. Nếu CHỈ MỘT
    SỐ học kỳ lỗi, vẫn trả về danh sách gộp từ các học kỳ tải được.
    """
    merged: dict[str, set[str]] = {}
    any_success = False

    session = aiohttp.ClientSession()
    try:
        client = CBDutClient(session, username, password)
        try:
            await client.ensure_logged_in()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Không đăng nhập được để tải danh sách giảng viên: %s", err)
            return None

        for hoc_ky in hoc_ky_list:
            last_err: Exception | None = None
            for attempt in range(2):
                try:
                    html = await client.fetch_exam_duty_all_html(hoc_ky)
                    duties = parse_exam_duty(html, hoc_ky)
                    directory = build_lecturer_directory(duties)
                    if not directory:
                        raise ValueError("Danh sách rỗng sau khi parse")
                    for code, names in directory.items():
                        merged.setdefault(code, set()).update(names)
                    any_success = True
                    break
                except Exception as err:  # noqa: BLE001
                    last_err = err
                    _LOGGER.warning(
                        "Lần %d/2 tải danh sách giảng viên (HK %s) thất bại: %s",
                        attempt + 1,
                        hoc_ky,
                        err,
                    )
            else:
                _LOGGER.error(
                    "Không tải được danh sách giảng viên cho HK %s sau 2 lần thử: %s",
                    hoc_ky,
                    last_err,
                )
    finally:
        await session.close()

    if not any_success:
        return None

    return {code: sorted(names) for code, names in merged.items()}


class _GiangDayLecturerMixin:
    """Bước chọn khoa -> chọn giảng viên cho loại dut_lichgiangday.

    Dùng chung cho cả ConfigFlow (thêm mới) và OptionsFlow (sửa).
    Lớp con phải có: _pending_data, _pending_hoc_ky_list, _chosen_khoa,
    _khoa_options, và _current_extra_lecturers().
    """

    # ---- Bước riêng cho dut_lichgiangday: chọn khoa -> chọn giảng viên ----
    async def _gd_step_khoa(self, user_input, on_done):
        """on_done(danh_sach_ten) -> kết thúc flow (tạo/lưu entry)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            khoa = user_input["khoa"]
            if khoa == KHOA_NONE_SENTINEL:
                return await on_done([])
            if khoa == KHOA_KEEP_SENTINEL:
                return await on_done(None)
            self._chosen_khoa = khoa
            return await self.async_step_gd_giang_vien()

        if not self._khoa_options:
            self._khoa_options = await _fetch_khoa_options(
                self._pending_data[CONF_USERNAME], self._pending_data[CONF_PASSWORD]
            )
            if not self._khoa_options:
                errors["base"] = "cannot_fetch_directory"

        cur = self._current_extra_lecturers()
        options = []
        if cur:
            options.append(
                SelectOptionDict(
                    value=KHOA_KEEP_SENTINEL,
                    label=f"↩️ Giữ nguyên {len(cur)} người đang theo dõi, không đổi gì",
                )
            )
        options.append(
            SelectOptionDict(value=KHOA_NONE_SENTINEL, label="🗑️ Xóa hết, không theo dõi ai")
        )
        options += [
            SelectOptionDict(value=k["value"], label=f"{k['value']} - {k['label']}")
            for k in self._khoa_options
        ]
        return self.async_show_form(
            step_id="gd_khoa",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "khoa",
                        default=KHOA_KEEP_SENTINEL if cur else KHOA_NONE_SENTINEL,
                    ): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
            errors=errors,
        )

    async def _gd_step_giang_vien(self, user_input, on_done):
        if user_input is not None:
            chosen = user_input.get(CONF_EXTRA_LECTURERS) or []
            return await on_done([f"{self._chosen_khoa}|{n}" for n in chosen])

        hk = (self._pending_hoc_ky_list or [""])[0]
        names = await _fetch_lecturers_of_khoa(
            self._pending_data[CONF_USERNAME],
            self._pending_data[CONF_PASSWORD],
            hk,
            self._chosen_khoa or "",
        )
        cur_names = [
            x.split("|", 1)[1]
            for x in self._current_extra_lecturers()
            if x.startswith(f"{self._chosen_khoa}|")
        ]
        return self.async_show_form(
            step_id="gd_giang_vien",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_EXTRA_LECTURERS, default=cur_names): SelectSelector(
                        SelectSelectorConfig(
                            options=[SelectOptionDict(value=n, label=n) for n in names],
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )



# =====================================================================
# Config Flow chính — menu 3 lựa chọn
# =====================================================================
class DutCalendarConfigFlow(_GiangDayLecturerMixin, ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._pending_data: dict[str, Any] = {}
        self._hocky_options: list[dict[str, Any]] = []
        self._pending_type: str | None = None
        self._lecturer_directory: dict[str, list[str]] | None = None
        self._chosen_khoa: str | None = None
        self._pending_hoc_ky_list: list[str] = []
        self._directory_failed: bool = False
        self._khoa_options: list[dict[str, str]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        return self.async_show_menu(
            step_id="user",
            menu_options=[
                "dut_lichtuan",
                "dut_coithi",
                "dut_deadline_diem",
                "dut_lichgiangday",
                "dut_mail",
            ],
        )

    # ---- dut_lichtuan: Lịch tuần công khai (1 bước, không cần đăng nhập) ----
    async def async_step_dut_lichtuan(self, user_input: dict[str, Any] | None = None) -> Any:
        errors: dict[str, str] = {}

        if user_input is not None:
            groups = parse_keyword_groups(user_input[CONF_KEYWORDS])
            if not groups:
                errors["base"] = "no_keywords"
            else:
                user_input[CONF_TYPE] = TYPE_LICHTUAN
                return self.async_create_entry(title="DUT Calendar - Lịch tuần", data=user_input)

        return self.async_show_form(
            step_id="dut_lichtuan",
            data_schema=_schema_lichtuan(user_input or {CONF_KEYWORDS: KEYWORDS_EXAMPLE}),
            errors=errors,
            description_placeholders={"example": KEYWORDS_EXAMPLE},
        )

    # ---- dut_coithi: bước 0 (chọn tài khoản có sẵn, nếu có) -> bước 1 (đăng nhập) ----
    async def async_step_dut_coithi(self, user_input: dict[str, Any] | None = None) -> Any:
        return await self._step_account_gate(user_input, "dut_coithi", TYPE_COITHI)

    async def async_step_dut_coithi_account(self, user_input: dict[str, Any] | None = None) -> Any:
        return await self._step_account_choice(user_input, "dut_coithi", TYPE_COITHI)

    async def async_step_dut_coithi_login(self, user_input: dict[str, Any] | None = None) -> Any:
        return await self._step_credentials(user_input, "dut_coithi", TYPE_COITHI)

    # ---- dut_deadline_diem: bước 0 (chọn tài khoản có sẵn, nếu có) -> bước 1 (đăng nhập) ----
    async def async_step_dut_deadline_diem(self, user_input: dict[str, Any] | None = None) -> Any:
        return await self._step_account_gate(user_input, "dut_deadline_diem", TYPE_DEADLINE_DIEM)

    async def async_step_dut_deadline_diem_account(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return await self._step_account_choice(user_input, "dut_deadline_diem", TYPE_DEADLINE_DIEM)

    async def async_step_dut_deadline_diem_login(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return await self._step_credentials(user_input, "dut_deadline_diem", TYPE_DEADLINE_DIEM)

    async def async_step_dut_lichgiangday(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return await self._step_account_gate(user_input, "dut_lichgiangday", TYPE_LICHGIANGDAY)

    async def async_step_dut_lichgiangday_account(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return await self._step_account_choice(
            user_input, "dut_lichgiangday", TYPE_LICHGIANGDAY
        )

    async def async_step_dut_lichgiangday_login(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return await self._step_credentials(
            user_input, "dut_lichgiangday", TYPE_LICHGIANGDAY
        )


    def _current_extra_lecturers(self) -> list[str]:
        return list(self._pending_data.get(CONF_EXTRA_LECTURERS) or [])

    async def async_step_gd_khoa(self, user_input: dict[str, Any] | None = None) -> Any:
        return await self._gd_step_khoa(user_input, self._gd_finish)

    async def async_step_gd_giang_vien(self, user_input: dict[str, Any] | None = None) -> Any:
        return await self._gd_step_giang_vien(user_input, self._gd_finish)

    async def _gd_finish(self, names: list[str] | None) -> Any:
        self._pending_data[CONF_EXTRA_LECTURERS] = names or []
        return self.async_create_entry(
            title=f"DUT Calendar - Lịch giảng dạy ({self._pending_data[CONF_USERNAME]})",
            data=self._pending_data,
        )

    async def async_step_dut_mail(self, user_input: dict[str, Any] | None = None) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not parse_keyword_groups(user_input.get(CONF_KEYWORDS, "")):
                errors["base"] = "no_keywords"
            else:
                data = {**user_input, CONF_TYPE: TYPE_MAIL}
                return self.async_create_entry(
                    title=f"DUT Calendar - Email ({data[CONF_USERNAME]})", data=data
                )
        return self.async_show_form(
            step_id="dut_mail",
            data_schema=_schema_mail(user_input or {}, require_password=True),
            errors=errors,
        )

    async def _step_account_gate(
        self, user_input: dict[str, Any] | None, base_step: str, type_value: str
    ) -> Any:
        """Vào từ menu: nếu đã có tài khoản cấu hình sẵn (từ entry loại
        dut_coithi/dut_deadline_diem khác), cho chọn dùng lại thay vì bắt
        gõ mật khẩu lần nữa. Nếu chưa có tài khoản nào, vào thẳng bước
        đăng nhập như bình thường.
        """
        if _existing_accounts(self.hass):
            return await self._step_account_choice(None, base_step, type_value)
        return await self._step_credentials(None, base_step, type_value)

    async def _step_account_choice(
        self, user_input: dict[str, Any] | None, base_step: str, type_value: str
    ) -> Any:
        accounts = _existing_accounts(self.hass)

        if user_input is not None:
            choice = user_input["existing_account"]
            if choice == ACCOUNT_NEW_SENTINEL:
                return await self._step_credentials(None, base_step, type_value)
            prefill = {CONF_USERNAME: choice, CONF_PASSWORD: accounts.get(choice, "")}
            return await self._step_credentials(None, base_step, type_value, prefill=prefill)

        return self.async_show_form(
            step_id=f"{base_step}_account",
            data_schema=_schema_account_choice(accounts),
        )

    async def _step_credentials(
        self,
        user_input: dict[str, Any] | None,
        base_step: str,
        type_value: str,
        prefill: dict[str, Any] | None = None,
    ) -> Any:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(f"{type_value}_{user_input[CONF_USERNAME]}")
            self._abort_if_unique_id_configured()

            err, options = await _try_login_and_fetch_hocky(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if err:
                errors["base"] = err
            elif not options:
                errors["base"] = "no_hocky_options"
            else:
                self._pending_data = user_input
                self._pending_type = type_value
                self._hocky_options = options
                return await self.async_step_hocky()

        return self.async_show_form(
            step_id=f"{base_step}_login",
            data_schema=_schema_login_credentials(
                user_input or prefill or {},
                require_password=True,
                show_lecturer_toggle=type_value in (TYPE_COITHI, TYPE_LICHGIANGDAY),
                show_exam_duration=(type_value == TYPE_COITHI),
                show_notify=(type_value != TYPE_LICHGIANGDAY),
            ),
            errors=errors,
        )

    # ---- Bước 2 chung: chọn học kỳ (dùng chung cho cả dut_coithi & dut_deadline_diem) ----
    async def async_step_hocky(self, user_input: dict[str, Any] | None = None) -> Any:
        errors: dict[str, str] = {}

        if user_input is not None:
            selected = user_input.get(CONF_HOC_KY) or []
            if not selected:
                errors["base"] = "no_hoc_ky"
            else:
                self._pending_data = {
                    **self._pending_data,
                    CONF_HOC_KY: ", ".join(selected),
                    CONF_TYPE: self._pending_type,
                }
                want_lecturer = self._pending_data.get(CONF_CONFIGURE_EXTRA_LECTURER, False)
                if self._pending_type == TYPE_COITHI and want_lecturer:
                    self._pending_hoc_ky_list = selected
                    return await self.async_step_chon_khoa()
                if self._pending_type == TYPE_COITHI:
                    self._pending_data[CONF_EXTRA_LECTURERS] = []
                    return self.async_create_entry(
                        title=f"DUT Calendar - Coi thi ({self._pending_data[CONF_USERNAME]})",
                        data=self._pending_data,
                    )
                if self._pending_type == TYPE_LICHGIANGDAY:
                    if self._pending_data.get(CONF_CONFIGURE_EXTRA_LECTURER):
                        self._pending_hoc_ky_list = selected
                        return await self.async_step_gd_khoa()
                    self._pending_data[CONF_EXTRA_LECTURERS] = []
                    return self.async_create_entry(
                        title=(
                            "DUT Calendar - Lịch giảng dạy "
                            f"({self._pending_data[CONF_USERNAME]})"
                        ),
                        data=self._pending_data,
                    )
                return self.async_create_entry(
                    title=f"DUT Calendar - Hạn nộp điểm ({self._pending_data[CONF_USERNAME]})",
                    data=self._pending_data,
                )

        default_selected = [o["value"] for o in self._hocky_options if o.get("selected")]
        return self.async_show_form(
            step_id="hocky",
            data_schema=_schema_hocky(self._hocky_options, default_selected),
            errors=errors,
        )


    # ---- Bước 3 (chỉ dut_coithi): chọn khoa -> chọn giảng viên khác cần theo dõi ----
    async def async_step_chon_khoa(self, user_input: dict[str, Any] | None = None) -> Any:
        errors: dict[str, str] = {}

        if user_input is not None:
            khoa = user_input["khoa"]
            if khoa == KHOA_RETRY_SENTINEL:
                self._lecturer_directory = None
                self._directory_failed = False
                return await self.async_step_chon_khoa()
            if khoa == KHOA_NONE_SENTINEL:
                self._pending_data[CONF_EXTRA_LECTURERS] = []
                return self.async_create_entry(
                    title=f"DUT Calendar - Coi thi ({self._pending_data[CONF_USERNAME]})",
                    data=self._pending_data,
                )
            self._chosen_khoa = khoa
            return await self.async_step_chon_giang_vien()

        if self._lecturer_directory is None and not self._directory_failed:
            directory = await _fetch_lecturer_directory(
                self._pending_data[CONF_USERNAME],
                self._pending_data[CONF_PASSWORD],
                self._pending_hoc_ky_list,
            )
            if directory is None:
                self._directory_failed = True
                errors["base"] = "cannot_fetch_directory"
            else:
                self._lecturer_directory = directory

        if self._directory_failed:
            return self.async_show_form(
                step_id="chon_khoa",
                data_schema=_schema_chon_khoa({}, KHOA_NONE_SENTINEL, failed=True),
                errors=errors,
            )

        khoa_counts = {k: len(v) for k, v in self._lecturer_directory.items()}
        return self.async_show_form(
            step_id="chon_khoa",
            data_schema=_schema_chon_khoa(khoa_counts, KHOA_NONE_SENTINEL),
            errors=errors,
        )

    async def async_step_chon_giang_vien(self, user_input: dict[str, Any] | None = None) -> Any:
        if user_input is not None:
            self._pending_data[CONF_EXTRA_LECTURERS] = user_input.get(CONF_EXTRA_LECTURERS) or []
            return self.async_create_entry(
                title=f"DUT Calendar - Coi thi ({self._pending_data[CONF_USERNAME]})",
                data=self._pending_data,
            )

        directory = self._lecturer_directory or {}
        if self._chosen_khoa == KHOA_ALL_SENTINEL:
            names = sorted(n for lst in directory.values() for n in lst)
        else:
            names = directory.get(self._chosen_khoa, [])

        return self.async_show_form(
            step_id="chon_giang_vien",
            data_schema=_schema_chon_giang_vien(names, []),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DutCalendarOptionsFlow(config_entry)


# =====================================================================
# Options Flow (nhánh theo loại entry đã tạo)
# =====================================================================
class DutCalendarOptionsFlow(_GiangDayLecturerMixin, OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._pending_data: dict[str, Any] = {}
        self._hocky_options: list[dict[str, Any]] = []
        self._lecturer_directory: dict[str, list[str]] | None = None
        self._chosen_khoa: str | None = None
        self._pending_hoc_ky_list: list[str] = []
        self._directory_failed: bool = False
        self._khoa_options: list[dict[str, str]] = []

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        entry_type = self._config_entry.data.get(CONF_TYPE)
        if entry_type == TYPE_LICHTUAN:
            return await self._step_lichtuan(user_input)
        if entry_type == TYPE_MAIL:
            return await self._step_mail(user_input)
        return await self._step_credentials(user_input)

    async def _step_mail(self, user_input: dict[str, Any] | None) -> Any:
        errors: dict[str, str] = {}
        current = {**self._config_entry.data, **self._config_entry.options}

        if user_input is not None:
            if not parse_keyword_groups(user_input.get(CONF_KEYWORDS, "")):
                errors["base"] = "no_keywords"
            else:
                data = dict(user_input)
                # Để trống mật khẩu = giữ mật khẩu đã lưu
                if not data.get(CONF_PASSWORD):
                    data[CONF_PASSWORD] = current.get(CONF_PASSWORD, "")
                return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="init",
            data_schema=_schema_mail(user_input or current, require_password=False),
            errors=errors,
        )

    async def _step_lichtuan(self, user_input: dict[str, Any] | None) -> Any:
        errors: dict[str, str] = {}
        current = {**self._config_entry.data, **self._config_entry.options}

        if user_input is not None:
            groups = parse_keyword_groups(user_input[CONF_KEYWORDS])
            if not groups:
                errors["base"] = "no_keywords"
            else:
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_schema_lichtuan(user_input or current),
            errors=errors,
            description_placeholders={"example": KEYWORDS_EXAMPLE},
        )

    async def _step_credentials(self, user_input: dict[str, Any] | None) -> Any:
        errors: dict[str, str] = {}
        current = {**self._config_entry.data, **self._config_entry.options}
        current.setdefault(
            CONF_CONFIGURE_EXTRA_LECTURER,
            bool(current.get(CONF_EXTRA_LECTURERS) or current.get(CONF_EXTRA_LECTURER)),
        )

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input.get(CONF_PASSWORD) or current.get(CONF_PASSWORD, "")

            err, options = await _try_login_and_fetch_hocky(username, password)
            if err:
                errors["base"] = err
            elif not options:
                errors["base"] = "no_hocky_options"
            else:
                user_input[CONF_PASSWORD] = password
                self._pending_data = user_input
                self._hocky_options = options
                return await self.async_step_hocky()

        return self.async_show_form(
            step_id="init",
            data_schema=_schema_login_credentials(
                user_input or current,
                require_password=False,
                show_lecturer_toggle=self._config_entry.data.get(CONF_TYPE)
                in (TYPE_COITHI, TYPE_LICHGIANGDAY),
                show_exam_duration=self._config_entry.data.get(CONF_TYPE) == TYPE_COITHI,
                show_notify=self._config_entry.data.get(CONF_TYPE) != TYPE_LICHGIANGDAY,
            ),
            errors=errors,
        )

    async def async_step_hocky(self, user_input: dict[str, Any] | None = None) -> Any:
        errors: dict[str, str] = {}
        current_hoc_ky = [
            x.strip()
            for x in str(
                self._config_entry.options.get(
                    CONF_HOC_KY, self._config_entry.data.get(CONF_HOC_KY, "")
                )
            ).split(",")
            if x.strip()
        ]

        if user_input is not None:
            selected = user_input.get(CONF_HOC_KY) or []
            if not selected:
                errors["base"] = "no_hoc_ky"
            else:
                self._pending_data = {**self._pending_data, CONF_HOC_KY: ", ".join(selected)}
                want_lecturer = self._pending_data.get(CONF_CONFIGURE_EXTRA_LECTURER, False)
                if (
                    self._config_entry.data.get(CONF_TYPE) == TYPE_LICHGIANGDAY
                    and want_lecturer
                ):
                    self._pending_hoc_ky_list = selected
                    return await self.async_step_gd_khoa()
                if self._config_entry.data.get(CONF_TYPE) == TYPE_COITHI and want_lecturer:
                    self._pending_hoc_ky_list = selected
                    return await self.async_step_chon_khoa()
                if self._config_entry.data.get(CONF_TYPE) == TYPE_COITHI:
                    # Bỏ tick -> không đụng tới lựa chọn giảng viên đã có,
                    # tiết kiệm thời gian không phải tải lại danh sách.
                    self._pending_data[CONF_EXTRA_LECTURERS] = self._config_entry.options.get(
                        CONF_EXTRA_LECTURERS,
                        self._config_entry.data.get(CONF_EXTRA_LECTURERS, []),
                    )
                return self.async_create_entry(title="", data=self._pending_data)

        return self.async_show_form(
            step_id="hocky",
            data_schema=_schema_hocky(self._hocky_options, current_hoc_ky),
            errors=errors,
        )

    def _current_extra_lecturers(self) -> list[str]:
        return list(
            self._config_entry.options.get(
                CONF_EXTRA_LECTURERS, self._config_entry.data.get(CONF_EXTRA_LECTURERS, [])
            )
            or []
        )

    async def async_step_gd_khoa(self, user_input: dict[str, Any] | None = None) -> Any:
        return await self._gd_step_khoa(user_input, self._gd_finish)

    async def async_step_gd_giang_vien(self, user_input: dict[str, Any] | None = None) -> Any:
        return await self._gd_step_giang_vien(user_input, self._gd_finish)

    async def _gd_finish(self, names: list[str] | None) -> Any:
        # names is None -> giữ nguyên lựa chọn cũ
        self._pending_data[CONF_EXTRA_LECTURERS] = (
            self._current_extra_lecturers() if names is None else names
        )
        return self.async_create_entry(title="", data=self._pending_data)

    # ---- Bước 3 (chỉ dut_coithi): chọn khoa -> chọn giảng viên khác cần theo dõi ----
    async def async_step_chon_khoa(self, user_input: dict[str, Any] | None = None) -> Any:
        errors: dict[str, str] = {}
        current_lecturers = self._config_entry.options.get(
            CONF_EXTRA_LECTURERS, self._config_entry.data.get(CONF_EXTRA_LECTURERS, [])
        )
        # Mặc định an toàn: có sẵn người đang theo dõi -> mặc định GIỮ
        # NGUYÊN (không phải xóa hay đổi khoa), tránh mất dữ liệu nếu
        # người dùng bấm nhầm/không chú ý tới dropdown này.
        default_khoa = KHOA_KEEP_SENTINEL if current_lecturers else KHOA_NONE_SENTINEL

        if user_input is not None:
            khoa = user_input["khoa"]
            if khoa == KHOA_RETRY_SENTINEL:
                self._lecturer_directory = None
                self._directory_failed = False
                return await self.async_step_chon_khoa()
            if khoa == KHOA_KEEP_SENTINEL:
                self._pending_data[CONF_EXTRA_LECTURERS] = current_lecturers
                return self.async_create_entry(title="", data=self._pending_data)
            if khoa == KHOA_NONE_SENTINEL:
                self._pending_data[CONF_EXTRA_LECTURERS] = []
                return self.async_create_entry(title="", data=self._pending_data)
            self._chosen_khoa = khoa
            return await self.async_step_chon_giang_vien()

        if self._lecturer_directory is None and not self._directory_failed:
            directory = await _fetch_lecturer_directory(
                self._pending_data[CONF_USERNAME],
                self._pending_data[CONF_PASSWORD],
                self._pending_hoc_ky_list,
            )
            if directory is None:
                self._directory_failed = True
                errors["base"] = "cannot_fetch_directory"
            else:
                self._lecturer_directory = directory

        if self._directory_failed:
            return self.async_show_form(
                step_id="chon_khoa",
                data_schema=_schema_chon_khoa(
                    {}, default_khoa, failed=True, current_count=len(current_lecturers)
                ),
                errors=errors,
            )

        khoa_counts = {k: len(v) for k, v in self._lecturer_directory.items()}
        return self.async_show_form(
            step_id="chon_khoa",
            data_schema=_schema_chon_khoa(
                khoa_counts, default_khoa, current_count=len(current_lecturers)
            ),
            errors=errors,
        )

    async def async_step_chon_giang_vien(self, user_input: dict[str, Any] | None = None) -> Any:
        if user_input is not None:
            self._pending_data[CONF_EXTRA_LECTURERS] = user_input.get(CONF_EXTRA_LECTURERS) or []
            return self.async_create_entry(title="", data=self._pending_data)

        current_lecturers = self._config_entry.options.get(
            CONF_EXTRA_LECTURERS, self._config_entry.data.get(CONF_EXTRA_LECTURERS, [])
        )
        directory = self._lecturer_directory or {}
        if self._chosen_khoa == KHOA_ALL_SENTINEL:
            names = sorted(n for lst in directory.values() for n in lst)
        else:
            names = directory.get(self._chosen_khoa, [])
            # Đảm bảo tên đã chọn trước đó (nếu thuộc khoa khác) vẫn
            # hiện trong danh sách để không bị mất khỏi lựa chọn mặc định.
            for n in current_lecturers:
                if n not in names and n.startswith(f"{self._chosen_khoa}-"):
                    names.append(n)
            names.sort()

        return self.async_show_form(
            step_id="chon_giang_vien",
            data_schema=_schema_chon_giang_vien(names, list(current_lecturers)),
        )
