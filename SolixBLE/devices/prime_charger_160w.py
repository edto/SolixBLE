"""Anker Prime Charger (160w) model.

.. moduleauthor:: Harvey Lelliott (flip-dots) <harveylelliott@duck.com>

"""

from ..const import DEFAULT_METADATA_FLOAT
from ..prime_device import PrimeDevice
from ..states import PortStatus

CMD_USB_OUTPUT = "4207"
CMD_USB_TIMER = "4209"

PAYLOAD_USB_C1_ON = "a10121a2020100a3020101"
PAYLOAD_USB_C1_OFF = "a10121a2020100a3020100"
PAYLOAD_USB_C1_TIMER = "a10121a2020100a30504"

PAYLOAD_USB_C2_ON = "a10121a2020101a3020101"
PAYLOAD_USB_C2_OFF = "a10121a2020101a3020100"
PAYLOAD_USB_C2_TIMER = "a10121a2020101a30504"

PAYLOAD_USB_C3_ON = "a10121a2020102a3020101"
PAYLOAD_USB_C3_OFF = "a10121a2020102a3020100"
PAYLOAD_USB_C3_TIMER = "a10121a2020102a30504"


class PrimeCharger160w(PrimeDevice):
    """
    Anker Prime Charger (160w) model.

    Use this class to connect and monitor the 160w charger.
    This model is also known as the A2687.
    """

    @property
    def usb_port_c1(self) -> PortStatus:
        """USB C1 Port Status.

        :returns: Status of the USB C1 port.
        """
        return PortStatus(self._parse_int("a5", begin=1, end=2))

    @property
    def usb_c1_voltage(self) -> float:
        """USB C1 Port voltage (V).

        :returns: Voltage of the USB C1 port or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("a5", begin=2, end=4) / 1000.0

    @property
    def usb_c1_current(self) -> float:
        """USB C1 Port current (A).

        :returns: Current of the USB C1 port or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("a5", begin=4, end=6) / 1000.0

    @property
    def usb_c1_power(self) -> float:
        """USB C1 Port power (W).

        :returns: Power of the USB C1 port or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("a5", begin=6, end=8) / 100.0

    @property
    def usb_port_c2(self) -> PortStatus:
        """USB C2 Port Status.

        :returns: Status of the USB C2 port.
        """
        return PortStatus(self._parse_int("a6", begin=1, end=2))

    @property
    def usb_c2_voltage(self) -> float:
        """USB C2 Port voltage (V).

        :returns: Voltage of the USB C2 port or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("a6", begin=2, end=4) / 1000.0

    @property
    def usb_c2_current(self) -> float:
        """USB C2 Port current (A).

        :returns: Current of the USB C2 port or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("a6", begin=4, end=6) / 1000.0

    @property
    def usb_c2_power(self) -> float:
        """USB C2 Port power (W).

        :returns: Power of the USB C2 port or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("a6", begin=6, end=8) / 100.0

    @property
    def usb_port_c3(self) -> PortStatus:
        """USB C3 Port Status.

        :returns: Status of the USB C3 port.
        """
        return PortStatus(self._parse_int("a7", begin=1, end=2))

    @property
    def usb_c3_voltage(self) -> float:
        """USB C3 Port voltage (V).

        :returns: Voltage of the USB C3 port or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("a7", begin=2, end=4) / 1000.0

    @property
    def usb_c3_current(self) -> float:
        """USB C3 Port current (A).

        :returns: Current of the USB C3 port or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("a7", begin=4, end=6) / 1000.0

    @property
    def usb_c3_power(self) -> float:
        """USB C3 Port power (W).

        :returns: Power of the USB C3 port or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("a7", begin=6, end=8) / 100.0

    async def turn_usb_c1_on(self) -> None:
        """Turn USB port C1 on.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_USB_OUTPUT),
            payload=bytes.fromhex(PAYLOAD_USB_C1_ON),
        )

    async def turn_usb_c1_off(self) -> None:
        """Turn USB port C1 off.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_USB_OUTPUT),
            payload=bytes.fromhex(PAYLOAD_USB_C1_OFF),
        )

    async def set_timer_usb_c1(self, time: int) -> None:
        """Set auto off timer for USB C1.

        :param time: Seconds until shutdown.
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_USB_TIMER),
            payload=bytes.fromhex(PAYLOAD_USB_C1_TIMER)
            + time.to_bytes(4, byteorder="little"),
        )

    async def turn_usb_c2_on(self) -> None:
        """Turn USB port C2 on.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_USB_OUTPUT),
            payload=bytes.fromhex(PAYLOAD_USB_C2_ON),
        )

    async def turn_usb_c2_off(self) -> None:
        """Turn USB port C2 off.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_USB_OUTPUT),
            payload=bytes.fromhex(PAYLOAD_USB_C2_OFF),
        )

    async def set_timer_usb_c2(self, time: int) -> None:
        """Set auto off timer for USB C2.

        :param time: Seconds until shutdown.
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_USB_TIMER),
            payload=bytes.fromhex(PAYLOAD_USB_C2_TIMER)
            + time.to_bytes(4, byteorder="little"),
        )

    async def turn_usb_c3_on(self) -> None:
        """Turn USB port C3 on.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_USB_OUTPUT),
            payload=bytes.fromhex(PAYLOAD_USB_C3_ON),
        )

    async def turn_usb_c3_off(self) -> None:
        """Turn USB port C3 off.

        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_USB_OUTPUT),
            payload=bytes.fromhex(PAYLOAD_USB_C3_OFF),
        )

    async def set_timer_usb_c3(self, time: int) -> None:
        """Set auto off timer for USB C3.

        :param time: Seconds until shutdown.
        :raises ConnectionError: If not connected to device.
        :raises BleakError: If command transmission fails.
        """
        await self._send_command(
            cmd=bytes.fromhex(CMD_USB_TIMER),
            payload=bytes.fromhex(PAYLOAD_USB_C3_TIMER)
            + time.to_bytes(4, byteorder="little"),
        )
