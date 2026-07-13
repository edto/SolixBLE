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
from ..states import ChargingStatus

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
            "b5": b"\x01\x00",
            "b6": b"\x01\x00",
            "b7": b"\x01\x00",
            "b8": b"\x01\x00",
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

        Bytes 19-20: AC input watts -> ac_power_in ("af")
        Bytes 21-22: AC output watts -> ac_power_out ("b0")
        Bytes 23-24: Top USB-C watts -> usb_c1_power ("a7")
        Bytes 25-26: Middle USB-C watts -> usb_c2_power ("a8")
        Bytes 27-28: Bottom USB-C watts -> usb_c3_power ("a9")
        Bytes 29-30: Top USB-A watts -> usb_a1_power ("aa")
        Bytes 31-32: Bottom USB-A watts -> usb_a2_power ("ab")
        Bytes 33-34: Top 12V watts -> dc_1_power_out ("ac")
        Bytes 35-36: Bottom 12V watts -> dc_2_power_out ("ad")
        Bytes 37-38: Solar input watts -> solar_power_in ("ae")
        Bytes 39-40: Total input watts -> total_power_in ("b4")
        Bytes 41-42: Total output watts -> ac_power_out_sockets ("a6")

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
            # CORRECTED: per README, byte 17 ALONE is "X / 10.0 = battery
            # hours remaining" and byte 18 ALONE is "battery days
            # remaining" -- these are two independent single-byte fields,
            # not a combined 2-byte word. My previous fix wrongly treated
            # bytes 16-17 as one 16-bit value, which pulled byte 16
            # (documented as "Unknown") into the calculation and broke
            # time_remaining for BOTH batteries, not just the expansion
            # one. Storing byte 17 directly as tenths-of-an-hour here;
            # time_remaining's existing /10.0 recovers the true hour value.
            # CORRECTED: README says "byte 17: X / 10.0 = battery hours
            # remaining". time_remaining already divides "a4" by 10.0, so
            # "a4" must store the raw byte 17 value X directly, with NO
            # multiplication. (An earlier fix mistakenly multiplied by 10
            # here, which combined with time_remaining's /10.0 produced a
            # value 10x too large.)
            set_u16("a4", int(raw[17]))

            # ADDED: read byte 18 directly for "battery days remaining" as
            # its own independent field (README documents it separately
            # from byte 17), instead of deriving days via
            # divmod(time_remaining, 24) which may not match the device's
            # own internal rounding.
            set_u16("b8", int(raw[18]))

        set_u16("af", le16(19))  # AC input watts
        set_u16("b0", le16(21))  # AC output watts
        set_u16("a7", le16(23))  # Top USB-C watts
        set_u16("a8", le16(25))  # Middle USB-C watts
        set_u16("a9", le16(27))  # Bottom USB-C watts
        set_u16("aa", le16(29))  # Top USB-A watts
        set_u16("ab", le16(31))  # Bottom USB-A watts
        set_u16("ac", le16(33))  # Top 12V watts
        set_u16("ad", le16(35))  # Bottom 12V watts
        set_u16("ae", le16(37))  # Solar input watts
        set_u16("b4", le16(39))  # Total input watts (was mis-mapped to "af")
        set_u16("a6", le16(41))  # Total output watts

        main_temp = b[66] if len(b) > 66 else 0
        if main_temp >= 128:
            main_temp -= 256
        set_s16("bd", main_temp)

        expansion_temp = b[67] if len(b) > 67 else 0
        if expansion_temp >= 128:
            expansion_temp -= 256
        set_s16("be", expansion_temp)

        # ADDED: byte 68 per README ("Battery state: 0=Idle,
        # 1=Discharging, 2=Charging"). Was previously entirely unmapped.
        set_u16("b7", b[68] if len(b) > 68 else 0)

        # FIX: README documents bytes 70, 71, and 72 as three
        # INDEPENDENT single bytes ("Main battery percentage", "External
        # battery percentage", "Total battery percentage" respectively) --
        # not a combined 16-bit word. The previous code first tried
        # interpreting raw[70:72] as one big-endian 16-bit "legacy" value
        # and only fell back to simple per-byte reads if that failed. This
        # coincidentally worked most of the time (percentages are 0-100,
        # so byte 71 is often small enough that the guess didn't misfire),
        # but it was needlessly convoluted and undocumented. Reading each
        # byte directly now, matching the README exactly.
        set_u16("c1", raw[70] if len(raw) > 70 else 0)
        set_u16("c2", raw[71] if len(raw) > 71 else 0)

        # NOTE: "battery health" (c3/c4) intentionally still reads bytes
        # 72-73 here (Total battery percentage / Unknown per README) --
        # left unchanged per explicit instruction; this is a separate,
        # already-flagged discrepancy from the true byte map and no
        # action was requested on it in this fix.
        set_u16("c3", raw[72] if len(raw) > 72 else 0)
        set_u16("c4", raw[73] if len(raw) > 73 else 0)

        # c5 (num_expansion) previously derived from whether the "legacy"
        # 16-bit guess above succeeded, which no longer applies now that
        # both fields are read as plain independent bytes. An expansion
        # battery is present whenever byte 71 (external battery
        # percentage) reports a real, non-zero value.
        set_u16("c5", 1 if len(raw) > 71 and raw[71] > 0 else 0)

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
            power_save_on = raw[11] if len(raw) > 11 else 0
            led_level = raw[12] if len(raw) > 12 else 0

            _LOGGER.debug(
                f"Received F2000 State Ack: AC={ac_on}, 12V={dc_on}, "
                f"PowerSave={power_save_on}, LED={led_level}"
            )

            params = dict(self._data) if self._data is not None else self._default_parameters()
            params["b1"] = b"\x01" + ac_on.to_bytes(2, byteorder="little")
            params["b2"] = b"\x01" + dc_on.to_bytes(2, byteorder="little")
            # Capture Power Saving Mode status from the State Ack frame
            # (byte 11), same pattern as AC/DC output above, so the Power
            # Saving Mode switch reflects real device state.
            params["b5"] = b"\x01" + power_save_on.to_bytes(2, byteorder="little")
            # ADDED: capture LED status from the State Ack frame (byte 12)
            # the same way. Previously this was read into the debug log
            # line only and then discarded -- the LED Light select entity
            # had no real device-reported state to sync to.
            params["b6"] = b"\x01" + led_level.to_bytes(2, byteorder="little")

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
                # Preserve Power Saving Mode state across routine
                # Telemetry updates, same reasoning as b1/b2 above.
                parameters["b5"] = self._data.get("b5", parameters["b5"])
                # ADDED: preserve LED state across routine Telemetry
                # updates too, same reasoning -- Telemetry frames don't
                # carry byte 9-12 status at all, so without this merge
                # every Telemetry update would silently reset LED state
                # back to the "off" default.
                parameters["b6"] = self._data.get("b6", parameters["b6"])

            await self._process_telemetry(parameters)
            return

    async def turn_ac_on(self) -> None:
        """Turn the AC output on.

        FIX: same root cause as the earlier LED "snaps back" bug -- State
        Ack (which populates "b1"/ac_inverter_enabled) only fires on a
        PHYSICAL button press per README, never after a software command.
        Without this, "b1" stayed at its stale pre-toggle value after a
        command sent from Home Assistant, and the next routine Telemetry
        frame (which preserves "b1" from self._data) would push that
        stale value back out via the state-change callback, snapping the
        switch back to its old position until a physical button press
        finally sent a real State Ack. We now optimistically write the
        confirmed-sent value into self._data ourselves, immediately after
        a successful command, so subsequent Telemetry frames preserve the
        CORRECT value instead of the stale one.
        """
        await self._send_command(0x86, b"\x00\x01")
        if self._data is not None:
            self._data["b1"] = b"\x01\x01\x00"
            # FIX: mutating self._data directly does NOT notify any
            # registered entity -- callbacks only fire from inside
            # _process_telemetry(), which this optimistic write bypasses
            # entirely. Without this, the switch entity never re-reads
            # the device and never calls async_write_ha_state(), so the
            # UI silently stays stale until some LATER, unrelated
            # Telemetry/State Ack frame happens to trigger a callback for
            # a different reason and coincidentally picks up the already-
            # correct value. This is exactly the "flips back, then later
            # reports correct" / "sticks on incorrect state" behavior --
            # explicitly running callbacks now makes the UI update
            # immediately, matching what the physical-button State Ack
            # path already does via _process_telemetry.
            self._run_state_changed_callbacks()

    async def turn_ac_off(self) -> None:
        """Turn the AC output off. See turn_ac_on for why b1 is updated here."""
        await self._send_command(0x86, b"\x00\x00")
        if self._data is not None:
            self._data["b1"] = b"\x01\x00\x00"
            self._run_state_changed_callbacks()

    async def turn_dc_on(self) -> None:
        """Turn the 12V (DC) output on. See turn_ac_on for why b2 is updated here."""
        await self._send_command(0x87, b"\x00\x01")
        if self._data is not None:
            self._data["b2"] = b"\x01\x01\x00"
            self._run_state_changed_callbacks()

    async def turn_dc_off(self) -> None:
        """Turn the 12V (DC) output off. See turn_ac_on for why b2 is updated here."""
        await self._send_command(0x87, b"\x00\x00")
        if self._data is not None:
            self._data["b2"] = b"\x01\x00\x00"
            self._run_state_changed_callbacks()

    async def turn_power_save_on(self) -> None:
        """Turn Power Saving Mode on.

        Command ID 0x8A per README ("Power Save" section), same payload
        shape as turn_ac_on/turn_dc_on above.

        FIX: this was missed when the same optimistic-update fix was
        applied to turn_ac_on/turn_dc_on/set_light_mode -- it had neither
        the self._data write nor the callback trigger, so it had the
        full original bug (State Ack only fires on physical button press,
        and even a direct self._data mutation alone does not notify
        entities). Same fix applied here: write the confirmed value into
        self._data ("b5") immediately, then explicitly run callbacks so
        the switch updates right away instead of waiting on some
        unrelated later notification.
        """
        await self._send_command(0x8A, b"\x00\x01")
        if self._data is not None:
            self._data["b5"] = b"\x01\x01\x00"
            self._run_state_changed_callbacks()

    async def turn_power_save_off(self) -> None:
        """Turn Power Saving Mode off. See turn_power_save_on for why b5 is updated here."""
        await self._send_command(0x8A, b"\x00\x00")
        if self._data is not None:
            self._data["b5"] = b"\x01\x00\x00"
            self._run_state_changed_callbacks()

    async def set_light_mode(self, mode) -> None:
        """Set the LED light bar mode (off/low/medium/high/SOS).

        Command ID 0x8B per README ("LED Control" section). Accepts either
        a LightStatus enum member or a raw int 0-4.

        FIX: Per README, State Ack (which is what populates "b6"/
        led_light_mode) only fires when a PHYSICAL button on the device
        is pressed -- it is never sent in response to a software command.
        Without this, "b6" stayed stuck at its last confirmed value after
        every command sent from Home Assistant, and the next routine
        Telemetry frame (which arrives continuously and preserves "b6"
        from self._data) would silently overwrite the select entity's
        optimistic UI update back to the stale value -- causing the LED
        to visually "snap back to off" moments after being set via HA.
        We now optimistically write the confirmed-sent value into
        self._data ourselves, immediately after a successful command, so
        subsequent Telemetry frames preserve the CORRECT value instead of
        the stale one.
        """
        level = mode.value if hasattr(mode, "value") else int(mode)
        if not 0 <= level <= 4:
            raise ValueError(f"LED light mode must be a value from 0 to 4. {level} was given.")
        await self._send_command(0x8B, bytes([0x00, level]))
        if self._data is not None:
            self._data["b6"] = b"\x01" + level.to_bytes(2, byteorder="little")
            # FIX: same missing-callback bug as turn_ac_on/turn_dc_on --
            # mutating self._data alone does not notify entities.
            self._run_state_changed_callbacks()

    async def set_ac_charging_power(self, watts: int) -> None:
        """Set the AC Charging Power Limit (recharge power).

        Command ID 0x80 per README ("Recharge Power" section). README
        documents 200-1440 watts as the range, with canned app values of
        200, 300, 400, 500, 600, 750, 1440 (silent 749, high speed 1439).
        UPDATED: range extended to 200-2200 watts per user testing --
        confirmed the device accepts values above the documented 1440W
        ceiling, up to 2200W.
        """
        if not 200 <= watts <= 2200:
            raise ValueError(f"power must be a value from 200 to 2200. {watts} was given.")
        # FIX: README specifies parameters = 0x00 + 2-byte watts (3 bytes
        # total), same leading-padding pattern as every other F2000
        # command (turn_ac_on, turn_dc_on, turn_power_save_on,
        # set_light_mode all include this 0x00 prefix). This byte was
        # dropped in a prior edit, which shifted the packet's length/byte
        # layout and caused the device to silently ignore the command.
        await self._send_command(0x80, bytes([0x00]) + watts.to_bytes(2, byteorder="little"))

    @property
    def hours_remaining(self) -> float:
        if self._data is None:
            return DEFAULT_METADATA_FLOAT
        return round(divmod(self.time_remaining, 24)[1], 1)

    @property
    def days_remaining(self) -> int:
        """Battery days remaining, read directly from byte 18 (README:
        "battery days remaining"), independent of hours_remaining.
        """
        if self._data is None:
            return DEFAULT_METADATA_INT
        return self._parse_int("b8", begin=1)

    @property
    def time_remaining(self) -> float:
        """Total remaining runtime in hours (days_remaining * 24 +
        hours_remaining), i.e. days and hours combined into one duration.

        UPDATED at user request: previously this returned only the raw
        byte 17 value (hours-of-current-day, "1.5 hours" in the example
        that prompted this fix), which duplicated hours_remaining and
        ignored days_remaining (byte 18) entirely -- e.g. "1 day, 1.5
        hours" displayed as just "1.5 hours" for both sensors. Now
        combines both fields so time_remaining reflects the true total
        duration (in this example, 25.5 hours).
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT
        return (self.days_remaining * 24) + (self._parse_int("a4", begin=1) / 10.0)

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
    def power_save_enabled(self) -> int:
        """Power Saving Mode state, captured from State Ack byte 11."""
        return self._parse_int("b5", begin=1)

    @property
    def led_light_mode(self) -> int:
        """LED light bar mode, captured from State Ack byte 12
        (0=off, 1=low, 2=mid, 3=high, 4=SOS).
        """
        return self._parse_int("b6", begin=1)

    @property
    def charging_status(self) -> ChargingStatus:
        """Battery charging state, captured from Telemetry byte 68.

        ADDED: per README ("Byte 68: Battery state
        (0=Idle, 1=Discharging, 2=Charging)"). Previously unmapped.
        UPDATED: returns the shared ChargingStatus enum (same as F2600's
        charging_status) rather than a plain int, so sensor.py's existing
        ENUM-based sensor plumbing (which expects an enum member with a
        `.value` attribute) can be reused for the F2000 without any
        further changes there.
        """
        return ChargingStatus(self._parse_int("b7", begin=1))

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
