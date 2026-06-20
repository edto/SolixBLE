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
        """F2000 legacy BLE path does not use the generic negotiated protocol."""
        return self.connected

    @property
    def available(self) -> bool:
        """Connected to device and raw telemetry has been received."""
        return self.connected and self._data is not None

    async def connect(self, max_attempts: int = 3, run_callbacks: bool = True) -> bool:
        """Connect to F2000 using direct notify on 8888 and skip generic negotiation."""
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
        """Populate keys expected by the existing F2000 properties."""
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
            "d0": b"\x10",
        }

    def _parse_raw_telemetry(self, raw: bytes) -> dict[str, bytes]:
        """
        Parse the observed 102-byte F2000 09FF telemetry frame.

        Current confidence:
        - time remaining uses byte 17 tenths of hours plus byte 18 days
        - total input matches repeated 0x0075/0x0073-style words
        - total output matches word 20 + word 21 combined at word boundaries
        - temperature and battery mappings are reasonably stable
        - serial number remains unconfirmed
        """
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

        def u16_be(idx: int) -> int:
            if idx < 0 or idx + 1 >= len(b):
                return 0
            return (b[idx] << 8) | b[idx + 1]

        # Remaining time:
        # b[17] is tenths-of-hours remainder, b[18] is days.
        remaining_hours_tenths = b[17] if len(b) > 17 else 0
        remaining_days = b[18] if len(b) > 18 else 0
        total_remaining_tenths = (remaining_days * 24 * 10) + remaining_hours_tenths
        if 0 <= total_remaining_tenths <= 24 * 365 * 10:
            set_u16("a4", total_remaining_tenths)

        # Total input:
        # In your captures these repeated words tracked the screen exactly:
        # 0075,0075 then 0073,0073 => 117,117 then 115,115.
        # Map screen total input to HA ac_power_in (af).
        total_input = words[18] if len(words) > 18 else 0
        if 0 <= total_input <= 5000:
            set_u16("af", total_input)
            set_u16("a5", total_input)

        # Total output:
        # Use word boundaries, not free byte offsets.
        # word20=0004, word21=0100 -> 0x0104 = 260
        # word20=0006, word21=0100 -> 0x0106 = 262
        # word20=0021, word21=0100 -> 0x0121 = 289
        # word20=0034, word21=0100 -> 0x0134 = 308
        total_output = 0
        if len(words) > 21:
            total_output = (words[21] & 0xFF00) | (words[20] & 0x00FF)

        if 0 <= total_output <= 5000:
            set_u16("b0", total_output)
            set_u16("a6", total_output)

        # Leave DC/solar input unset for now; current mapping is not validated.
        # Leave dedicated DC outputs unset for now; not enough evidence yet.

        # Temperature
        main_temp = b[66] if len(b) > 66 else 0
        if main_temp >= 128:
            main_temp -= 256
        set_s16("bd", main_temp)

        # Battery
        main_battery = b[70] if len(b) > 70 else 0
        if 0 <= main_battery <= 100:
            set_u16("c1", main_battery)

        expansion_battery = b[71] if len(b) > 71 else 0
        if 0 <= expansion_battery <= 100:
            set_u16("c2", expansion_battery)

        return params

    async def _process_notification(
        self, client: BleakClient, handle: int, data: bytearray
    ) -> None:
        """Process raw F2000 notifications from 8888 without generic packet splitting."""
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

        if len(raw) != self._EXPECTED_TELEMETRY_LENGTH:
            _LOGGER.debug(
                f"Unexpected F2000 raw telemetry length {len(raw)} (expected {self._EXPECTED_TELEMETRY_LENGTH})"
            )

        parameters = self._parse_raw_telemetry(raw)
        await self._process_telemetry(parameters)

    @property
    def hours_remaining(self) -> float:
        """Time remaining to full/empty in hours modulo 24."""
        if self._data is None:
            return DEFAULT_METADATA_FLOAT
        return round(divmod(self.time_remaining, 24)[1], 1)

    @property
    def days_remaining(self) -> int:
        """Time remaining to full/empty in days."""
        if self._data is None:
            return DEFAULT_METADATA_INT
        return round(divmod(self.time_remaining, 24)[0])

    @property
    def time_remaining(self) -> float:
        """Time remaining to full/empty in hours."""
        return (
            self._parse_int("a4", begin=1) / 10.0
            if self._data is not None
            else DEFAULT_METADATA_FLOAT
        )

    @property
    def timestamp_remaining(self) -> datetime | None:
        """Timestamp of when device will be full/empty."""
        if self._data is None:
            return None
        return datetime.now() + timedelta(hours=self.time_remaining)

    @property
    def ac_to_battery(self) -> int:
        """Charging/input-related power to battery."""
        return self._parse_int("a5", begin=1)

    @property
    def ac_power_out_sockets(self) -> int:
        """Currently mirrored from total output until socket-only mapping is known."""
        return self._parse_int("a6", begin=1)

    @property
    def usb_c1_power(self) -> int:
        """USB C1 Power."""
        return self._parse_int("a7", begin=1)

    @property
    def usb_c2_power(self) -> int:
        """USB C2 Power."""
        return self._parse_int("a8", begin=1)

    @property
    def usb_c3_power(self) -> int:
        """USB C3 Power."""
        return self._parse_int("a9", begin=1)

    @property
    def usb_a1_power(self) -> int:
        """USB A1 Power."""
        return self._parse_int("aa", begin=1)

    @property
    def usb_a2_power(self) -> int:
        """USB A2 Power."""
        return self._parse_int("ab", begin=1)

    @property
    def dc_1_power_out(self) -> int:
        """DC Power out for port 1."""
        return self._parse_int("ac", begin=1)

    @property
    def dc_2_power_out(self) -> int:
        """DC Power out for port 2."""
        return self._parse_int("ad", begin=1)

    @property
    def solar_power_in(self) -> int:
        """Solar / DC power in."""
        return self._parse_int("ae", begin=1)

    @property
    def ac_power_in(self) -> int:
        """Mapped to screen total input."""
        return self._parse_int("af", begin=1)

    @property
    def ac_power_out(self) -> int:
        """Mapped to screen total output."""
        return self._parse_int("b0", begin=1)

    @property
    def software_version(self) -> str:
        """Main software version."""
        if self._data is None:
            return DEFAULT_METADATA_STRING
        return ".".join([digit for digit in str(self._parse_int("b3", begin=1))])

    @property
    def software_version_expansion(self) -> str:
        """Software version of any expansion batteries."""
        if self._data is None:
            return DEFAULT_METADATA_STRING
        return ".".join([digit for digit in str(self._parse_int("b9", begin=1))])

    @property
    def software_version_controller(self) -> str:
        """Software version of the controller."""
        if self._data is None:
            return DEFAULT_METADATA_STRING
        return ".".join([digit for digit in str(self._parse_int("ba", begin=1))])

    @property
    def temperature(self) -> int:
        """Temperature of the unit in C."""
        return self._parse_int("bd", begin=1, signed=True)

    @property
    def temperature_expansion(self) -> int:
        """Temperature of the expansion battery in C."""
        return self._parse_int("be", begin=1, signed=True)

    @property
    def battery_percentage(self) -> int:
        """Battery percentage."""
        return self._parse_int("c1", begin=1)

    @property
    def battery_percentage_expansion(self) -> int:
        """Expansion battery percentage."""
        return self._parse_int("c2", begin=1)

    @property
    def battery_health(self) -> int:
        """Battery health percentage."""
        return self._parse_int("c3", begin=1)

    @property
    def battery_health_expansion(self) -> int:
        """Expansion battery health percentage."""
        return self._parse_int("c4", begin=1)

    @property
    def num_expansion(self) -> int:
        """Number of expansion batteries."""
        return self._parse_int("c5", begin=1)

    @property
    def serial_number(self) -> str:
        """Device serial number."""
        if self._data is None:
            return DEFAULT_METADATA_STRING
        value = self._parse_string("d0", begin=1)
        if not value or value == "0" or set(value) == {"0"}:
            return DEFAULT_METADATA_STRING
        return value
