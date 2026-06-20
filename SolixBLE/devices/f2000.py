import asyncio
import logging
import time
from datetime import datetime, timedelta
from functools import partial

from bleak import BleakClient, BleakError
from bleak_retry_connector import establish_connection

from ..const import (
    DEFAULT_METADATA_FLOAT,
    DEFAULT_METADATA_INT,
    DEFAULT_METADATA_STRING,
    UUID_TELEMETRY,
)
from ..device import SolixBLEDevice

_LOGGER = logging.getLogger(__name__)


class F2000(SolixBLEDevice):
    """
    F2000(P) Power Station.

    Use this class to connect and monitor a F2000(P) power station.
    This model is also known as the A1780 or the 767 PowerHouse.
    """

    _EXPECTED_TELEMETRY_LENGTH: int = 102

    @property
    def negotiated(self) -> bool:
        return self.connected

    @property
    def available(self) -> bool:
        return self.connected and self._data is not None

    async def connect(self, max_attempts: int = 3, run_callbacks: bool = True) -> bool:
        self._connection_attempts = self._connection_attempts + 1

        try:
            if self._client is not None:
                await self._dispose_of_client()

            self._reset_session(reset_data=False)

            self._client = await establish_connection(
                BleakClient,
                device=self._ble_device,
                name=self.address,
                max_attempts=max_attempts,
                use_services_cache=False,
                disconnected_callback=self._disconnect_callback,
            )
        except BleakError:
            _LOGGER.exception(
                f"Error establishing initial connection to '{self.name}'!"
            )
            return False

        if not self.connected:
            _LOGGER.error(
                f"Failed to establish initial connection to '{self.name}' on attempt {self._connection_attempts}!"
            )
            return False

        _LOGGER.debug(
            f"Established initial F2000 connection to '{self.name}' on attempt {self._connection_attempts}!"
        )

        try:
            await self._client.start_notify(
                UUID_TELEMETRY,
                partial(self._process_notification, self._client),
            )
        except BleakError:
            _LOGGER.exception(
                f"Error subscribing to F2000 telemetry on '{self.name}'!"
            )
            return False

        self._connection_attempts = 0

        if self._disconnect_event.is_set():
            self._disconnect_event.clear()

        if self._auto_reconnect_task is None:
            self._auto_reconnect_task = asyncio.create_task(self._auto_reconnect())

        if run_callbacks:
            self._run_state_changed_callbacks()

        return True

    def _default_parameters(self) -> dict[str, bytes]:
        return {
            "a4": b"\x01\x00",
            "a5": b"\x01\x00",
            "a6": b"\x01\x00",
            "a7": b"\x01\x00",
            "a8": b"\x01\x00",
            "a9": b"\x01\x00",
            "aa": b"\x01\x00",
            "ab": b"\x01\x00",
            "ac": b"\x01\x00",
            "ad": b"\x01\x00",
            "ae": b"\x01\x00",
            "af": b"\x01\x00",
            "b0": b"\x01\x00",
            "b1": b"\x01\x00",
            "b2": b"\x01\x00",
            "b3": b"\x01\x00",
            "b9": b"\x01\x00",
            "ba": b"\x01\x00",
            "bd": b"\x01\x00",
            "be": b"\x01\x00",
            "c1": b"\x01\x00",
            "c2": b"\x01\x00",
            "c3": b"\x01\x00",
            "c4": b"\x01\x00",
            "c5": b"\x01\x00",
            "d0": b"\x10" + b"0" * 16,
        }

    def _parse_raw_telemetry(self, raw: bytes) -> dict[str, bytes]:
        params = self._default_parameters()

        if len(raw) != self._EXPECTED_TELEMETRY_LENGTH:
            return params

        b = list(raw)
        words = [
            int.from_bytes(raw[i:i + 2], byteorder="big", signed=False)
            for i in range(0, len(raw), 2)
        ]

        def set_u16(key: str, value: int) -> None:
            params[key] = b"\x01" + int(value).to_bytes(
                2, byteorder="little", signed=False
            )

        def set_s16(key: str, value: int) -> None:
            params[key] = b"\x01" + int(value).to_bytes(
                2, byteorder="little", signed=True
            )

        if len(words) > 8:
            remaining_tenths = words[8]
            if 0 <= remaining_tenths <= 10000:
                set_u16("a4", remaining_tenths)

        if len(words) > 18:
            solar_input = words[18]
            if 0 <= solar_input <= 5000:
                set_u16("ae", solar_input)

        if len(words) > 10:
            total_input = (words[10] & 0xFF00) | (words[9] & 0x00FF)
            if 0 <= total_input <= 5000:
                set_u16("af", total_input)
                set_u16("a5", total_input)

        if len(words) > 21:
            total_output = (words[21] & 0xFF00) | (words[20] & 0x00FF)
            if 0 <= total_output <= 5000:
                set_u16("b0", total_output)
                set_u16("a6", total_output)

        if len(words) > 16:
            dc_output_candidate = words[16]
            if 0 <= dc_output_candidate <= 5000:
                set_u16("ac", dc_output_candidate)

        if len(words) > 30:
            ac_enabled = 1 if words[30] == 0x0001 else 0
            set_u16("b1", ac_enabled)

        if len(words) > 32:
            dc_state_bucket = words[32]
            if dc_state_bucket in (0x2000, 0x2200):
                set_u16("b2", 1 if dc_state_bucket == 0x2200 else 0)
            else:
                set_u16("b2", 0)

        main_temp = b[66] if len(b) > 66 else 0
        if main_temp >= 128:
            main_temp -= 256
        set_s16("bd", main_temp)

        if len(words) > 35:
            main_battery = (words[35] >> 8) | ((words[35] & 0x00FF) << 8)
            if 0 <= main_battery <= 100:
                set_u16("c1", main_battery)

        if len(words) > 36:
            battery_health = (words[36] >> 8) | ((words[36] & 0x00FF) << 8)
            if 0 <= battery_health <= 100:
                set_u16("c3", battery_health)

        serial_bytes = raw[-17:-1]
        if len(serial_bytes) == 16 and all(32 <= x < 127 for x in serial_bytes):
            params["d0"] = b"\x10" + serial_bytes

        return params

    async def _process_notification(
        self, client: BleakClient, handle: int, data: bytearray
    ) -> None:
        if self._client is not client:
            _LOGGER.debug("Ignoring notification from old client")
            return

        raw = bytes(data)
        self._last_packet_timestamp = time.time()

        _LOGGER.debug(
            f"Received raw F2000 notification from '{self.name}'. length: {len(raw)}, packet: '{raw.hex()}'"
        )

        if len(raw) < 4:
            _LOGGER.debug("Ignoring short F2000 notification")
            return

        if raw[:2] not in (bytes.fromhex("09ff"), bytes.fromhex("ff09")):
            _LOGGER.debug(f"Ignoring non-F2000 frame header: {raw[:2].hex()}")
            return

        parameters = self._parse_raw_telemetry(raw)
        await self._process_telemetry(parameters)

    @property
    def hours_remaining(self) -> float:
        if self._data is None:
            return DEFAULT_METADATA_FLOAT
        return round(divmod(self.time_remaining, 24)[1], 1)

    @property
    def days_remaining(self) -> int:
        if self._data is None:
            return DEFAULT_METADATA_INT
        return round(divmod(self.time_remaining, 24)[0])

    @property
    def time_remaining(self) -> float:
        return (
            self._parse_int("a4", begin=1) / 10.0
            if self._data is not None
            else DEFAULT_METADATA_FLOAT
        )

    @property
    def timestamp_remaining(self) -> datetime | None:
        if self._data is None:
            return None
        return datetime.now() + timedelta(hours=self.time_remaining)

    @property
    def ac_to_battery(self) -> int:
        return self._parse_int("a5", begin=1)

    @property
    def ac_power_out_sockets(self) -> int:
        return self._parse_int("a6", begin=1)

    @property
    def usb_c1_power(self) -> int:
        return self._parse_int("a7", begin=1)

    @property
    def usb_c2_power(self) -> int:
        return self._parse_int("a8", begin=1)

    @property
    def usb_c3_power(self) -> int:
        return self._parse_int("a9", begin=1)

    @property
    def usb_a1_power(self) -> int:
        return self._parse_int("aa", begin=1)

    @property
    def usb_a2_power(self) -> int:
        return self._parse_int("ab", begin=1)

    @property
    def dc_1_power_out(self) -> int:
        return self._parse_int("ac", begin=1)

    @property
    def dc_2_power_out(self) -> int:
        return self._parse_int("ad", begin=1)

    @property
    def solar_power_in(self) -> int:
        return self._parse_int("ae", begin=1)

    @property
    def ac_power_in(self) -> int:
        return self._parse_int("af", begin=1)

    @property
    def ac_power_out(self) -> int:
        return self._parse_int("b0", begin=1)

    @property
    def ac_inverter_enabled(self) -> int:
        return self._parse_int("b1", begin=1)

    @property
    def dc12v_enabled(self) -> int:
        return self._parse_int("b2", begin=1)

    @property
    def software_version(self) -> str:
        if self._data is None:
            return DEFAULT_METADATA_STRING
        return ".".join([digit for digit in str(self._parse_int("b3", begin=1))])

    @property
    def software_version_expansion(self) -> str:
        if self._data is None:
            return DEFAULT_METADATA_STRING
        return ".".join([digit for digit in str(self._parse_int("b9", begin=1))])

    @property
    def software_version_controller(self) -> str:
        if self._data is None:
            return DEFAULT_METADATA_STRING
        return ".".join([digit for digit in str(self._parse_int("ba", begin=1))])

    @property
    def temperature(self) -> int:
        return self._parse_int("bd", begin=1, signed=True)

    @property
    def temperature_expansion(self) -> int:
        return self._parse_int("be", begin=1, signed=True)

    @property
    def battery_percentage(self) -> int:
        return self._parse_int("c1", begin=1)

    @property
    def battery_percentage_expansion(self) -> int:
        return self._parse_int("c2", begin=1)

    @property
    def battery_health(self) -> int:
        return self._parse_int("c3", begin=1)

    @property
    def battery_health_expansion(self) -> int:
        return self._parse_int("c4", begin=1)

    @property
    def num_expansion(self) -> int:
        return self._parse_int("c5", begin=1)

    @property
    def serial_number(self) -> str:
        if self._data is None:
            return DEFAULT_METADATA_STRING
        value = self._parse_string("d0", begin=1)
        if not value or value == "0" or set(value) == {"0"}:
            return DEFAULT_METADATA_STRING
        return value
