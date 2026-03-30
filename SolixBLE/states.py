"""Enums for SolixBLE module.

.. moduleauthor:: Harvey Lelliott (flip-dots) <harveylelliott@duck.com>

"""

from enum import Enum


class PortStatus(Enum):
    """The status of a port on the device."""

    #: The status of the port is unknown.
    UNKNOWN = -1

    #: The port is not connected / off.
    NOT_CONNECTED = 0

    #: The port is an output / on.
    OUTPUT = 1

    #: The port is an input / on.
    INPUT = 2

    @classmethod
    def from_input_only(cls, value: int):
        """Custom factory for ports which only support being inputs."""

        # If it would be an output (i.e 1) set it to input (i.e 2).
        if value == PortStatus.OUTPUT.value:
            value = PortStatus.INPUT.value

        return cls(value)


class ChargingStatus(Enum):
    """The status of charging/discharging on a device."""

    #: The status is unknown.
    UNKNOWN = -1

    #: The device is idle (Battery not charging or discharging).
    IDLE = 0

    #: The device is discharging.
    DISCHARGING = 1

    #: The device is charging.
    CHARGING = 2


class ChargingStatusF3800(Enum):
    """The charging type of an F3800."""

    #: The status is unknown.
    UNKNOWN = -1

    #: The device is idle.
    INACTIVE = 0

    #: The device is charging via solar.
    SOLAR = 1

    #: The device is charging via AC.
    AC = 2

    #: The device is charging via solar and AC.
    BOTH = 3


class LightStatus(Enum):
    """The status of the light on the device."""

    #: The status of the light is unknown.
    UNKNOWN = -1

    #: The light is off.
    OFF = 0

    #: The light is on low.
    LOW = 1

    #: The light is on medium.
    MEDIUM = 2

    #: The light is on high.
    HIGH = 3

    #: SOS mode. Not supported by all devices.
    SOS = 4


class DisplayTimeout(Enum):
    """Display timeout on device in seconds. Only specific values are allowed."""

    #: The status of the display timeout is unknown.
    UNKNOWN = -1

    #: 20 seconds.
    S20 = 20

    #: 30 seconds.
    S30 = 30

    #: 60 seconds.
    S60 = 60

    #: 300 seconds (5m).
    S300 = 300

    #: 1800 seconds (30m).
    S1800 = 1800

class TemperatureUnit(Enum):
    """The status of the temperature unit of the device."""

    #: The display unit is unknown.
    UNKNOWN = -1

    #: Display unit Celsius.
    CELSIUS = 0

    #: Display unit is Fahrenheit.
    FAHRENHEIT = 1

class PortOverload(Enum):
    """The overload status of a port."""

    #: Overload status is unknown.
    UNKNOWN = -1

    #: No overload event.
    NONE = 0

    #: USB C1 overload detected.
    USB_C1 = 8

    #: USB C2 overload detected.
    USB_C2 = 9

    #: USB C3 overload detected.
    USB_C3 = 10
