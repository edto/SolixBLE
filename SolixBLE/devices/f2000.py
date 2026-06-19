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
            "d0": b"\x10" + b"0" * 16,
        }

    def _parse_raw_telemetry(self, raw: bytes) -> dict[str, bytes]:
        """
        Parse the observed 102-byte F2000 09FF telemetry frame.

        Confirmed working mappings from live validation:
        - time remaining (hours * 10): raw byte index 17
        - main battery: column 71
        - AC output: column 22
        - main temperature: column 67

        Provisional mappings:
        - expansion battery: column 72
        - AC input: columns 20 and 21
        - DC / solar input: columns 38 and 39
        - expansion temperature: column 68

        Column-style mappings are treated as 1-based indexes.
        """
        params = self._default_parameters()

        if len(raw) != self._EXPECTED_TELEMETRY_LENGTH:
            return params

        b = list(raw)

        def set_u16(key: str, value: int) -> None:
            params[key] = b"\x01" + int(value).to_bytes(
                2, byteorder="little", signed=False
            )

        def set_s16(key: str, value: int) -> None:
            params[key] = b"\x01" + int(value).to_bytes(
                2, byteorder="little", signed=True
            )

        def one_based(idx: int) -> int:
            return b[idx - 1]

        def combine_255(msb_col: int, lsb_col: int) -> int:
            return (one_based(msb_col) * 255) + one_based(lsb_col)

        def combine_256(msb_col: int, lsb_col: int) -> int:
            return (one_based(msb_col) << 8) | one_based(lsb_col)

        # Confirmed remaining time mapping from observed community example:
        # x[17] / 10.0 hours
        if len(b) > 17:
            remaining_tenths = b[17]
            if 0 <= remaining_tenths <= 255:
                set_u16("a4", remaining_tenths)

        # Confirmed main battery mapping
        main_battery = one_based(71)
        if 0 <= main_battery <= 100:
            set_u16("c1", main_battery)

        # Provisional expansion battery mapping
        expansion_battery = one_based(72)
        if 0 <= expansion_battery <= 100:
            set_u16("c2", expansion_battery)

        # Confirmed AC output mapping
        ac_output = one_based(22)
        if 0 <= ac_output <= 5000:
            set_u16("b0", ac_output)
            set_u16("a6", ac_output)

        # Provisional AC input mapping; only expose main AC input field for now
        ac_input_255 = combine_255(20, 21)
        ac_input_256 = combine_256(20, 21)
        ac_input = ac_input_256 if 0 <= ac_input_256 <= 5000 else ac_input_255
        if 0 <= ac_input <= 5000:
            set_u16("af", ac_input)

        # Provisional DC / solar input mapping
        dc_input_255 = combine_255(39, 38)
        dc_input_256 = combine_256(39, 38)
        dc_input = dc_input_255
        if not (0 <= dc_input <= 5000):
            dc_input = dc_input_256

        if 0 <= dc_input <= 5000:
            set_u16("ae", dc_input)

        # Confirmed main temperature mapping
        main_temp = one_based(67)
        if main_temp >= 128:
            main_temp -= 256
        set_s16("bd", main_temp)

        # Provisional expansion temperature mapping
        expansion_temp = one_based(68)
        if expansion_temp >= 128:
            expansion_temp -= 256
        set_s16("be", expansion_temp)

        # Serial number from raw telemetry is not stable yet; leave default placeholder
        # until a dedicated fixed mapping is confirmed.

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
        """AC Power going to the battery."""
        return self._parse_int("a5", begin=1)

    @property
    def ac_power_out_sockets(self) -> int:
        """AC Power Out to sockets."""
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
        """Solar Power In."""
        return self._parse_int("ae", begin=1)

    @property
    def ac_power_in(self) -> int:
        """AC Power In."""
        return self._parse_int("af", begin=1)

    @property
    def ac_power_out(self) -> int:
        """AC Power Out."""
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
        return self._parse_string("d0", begin=1)
