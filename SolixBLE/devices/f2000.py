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
    UUID_COMMAND,
    UUID_TELEMETRY,
)
from ..device import SolixBLEDevice

_LOGGER = logging.getLogger(__name__)

CMD_AC_OUTPUT = "404a"
CMD_DC_OUTPUT = "404b"
CMD_LIGHT_MODE = "404f"
CMD_DISPLAY_ON_OFF = "4052"
CMD_POWER_SAVING_MODE = "404e"
CMD_AC_CHARGING_POWER = "4044"

PAYLOAD_ON = "a10121a2020101"
PAYLOAD_OFF = "a10121a2020100"
PAYLOAD_LIGHT_MODE = "a10121a20201"
PAYLOAD_AC_CHARGING_POWER = "a10121a20302"


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

    @staticmethod
    def _checksum(packet: bytes) -> int:
        return sum(packet) & 0xFF

    async def _send_command(self, command_id: int, parameters: bytes = b"") -> None:
        length = 9 + len(parameters)
        header = bytes.fromhex("08ee00000002")
        body = header + bytes([command_id, length]) + parameters
        checksum = self._checksum(body)
        packet = body + bytes([checksum])
        await self._client.write_gatt_char(UUID_COMMAND, packet, response=True)

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
            "b4": b"\x01\x00",
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
        """Parse a full 102-byte F2000 Telemetry frame.

        Byte offsets confirmed directly from the anker_ble README (all
        2-byte integers little-endian):

            Bytes 19-20: AC input watts          -> ac_power_in ("af")
            Bytes 21-22: AC output watts         -> ac_power_out ("b0")
            Bytes 23-24: Top USB-C watts         -> usb_c1_power ("a7")
            Bytes 25-26: Middle USB-C watts      -> usb_c2_power ("a8")
            Bytes 27-28: Bottom USB-C watts      -> usb_c3_power ("a9")
            Bytes 29-30: Top USB-A watts         -> usb_a1_power ("aa")
            Bytes 31-32: Bottom USB-A watts      -> usb_a2_power ("ab")
            Bytes 33-34: Top 12V watts           -> dc_1_power_out ("ac")
            Bytes 35-36: Bottom 12V watts        -> dc_2_power_out ("ad")
            Bytes 37-38: Solar input watts       -> solar_power_in ("ae")
            Bytes 39-40: Total input watts       -> total_power_in ("b4")
            Bytes 41-42: Total output watts      -> ac_power_out_sockets ("a6")

        FIX: previously "af" (ac_power_in) was wired to bytes 39-40 (Total
        input), which is a DIFFERENT quantity than "AC input watts" (bytes
        19-20). This caused ac_power_in to silently equal solar_power_in
        whenever the unit was running on solar only with no AC charging
        (since Total input = AC input + Solar input, and AC input = 0 in
        that case), which looked like "AC Power In reports the same as
        solar" -- it was actually reporting Total input under the wrong
        name. Total input now gets its own key/property (`total_power_in`,
        "b4") so it is not confused with true AC-only input.

        NOTE: Bytes 9-12 (switch/LED/Power-Save status) are intentionally
        NOT read here -- those only exist in the separate State Ack frame.
        """
        params = self._default_parameters()

        if len(raw) != self._EXPECTED_TELEMETRY_LENGTH:
            return params

        b = list(raw)

        def set_u16(key: str, value: int) -> None:
            params[key] = b"\x01" + int(value).to_bytes(2, byteorder="little", signed=False)

        def set_s16(key: str, value: int) -> None:
            params[key] = b"\x01" + int(value).to_bytes(2, byteorder="little", signed=True)

        def le16(index: int) -> int:
            return int.from_bytes(raw[index : index + 2], byteorder="little")

        if len(raw) > 18:
            remaining_tenths = int(b[17]) * 10 if len(b) > 17 else 0
            set_u16("a4", remaining_tenths)

        set_u16("af", le16(19))    # AC input watts
        set_u16("b0", le16(21))    # AC output watts
        set_u16("a7", le16(23))    # Top USB-C watts
        set_u16("a8", le16(25))    # Middle USB-C watts
        set_u16("a9", le16(27))    # Bottom USB-C watts
        set_u16("aa", le16(29))    # Top USB-A watts
        set_u16("ab", le16(31))    # Bottom USB-A watts
        set_u16("ac", le16(33))    # Top 12V watts
        set_u16("ad", le16(35))    # Bottom 12V watts
        set_u16("ae", le16(37))    # Solar input watts
        set_u16("b4", le16(39))    # Total input watts (was mis-mapped to "af")
        set_u16("a6", le16(41))    # Total output watts

        main_temp = b[66] if len(b) > 66 else 0
        if main_temp >= 128:
            main_temp -= 256
        set_s16("bd", main_temp)

        expansion_temp = b[67] if len(b) > 67 else 0
        if expansion_temp >= 128:
            expansion_temp -= 256
        set_s16("be", expansion_temp)

        main_battery = b[70] if len(b) > 70 else 0
        expansion_battery = b[71] if len(b) > 71 else 0
        set_u16("c1", main_battery if 0 <= main_battery <= 100 else 0)
        set_u16("c2", expansion_battery if 0 <= expansion_battery <= 100 else 0)

        serial_bytes = raw[85:101] if len(raw) >= 101 else b""
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

        if len(raw) < 7:
            _LOGGER.debug("Ignoring short F2000 notification")
            return

        if raw[:2] not in (bytes.fromhex("09ff"), bytes.fromhex("ff09")):
            _LOGGER.debug(f"Ignoring non-F2000 frame header: {raw[:2].hex()}")
            return

        if raw[5] == 0x02:
            _LOGGER.debug(
                f"Received F2000 Command Ack for command ID 0x{raw[6]:02x} -- command was accepted by device!"
            )
            return

        if raw[6] == 0x48:
            ac_on = raw[9]
            dc_on = raw[10]

            _LOGGER.debug(
                f"Received F2000 State Ack: AC={ac_on}, 12V={dc_on}, "
                f"PowerSave={raw[11]}, LED={raw[12]}"
            )

            params = dict(self._data) if self._data is not None else self._default_parameters()
            params["b1"] = b"\x01" + ac_on.to_bytes(2, byteorder="little")
            params["b2"] = b"\x01" + dc_on.to_bytes(2, byteorder="little")

            await self._process_telemetry(params)
            return

        if raw[6] == 0x49:
            parameters = self._parse_raw_telemetry(raw)

            # FIX: Telemetry frames do not carry switch state (bytes 9-12
            # only exist in State Ack) -- `_parse_raw_telemetry` rebuilds
            # its dict from `_default_parameters()` every call, which
            # defaults b1/b2 to off. Without this merge, every routine
            # Telemetry update (which arrives continuously) would silently
            # stomp the AC/DC switch state that was last confirmed by a
            # State Ack, causing switches to appear to revert to off.
            if self._data is not None:
                parameters["b1"] = self._data.get("b1", parameters["b1"])
                parameters["b2"] = self._data.get("b2", parameters["b2"])

            await self._process_telemetry(parameters)
            return

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
        return self._parse_int("af", begin=1)

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
        """True AC input watts (bytes 19-20), NOT total input.

        Previously this read the "af" key which was wired to Total input
        watts (bytes 39-40) -- fixed so ac_power_in and total_power_in are
        now distinct, correctly-named properties.
        """
        return self._parse_int("af", begin=1)

    @property
    def total_power_in(self) -> int:
        """Total input watts (bytes 39-40): AC input + solar input combined."""
        return self._parse_int("b4", begin=1)

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
