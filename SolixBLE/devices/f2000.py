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

        header = bytes.fromhex("08ee000000 02".replace(" ", ""))
        length = len(parameters) + 3  # command_id + length byte + parameters + checksum, per observed packet lengths
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

    async def set_light_mode(self, level: int) -> None:
        """Set the side LED strip mode.

        :param level: 0=off, 1=low, 2=medium, 3=high, 4=SOS.
        :raises ValueError: If level is out of range.
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        if level not in (0, 1, 2, 3, 4):
            raise ValueError("LED mode must be between 0 and 4")
        await self._send_command(command_id=0x8B, parameters=bytes([0x00, level]))

    async def set_ac_charging_power(self, watts: int) -> None:
        """Set AC recharge power limit in watts.

        :param watts: Recharge power in watts. Known-good values from the
            Anker app: 200, 300, 400, 500, 600, 750, 1440.
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
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
        }

    def _parse_raw_telemetry(self, raw: bytes) -> dict[str, bytes]:
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

        def swap_u16(value: int) -> int:
            return (value >> 8) | ((value & 0x00FF) << 8)

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
            _LOGGER.debug(
                f"Received F2000 State Ack: AC={raw[9]}, 12V={raw[10]}, "
                f"PowerSave={raw[11]}, LED={raw[12]}"
            )
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

    # ------------------------------------------------------------------
    # Commands ported from the F2600 command set. Confirmed working on
    # F2000 by community testing (see project discussion):
    #   - AC output on/off
    #   - DC output on/off
    #   - LED (low, med, high, SOS, off)
    #   - Display on/off
    #   - Power Saving Mode on/off
    # Not yet confirmed working on F2000:
    #   - AC charging power limit
    # ------------------------------------------------------------------

    async def turn_ac_on(self) -> None:
        """Turn the AC output on.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_AC_OUTPUT), payload=bytes.fromhex(PAYLOAD_ON)
        )

    async def turn_ac_off(self) -> None:
        """Turn the AC output off.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_AC_OUTPUT), payload=bytes.fromhex(PAYLOAD_OFF)
        )

    async def turn_dc_on(self) -> None:
        """Turn the DC output on.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_DC_OUTPUT), payload=bytes.fromhex(PAYLOAD_ON)
        )

    async def turn_dc_off(self) -> None:
        """Turn the DC output off.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_DC_OUTPUT), payload=bytes.fromhex(PAYLOAD_OFF)
        )

    async def set_light_mode(self, mode: LightStatus) -> None:
        """Set the light mode of the LED bar.

        Supports LOW, MEDIUM, HIGH, SOS, and OFF.

        :param mode: Mode to set light bar to.
        :raises ValueError: If requested mode is invalid.
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        if mode is LightStatus.UNKNOWN:
            raise ValueError("You cannot set the light status to unknown")
        await self._send_command(
            cmd=bytes.fromhex(CMD_LIGHT_MODE),
            payload=bytes.fromhex(PAYLOAD_LIGHT_MODE) + mode.value.to_bytes(),
        )

    async def turn_display_on(self) -> None:
        """Turn the display on.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_DISPLAY_ON_OFF), payload=bytes.fromhex(PAYLOAD_ON)
        )

    async def turn_display_off(self) -> None:
        """Turn the display off.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_DISPLAY_ON_OFF), payload=bytes.fromhex(PAYLOAD_OFF)
        )

    async def turn_power_saving_mode_on(self) -> None:
        """Turn power saving mode on.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_POWER_SAVING_MODE),
            payload=bytes.fromhex(PAYLOAD_ON),
        )

    async def turn_power_saving_mode_off(self) -> None:
        """Turn power saving mode off.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_POWER_SAVING_MODE),
            payload=bytes.fromhex(PAYLOAD_OFF),
        )

    async def set_ac_charging_power(self, watts: int) -> None:
        """Set the AC charging power limit in watts.

        NOTE: Not yet confirmed working on F2000 hardware. Ported from the
        F2600 command set for testing purposes; verify behaviour carefully
        on your device before relying on it.

        :param watts: AC charging power limit in watts.
        :raises ValueError: If power value is out of valid range.
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        if watts < 100 or watts > 1440:  # below 100 causes max charge, 1440 is max in app.
            raise ValueError("AC charging power must be between 100 and 1440 W")

        await self._send_command(
            cmd=bytes.fromhex(CMD_AC_CHARGING_POWER),
            payload=bytes.fromhex(PAYLOAD_AC_CHARGING_POWER)
            + watts.to_bytes(length=2, byteorder="little", signed=False),
        )
