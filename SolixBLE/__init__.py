"""SolixBLE module.

.. moduleauthor:: Harvey Lelliott (flip-dots) <harveylelliott@duck.com>

"""

from .device import SolixBLEDevice
from .devices import (
    C300,
    C300DC,
    C800,
    C1000,
    C1000G2,
    F2000,
    F3800,
    Generic,
    PrimeCharger160w,
    PrimeCharger250w,
    Solarbank2,
    Solarbank3,
)
from .prime_device import PrimeDevice
from .states import (
    ChargingStatus,
    ChargingStatusC300DC,
    ChargingStatusF3800,
    DisplayTimeout,
    LightStatus,
    PortStatus,
)
from .utilities import discover_devices

__all__ = [
    "SolixBLEDevice",
    "PrimeDevice",
    "C300",
    "C300DC",
    "C800",
    "C1000",
    "C1000G2",
    "F2000",
    "F3800",
    "Solarbank2",
    "Solarbank3",
    "PrimeCharger160w",
    "PrimeCharger250w",
    "Generic",
    "ChargingStatus",
    "ChargingStatusC300DC",
    "ChargingStatusF3800",
    "DisplayTimeout",
    "LightStatus",
    "PortStatus",
    "discover_devices",
]
