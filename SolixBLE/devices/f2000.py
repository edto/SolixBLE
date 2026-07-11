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
from ..states import LightStatus
from ..device import SolixBLEDevice

_LOGGER = logging.getLogger(__name__)

# Commands confirmed working on F2000 by community testing against F2600 command set.
CMD_AC_OUTPUT = "404a"
CMD_DC_OUTPUT = "404b"
CMD_LIGHT_MODE = "404f"
CMD_DISPLAY_ON_OFF = "4052"
CMD_POWER_SAVING_MODE = "404e"
CMD_AC_CHARGING_POWER = "4044"  # Not yet confirmed working on F2000.

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
        """F2000 has no encryption negotiation step (confirmed via testing:
        it never responds to negotiation requests), so this simply mirrors
        `connected`.
        """
        return self.connected

    @property
    def available(self) -> bool:
        return self.connected and self._data is not None

    @staticmethod
    def _checksum(packet: bytes) -> int:
        """Compute the F2000 command checksum.

        The reverse-engineered protocol docs (cclaunch/anker_ble) do not
        state the exact checksum algorithm used, only that byte N+1 (the
        last byte) of a command packet is "a checksum". This uses a
        simple sum-of-bytes-mod-256 as a first guess, which is the most
        common scheme for this style of simple serial/BLE protocol.

        NOTE: NOT CONFIRMED. If commands are accepted (a "Command Ack"
        notification with the matching command ID appears) then this
        guess was right. If the device silently ignores the command, this
        is the most likely culprit and the algorithm will need to be
        determined empirically (e.g. by installing the reference
        `anker_ble` library directly and comparing its checksum output
        for known packets against this implementation).

        :param packet: All bytes of the packet before the checksum byte.
        :returns: Single checksum byte value.
        """
        return sum(packet) & 0xFF

    async def _send_command(self, command_id: int, parameters: bytes = b"") -> None:
        """Send a command to the F2000 using its native (non-SolixBLE)
        command protocol, reverse engineered by cclaunch/anker_ble.

        Confirmed via testing that the F2000 does not use the standard
        SolixBLE framing/encryption at all: it exposes its own plaintext
        GATT characteristics (0x7777 for commands, 0x8888 for telemetry)
        completely separate from `UUID_COMMAND`/`UUID_TELEMETRY` used by
        other Solix devices. This method builds packets in that device's
        native format instead of using `_build_packet`/`_encrypt_payload`
        from the base class.

        Packet format: `08 ee 00 00 00 02` + command_id + length byte +
        parameter bytes + checksum byte.

        :param command_id: Single byte command ID (see F2000 command
            table, e.g. 0x86 for AC output, 0x87 for 12V output).
        :param parameters: Parameter bytes for the command (already
            including any required 0x00 padding bytes per the command
            spec -- this method does not add padding automatically).
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        if not self.connected:
            raise ConnectionError("Not connected to device")

        header = bytes.fromhex("08ee00000002")
        # "length" here is the length of the ENTIRE packet (header + command
        # ID byte + length byte + parameters + checksum), confirmed against
        # the reference cclaunch/anker_ble command.py implementation -- NOT
        # just len(parameters). Header is 6 bytes, +1 command ID, +1 length
        # byte, +1 checksum = 9 fixed bytes plus the parameter bytes.
        length = 9 + len(parameters)
        body = header + bytes([command_id, length]) + parameters
        checksum = self._checksum(body)
        packet = body + bytes([checksum])

        _LOGGER.debug(f"Sending F2000 native command packet: {packet.hex()}")
        await self._client.write_gatt_char(UUID_COMMAND, packet)

    async def turn_ac_on(self) -> None:
        """Turn the AC output on.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(command_id=0x86, parameters=bytes.fromhex("0001"))

    async def turn_ac_off(self) -> None:
        """Turn the AC output off.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(command_id=0x86, parameters=bytes.fromhex("0000"))

    async def turn_dc_on(self) -> None:
        """Turn the 12V/DC output on.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(command_id=0x87, parameters=bytes.fromhex("0001"))

    async def turn_dc_off(self) -> None:
        """Turn the 12V/DC output off.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(command_id=0x87, parameters=bytes.fromhex("0000"))

    async def turn_power_saving_mode_on(self) -> None:
        """Turn Power Save mode on.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(command_id=0x8A, parameters=bytes.fromhex("0001"))

    async def turn_power_saving_mode_off(self) -> None:
        """Turn Power Save mode off.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(command_id=0x8A, parameters=bytes.fromhex("0000"))

    async def set_display_mode(self, level: int) -> None:
        """Set screen brightness.

        :param level: 0=off, 1=low, 2=medium, 3=high.
        :raises ValueError: If level is out of range.
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        if level not in (0, 1, 2, 3):
            raise ValueError("Screen brightness level must be between 0 and 3")
        await self._send_command(command_id=0x88, parameters=bytes([0x00, level]))

    async def set_light_mode(self, level) -> None:
        """Set the side LED strip mode.

        Accepts either a plain int (0=off, 1=low, 2=medium, 3=high, 4=SOS)
        or a `LightStatus` enum member -- select.py passes the enum
        directly, so we normalize via `.value` if present rather than
        comparing the enum member against raw ints (which silently fails
        and raises ValueError for every option if `LightStatus` is not an
        `IntEnum`).

        :param level: 0=off, 1=low, 2=medium, 3=high, 4=SOS, or the
            equivalent `LightStatus` enum member.
        :raises ValueError: If level is out of range.
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        level = getattr(level, "value", level)
        if level not in (0, 1, 2, 3, 4):
            raise ValueError("LED mode must be between 0 and 4")
        await self._send_command(command_id=0x8B, parameters=bytes([0x00, level]))

    async def set_ac_charging_power(self, watts: int) -> None:
        """Set AC recharge power limit in watts.

        The README's documented canned values (200-1440W) reflect the
        base F2000/PowerHouse 767 -- confirmed via user testing this
        specific unit accepts up to 2200W, so the valid range is widened
        to 200-2200W accordingly.

        :param watts: Recharge power in watts, 200-2200.
        :raises ValueError: If watts is out of range.
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        if not 200 <= watts <= 2200:
            raise ValueError("AC charging power must be between 200 and 2200 W")
        await self._send_command(
            command_id=0x80,
            parameters=bytes([0x00]) + watts.to_bytes(2, byteorder="little"),
        )

    async def set_display_timeout(self, seconds: int) -> None:
        """Set the screen timeout in seconds. Anecdotally must be >= 10.

        :param seconds: Timeout in seconds.
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            command_id=0x82,
            parameters=bytes([0x00]) + seconds.to_bytes(2, byteorder="little"),
        )

    async def set_ac_timer(self, seconds: int) -> None:
        """Set AC auto-off timer. Anecdotally must be >= 10.

        :param seconds: Seconds until AC output shuts off.
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            command_id=0x02,
            parameters=bytes([0x00])
            + seconds.to_bytes(2, byteorder="little")
            + bytes([0x00, 0x00]),
        )

    async def set_dc_timer(self, seconds: int) -> None:
        """Set 12V auto-off timer. Anecdotally must be >= 10.

        :param seconds: Seconds until 12V output shuts off.
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            command_id=0x03,
            parameters=bytes([0x00])
            + seconds.to_bytes(2, byteorder="little")
            + bytes([0x00, 0x00]),
        )

    async def connect(self, max_attempts: int = 3, run_callbacks: bool = True) -> bool:
        """Connect to the F2000, subscribing to raw telemetry AND running
        the standard ECDH/AES negotiation handshake.

        The F2000 sends telemetry as fixed-length raw frames rather than
        the fragmented/encrypted format other Solix devices use, which is
        why `_process_notification` is overridden below to parse those
        separately. However, commands (AC/DC output, etc.) still require a
        real negotiated shared secret and negotiation timestamp -- without
        running negotiation, `_send_command` (inherited from the base
        class) will silently send garbage encrypted payloads the device
        ignores. This override performs both: it subscribes to telemetry
        notifications, then runs the same negotiation loop as the base
        class's `connect()`.
        """
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

        # NOTE: Confirmed via testing that the F2000 does NOT respond to
        # negotiation requests at all (no "030001" pattern packet is ever
        # received), unlike other Solix devices. The handshake attempt
        # below has been removed since it always times out and delays
        # connect() for no benefit. Commands are sent unencrypted -- see
        # `_send_command` override below.
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
            "d5": b"\x01\x00",
            "d6": b"\x01\x00",
        }

    def _parse_raw_telemetry(self, raw: bytes) -> dict[str, bytes]:
        """Parse a full 102-byte F2000 Telemetry frame.

        Byte offsets below are taken directly from the documented
        cclaunch/anker_ble Telemetry format (all 2-byte integers are
        little-endian per that spec) rather than the previous
        heuristic/guessed "word bucket" parsing. Confirmed byte layout:

            Bytes 19-20: AC input watts
            Bytes 21-22: AC output watts
            Bytes 23-24: Top USB-C watts
            Bytes 25-26: Middle USB-C watts
            Bytes 27-28: Bottom USB-C watts
            Bytes 29-30: Top USB-A watts
            Bytes 31-32: Bottom USB-A watts
            Bytes 33-34: Top 12V watts
            Bytes 35-36: Bottom 12V watts
            Bytes 37-38: Solar input watts
            Bytes 39-40: Total input watts
            Bytes 41-42: Total output watts

        NOTE: Bytes 9-12 (AC/12V/Power Save/LED status) are NOT read here.
        Those only exist in the separate 14-byte State Ack frame -- in the
        full Telemetry frame, bytes 9-10 mean something different (AC
        timer remaining). Reading switch state from Telemetry bytes 9-12
        would misparse the AC timer as outlet status, and would also
        reset AC/12V switch state to off on every routine Telemetry
        update since this method rebuilds its params dict from scratch.
        Switch state is populated exclusively from State Ack frames in
        `_process_notification`, merged onto existing data rather than
        overwriting it.
        """
        params = self._default_parameters()

        if len(raw) != self._EXPECTED_TELEMETRY_LENGTH:
            return params

        b = list(raw)
        words = [
            int.from_bytes(raw[i : i + 2], byteorder="big", signed=False)
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

        def le16(index: int) -> int:
            """Read a documented little-endian 2-byte field at byte `index`."""
            return int.from_bytes(raw[index : index + 2], byteorder="little")

        def swap_u16(value: int) -> int:
            return (value >> 8) | ((value & 0x00FF) << 8)

        if len(words) > 8:
            remaining_tenths = words[8]
            if 0 <= remaining_tenths <= 10000:
                set_u16("a4", remaining_tenths)

        # Documented power telemetry fields (bytes 19-42), read directly
        # per the README's confirmed little-endian byte offsets. Mapped
        # onto the existing property names used elsewhere in this class:
        set_u16("a5", le16(19))    # AC input watts       -> ac_to_battery
        set_u16("b0", le16(21))    # AC output watts       -> ac_power_out
        set_u16("a7", le16(23))    # Top USB-C watts        -> usb_c1_power
        set_u16("a8", le16(25))    # Middle USB-C watts     -> usb_c2_power
        set_u16("a9", le16(27))    # Bottom USB-C watts     -> usb_c3_power
        set_u16("aa", le16(29))    # Top USB-A watts        -> usb_a1_power
        set_u16("ab", le16(31))    # Bottom USB-A watts     -> usb_a2_power
        set_u16("ac", le16(33))    # Top 12V watts          -> dc_1_power_out
        set_u16("ad", le16(35))    # Bottom 12V watts       -> dc_2_power_out
        set_u16("ae", le16(37))    # Solar input watts      -> solar_power_in
        set_u16("af", le16(39))    # Total input watts      -> ac_power_in
        set_u16("a6", le16(41))    # Total output watts     -> ac_power_out_sockets

        main_temp = b[66] if len(b) > 66 else 0
        if main_temp >= 128:
            main_temp -= 256
        set_s16("bd", main_temp)

        expansion_temp = b[67] if len(b) > 67 else 0
        if expansion_temp >= 128:
            expansion_temp -= 256
        set_s16("be", expansion_temp)

        packed_battery_format = False

        if len(words) > 35:
            legacy_main_battery = swap_u16(words[35])
            main_battery_byte = (words[35] >> 8) & 0xFF
            expansion_battery_byte = words[35] & 0xFF

            if 0 <= legacy_main_battery <= 100:
                set_u16("c1", legacy_main_battery)
                set_u16("c2", 0)
            elif 0 <= main_battery_byte <= 100 and 0 <= expansion_battery_byte <= 100:
                set_u16("c1", main_battery_byte)
                set_u16("c2", expansion_battery_byte)
                packed_battery_format = True

        if len(words) > 36:
            legacy_battery_health = swap_u16(words[36])
            main_battery_health_byte = (words[36] >> 8) & 0xFF
            expansion_battery_health_byte = words[36] & 0xFF

            if packed_battery_format:
                if 0 <= main_battery_health_byte <= 100:
                    set_u16("c3", main_battery_health_byte)
                if 0 <= expansion_battery_health_byte <= 100:
                    set_u16("c4", expansion_battery_health_byte)
            elif 0 <= legacy_battery_health <= 100:
                set_u16("c3", legacy_battery_health)
                set_u16("c4", 0)
            elif (
                0 <= main_battery_health_byte <= 100
                and 0 <= expansion_battery_health_byte <= 100
            ):
                set_u16("c3", main_battery_health_byte)
                set_u16("c4", expansion_battery_health_byte)
                packed_battery_format = True

        set_u16("c5", 1 if packed_battery_format else 0)

        serial_bytes = raw[-17:-1]
        if len(serial_bytes) == 16 and all(32 <= x < 127 for x in serial_bytes):
            params["d0"] = b"\x10" + serial_bytes

        return params

    async def _process_notification(
        self, client: BleakClient, handle: int, data: bytearray
    ) -> None:
        """Process a notification from the F2000.

        Confirmed via cclaunch/anker_ble reverse engineering that F2000
        notifications share a common header `09 ff 00 00 01` followed by
        a type byte that distinguishes three formats:

        - Telemetry (type byte 6 == 0x49): full 102-byte telemetry frame,
          parsed with `_parse_raw_telemetry`.
        - State Ack (type byte 6 == 0x48): 14-byte frame sent whenever a
          physical button is pressed on the device; reflects the current
          AC/12V/Power Save/LED state.
        - Command Ack (byte 5 == 0x02): 10-byte frame sent in response to
          a command being received, echoing the command ID in byte 6.
          This is the confirmation that a command was actually accepted
          by the device -- watch for this in logs after sending a
          command.
        """
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
            power_save_on = raw[11]
            led_state = raw[12]

            _LOGGER.debug(
                f"Received F2000 State Ack: AC={ac_on}, 12V={dc_on}, "
                f"PowerSave={power_save_on}, LED={led_state}"
            )

            # State Ack packets confirm the actual current state of the
            # switchable outputs -- these must be merged into self._data
            # and trigger callbacks. Previously this branch only logged
            # and returned, so the AC/DC switch entities (which read
            # `ac_inverter_enabled`/`dc12v_enabled`, backed by params
            # "b1"/"b2") never learned the confirmed state and reverted
            # to whatever the last full Telemetry packet showed -- this
            # was the cause of "switches don't remember state".
            params = dict(self._data) if self._data is not None else self._default_parameters()
            params["b1"] = b"\x01" + ac_on.to_bytes(2, byteorder="little")
            params["b2"] = b"\x01" + dc_on.to_bytes(2, byteorder="little")
            params["d5"] = b"\x01" + power_save_on.to_bytes(2, byteorder="little")
            params["d6"] = b"\x01" + led_state.to_bytes(2, byteorder="little")

            await self._process_telemetry(params)
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
    def power_save_enabled(self) -> int:
        """Power Save mode status, confirmed only via State Ack packets
        (byte 11). Full Telemetry frames do not carry this."""
        return self._parse_int("d5", begin=1)

    @property
    def led_state(self) -> int:
        """LED strip status, confirmed only via State Ack packets (byte
        12): 0=off, 1=low, 2=mid, 3=high, 4=SOS. Full Telemetry frames do
        not carry this -- this will read as the default/unknown value
        until a button is pressed or a command is sent, since the F2000
        only reports LED state reactively via State Ack."""
        return self._parse_int("d6", begin=1)

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

