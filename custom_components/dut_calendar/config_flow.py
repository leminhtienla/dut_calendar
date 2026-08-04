"""Config flow cho DUT Calendar — menu 3 loại, 2 bước cho loại cần đăng nhập
(bước 1: xác thực tài khoản, bước 2: chọn học kỳ từ danh sách thật)."""
from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
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
    CONF_EXAM_DURATION,
    CONF_HOC_KY,
    CONF_KEYWORDS,
    CONF_NOTIFY_SERVICE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TYPE,
    CONF_USERNAME,
    CONF_WEEKS_AHEAD,
    DEFAULT_EXAM_DURATION,
    DEFAULT_SCAN_INTERVAL_EXAM,
    DEFAULT_SCAN_INTERVAL_PUBLIC,
    DEFAULT_WEEKS_AHEAD,
    DOMAIN,
    MAX_SCAN_INTERVAL_EXAM,
    MAX_SCAN_INTERVAL_PUBLIC,
    MAX_WEEKS_AHEAD,
    MIN_SCAN_INTERVAL_EXAM,
    MIN_SCAN_INTERVAL_PUBLIC,
    TYPE_COITHI,
    TYPE_DEADLINE_DIEM,
    TYPE_LICHTUAN,
)
from .parser_exam import parse_hoc_ky_options
from .parser_public import parse_keyword_groups

KEYWORDS_EXAMPLE = (
    "Lê Minh Tiến: Lê Minh Tiến, LMT, Thầy Tiến\n"
    "Khoa Cơ khí Giao thông: Khoa Cơ khí Giao thông, CKGT\n"
    "Bộ môn Kỹ thuật Ô tô: Kỹ thuật Ô tô, KTOT"
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
            vol.Optional(
                CONF_WEEKS_AHEAD, default=defaults.get(CONF_WEEKS_AHEAD, DEFAULT_WEEKS_AHEAD)
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=MAX_WEEKS_AHEAD, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_NOTIFY_SERVICE, default=defaults.get(CONF_NOTIFY_SERVICE, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        }
    )


def _schema_login_credentials(defaults: dict[str, Any], require_password: bool) -> vol.Schema:
    """Bước 1: tài khoản/mật khẩu + các tuỳ chọn khác (KHÔNG có học kỳ)."""
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
            vol.Optional(
                CONF_EXAM_DURATION, default=defaults.get(CONF_EXAM_DURATION, DEFAULT_EXAM_DURATION)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=15, max=240, step=5, mode=NumberSelectorMode.BOX, unit_of_measurement="phút"
                )
            ),
            vol.Optional(
                CONF_NOTIFY_SERVICE, default=defaults.get(CONF_NOTIFY_SERVICE, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
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


# =====================================================================
# Config Flow chính — menu 3 lựa chọn
# =====================================================================
class DutCalendarConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._pending_data: dict[str, Any] = {}
        self._hocky_options: list[dict[str, Any]] = []
        self._pending_type: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        return self.async_show_menu(
            step_id="user",
            menu_options=["dut_lichtuan", "dut_coithi", "dut_deadline_diem"],
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
                user_input or prefill or {}, require_password=True
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
                data = {**self._pending_data, CONF_HOC_KY: ", ".join(selected), CONF_TYPE: self._pending_type}
                title_suffix = "Coi thi" if self._pending_type == TYPE_COITHI else "Hạn nộp điểm"
                return self.async_create_entry(
                    title=f"DUT Calendar - {title_suffix} ({data[CONF_USERNAME]})",
                    data=data,
                )

        default_selected = [o["value"] for o in self._hocky_options if o.get("selected")]
        return self.async_show_form(
            step_id="hocky",
            data_schema=_schema_hocky(self._hocky_options, default_selected),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DutCalendarOptionsFlow(config_entry)


# =====================================================================
# Options Flow (nhánh theo loại entry đã tạo)
# =====================================================================
class DutCalendarOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._pending_data: dict[str, Any] = {}
        self._hocky_options: list[dict[str, Any]] = []

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        entry_type = self._config_entry.data.get(CONF_TYPE)
        if entry_type == TYPE_LICHTUAN:
            return await self._step_lichtuan(user_input)
        return await self._step_credentials(user_input)

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
            data_schema=_schema_login_credentials(user_input or current, require_password=False),
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
                data = {**self._pending_data, CONF_HOC_KY: ", ".join(selected)}
                return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="hocky",
            data_schema=_schema_hocky(self._hocky_options, current_hoc_ky),
            errors=errors,
        )
