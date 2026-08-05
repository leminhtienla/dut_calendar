"""Coordinator: đăng nhập, tải lịch coi thi định kỳ, cảnh báo mục mới."""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_exam import CBDutAuthError, CBDutClient
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_EXAM_DURATION,
    CONF_EXTRA_LECTURER,
    CONF_EXTRA_LECTURERS,
    CONF_HOC_KY,
    LICHTUAN_BASE_URL,
    CONF_NOTIFY_SERVICE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TYPE,
    CONF_USERNAME,
    DEFAULT_EXAM_DURATION,
    DEFAULT_SCAN_INTERVAL_EXAM as DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_GRADE_DEADLINE_CHANGED,
    EVENT_NEW_EXAM_DUTY,
    MAX_STORED_HASHES_EXAM as MAX_STORED_HASHES,
    STORAGE_KEY_TEMPLATE,
    STORAGE_VERSION,
    TYPE_COITHI,
    TYPE_DEADLINE_DIEM,
    TYPE_LICHGIANGDAY,
)
from .parser_exam import (
    duty_role,
    exam_hash,
    filter_exam_duty_by_lecturer,
    filter_exam_duty_by_lecturers,
    infer_self_name,
    infer_self_name_from_khoa,
    apply_bao_nghi,
    build_teaching_events,
    lgd_to_grade_deadlines,
    parse_class_deadline,
    parse_class_list,
    parse_exam_datetime,
    parse_exam_duty,
    parse_grade_deadline,
    filter_lop_hp_by_lecturer,
    parse_bao_nghi,
    parse_bieu_do_nam_hoc,
    parse_lich_giang_day,
    parse_lop_hp_khoa,
)
from .parser_public import parse_all_weeks

_LOGGER = logging.getLogger(__name__)


class CBDutCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Tải & xử lý dữ liệu lịch coi thi từ cb.dut.udn.vn."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        interval_min = entry.options.get(
            CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval_min),
        )

        # Session HTTP riêng (cookie jar riêng), không dùng chung của HA,
        # để cookie đăng nhập cổng cb.dut.udn.vn không lẫn integration khác.
        self._session = aiohttp.ClientSession()
        username = entry.options.get(CONF_USERNAME, entry.data[CONF_USERNAME])
        password = entry.options.get(CONF_PASSWORD, entry.data[CONF_PASSWORD])
        self._client = CBDutClient(self._session, username, password)

        self._store: Store = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_TEMPLATE.format(entry_id=entry.entry_id)
        )
        self._seen_hashes: set[str] = set()
        self._known_deadlines: dict[str, dict[str, str | None]] = {}
        self._loaded_storage = False

    async def async_close(self) -> None:
        await self._session.close()

    @property
    def hoc_ky_list(self) -> list[str]:
        raw = self.entry.options.get(
            CONF_HOC_KY, self.entry.data.get(CONF_HOC_KY, "")
        )
        return [x.strip() for x in str(raw).split(",") if x.strip()]

    @property
    def exam_duration(self) -> int:
        return int(
            self.entry.options.get(
                CONF_EXAM_DURATION,
                self.entry.data.get(CONF_EXAM_DURATION, DEFAULT_EXAM_DURATION),
            )
        )

    @property
    def notify_service(self) -> str | None:
        val = self.entry.options.get(
            CONF_NOTIFY_SERVICE, self.entry.data.get(CONF_NOTIFY_SERVICE, "")
        )
        return val.strip() if val and val.strip() else None

    @property
    def is_coithi(self) -> bool:
        return self.entry.data.get(CONF_TYPE) == TYPE_COITHI

    @property
    def is_deadline_diem(self) -> bool:
        return self.entry.data.get(CONF_TYPE) == TYPE_DEADLINE_DIEM

    @property
    def username(self) -> str:
        return str(
            self.entry.options.get(CONF_USERNAME, self.entry.data.get(CONF_USERNAME, ""))
        )

    @property
    def is_lichgiangday(self) -> bool:
        return self.entry.data.get(CONF_TYPE) == TYPE_LICHGIANGDAY

    @property
    def extra_lecturers(self) -> list[str]:
        """Danh sách tên giảng viên khác cần theo dõi thêm (đã chọn qua
        UI khoa/tên). Vẫn đọc tương thích ngược cấu hình CŨ (1 tên dạng
        text tự do) nếu entry chưa được cấu hình lại theo cách mới.
        """
        names = self.entry.options.get(
            CONF_EXTRA_LECTURERS, self.entry.data.get(CONF_EXTRA_LECTURERS, None)
        )
        if isinstance(names, list) and names:
            return [n for n in names if n and n.strip()]

        # Tương thích ngược: cấu hình cũ chỉ có 1 tên dạng text tự do
        old_val = self.entry.options.get(
            CONF_EXTRA_LECTURER, self.entry.data.get(CONF_EXTRA_LECTURER, "")
        )
        return [old_val.strip()] if old_val and old_val.strip() else []

    async def _async_load_storage(self) -> None:
        if self._loaded_storage:
            return
        data = await self._store.async_load()
        if data and isinstance(data.get("seen"), list):
            self._seen_hashes = set(data["seen"])
        if data and isinstance(data.get("deadlines"), dict):
            self._known_deadlines = data["deadlines"]
        self._loaded_storage = True

    async def _async_save_storage(self) -> None:
        hashes = list(self._seen_hashes)[-MAX_STORED_HASHES:]
        self._seen_hashes = set(hashes)
        await self._store.async_save(
            {"seen": hashes, "deadlines": self._known_deadlines}
        )

    async def _async_update_data(self) -> dict[str, Any]:
        await self._async_load_storage()

        hoc_ky_list = self.hoc_ky_list
        if not hoc_ky_list:
            return {"duties": [], "new_duties": []}

        all_duties: list[dict[str, Any]] = []
        # Loại "lịch giảng dạy" không cần danh sách ca coi thi -> bỏ qua
        # để khỏi tải thừa.
        for hoc_ky in ([] if self.is_lichgiangday else hoc_ky_list):
            try:
                html = await self._client.fetch_exam_duty_html(hoc_ky)
            except CBDutAuthError as err:
                raise UpdateFailed(f"Lỗi đăng nhập cb.dut.udn.vn: {err}") from err
            except Exception as err:  # noqa: BLE001
                raise UpdateFailed(f"Lỗi tải lịch coi thi (HK {hoc_ky}): {err}") from err

            duties = await self.hass.async_add_executor_job(
                parse_exam_duty, html, hoc_ky
            )
            for d in duties:
                d["extra_lecturer_match"] = False
            all_duties.extend(duties)

        # Suy luận tên hiển thị của chính tài khoản đăng nhập từ danh
        # sách ca thi CỦA CHÍNH MÌNH (trước khi gộp thêm ca của giảng
        # viên khác) — CB1/CB2 không cố định vị trí nên phải suy luận,
        # không thể giả định CB1 luôn là mình.
        self_name = await self.hass.async_add_executor_job(infer_self_name, all_duties)
        for d in all_duties:
            d["target_name"] = self_name
            d["role"] = duty_role(d, self_name)

        # --- Theo dõi thêm giảng viên khác (nếu có chọn) ---
        # Tải danh sách TOÀN BỘ (không giới hạn theo tài khoản đăng nhập)
        # rồi lọc cục bộ theo (các) tên đã chọn, gộp thêm vào all_duties.
        lecturers = self.extra_lecturers
        if self.is_coithi and lecturers:
            for hoc_ky in hoc_ky_list:
                try:
                    html_all = await self._client.fetch_exam_duty_all_html(hoc_ky)
                except CBDutAuthError as err:
                    raise UpdateFailed(f"Lỗi đăng nhập cb.dut.udn.vn: {err}") from err
                except Exception:  # noqa: BLE001
                    _LOGGER.warning(
                        "Không lấy được danh sách toàn bộ ca thi cho HK %s (giảng viên khác)",
                        hoc_ky,
                    )
                    continue

                all_that_week = await self.hass.async_add_executor_job(
                    parse_exam_duty, html_all, hoc_ky
                )
                matched = await self.hass.async_add_executor_job(
                    filter_exam_duty_by_lecturers, all_that_week, lecturers
                )
                for d in matched:
                    d["extra_lecturer_match"] = True
                    # Xác định ĐÚNG người trong (các) giảng viên đang
                    # theo dõi khớp với dòng này (để hiện tên + vai trò
                    # GT1/GT2 chính xác, không phải tên đầu tiên bất kỳ).
                    matched_name = next(
                        (
                            lecturer
                            for lecturer in lecturers
                            if duty_role(d, lecturer) is not None
                        ),
                        None,
                    )
                    d["target_name"] = matched_name
                    d["role"] = duty_role(d, matched_name)
                all_duties.extend(matched)

        # Khử trùng theo id (vd giảng viên khác vốn đã là "Cán bộ 2" cùng
        # coi thi với tài khoản đang đăng nhập -> giữ lại bản ghi xuất
        # hiện TRƯỚC, tức bản của chính tài khoản đăng nhập).
        seen_ids: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for d in all_duties:
            _id = exam_hash(d)
            d["id"] = _id
            if _id in seen_ids:
                continue
            seen_ids.add(_id)
            deduped.append(d)
        all_duties = deduped

        # Tính start/end + id cho từng ca thi
        duration = self.exam_duration
        for d in all_duties:
            start, end = parse_exam_datetime(d["thoi_gian_raw"], duration)
            d["start"] = start
            d["end"] = end
            d["id"] = exam_hash(d)

        from datetime import datetime as _dt

        all_duties.sort(key=lambda d: d["start"] or _dt.min)

        new_duties = [d for d in all_duties if d["id"] not in self._seen_hashes]

        if self.is_coithi and new_duties:
            for d in new_duties:
                self._seen_hashes.add(d["id"])
                # CalendarEvent/datetime không tự serialize qua bus event, nên
                # bắn dữ liệu dạng chuỗi để tránh lỗi JSON serialize.
                event_data = {k: v for k, v in d.items() if k not in ("start", "end")}
                event_data["start"] = d["start"].isoformat() if d["start"] else None
                event_data["end"] = d["end"].isoformat() if d["end"] else None
                self.hass.bus.async_fire(EVENT_NEW_EXAM_DUTY, event_data)
            await self._async_save_storage()
            await self._async_notify(new_duties)

        # --- Hạn nhập điểm (chỉ với entry loại "dut_deadline_diem") ---
        # Nguồn CHÍNH: trang "Kế hoạch giảng dạy & thi" — MỘT request cho
        # cả học kỳ, trả về đủ: hạn nhập điểm GK/TP/CK từng lớp, hạn đính
        # chính, ĐÃ XÁC NHẬN NHẬP ĐIỂM CHƯA, hạn nộp bảng in điểm, và mốc
        # thi chung. Trước đây phải gọi ctrlLopHP + ctrlListHP cho TỪNG
        # lớp (≈11 request/học kỳ) mà vẫn thiếu các thông tin trên.
        # Nếu endpoint này lỗi -> tự lùi về cách cũ để không mất dữ liệu.
        # CHỦ Ý: chỉ đọc các bảng kế hoạch/hạn nộp, KHÔNG đụng tới bảng
        # điểm hay thông tin sinh viên.
        grade_deadlines: dict[str, dict[str, Any]] = {}
        changed_deadlines: list[dict[str, Any]] = []
        lich_giang_day: dict[str, Any] = {}

        if self.is_deadline_diem or self.is_lichgiangday:
            for hoc_ky in hoc_ky_list:
                hk_result: dict[str, Any] | None = None

                try:
                    raw = await self._client.fetch_lich_giang_day_html(hoc_ky)
                    parsed_lgd = await self.hass.async_add_executor_job(
                        parse_lich_giang_day, raw
                    )
                    if parsed_lgd.get("nhap_diem_theo_lop") or parsed_lgd.get("thi_chung"):
                        lich_giang_day[hoc_ky] = parsed_lgd
                        hk_result = await self.hass.async_add_executor_job(
                            lgd_to_grade_deadlines, parsed_lgd, hoc_ky
                        )
                except CBDutAuthError as err:
                    raise UpdateFailed(f"Lỗi đăng nhập cb.dut.udn.vn: {err}") from err
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "Không tải được Kế hoạch giảng dạy HK %s (%s), lùi về cách cũ",
                        hoc_ky,
                        err,
                    )

                if not self.is_deadline_diem:
                    # Loại "lịch giảng dạy" chỉ cần bảng lớp/TKB,
                    # không tính hạn nộp điểm, không thông báo.
                    continue

                if hk_result is None:
                    hk_result = await self._async_fetch_deadlines_legacy(hoc_ky, all_duties)

                grade_deadlines[hoc_ky] = hk_result

                if self._known_deadlines.get(hoc_ky) != hk_result:
                    self._known_deadlines[hoc_ky] = hk_result
                    changed_deadlines.append({"hoc_ky": hoc_ky, **hk_result})

            if changed_deadlines:
                for c in changed_deadlines:
                    self.hass.bus.async_fire(EVENT_GRADE_DEADLINE_CHANGED, c)
                await self._async_save_storage()
                await self._async_notify_deadline(changed_deadlines)

        # --- Buổi dạy cụ thể (Calendar "Giảng dạy") ---
        # Thời khóa biểu chỉ cho SỐ TUẦN học (vd "22-27;31-40"), phải
        # quy đổi sang ngày thật. Bảng quy đổi lấy từ dropdown CÔNG KHAI
        # của chính cb.dut.udn.vn, dự phòng bằng lichtuan.dut.udn.vn —
        # chính xác hơn tự cộng 7 ngày từ tuần 1, vì năm học có tuần
        # ngắt quãng (nghỉ Tết). Chỉ áp dụng cho loại "lịch giảng dạy".
        buoi_day: list[dict[str, Any]] = []
        if lich_giang_day and self.is_lichgiangday:
            # LƯU Ý: mỗi HỌC KỲ thuộc một NĂM HỌC khác nhau nên phải
            # dựng bảng quy đổi tuần RIÊNG cho từng học kỳ. Trước đây
            # dùng chung 1 bảng lấy từ học kỳ đầu tiên -> khi chọn
            # nhiều học kỳ khác năm học (vd HK2 25-26 + HK1 26-27),
            # lớp của năm sau bị quy ra ngày của năm trước (lệch ~1 năm)
            # nên không thấy buổi dạy nào ở tuần hiện tại/tuần sau.
            week_maps: dict[str, dict[int, Any]] = {}
            for hk in lich_giang_day:
                try:
                    raw_bd = await self._client.fetch_bieu_do_nam_hoc_html(hk)
                    wm = await self.hass.async_add_executor_job(
                        parse_bieu_do_nam_hoc, raw_bd, hk
                    )
                    if wm:
                        week_maps[hk] = wm
                        _LOGGER.debug(
                            "HK %s: đọc được %d tuần, tuần 1 = %s",
                            hk, len(wm), wm.get(1)
                        )
                    else:
                        _LOGGER.warning(
                            "HK %s: đọc biểu đồ năm học nhưng KHÔNG parse được tuần nào", hk
                        )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Không đọc được biểu đồ năm học HK %s: %s", hk, err)

            # Dự phòng cho học kỳ không đọc được biểu đồ: dropdown công
            # khai của lichtuan.dut.udn.vn (chỉ đúng cho NĂM HỌC HIỆN
            # TẠI nên chỉ dùng khi thiếu, không áp cho mọi học kỳ).
            missing = [hk for hk in lich_giang_day if hk not in week_maps]
            if missing:
                try:
                    session = async_get_clientsession(self.hass)
                    async with session.get(LICHTUAN_BASE_URL, timeout=30) as resp:
                        resp.raise_for_status()
                        html_week = await resp.text()
                    wm_public = await self.hass.async_add_executor_job(
                        parse_all_weeks, html_week
                    )
                    # CHỈ dùng dự phòng khi ĐÚNG năm học, vì lichtuan chỉ
                    # có tuần của năm học HIỆN TẠI. Áp nhầm sang năm học
                    # khác sẽ sinh ra buổi dạy lệch nguyên 1 năm — sai
                    # dữ liệu còn tệ hơn là để trống.
                    nam_dau_public = None
                    if wm_public and wm_public.get(1):
                        d1 = wm_public[1]
                        nam_dau_public = d1.year if d1.month >= 8 else d1.year - 1

                    for hk in missing:
                        if not wm_public or nam_dau_public is None:
                            continue
                        nam_dau_hk = 2000 + int(hk[:2]) if hk[:2].isdigit() else None
                        if nam_dau_hk == nam_dau_public:
                            week_maps[hk] = wm_public
                            _LOGGER.warning(
                                "HK %s dùng bảng tuần dự phòng từ lichtuan", hk
                            )
                        else:
                            _LOGGER.error(
                                "HK %s (năm học %s-%s): không đọc được biểu đồ năm học "
                                "và KHÔNG dùng được bảng dự phòng (lichtuan đang ở năm "
                                "học %s-%s). Bỏ qua để tránh tạo lịch sai năm.",
                                hk, nam_dau_hk, (nam_dau_hk or 0) + 1,
                                nam_dau_public, nam_dau_public + 1,
                            )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Không lấy được bảng quy đổi tuần học: %s", err)

            for hk, parsed_lgd in lich_giang_day.items():
                wm = week_maps.get(hk)
                if not wm:
                    _LOGGER.warning("Bỏ qua dựng lịch dạy HK %s: thiếu bảng quy đổi tuần", hk)
                    continue

                # Tuần thi giữa kỳ nằm TRONG chuỗi tuần của thời khóa
                # biểu nhưng KHÔNG lên lớp -> phải loại ra, nếu không
                # sẽ sinh buổi dạy "ma".
                exclude: dict[str, set[int]] = {}
                for row in parsed_lgd.get("nhap_diem_theo_lop", []):
                    tuan_thi = str(row.get("tuan_thi") or "").strip()
                    if tuan_thi.isdigit():
                        ma_digits = re.sub(r"\D", "", str(row.get("ma_lop") or ""))
                        exclude.setdefault(ma_digits, set()).add(int(tuan_thi))

                lop_hoc = parsed_lgd.get("lop_hoc", [])
                co_tkb = sum(1 for l in lop_hoc if l.get("tkb_tuan"))
                ev_hk = await self.hass.async_add_executor_job(
                    build_teaching_events, lop_hoc, wm, exclude
                )
                _LOGGER.debug(
                    "HK %s: %d lớp (%d lớp có TKB) -> %d buổi dạy",
                    hk, len(lop_hoc), co_tkb, len(ev_hk)
                )
                if lop_hoc and not ev_hk:
                    _LOGGER.warning(
                        "HK %s: có %d lớp nhưng KHÔNG dựng được buổi dạy nào "
                        "(số lớp có TKB: %d, số tuần tra được: %d)",
                        hk, len(lop_hoc), co_tkb, len(wm)
                    )
                buoi_day.extend(ev_hk)

            # Áp dụng báo nghỉ / dạy bù: buổi đã báo nghỉ được
            # đánh dấu (không im lặng biến mất), buổi dạy bù được
            # thêm vào đúng ngày/giờ/phòng đã đăng ký.
            bao_nghi_all: list[dict[str, Any]] = []
            for hk in lich_giang_day:
                try:
                    raw_bn = await self._client.fetch_bao_nghi_html(hk)
                    bao_nghi_all.extend(
                        await self.hass.async_add_executor_job(parse_bao_nghi, raw_bn)
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Không lấy được báo nghỉ/dạy bù HK %s: %s", hk, err)

            if bao_nghi_all:
                buoi_day = await self.hass.async_add_executor_job(
                    apply_bao_nghi, buoi_day, bao_nghi_all
                )

            # --- Lịch dạy của giảng viên khác (nếu có chọn) ---
            # Lấy từ danh sách lớp học phần CỦA CẢ KHOA. Lưu ý:
            # nguồn này KHÔNG có thông tin báo nghỉ/dạy bù, nên
            # lịch của người khác chỉ là thời khóa biểu gốc.
            # Tên lưu dạng "<mã khoa>|<họ tên>".
            theo_khoa: dict[str, list[str]] = {}
            for muc in self.extra_lecturers:
                if "|" not in muc:
                    continue
                khoa, ten = muc.split("|", 1)
                theo_khoa.setdefault(khoa.strip(), []).append(ten.strip())

            # Cache theo (học kỳ, khoa) để không tải trùng — response
            # danh sách lớp cả khoa khá nặng (~170KB).
            cache_khoa: dict[tuple[str, str], list[dict[str, Any]]] = {}

            async def _rows_of(hk: str, khoa: str) -> list[dict[str, Any]]:
                key = (hk, khoa)
                if key in cache_khoa:
                    return cache_khoa[key]
                raw_kh = await self._client.fetch_lop_hp_khoa_html(hk, khoa)
                rows = await self.hass.async_add_executor_job(parse_lop_hp_khoa, raw_kh)
                cache_khoa[key] = rows
                return rows

            # Nếu có theo dõi người khác thì gắn luôn TÊN CỦA CHÍNH
            # MÌNH lên buổi dạy của mình, để nhìn lịch biết ngay
            # buổi nào của ai (trước đây chỉ người khác mới có tên).
            # Khoa của mình suy từ 3 số đầu của tài khoản (theo quy
            # ước mã tài khoản của trường: 3 số mã đơn vị + tên).
            if theo_khoa:
                own_khoa = (self.username or "")[:3]
                if own_khoa.isdigit():
                    for hk, parsed_lgd in lich_giang_day.items():
                        own_ma = {
                            re.sub(r"\D", "", str(l.get("ma_lop") or ""))
                            for l in parsed_lgd.get("lop_hoc", [])
                        }
                        try:
                            rows_own = await _rows_of(hk, own_khoa)
                        except Exception:  # noqa: BLE001
                            continue
                        ten_toi = await self.hass.async_add_executor_job(
                            infer_self_name_from_khoa, rows_own, own_ma
                        )
                        if ten_toi:
                            for ev in buoi_day:
                                ev.setdefault("nguoi", ten_toi)

            for hk in lich_giang_day:
                wm_hk = week_maps.get(hk)
                if not wm_hk:
                    continue
                for khoa, ten_list in theo_khoa.items():
                    try:
                        rows_kh = await _rows_of(hk, khoa)
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning(
                            "Không lấy được lớp học phần khoa %s (HK %s): %s",
                            khoa,
                            hk,
                            err,
                        )
                        continue

                    for ten in ten_list:
                        lop_cua_ho = await self.hass.async_add_executor_job(
                            filter_lop_hp_by_lecturer, rows_kh, ten
                        )
                        ev_ho = await self.hass.async_add_executor_job(
                            build_teaching_events, lop_cua_ho, wm_hk, None
                        )
                        for ev in ev_ho:
                            ev["nguoi"] = ten
                        buoi_day.extend(ev_ho)

            buoi_day.sort(key=lambda e: e["start"])

        return {
            "duties": all_duties,
            "new_duties": new_duties,
            "grade_deadlines": grade_deadlines,
            "lich_giang_day": lich_giang_day,
            "buoi_day": buoi_day,
        }

    async def _async_fetch_deadlines_legacy(
        self, hoc_ky: str, all_duties: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Cách lấy hạn nộp điểm CŨ (nhiều request), chỉ dùng khi trang
        Kế hoạch giảng dạy không truy cập được.
        """
        hk_result: dict[str, Any] = {"ca_thi_chung": None, "theo_lop": {}}

        sample_ca = next(
            (
                d["ma_ca_thi"]
                for d in all_duties
                if d["hoc_ky_label"] == hoc_ky and d.get("ma_ca_thi")
            ),
            None,
        )
        if sample_ca:
            try:
                raw = await self._client.fetch_grade_deadline_html(sample_ca)
                hk_result["ca_thi_chung"] = await self.hass.async_add_executor_job(
                    parse_grade_deadline, raw
                )
            except CBDutAuthError as err:
                raise UpdateFailed(f"Lỗi đăng nhập cb.dut.udn.vn: {err}") from err
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Không lấy được hạn điểm cuối kỳ thi chung cho HK %s", hoc_ky)

        try:
            class_list_html = await self._client.fetch_class_list_html(hoc_ky)
            classes = await self.hass.async_add_executor_job(parse_class_list, class_list_html)
        except CBDutAuthError as err:
            raise UpdateFailed(f"Lỗi đăng nhập cb.dut.udn.vn: {err}") from err
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Không lấy được danh sách lớp cho HK %s", hoc_ky)
            classes = []

        for cls in classes:
            try:
                raw = await self._client.fetch_class_deadline_html(cls["ma_lop"])
            except CBDutAuthError as err:
                raise UpdateFailed(f"Lỗi đăng nhập cb.dut.udn.vn: {err}") from err
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Không lấy được hạn điểm cho lớp %s", cls["ma_lop"])
                continue

            parsed = await self.hass.async_add_executor_job(parse_class_deadline, raw)
            hk_result["theo_lop"][cls["ma_lop"]] = {
                **parsed,
                "ten_lop": cls["ten_lop"],
                "ma_lop_display": cls["ma_lop_display"],
            }

        return hk_result

    async def _async_notify_deadline(self, changed: list[dict[str, Any]]) -> None:
        title = "Hạn nộp điểm cập nhật"
        lines = []
        for c in changed:
            lines.append(f"HK {c['hoc_ky']}:")
            ca_thi_chung = c.get("ca_thi_chung")
            if ca_thi_chung:
                lines.append(
                    f"  • Thi chung: nhập điểm {ca_thi_chung.get('ngay_bat_dau') or '?'} → "
                    f"{ca_thi_chung.get('ngay_ket_thuc') or '?'}, nộp bản điểm "
                    f"{ca_thi_chung.get('ngay_nop_ban_diem') or '?'}"
                )
            for ma_lop, info in c.get("theo_lop", {}).items():
                gk = info.get("ngay_giua_ky")
                tp = info.get("ngay_thanh_phan") or info.get("ngay_cuoi_ky")
                if gk or tp:
                    lines.append(
                        f"  • {info.get('ten_lop', ma_lop)}: giữa kỳ {gk or '?'}, "
                        f"thành phần/cuối kỳ {tp or '?'}"
                    )
        message = "\n".join(lines)

        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"{DOMAIN}_{self.entry.entry_id}_deadline",
            },
            blocking=False,
        )

        service = self.notify_service
        if service and "." in service:
            domain, _, service_name = service.partition(".")
            try:
                await self.hass.services.async_call(
                    domain,
                    service_name,
                    {"title": title, "message": message},
                    blocking=False,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Không thể gọi notify service '%s'", service)

    async def _async_notify(self, new_duties: list[dict[str, Any]]) -> None:
        title = f"Lịch coi thi: {len(new_duties)} ca thi mới"
        lines = []
        for d in new_duties[:10]:
            start = d["start"]
            time_str = start.strftime("%H:%M %d/%m/%Y") if start else d["thoi_gian_raw"]
            name = d.get("target_name")
            role = d.get("role")
            tag = f"[{name} · GT{role}] " if name and role else ""
            other = d["can_bo_2"] if role == "1" else d["can_bo_1"]
            lines.append(
                f"• {tag}{d['mon_thi']} — {time_str}, phòng {d['phong']} "
                f"(cùng coi thi: {other})"
            )
        if len(new_duties) > 10:
            lines.append(f"... và {len(new_duties) - 10} ca khác.")
        message = "\n".join(lines)

        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"{DOMAIN}_{self.entry.entry_id}",
            },
            blocking=False,
        )

        service = self.notify_service
        if service and "." in service:
            domain, _, service_name = service.partition(".")
            try:
                await self.hass.services.async_call(
                    domain,
                    service_name,
                    {"title": title, "message": message},
                    blocking=False,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Không thể gọi notify service '%s'", service)
