"""Chọn nhanh sinh viên để xem ảnh (không tải, không lưu ảnh).

Chỉ dựng ĐƯỜNG DẪN ảnh trên hệ thống trường rồi đưa ra thuộc tính; thẻ
Markdown trên dashboard sẽ hiển thị. Home Assistant KHÔNG tải, KHÔNG
lưu ảnh xuống đĩa, và danh sách sinh viên chỉ nằm trong bộ nhớ.

Danh sách sinh viên chỉ gồm MÃ SỐ + HỌ TÊN — số điện thoại và địa chỉ
trong bảng gốc không được đọc (xem parser_exam.parse_student_list).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_TYPE, DOMAIN, TYPE_LICHGIANGDAY
from .coordinator_exam import CBDutCoordinator
from .parser_exam import (
    anh_sinh_vien_url,
    hoc_ky_lien_truoc,
    parse_class_gpa,
    parse_lop_sinh_hoat_map,
    parse_student_class_info,
    parse_student_list,
)

_LOGGER = logging.getLogger(__name__)

KHONG_CHON = "— Chưa chọn —"
# Số lần tối đa lùi học kỳ khi tra GPA nếu kỳ đó chưa có điểm (kỳ mới
# nhập học / học kỳ chưa công bố điểm) — tránh vòng lặp vô hạn nếu
# trường chưa từng có dữ liệu quá xa.
SO_LAN_LUI_HOC_KY_TOI_DA = 4


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if (
        not isinstance(coordinator, CBDutCoordinator)
        or entry.data.get(CONF_TYPE) != TYPE_LICHGIANGDAY
    ):
        return

    lop = LopSelect(coordinator, entry)
    sv = SinhVienSelect(coordinator, entry, lop)
    lop.gan_o_sinh_vien(sv)
    async_add_entities([lop, sv])

    # Đăng ký vào registry toàn cục để service "nap_gpa_sinh_vien" (xem
    # __init__.py) tìm được đúng entity cần gọi, kể cả khi không truyền
    # entity_id cụ thể (trường hợp phổ biến: chỉ 1 entry loại này).
    hass.data.setdefault(DOMAIN, {}).setdefault("_sv_select_entities", []).append(sv)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="DUT Calendar - Lịch dạy",
        manufacturer="cb.dut.udn.vn (không chính thức)",
        model="Lịch giảng dạy",
    )


class LopSelect(SelectEntity):
    """Chọn lớp học phần đang dạy."""

    _attr_has_entity_name = True
    _attr_name = "Lớp"
    _attr_icon = "mdi:google-classroom"

    def __init__(self, coordinator: CBDutCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._chon = KHONG_CHON
        self._o_sinh_vien: SinhVienSelect | None = None
        self._attr_unique_id = f"{entry.entry_id}_chon_lop"
        self._attr_device_info = _device_info(entry)

    def gan_o_sinh_vien(self, o: SinhVienSelect) -> None:
        self._o_sinh_vien = o

    def _cac_lop(self) -> dict[str, str]:
        """{nhãn hiển thị -> mã lớp CHỈ GỒM CHỮ SỐ}.

        Bảng lịch giảng dạy hiển thị mã lớp có dấu chấm
        (1033580.2610.24.21) nhưng endpoint danh sách sinh viên chỉ
        nhận dạng liền 15 chữ số (103358026102421) — truyền sai định
        dạng thì trả về danh sách rỗng.
        """
        data = self._coordinator.data or {}
        out: dict[str, str] = {}
        for parsed in (data.get("lich_giang_day") or {}).values():
            for lop in parsed.get("lop_hoc", []):
                ma_hien = str(lop.get("ma_lop") or "").strip()
                # Chỉ bỏ dấu chấm/khoảng trắng, GIỮ hậu tố chữ của nhóm
                # con (vd 1033910.2610.23.20A -> 103391026102320A).
                ma_so = re.sub(r"[^0-9A-Za-z]", "", ma_hien)
                ten = str(lop.get("ten_lop") or "").strip()
                if ma_so:
                    out[f"{ten} ({ma_hien})" if ten else ma_hien] = ma_so
        return out

    @property
    def options(self) -> list[str]:
        return [KHONG_CHON] + sorted(self._cac_lop())

    @property
    def current_option(self) -> str:
        return self._chon if self._chon in self.options else KHONG_CHON

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"ma_lop": self._cac_lop().get(self._chon)}

    async def async_select_option(self, option: str) -> None:
        self._chon = option
        self.async_write_ha_state()
        if self._o_sinh_vien is not None:
            await self._o_sinh_vien.nap_danh_sach(self._cac_lop().get(option))


class SinhVienSelect(SelectEntity):
    """Chọn sinh viên trong lớp đã chọn; xuất đường dẫn ảnh."""

    _attr_has_entity_name = True
    _attr_name = "Sinh viên"
    _attr_icon = "mdi:account-search"

    def __init__(
        self, coordinator: CBDutCoordinator, entry: ConfigEntry, o_lop: LopSelect
    ) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._o_lop = o_lop
        self._danh_sach: list[dict[str, str]] = []
        self._chon = KHONG_CHON
        self._ma_lop: str | None = None
        self._trang_thai = "chưa chọn lớp"
        self._attr_unique_id = f"{entry.entry_id}_chon_sinh_vien"
        self._attr_device_info = _device_info(entry)
        # GPA CHỦ Ý không tự tải kèm danh sách — chỉ nạp khi người dùng
        # chủ động gọi service "nap_gpa_sinh_vien", đúng nguyên tắc hạn
        # chế tối đa tiếp xúc dữ liệu học tập của sinh viên.
        self._gpa: str | None = None
        self._hoc_ky_gpa: str | None = None
        self._trang_thai_gpa = "chưa nạp"
        # Cache map "tên lớp sinh hoạt" -> MLSH — danh sách lớp sinh
        # hoạt của khoa gần như cố định trong năm, không cần tải lại
        # mỗi lần bấm nạp GPA.
        self._lop_sh_map: dict[str, str] | None = None
        # Cache TOÀN BỘ điểm 1 lớp sinh hoạt theo (MLSH, học kỳ) —
        # 1 lớp học phần thường trộn sinh viên từ NHIỀU lớp sinh hoạt
        # khác nhau (khác khóa/lớp), nên khi xem lần lượt nhiều SV,
        # nếu trùng lớp sinh hoạt + học kỳ đã tra thì dùng lại ngay,
        # không gọi mạng lại (API vốn đã trả cả lớp, không có cách
        # xin đúng 1 sinh viên).
        self._gpa_cache: dict[tuple[str, str], dict[str, str]] = {}
        # Học kỳ ĐÃ XÁC ĐỊNH là có dữ liệu cho từng lớp sinh hoạt (MLSH)
        # — tiêu chí là LỚP có dữ liệu (bảng không rỗng), KHÔNG bắt
        # buộc đúng sinh viên đang xem phải có điểm (có thể SV đó
        # chuyển vào muộn, được miễn...). Nhờ vậy, 1 khi đã dò ra học
        # kỳ đúng cho 1 lớp sinh hoạt, các sinh viên KHÁC cùng lớp
        # dùng thẳng, không phải dò lại từ đầu mỗi người.
        self._mlsh_hoc_ky_da_biet: dict[str, str] = {}

    def _nhan(self, sv: dict[str, str]) -> str:
        """Nhãn trong ô chọn — có số thứ tự để khớp danh sách lớp in ra."""
        stt = sv.get("stt")
        dau = f"{stt}. " if stt else ""
        return f"{dau}{sv['ho_ten']} ({sv['ma_sv']})"

    async def nap_danh_sach(self, ma_lop: str | None) -> None:
        """Tải danh sách sinh viên của lớp vừa chọn (chỉ mã + họ tên)."""
        self._danh_sach = []
        self._chon = KHONG_CHON
        self._ma_lop = ma_lop
        self._trang_thai = "chưa chọn lớp" if not ma_lop else "đang tải…"
        self._gpa = None
        self._hoc_ky_gpa = None
        self._trang_thai_gpa = "chưa nạp"
        self.async_write_ha_state()
        if ma_lop:
            try:
                raw = await self._coordinator.client.fetch_student_list_html(ma_lop)
                self._danh_sach = await self.hass.async_add_executor_job(
                    parse_student_list, raw
                )
                # Gọi thêm chế độ xem ảnh để lấy LỚP SINH HOẠT
                try:
                    raw_anh = await self._coordinator.client.fetch_student_list_html(
                        ma_lop, anh=True
                    )
                    lop_sh = await self.hass.async_add_executor_job(
                        parse_student_class_info, raw_anh
                    )
                    for sv in self._danh_sach:
                        sv["lop_sinh_hoat"] = lop_sh.get(sv["ma_sv"], "")
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Không lấy được lớp sinh hoạt lớp %s: %s", ma_lop, err)

                self._trang_thai = (
                    f"đã tải {len(self._danh_sach)} sinh viên"
                    if self._danh_sach
                    else "tải được nhưng không đọc ra sinh viên nào"
                )
                if not self._danh_sach:
                    _LOGGER.warning(
                        "Lớp %s: tải được nhưng KHÔNG đọc được sinh viên nào "
                        "(kiểm tra mã lớp có đúng 15 chữ số không)",
                        ma_lop,
                    )
                else:
                    _LOGGER.debug("Lớp %s: %d sinh viên", ma_lop, len(self._danh_sach))
            except Exception as err:  # noqa: BLE001
                self._trang_thai = f"lỗi: {err}"
                _LOGGER.warning("Không lấy được danh sách sinh viên lớp %s: %s", ma_lop, err)
        self.async_write_ha_state()

    @property
    def options(self) -> list[str]:
        return [KHONG_CHON] + [self._nhan(sv) for sv in self._danh_sach]

    @property
    def current_option(self) -> str:
        return self._chon if self._chon in self.options else KHONG_CHON

    def _sv_dang_chon(self) -> dict[str, str] | None:
        return next((x for x in self._danh_sach if self._nhan(x) == self._chon), None)

    def co_sinh_vien_dang_chon(self) -> bool:
        """True nếu đang có 1 sinh viên cụ thể được chọn (không phải
        '— Chưa chọn —') — dùng bởi service nap_gpa_sinh_vien khi gọi
        không kèm entity_id cụ thể.
        """
        return self._sv_dang_chon() is not None

    def co_gpa_dang_hien(self) -> bool:
        """True nếu GPA đang có giá trị hiển thị — dùng bởi service
        an_gpa_sinh_vien khi gọi không kèm entity_id cụ thể.
        """
        return self._gpa is not None

    @property
    def entity_picture(self) -> str | None:
        """Ảnh hiện ngay trên entity (more-info, thẻ picture-entity...).

        Đây chỉ là ĐƯỜNG DẪN — trình duyệt tải thẳng từ máy chủ trường,
        Home Assistant không tải và không lưu ảnh.
        """
        sv = self._sv_dang_chon()
        return anh_sinh_vien_url(sv["ma_sv"]) if sv else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        sv = self._sv_dang_chon()
        return {
            "stt": sv.get("stt") if sv else None,
            "ma_sv": sv["ma_sv"] if sv else None,
            "ho_ten": sv["ho_ten"] if sv else None,
            "dien_thoai": sv.get("dien_thoai") or None if sv else None,
            "lop_sinh_hoat": sv.get("lop_sinh_hoat") or None if sv else None,
            # Chỉ là ĐƯỜNG DẪN tới ảnh trên máy chủ trường — HA không tải về.
            "anh_url": anh_sinh_vien_url(sv["ma_sv"]) if sv else None,
            "so_sinh_vien": len(self._danh_sach),
            # Thông tin chẩn đoán — xem ngay trong more-info, khỏi đào log
            "ma_lop_da_goi": self._ma_lop,
            "trang_thai": self._trang_thai,
            # GPA CHỦ Ý mặc định None — chỉ có giá trị sau khi gọi
            # service "dut_calendar.nap_gpa_sinh_vien" (xem __init__.py).
            "gpa_tich_luy": self._gpa,
            "gpa_hoc_ky": self._hoc_ky_gpa,
            "gpa_trang_thai": self._trang_thai_gpa,
        }

    async def async_select_option(self, option: str) -> None:
        self._chon = option
        # Đổi sinh viên -> GPA cũ (của người trước) không còn đúng nữa.
        self._gpa = None
        self._hoc_ky_gpa = None
        self._trang_thai_gpa = "chưa nạp"
        self.async_write_ha_state()

    async def async_nap_gpa(self) -> None:
        """Tra điểm TBC tích lũy của sinh viên ĐANG CHỌN — CHỈ chạy khi
        được gọi tường minh (qua service), không tự động kèm theo bất
        kỳ luồng nào khác.

        Tự lùi dần học kỳ (theo `hoc_ky_lien_truoc`, dựa đúng quy ước
        mã học kỳ chính thức, không đoán công thức mới) cho tới khi
        LỚP SINH HOẠT có dữ liệu (bảng không rỗng) — KHÔNG bắt buộc
        đúng sinh viên đang xem phải có điểm trong đó (SV có thể
        chuyển vào muộn, được miễn học phần...). Tối đa lùi
        `SO_LAN_LUI_HOC_KY_TOI_DA` lần.

        Học kỳ xác định được cho 1 lớp sinh hoạt sẽ dùng CHUNG cho mọi
        sinh viên khác cùng lớp — chỉ cần dò 1 lần/lớp, không dò lại
        theo từng người.
        """
        sv = self._sv_dang_chon()
        if sv is None:
            self._trang_thai_gpa = "chưa chọn sinh viên"
            self.async_write_ha_state()
            return

        ten_lop_sh = (sv.get("lop_sinh_hoat") or "").strip()
        if not ten_lop_sh:
            self._trang_thai_gpa = "sinh viên này không rõ lớp sinh hoạt"
            self.async_write_ha_state()
            return

        self._trang_thai_gpa = "đang tra…"
        self.async_write_ha_state()

        try:
            if self._lop_sh_map is None:
                khoa = (self._coordinator.username or "")[:3]
                if not khoa.isdigit():
                    self._trang_thai_gpa = "không xác định được mã khoa từ tài khoản"
                    self.async_write_ha_state()
                    return
                raw_lop = await self._coordinator.client.fetch_lop_sinh_hoat_list_html(khoa)
                self._lop_sh_map = await self.hass.async_add_executor_job(
                    parse_lop_sinh_hoat_map, raw_lop
                )

            mlsh = self._lop_sh_map.get(ten_lop_sh)
            if not mlsh:
                self._trang_thai_gpa = f"không tìm thấy mã lớp sinh hoạt cho '{ten_lop_sh}'"
                self.async_write_ha_state()
                return

            # Lớp sinh hoạt này đã từng dò ra học kỳ có dữ liệu -> dùng
            # thẳng, không dò lại (áp dụng cho SV khác cùng lớp).
            hoc_ky = self._mlsh_hoc_ky_da_biet.get(mlsh)

            if hoc_ky is None:
                hoc_ky_list = self._coordinator.hoc_ky_list
                thu = hoc_ky_lien_truoc(hoc_ky_list[0]) if hoc_ky_list else None
                if not thu:
                    self._trang_thai_gpa = "chưa cấu hình học kỳ để suy ra mã học kỳ tra GPA"
                    self.async_write_ha_state()
                    return

                for _lan in range(SO_LAN_LUI_HOC_KY_TOI_DA):
                    cache_key = (mlsh, thu)
                    gpa_map = self._gpa_cache.get(cache_key)
                    if gpa_map is None:
                        raw_gpa = await self._coordinator.client.fetch_class_gpa_html(
                            mlsh, thu
                        )
                        gpa_map = await self.hass.async_add_executor_job(
                            parse_class_gpa, raw_gpa
                        )
                        self._gpa_cache[cache_key] = gpa_map
                    if gpa_map:
                        # LỚP có dữ liệu ở kỳ này -> chốt dùng kỳ này
                        # cho cả lớp sinh hoạt, không cần đúng SV hiện
                        # tại phải có điểm trong đó.
                        hoc_ky = thu
                        self._mlsh_hoc_ky_da_biet[mlsh] = thu
                        break
                    thu_truoc = hoc_ky_lien_truoc(thu)
                    if not thu_truoc:
                        break
                    thu = thu_truoc

            if hoc_ky is None:
                self._trang_thai_gpa = (
                    f"lớp sinh hoạt '{ten_lop_sh}' không có dữ liệu điểm trong "
                    f"{SO_LAN_LUI_HOC_KY_TOI_DA} học kỳ gần nhất"
                )
                self.async_write_ha_state()
                return

            gpa_map = self._gpa_cache.get((mlsh, hoc_ky), {})
            gia_tri = gpa_map.get(sv["ma_sv"])
            self._gpa = gia_tri
            self._hoc_ky_gpa = hoc_ky if gia_tri else None
            self._trang_thai_gpa = (
                "đã nạp"
                if gia_tri
                else f"lớp có dữ liệu học kỳ {hoc_ky} nhưng sinh viên này chưa có điểm"
            )
            self.async_write_ha_state()
        except Exception as err:  # noqa: BLE001
            self._trang_thai_gpa = f"lỗi: {err}"
            _LOGGER.warning("Không tra được GPA cho %s: %s", sv.get("ma_sv"), err)
            self.async_write_ha_state()

    async def async_an_gpa(self) -> None:
        """Ẩn GPA đang hiển thị — chỉ xóa GIÁ TRỊ đang show trên
        attribute, KHÔNG đụng tới cache (`_gpa_cache`,
        `_mlsh_hoc_ky_da_biet`). Nhờ vậy nếu gọi lại
        `nap_gpa_sinh_vien` sau đó, dữ liệu đã có sẵn trong cache nên
        hiện lại gần như tức thì, không gọi mạng lại.
        """
        self._gpa = None
        self._hoc_ky_gpa = None
        self._trang_thai_gpa = "đã ẩn"
        self.async_write_ha_state()
