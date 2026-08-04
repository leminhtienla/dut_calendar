"""Client HTTP: đăng nhập & lấy dữ liệu lịch coi thi từ cb.dut.udn.vn."""
from __future__ import annotations

import logging

import aiohttp

from .const import (
    CB_EXAM_AJAX_URL as EXAM_AJAX_URL,
    CB_GRADE_DEADLINE_AJAX_URL as GRADE_DEADLINE_AJAX_URL,
    CB_LOGIN_URL as LOGIN_URL,
    CB_PAGE_COITHI_URL as PAGE_COITHI_URL,
    CB_PAGE_DIEMHP_URL as PAGE_DIEMHP_URL,
    CB_PAGE_LTDIEM_URL as PAGE_LTDIEM_URL,
    LOGIN_BUTTON_VALUE,
    LOGIN_FIELD_BUTTON,
)
from .parser_exam import is_login_page, parse_hidden_field

_LOGGER = logging.getLogger(__name__)


class CBDutAuthError(Exception):
    """Sai tài khoản/mật khẩu, hoặc không đăng nhập được."""


class CBDutClient:
    """Quản lý phiên đăng nhập + gọi API lấy lịch coi thi.

    Giữ 1 aiohttp.ClientSession riêng (có cookie jar) cho suốt vòng đời
    config entry, KHÔNG dùng chung session mặc định của Home Assistant,
    để cookie phiên đăng nhập của cổng cb.dut.udn.vn không lẫn với các
    tích hợp khác.
    """

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._logged_in = False

    async def _login(self) -> bool:
        """Đăng nhập: GET trang login lấy __VIEWSTATE, rồi POST tài khoản/mật khẩu."""
        async with self._session.get(LOGIN_URL, timeout=30) as resp:
            html = await resp.text()

        viewstate = parse_hidden_field(html, "__VIEWSTATE")
        viewstate_gen = parse_hidden_field(html, "__VIEWSTATEGENERATOR")

        data = {
            "_ctl0:Main_panLogin:Login_txtUS": self._username,
            "_ctl0:Main_panLogin:Login_txtPW": self._password,
            LOGIN_FIELD_BUTTON: LOGIN_BUTTON_VALUE,
        }
        if viewstate is not None:
            data["__VIEWSTATE"] = viewstate
        if viewstate_gen is not None:
            data["__VIEWSTATEGENERATOR"] = viewstate_gen

        async with self._session.post(
            LOGIN_URL, data=data, timeout=30, allow_redirects=False
        ) as resp:
            # Đăng nhập thành công -> server trả 302 redirect ra khỏi default.aspx
            # kèm set-cookie HocVi/TaiKhoan/MatKhau.
            success = resp.status in (301, 302) and "TaiKhoan" in resp.cookies

        self._logged_in = success
        if not success:
            _LOGGER.warning("Đăng nhập cb.dut.udn.vn thất bại cho tài khoản %s", self._username)
        return success

    async def ensure_logged_in(self) -> None:
        if not self._logged_in:
            ok = await self._login()
            if not ok:
                raise CBDutAuthError("Sai tài khoản/mật khẩu hoặc cổng từ chối đăng nhập")

    async def fetch_exam_duty_html(self, hoc_ky: str) -> str:
        """Lấy HTML bảng lịch coi thi (đã đăng ký) cho 1 mã học kỳ.

        Tự động đăng nhập lại đúng 1 lần nếu phát hiện phiên đã hết hạn
        (server trả về trang đăng nhập thay vì dữ liệu).
        """
        await self.ensure_logged_in()
        text = await self._call_exam_api(hoc_ky)

        if is_login_page(text):
            _LOGGER.info("Phiên cb.dut.udn.vn đã hết hạn, đăng nhập lại")
            self._logged_in = False
            await self.ensure_logged_in()
            text = await self._call_exam_api(hoc_ky)
            if is_login_page(text):
                raise CBDutAuthError("Đăng nhập lại vẫn không truy cập được dữ liệu")

        return text

    async def fetch_exam_duty_all_html(self, hoc_ky: str) -> str:
        """Lấy TOÀN BỘ danh sách ca thi (mọi khoa, mọi cán bộ coi thi)
        cho 1 mã học kỳ — dùng để lọc cục bộ theo tên 1 giảng viên khác
        (xem CONF_EXTRA_LECTURER). Response lớn hơn nhiều so với
        fetch_exam_duty_html (chỉ trả về ca của chính tài khoản đăng
        nhập), nên chỉ gọi khi tính năng này được bật.
        """
        await self.ensure_logged_in()
        text = await self._call_exam_api_all(hoc_ky)

        if is_login_page(text):
            self._logged_in = False
            await self.ensure_logged_in()
            text = await self._call_exam_api_all(hoc_ky)
            if is_login_page(text):
                raise CBDutAuthError("Đăng nhập lại vẫn không truy cập được dữ liệu")

        return text

    async def fetch_grade_deadline_html(self, ma_ca_thi: str) -> str:
        """Lấy response API LTDICT cho 1 mã ca thi — chỉ dùng để đọc phần
        header hạn nhập điểm ở đầu response (xem parser.parse_grade_deadline).
        """
        await self.ensure_logged_in()
        text = await self._call_grade_deadline_api(ma_ca_thi)

        if is_login_page(text):
            self._logged_in = False
            await self.ensure_logged_in()
            text = await self._call_grade_deadline_api(ma_ca_thi)
            if is_login_page(text):
                raise CBDutAuthError("Đăng nhập lại vẫn không truy cập được dữ liệu")

        return text

    async def fetch_hocky_options_html(self) -> str:
        """Lấy HTML trang PageCNDKCoiThi.aspx — chỉ dùng để đọc dropdown
        học kỳ có sẵn (parser.parse_hoc_ky_options), không lấy dữ liệu
        lịch coi thi ở đây (dùng fetch_exam_duty_html cho việc đó).
        """
        await self.ensure_logged_in()
        async with self._session.get(PAGE_COITHI_URL, timeout=30) as resp:
            text = await resp.text()

        if is_login_page(text):
            self._logged_in = False
            await self.ensure_logged_in()
            async with self._session.get(PAGE_COITHI_URL, timeout=30) as resp:
                text = await resp.text()

        return text

    async def fetch_class_list_html(self, hoc_ky: str) -> str:
        """Lấy danh sách lớp học phần phụ trách (để lấy mã lớp/MHP)."""
        await self.ensure_logged_in()
        text = await self._call_class_list_api(hoc_ky)

        if is_login_page(text):
            self._logged_in = False
            await self.ensure_logged_in()
            text = await self._call_class_list_api(hoc_ky)
            if is_login_page(text):
                raise CBDutAuthError("Đăng nhập lại vẫn không truy cập được dữ liệu")

        return text

    async def fetch_class_deadline_html(self, ma_lop: str) -> str:
        """Lấy response API ctrlListHP cho 1 mã lớp — chỉ dùng để đọc phần
        header hạn nhập điểm giữa kỳ/thành phần (parser.parse_class_deadline).
        """
        await self.ensure_logged_in()
        text = await self._call_class_deadline_api(ma_lop)

        if is_login_page(text):
            self._logged_in = False
            await self.ensure_logged_in()
            text = await self._call_class_deadline_api(ma_lop)
            if is_login_page(text):
                raise CBDutAuthError("Đăng nhập lại vẫn không truy cập được dữ liệu")

        return text

    async def _call_class_list_api(self, hoc_ky: str) -> str:
        params = {"E": "ctrlLopHP", "HK": hoc_ky}
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": PAGE_DIEMHP_URL,
        }
        async with self._session.post(
            GRADE_DEADLINE_AJAX_URL, params=params, headers=headers, timeout=30
        ) as resp:
            return await resp.text()

    async def _call_class_deadline_api(self, ma_lop: str) -> str:
        params = {"E": "ctrlListHP", "MHP": ma_lop, "ChR": "false"}
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": PAGE_DIEMHP_URL,
        }
        async with self._session.post(
            GRADE_DEADLINE_AJAX_URL, params=params, headers=headers, timeout=30
        ) as resp:
            return await resp.text()

    async def _call_grade_deadline_api(self, ma_ca_thi: str) -> str:
        params = {"E": "LTDICT", "CA": ma_ca_thi}
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": PAGE_LTDIEM_URL,
        }
        async with self._session.post(
            GRADE_DEADLINE_AJAX_URL, params=params, headers=headers, timeout=30
        ) as resp:
            return await resp.text()

    async def _call_exam_api(self, hoc_ky: str) -> str:
        params = {
            "E": "PhongThiDK",
            "HK": hoc_ky,
            "NCB": "false",
            "DDK": "true",
            "KHOA": "ALL",
        }
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": PAGE_COITHI_URL,
        }
        async with self._session.post(
            EXAM_AJAX_URL, params=params, headers=headers, timeout=30
        ) as resp:
            return await resp.text()

    async def _call_exam_api_all(self, hoc_ky: str) -> str:
        """Giống _call_exam_api nhưng NCB=true&DDK=false -> trả về TOÀN
        BỘ ca thi mọi cán bộ, mọi khoa (không giới hạn theo tài khoản
        đăng nhập). Response có thể tới ~1MB.
        """
        params = {
            "E": "PhongThiDK",
            "HK": hoc_ky,
            "NCB": "true",
            "DDK": "false",
            "KHOA": "ALL",
        }
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": PAGE_COITHI_URL,
        }
        async with self._session.post(
            EXAM_AJAX_URL, params=params, headers=headers, timeout=30
        ) as resp:
            return await resp.text()
