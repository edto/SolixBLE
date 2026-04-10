"""Solarbank 2 power station model.

.. moduleauthor:: Harvey Lelliott (flip-dots) <harveylelliott@duck.com>

"""

from ..const import DEFAULT_METADATA_FLOAT, DEFAULT_METADATA_STRING
from ..device import SolixBLEDevice


class Solarbank2(SolixBLEDevice):
    """
    SolarBank 2 Power Station.

    Use this class to connect and monitor a Solarbank 2 power station.
    This model is also known as the A17C1.

    .. note::
        It should be possible to add more sensors. I think devices with lots of
        telemetry values split them up into multiple messages but I have not
        played around with this yet. That and I am being a bit conservative with
        these initial implementations, if you want more sensors and are willing
        to help with testing feel free to raise a GitHub issue.

    """

    _EXPECTED_TELEMETRY_LENGTH: int = 253

    @property
    def serial_number(self) -> str:
        """Device serial number.

        :returns: Device serial number or default str value.
        """
        return self._parse_string("a2", begin=1)

    @property
    def battery_percentage(self) -> int:
        """Battery Percentage.

        :returns: Percentage charge of battery or default int value.
        """
        return self._parse_int("a3", begin=1)

    @property
    def software_version(self) -> str:
        """Main software version.

        :returns: Firmware version or default str value.
        """
        if self._data is None:
            return DEFAULT_METADATA_STRING

        return ".".join([digit for digit in str(self._parse_int("a6", begin=1))])

    @property
    def software_version_controller(self) -> str:
        """Software version of the controller.

        :returns: Firmware version or default str value.
        """
        if self._data is None:
            return DEFAULT_METADATA_STRING

        return ".".join([digit for digit in str(self._parse_int("a7", begin=1))])

    @property
    def software_version_expansion(self) -> str:
        """Software version of any expansion batteries.

        If there is no expansion battery then it will be "0".

        :returns: Firmware version or default str value.
        """
        if self._data is None:
            return DEFAULT_METADATA_STRING

        return ".".join([digit for digit in str(self._parse_int("a8", begin=1))])

    @property
    def temperature(self) -> int:
        """Temperature of the unit (C).

        :returns: Temperature of the unit in degrees C.
        """
        return self._parse_int("aa", begin=1, signed=True)

    @property
    def solar_power_in(self) -> float:
        """Total Solar Power In.

        :returns: Total solar power in or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("ab", begin=1) / 10.0

    @property
    def ac_power_out(self) -> float:
        """AC Power Out.

        :returns: Total AC power out or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("ac", begin=1) / 10.0

    @property
    def battery_percentage_aggregate(self) -> int:
        """Battery Percentage average across all batteries.

        :returns: Percentage charge of battery or default int value.
        """
        return self._parse_int("ad", begin=1)

    @property
    def battery_charge_power(self) -> float:
        """Battery charging power.

        :returns: Total battery power in or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("b0", begin=1) / 100.0

    @property
    def pv_yield(self) -> float:
        """Solar power generated.

        :returns: Total solar power generated or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("b1", begin=1) / 10000.0

    @property
    def charged_energy(self) -> float:
        """Energy used to charge the battery?

        :returns: I don't know what this means or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("b2", begin=1) / 10000.0

    @property
    def output_energy(self) -> float:
        """Output energy.

        :returns: Total energy output or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("b3", begin=1) / 10000.0

    @property
    def battery_discharge_power(self) -> float:
        """Battery discharging power.

        :returns: Total battery power out or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("b7", begin=1) / 100.0

    @property
    def grid_to_home_power(self) -> float:
        """Grid to home power.

        :returns: Power from grid to home or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("bc", begin=1) / 10.0

    @property
    def pv_to_grid_power(self) -> float:
        """PV to grid power.

        :returns: Power from PV to grid or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("bd", begin=1) / 10.0

    @property
    def grid_import_energy(self) -> float:
        """Grid import energy.

        :returns: Total energy imported from grid or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("be", begin=1) / 10000.0

    @property
    def grid_export_energy(self) -> float:
        """Grid export energy.

        :returns: Total energy exported to grid or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("bf", begin=1) / 10000.0

    @property
    def house_demand(self) -> float:
        """House demand power.

        :returns: Power used by house or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("c4", begin=1) / 10.0

    @property
    def ac_power_out_sockets(self) -> float:
        """AC Power Out to sockets.

        :returns: AC power out or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("c8", begin=1) / 10.0

    @property
    def consumed_energy(self) -> float:
        """Consumed energy by house.

        :returns: Total energy consumed by house or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("c9", begin=1) / 10000.0

    @property
    def solar_pv_1_power_in(self) -> float:
        """Solar Power In for port 1.

        :returns: Solar power in or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("ca", begin=1) / 10.0

    @property
    def solar_pv_2_power_in(self) -> float:
        """Solar Power In for port 2.

        :returns: Solar power in or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("cb", begin=1) / 10.0

    @property
    def solar_pv_3_power_in(self) -> float:
        """Solar Power In for port 3.

        :returns: Solar power in or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("cc", begin=1) / 10.0

    @property
    def solar_pv_4_power_in(self) -> float:
        """Solar Power In for port 4.

        :returns: Solar power in or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("cd", begin=1) / 10.0

    @property
    def power_out(self) -> float:
        """Total Power Out.

        :returns: Total power out or default float value.
        """
        if self._data is None:
            return DEFAULT_METADATA_FLOAT

        return self._parse_int("d3", begin=1) / 10.0
