import asyncio
import logging
import time
from functools import partial
_LOGGER = logging.getLogger(__name__)
from bleak import BleakClient, BleakError
from bleak_retry_connector import establish_connection


from datetime import datetime, timedelta

from ..const import (
    DEFAULT_METADATA_FLOAT,
    DEFAULT_METADATA_INT,
    DEFAULT_METADATA_STRING,
    UUID_TELEMETRY,
)
from ..device import SolixBLEDevice


class F2000(SolixBLEDevice):
    """
    F2000(P) Power Station.

    Use this class to connect and monitor a F2000(P) power station.
    This model is also known as the A1780 or the 767 PowerHouse.

    .. note::
        This model was added using data from anker-solix-api. It has not been
        tested!

    .. note::
        It should be possible to add more sensors. I think devices with lots of
        telemetry values split them up into multiple messages but I have not
        played around with this yet. That and I am being a bit conservative with
        these initial implementations, if you want more sensors and are willing
        to help with testing feel free to raise a GitHub issue.

    """

    _EXPECTED_TELEMETRY_LENGTH: int = 102

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
            _LOGGER.exception(f"Error establishing initial connection to '{self.name}'!")
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
            _LOGGER.exception(f"Error subscribing to F2000 telemetry on '{self.name}'!")
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
        params = {
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
        return params

    def _parse_raw_telemetry(self, raw: bytes) -> dict[str, bytes]:
        """
        Minimal raw F2000 parser.

        This is a transport proof-of-concept parser that accepts the observed
        09ff/ff09 102-byte frame and fills placeholder parameter keys so the
        existing F2000 property accessors do not crash.
        """
        params = self._default_parameters()

        # Best effort serial number extraction from the last 16 bytes if printable.
        if len(raw) >= 16:
            tail = raw[-16:]
            if all(32 <= b < 127 for b in tail):
                params["d0"] = b"\x10" + tail

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
        """Time remaining to full/empty.

        Note that any hours over 24 are overflowed to the
        days remaining. Use time_remaining if you want
        days to be included.

        :returns: Hours remaining or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return round(divmod(self.time_remaining, 24)[1], 1)

    @property
    def days_remaining(self) -> int:
        """Time remaining to full/empty.

        Note that any partial days are overflowed into
        the hours remaining. Use time_remaining if you want
        hours to be included.

        :returns: Days remaining or default int value.
        """
        if self._data is None:
            return DEFAULT_METADATA_INT

        return round(divmod(self.time_remaining, 24)[0])

    @property
    def time_remaining(self) -> float:
        """Time remaining to full/empty in hours.

        :returns: Hours remaining or default float value.
        """
        return (
            self._parse_int("a4", begin=1) / 10.0
            if self._data is not None
            else DEFAULT_METADATA_FLOAT
        )

    @property
    def timestamp_remaining(self) -> datetime | None:
        """Timestamp of when device will be full/empty.

        :returns: Timestamp of when will be full/empty or None.
        """
        if self._data is None:
            return None
        return datetime.now() + timedelta(hours=self.time_remaining)

    @property
    def ac_to_battery(self) -> int:
        """AC Power that is going to the battery.

        :returns: Total AC power to battery or default int value.
        """
        return self._parse_int("a5", begin=1)

    @property
    def ac_power_out_sockets(self) -> int:
        """AC Power Out to sockets.

        :returns: AC power out or default int value.
        """
        return self._parse_int("a6", begin=1)

    @property
    def usb_c1_power(self) -> int:
        """USB C1 Power.

        :returns: USB port C1 power or default int value.
        """
        return self._parse_int("a7", begin=1)

    @property
    def usb_c2_power(self) -> int:
        """USB C2 Power.

        :returns: USB port C2 power or default int value.
        """
        return self._parse_int("a8", begin=1)

    @property
    def usb_c3_power(self) -> int:
        """USB C3 Power.

        :returns: USB port C3 power or default int value.
        """
        return self._parse_int("a9", begin=1)

    @property
    def usb_a1_power(self) -> int:
        """USB A1 Power.

        :returns: USB port A1 power or default int value.
        """
        return self._parse_int("aa", begin=1)

    @property
    def usb_a2_power(self) -> int:
        """USB A2 Power.

        :returns: USB port A2 power or default int value.
        """
        return self._parse_int("ab", begin=1)

    @property
    def dc_1_power_out(self) -> int:
        """DC Power out for port 1.

        :returns: DC power out for port 1 or default int value.
        """
        return self._parse_int("ac", begin=1)

    @property
    def dc_2_power_out(self) -> int:
        """DC Power out for port 2.

        :returns: DC power out for port 2 or default int value.
        """
        return self._parse_int("ad", begin=1)

    @property
    def solar_power_in(self) -> int:
        """Solar Power In.

        :returns: Total solar power in or default int value.
        """
        return self._parse_int("ae", begin=1)

    @property
    def ac_power_in(self) -> int:
        """AC Power In.

        :returns: Total AC power in or default int value.
        """
        return self._parse_int("af", begin=1)

    @property
    def ac_power_out(self) -> int:
        """AC Power Out.

        :returns: Total AC power out or default int value.
        """
        return self._parse_int("b0", begin=1)

    @property
    def software_version(self) -> str:
        """Main software version.

        :returns: Firmware version or default str value.
        """
        if self._data is None:
            return DEFAULT_METADATA_STRING

        return ".".join([digit for digit in str(self._parse_int("b3", begin=1))])

    @property
    def software_version_expansion(self) -> str:
        """Software version of any expansion batteries.

        If there is no expansion battery then it will be "0".

        :returns: Firmware version or default str value.
        """
        if self._data is None:
            return DEFAULT_METADATA_STRING

        return ".".join([digit for digit in str(self._parse_int("b9", begin=1))])

    @property
    def software_version_controller(self) -> str:
        """Software version of the controller.

        :returns: Firmware version or default str value.
        """
        if self._data is None:
            return DEFAULT_METADATA_STRING

        return ".".join([digit for digit in str(self._parse_int("ba", begin=1))])

    @property
    def temperature(self) -> int:
        """Temperature of the unit (C).

        :returns: Temperature of the unit in degrees C.
        """
        return self._parse_int("bd", begin=1, signed=True)

    @property
    def temperature_expansion(self) -> int:
        """Temperature of the expansion battery if present (C).

        :returns: Temperature of expansion battery in degrees C or 0 if not present or default int value.
        """
        return self._parse_int("be", begin=1, signed=True)

    @property
    def battery_percentage(self) -> int:
        """Battery Percentage.

        :returns: Percentage charge of battery or default int value.
        """
        return self._parse_int("c1", begin=1)

    @property
    def battery_percentage_expansion(self) -> int:
        """Battery Percentage of the expansion battery.

        :returns: Percentage charge of expansion battery or 0 if not present or default int value.
        """
        return self._parse_int("c2", begin=1)

    @property
    def battery_health(self) -> int:
        """Battery health as a percentage.

        :returns: Percentage of battery health or default int value.
        """
        return self._parse_int("c3", begin=1)

    @property
    def battery_health_expansion(self) -> int:
        """Battery health as a percentage for expansion battery.

        :returns: Percentage of expansion battery health or 0 if not present or default int value.
        """
        return self._parse_int("c4", begin=1)

    @property
    def num_expansion(self) -> int:
        """Number of expansion batteries.

        :returns: Number of expansion batteries or default int value.
        """
        return self._parse_int("c5", begin=1)

    @property
    def serial_number(self) -> str:
        """Device serial number.

        :returns: Device serial number or default str value.
        """
        return self._parse_string("d0", begin=1)
