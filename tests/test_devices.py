"""Tests for the parsing of a decrypted telemetry packet into device attributes.

.. moduleauthor:: Harvey Lelliott (flip-dots) <harveylelliott@duck.com>

"""

from typing import Any
from unittest import mock

import pytest
from bleak import BLEDevice

from SolixBLE import (
    C300,
    C1000,
    C1000G2,
    ChargingStatus,
    LightStatus,
    PortStatus,
    SolixBLEDevice,
    const,
)

MOCK_DEVICE_NAME = "Mock Device"
MOCK_DEVICE_ADDRESS = "AA:BB:CC:DD:EE:FF"
MOCK_BLE_DEVICE = BLEDevice(MOCK_DEVICE_ADDRESS, MOCK_DEVICE_NAME, {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "device_class,payload,mapping",
    [
        pytest.param(
            C1000,
            "a10131a2050300000000a3050300000000a403026b06a503020000a603020000a703020000a803020000a903020000aa03020000ab03020000ac03020000ad03020000ae03020000af03020000b003020100b103020000b203020000b30302a600b403020000b503020000b60302ff01b703020000b803029a00b903020000ba0302a600bb03020000bc020100bd020117be020100bf020101c0020100c1020157c2020100c3020164c4020100c5020100c6020100c7020100c8020100c9020100ca020100cb020100cc020100cd020100ce020100cf020100d0110041504339464530453237333030323735e5020100",
            {
                "ac_timer_remaining": 0,
                "ac_timer": None,
                "hours_remaining": 20.3,
                "days_remaining": 6,
                "ac_power_in": 0,
                "ac_power_out": 0,
                "usb_c1_power": 0,
                "usb_c2_power": 0,
                "usb_a1_power": 0,
                "usb_a2_power": 0,
                "solar_power_in": 0,
                "power_in": 0,
                "power_out": 1,
                "software_version": "1.6.6",
                "software_version_expansion": "0",
                "software_version_controller": "1.6.6",
                "ac_on": False,
                "solar_port": PortStatus.NOT_CONNECTED,
                "temperature": 23,
                "temperature_expansion": 0,
                "battery_percentage": 87,
                "battery_percentage_expansion": 0,
                "battery_health": 100,
                "battery_health_expansion": 0,
                "num_expansion": 0,
                "serial_number": "APC9FE0E27300275",
            },
            id="c1000_idle",
        ),
        pytest.param(
            C1000,
            "a10131a2050300000000a3050300000000a403020800a503020000a60302d203a703020000a803020000a903020000aa03020000ab03020000ac03020000ad03020000ae03020000af03020000b00302d303b103020000b203020000b30302a600b403020000b50302ff01b60302ff01b703020000b803029a00b903020000ba0302a600bb03020100bc020100bd02011abe020100bf020101c0020100c102014fc2020100c3020164c4020100c5020100c6020100c7020100c8020100c9020100ca020100cb020100cc020100cd020100ce020100cf020100d0110041504339464530453237333030323735e5020100",
            {
                "ac_timer_remaining": 0,
                "ac_timer": None,
                "hours_remaining": 0.8,
                "days_remaining": 0,
                "ac_power_in": 0,
                "ac_power_out": 978,
                "usb_c1_power": 0,
                "usb_c2_power": 0,
                "usb_a1_power": 0,
                "usb_a2_power": 0,
                "solar_power_in": 0,
                "power_in": 0,
                "power_out": 979,
                "software_version": "1.6.6",
                "software_version_expansion": "0",
                "software_version_controller": "1.6.6",
                "ac_on": True,
                "solar_port": PortStatus.NOT_CONNECTED,
                "temperature": 26,
                "temperature_expansion": 0,
                "battery_percentage": 79,
                "battery_percentage_expansion": 0,
                "battery_health": 100,
                "battery_health_expansion": 0,
                "num_expansion": 0,
                "serial_number": "APC9FE0E27300275",
            },
            id="c1000_ac_load",
        ),
        pytest.param(
            C1000,
            "a10131a2050300000000a3050300000000a403020f00a503024802a603020000a703020000a803020000a903020000aa03020000ab03020000ac03020000ad03020000ae03020000af03024802b003020000b103020000b203020100b30302a600b403020000b50302ff01b60302ff01b703020000b803029a00b903020000ba0302a600bb03020000bc020102bd020117be020100bf020102c0020100c1020118c2020100c3020164c4020100c5020100c6020100c7020100c8020100c9020100ca020100cb020100cc020100cd020100ce020100cf020100d0110041504339464530453237333030323735e5020100",
            {
                "ac_timer_remaining": 0,
                "ac_timer": None,
                "hours_remaining": 1.5,
                "days_remaining": 0,
                "ac_power_in": 584,
                "ac_power_out": 0,
                "usb_c1_power": 0,
                "usb_c2_power": 0,
                "usb_a1_power": 0,
                "usb_a2_power": 0,
                "solar_power_in": 0,
                "power_in": 584,
                "power_out": 0,
                "software_version": "1.6.6",
                "software_version_expansion": "0",
                "software_version_controller": "1.6.6",
                "ac_on": False,
                "solar_port": PortStatus.INPUT,
                "temperature": 23,
                "temperature_expansion": 0,
                "battery_percentage": 24,
                "battery_percentage_expansion": 0,
                "battery_health": 100,
                "battery_health_expansion": 0,
                "num_expansion": 0,
                "serial_number": "APC9FE0E27300275",
            },
            id="c1000_ac_charge",
        ),
        pytest.param(
            C1000,
            "a10131a2050300000000a3050300000000a403025a00a503020000a603020000a703020000a803020000a903020000aa03020000ab03020000ac03020000ad03020000ae03026200af03026200b003020300b103020000b203020000b30302a600b403020000b503020000b60302ff01b703020000b803029a00b903020000ba0302a600bb03020000bc020101bd020117be020100bf020102c0020100c102011ac2020100c3020164c4020100c5020100c6020100c7020100c8020100c9020100ca020100cb020100cc020100cd020100ce020100cf020100d0110041504339464530453237333030323735e5020100",
            {
                "ac_timer_remaining": 0,
                "ac_timer": None,
                "hours_remaining": 9.0,
                "days_remaining": 0,
                "ac_power_in": 0,
                "ac_power_out": 0,
                "usb_c1_power": 0,
                "usb_c2_power": 0,
                "usb_a1_power": 0,
                "usb_a2_power": 0,
                "solar_power_in": 98,
                "power_in": 98,
                "power_out": 3,
                "software_version": "1.6.6",
                "software_version_expansion": "0",
                "software_version_controller": "1.6.6",
                "ac_on": False,
                "solar_port": PortStatus.OUTPUT,
                "temperature": 23,
                "temperature_expansion": 0,
                "battery_percentage": 26,
                "battery_percentage_expansion": 0,
                "battery_health": 100,
                "battery_health_expansion": 0,
                "num_expansion": 0,
                "serial_number": "APC9FE0E27300275",
            },
            id="c1000_dc_charge_light_high",
        ),
        pytest.param(
            C1000,
            "a10131a2050300000000a3050300000000a403022900a503020000a603020000a703021400a803021000a903020b00aa03020100ab03020000ac03020000ad03020000ae03020000af03020000b003023100b103020000b203020000b30302a600b403020000b503020000b60302ff01b703020000b803029a00b903020000ba0302a600bb03020000bc020100bd020117be020100bf020101c0020100c1020117c2020100c3020164c4020100c5020100c6020101c7020101c8020101c9020101ca020100cb020100cc020100cd020100ce020100cf020100d0110041504339464530453237333030323735e5020100",
            {
                "ac_timer_remaining": 0,
                "ac_timer": None,
                "hours_remaining": 4.1,
                "days_remaining": 0,
                "ac_power_in": 0,
                "ac_power_out": 0,
                "usb_c1_power": 20,
                "usb_c2_power": 16,
                "usb_a1_power": 11,
                "usb_a2_power": 1,
                "solar_power_in": 0,
                "power_in": 0,
                "power_out": 49,
                "software_version": "1.6.6",
                "software_version_expansion": "0",
                "software_version_controller": "1.6.6",
                "ac_on": False,
                "solar_port": PortStatus.NOT_CONNECTED,
                "temperature": 23,
                "temperature_expansion": 0,
                "battery_percentage": 23,
                "battery_percentage_expansion": 0,
                "battery_health": 100,
                "battery_health_expansion": 0,
                "num_expansion": 0,
                "serial_number": "APC9FE0E27300275",
            },
            id="c1000_usb_load",
        ),
        pytest.param(
            C1000G2,
            "a10134a221062011415043444b39363146333734303032393000054131373633060201010100a30b0400000000b0040058dc00a41b0400000000b0043201000000000000001e00010000000000640103a506041700646400a60a04000000000000ab2a64a70704000000010000a80404000000aa0404000000ab0404000000ac0404000000ae0404000000b20404000000d91a0400001964010000000100000000000000000000000000000000da18040000000000000000000001e00164057f00000000000000dc06040000000000f91d0406020101050005000000000005000500050300010000000000020200fa150401010101001f0300000000000000000000000000fd0e0031373634363538323735393838fe0503638c2e69f0",
            {
                "serial_number": "APCDK961F37400290",
                "part_number": "A1763",
                "temperature": 23,
                "battery_percentage": 100,
                "battery_health": 100,
                "power_out": 0,
                "ac_power_in": 0,
                "ac_on": False,
                "ac_power_out": 0,
                "dc_input_on": False,
                "dc_power_in": 0,
                "usb_port_c1": PortStatus.NOT_CONNECTED,
                "usb_c1_power": 0,
                "usb_port_c2": PortStatus.NOT_CONNECTED,
                "usb_c2_power": 0,
                "usb_port_c3": PortStatus.NOT_CONNECTED,
                "usb_c3_power": 0,
                "usb_port_a1": PortStatus.NOT_CONNECTED,
                "usb_a1_power": 0,
                "dc_port": PortStatus.NOT_CONNECTED,
                "dc_power_out": 0,
                "max_battery_percentage": 100,
                "min_battery_percentage": 1,
            },
            id="c1000g2",
        ),
        pytest.param(
            C300,
            "a10131a2050300000000a3050300000000a40302ffffa503020000a603025400a703020000a803020000a903020000aa03020100ab03020000ac03020000ad03020000ae03025500af03020000b003020100b103021b04b20302fc01b30302fc01b403021c00b503027b00b603021b04b7020101b8020100b9020124ba020100bb020164bc020164bd020100be020100bf020100c0020101c1020100c2020100c3020100c4020100c51100415a5653424a30453339323030303438c603024a01c70302a005c803022c01c903023c00ca03020000cb020101cc020100cd020102ce020132cf020100d0020100d1020101",
            {
                "ac_timer_remaining": 0,
                "ac_timer": None,
                "dc_timer_remaining": 0,
                "dc_timer": None,
                "hours_remaining": 1.5,
                "days_remaining": 273,
                "ac_power_in": 0,
                "ac_power_out": 84,
                "ac_on": True,
                "usb_c1_power": 0,
                "usb_c2_power": 0,
                "usb_c3_power": 0,
                "usb_a1_power": 1,
                "dc_power_out": 0,
                "solar_power_in": 0,
                "power_in": 0,
                "power_out": 85,
                "temperature": 36,
                "charging_status": ChargingStatus.IDLE,
                "battery_percentage": 100,
                "usb_port_c1": PortStatus.NOT_CONNECTED,
                "usb_port_c2": PortStatus.NOT_CONNECTED,
                "usb_port_c3": PortStatus.NOT_CONNECTED,
                "usb_port_a1": PortStatus.OUTPUT,
                "dc_port": PortStatus.NOT_CONNECTED,
                "light": LightStatus.OFF,
                "serial_number": "AZVSBJ0E39200048",
            },
            id="c300_ac_passthrough",
        ),
        pytest.param(
            C300,
            "a10131a2050300000000a3050300000000a403021200a503020000a603025300a703020900a803022000a903021000aa03020000ab03020000ac03020000ad03020000ae03028c00af03020000b003020000b103021b04b20302fc01b30302fc01b403021c00b503027b00b603021b04b7020101b8020100b9020124ba020101bb020164bc020164bd020101be020101bf020101c0020101c1020100c2020100c3020100c4020100c51100415a5653424a30453339323030303438c603024a01c70302a005c803022c01c903023c00ca03020000cb020101cc020100cd020102ce020132cf020100d0020100d1020101",
            {
                "ac_timer_remaining": 0,
                "ac_timer": None,
                "dc_timer_remaining": 0,
                "dc_timer": None,
                "hours_remaining": 1.8,
                "days_remaining": 0,
                "ac_power_in": 0,
                "ac_power_out": 83,
                "ac_on": True,
                "usb_c1_power": 9,
                "usb_c2_power": 32,
                "usb_c3_power": 16,
                "usb_a1_power": 0,
                "dc_power_out": 0,
                "solar_power_in": 0,
                "power_in": 0,
                "power_out": 140,
                "software_version": "1.0.5.1",
                "temperature": 36,
                "charging_status": ChargingStatus.DISCHARGING,
                "battery_percentage": 100,
                "usb_port_c1": PortStatus.OUTPUT,
                "usb_port_c2": PortStatus.OUTPUT,
                "usb_port_c3": PortStatus.OUTPUT,
                "usb_port_a1": PortStatus.OUTPUT,
                "dc_port": PortStatus.NOT_CONNECTED,
                "light": LightStatus.OFF,
                "serial_number": "AZVSBJ0E39200048",
            },
            id="c300_discharging_ac_usb_load",
        ),
        pytest.param(
            C300,
            "a10131a2050300000000a3050300000000a403021000a503020000a603025600a703020000a803020000a903020000aa03020100ab03023900ac03020000ad03020000ae03029000af03020000b003020000b103021b04b20302fc01b30302fc01b403021c00b503027b00b603021b04b7020101b8020100b9020125ba020101bb02015dbc02015dbd020100be020100bf020100c0020101c1020101c2020100c3020100c4020100c51100415a5653424a30453339323030303438c603024a01c70302a005c803022c01c903023c00ca03020000cb020101cc020101cd020102ce020132cf020100d0020100d1020101",
            {
                "ac_timer_remaining": 0,
                "ac_timer": None,
                "dc_timer_remaining": 0,
                "dc_timer": None,
                "hours_remaining": 1.6,
                "days_remaining": 0,
                "ac_power_in": 0,
                "ac_power_out": 86,
                "ac_on": True,
                "usb_c1_power": 0,
                "usb_c2_power": 0,
                "usb_c3_power": 0,
                "usb_a1_power": 1,
                "dc_power_out": 57,
                "solar_power_in": 0,
                "power_in": 0,
                "power_out": 144,
                "software_version": "1.0.5.1",
                "temperature": 37,
                "charging_status": ChargingStatus.DISCHARGING,
                "battery_percentage": 93,
                "usb_port_c1": PortStatus.NOT_CONNECTED,
                "usb_port_c2": PortStatus.NOT_CONNECTED,
                "usb_port_c3": PortStatus.NOT_CONNECTED,
                "usb_port_a1": PortStatus.OUTPUT,
                "dc_port": PortStatus.OUTPUT,
                "light": LightStatus.OFF,
                "serial_number": "AZVSBJ0E39200048",
            },
            id="c300_discharging_ac_dc_load",
        ),
        pytest.param(
            C300,
            "a10131a2050300000000a3050300000000a403022200a503020000a603025700a703020000a803021d00a903020000aa03020100ab03020000ac03020000ad03021d00ae03025a00af03020000b003020000b103021b04b20302fc01b30302fc01b403021c00b503027b00b603021b04b7020101b8020100b9020125ba020101bb02015abc02015abd020100be020102bf020100c0020101c1020100c2020100c3020100c4020100c51100415a5653424a30453339323030303438c603024a01c70302a005c803022c01c903023c00ca03020000cb020101cc020100cd020102ce020132cf020102d0020100d1020101",
            {
                "ac_timer_remaining": 0,
                "ac_timer": None,
                "dc_timer_remaining": 0,
                "dc_timer": None,
                "hours_remaining": 3.4,
                "days_remaining": 0,
                "ac_power_in": 0,
                "ac_power_out": 87,
                "ac_on": True,
                "usb_c1_power": 0,
                "usb_c2_power": 29,
                "usb_c3_power": 0,
                "usb_a1_power": 1,
                "dc_power_out": 0,
                "solar_power_in": 0,
                "power_in": 29,
                "power_out": 90,
                "software_version": "1.0.5.1",
                "temperature": 37,
                "charging_status": ChargingStatus.DISCHARGING,
                "battery_percentage": 90,
                "usb_port_c1": PortStatus.NOT_CONNECTED,
                "usb_port_c2": PortStatus.INPUT,
                "usb_port_c3": PortStatus.NOT_CONNECTED,
                "usb_port_a1": PortStatus.OUTPUT,
                "dc_port": PortStatus.NOT_CONNECTED,
                "light": LightStatus.MEDIUM,
                "serial_number": "AZVSBJ0E39200048",
            },
            id="c300_charging_over_usb_and_light",
        ),
        pytest.param(
            C300,
            "a10131a2050300000000a3050300000000a403020100a503029301a603025400a703020000a803020000a903020000aa03020100ab03020000ac03020000ad03029301ae03025800af03020000b003020100b103021b04b20302fc01b30302fc01b403021c00b503027b00b603021b04b7020101b8020102b9020126ba020102bb020159bc020159bd020100be020100bf020100c0020101c1020100c2020100c3020100c4020100c51100415a5653424a30453339323030303438c603024a01c70302a005c803022c01c903023c00ca03020000cb020101cc020100cd020102ce020132cf020103d0020100d1020101",
            {
                "ac_timer_remaining": 0,
                "ac_timer": None,
                "dc_timer_remaining": 0,
                "dc_timer": None,
                "hours_remaining": 0.1,
                "days_remaining": 0,
                "ac_power_in": 403,
                "ac_power_out": 84,
                "ac_on": True,
                "usb_c1_power": 0,
                "usb_c2_power": 0,
                "usb_c3_power": 0,
                "usb_a1_power": 1,
                "dc_power_out": 0,
                "solar_power_in": 0,
                "power_in": 403,
                "power_out": 88,
                "software_version": "1.0.5.1",
                "temperature": 38,
                "charging_status": ChargingStatus.CHARGING,
                "battery_percentage": 89,
                "usb_port_c1": PortStatus.NOT_CONNECTED,
                "usb_port_c2": PortStatus.NOT_CONNECTED,
                "usb_port_c3": PortStatus.NOT_CONNECTED,
                "usb_port_a1": PortStatus.OUTPUT,
                "dc_port": PortStatus.NOT_CONNECTED,
                "light": LightStatus.HIGH,
                "serial_number": "AZVSBJ0E39200048",
            },
            id="c300_charging_ac_and_light",
        ),
    ],
)
async def test_values(
    device_class: SolixBLEDevice, payload: str, mapping: dict[str, Any]
) -> None:
    """
    Test that a payload is parsed into the correct values.

    :param device_class: Class of device under test.
    :param payload: The payload bytes from a telemetry packet.
    :param mapping: Mapping of class properties to their expected value.
    """
    device = device_class(MOCK_BLE_DEVICE)
    parameters = device._parse_payload(bytes.fromhex(payload))
    await device._process_telemetry(None, parameters)

    for class_property, expected_value in mapping.items():
        assert (
            getattr(device, class_property) == expected_value
        ), f"Mismatch for property '{class_property}'!"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "device_class, packet_1, packet_2, packet_3, packet_4, packet_5, secret",
    [
        pytest.param(
            C300,
            "ff090e00030001080100a1010152",
            "ff091b00030001080300a10102a202fd00a30144a40101a50102ff",
            "ff093800030001082900a10103a2054553503332a307302e302e302e33a410415a5653424a30453339323030303438a506f49d8a53a95a14",
            "ff090b00030001080500f2",
            "ff094d00030001082100a140c2a5a88fab34c1ac0f96a52e1b93354a47fb6c674b5afebacf5a2ed755435f41f0d26e97782e54e268b46d9f8a58a267cd7f7a239771e6289e55d94f7669ed448a",
            "2e9edc471d11bd214d45c0a651ab42e3cd370e04f1b860fc85adfaf612aba33f",
            id="c300_1",
        ),
        pytest.param(
            C300,
            "ff090e00030001080100a1010152",
            "ff091b00030001080300a10102a202fd00a30144a40101a50102ff",
            "ff093800030001082900a10103a2054553503332a307302e302e302e33a410415a5653424a30453339323030303438a506f49d8a53a95a14",
            "ff090b00030001080500f2",
            "ff094d00030001082100a140a7b5d3824a36cae20bab9fc4d9358191e5351905a782eda157f376cc43f1f761ab772d437f33787188716d1bebd81719d1eb76b94f08499ee93895d5b43e75ef5f",
            "f97b0112a955846530c60e4cf95f941df76d86ab9ca106aa4bd00fe1c4fcb14f",
            id="c300_2",
        ),
        pytest.param(
            C1000,
            "ff090e00030001080100a1010152",
            "ff091b00030001080300a10102a202fd00a30144a40101a50102ff",
            "ff093800030001082900a10103a2054553503332a307302e302e302e33a41041504339464530453237333030323735a506f49d8a104e0c9a",
            "ff090b00030001080500f2",
            "ff094d00030001082100a140d3ef70a8faeb9ae7d9be034390108c2c7b177f3d549eb87318bd7a31703fc604664efb0e4600298ca9a905fb5af170955fb76229791dd583478b84d9950bd65420",
            "2bdc8c8bfecf40814f602e6547cf29bf125abcc1a93be0751d8f1065a2bb5570",
            id="c1000_1",
        ),
        pytest.param(
            C1000,
            "ff090e00030001080100a1010152",
            "ff091b00030001080300a10102a202fd00a30144a40101a50102ff",
            "ff093800030001082900a10103a2054553503332a307302e302e302e33a41041504339464530453237333030323735a506f49d8a104e0c9a",
            "ff090b00030001080500f2",
            "ff094d00030001082100a140b2ade5cac4f4a0c1307e44a0e9c5363cb21e4c8485ee324c23be949fa5d5929a75e57da3207c948a0c366ca9ea1ab2cb8e57d2d046a6ebefe5d96adb5d4cb35039",
            "0c4d9db9ef376fcfe627b9b73089eda514315d4bf67fb7eb299f2894ef7a059c",
            id="c1000_2",
        ),
    ],
)
async def test_negotiation(
    device_class: SolixBLEDevice,
    packet_1: str,
    packet_2: str,
    packet_3: str,
    packet_4: str,
    packet_5: str,
    secret: str,
):
    """
    Test negotiation of the shared secret by mocking a device.

    :param device_class: The class of the device being tested.
    :param packet_1: Packet sent by device in response to negotiation command 0.
    :param packet_2: Packet sent by device in response to negotiation command 1.
    :param packet_3: Packet sent by device in response to negotiation command 2.
    :param packet_4: Packet sent by device in response to negotiation command 3.
    :param packet_5: Packet sent by device in response to negotiation command 4.
    :param secret: The expected shared secret.
    """

    # Mock the bleak client to allow us to simulate the packet exchange
    mock_bleak_client = mock.AsyncMock()
    with mock.patch(
        "SolixBLE.device.establish_connection", return_value=mock_bleak_client
    ):

        device = device_class(MOCK_BLE_DEVICE)

        async def write_gatt_char(
            char_specifier: str, data: bytes, response: bool = False
        ):
            """
            Mock the device responding to commands from the module by
            mocking the write_gatt_char function of bleak.
            """

            # Check correct UUID is written to
            assert char_specifier == const.UUID_COMMAND, "Module wrote to wrong UUID"

            # Respond with appropriate packet that the device would send
            match data.hex():

                case const.NEGOTIATION_COMMAND_0:
                    await device._process_notification(-1, bytes.fromhex(packet_1))

                case const.NEGOTIATION_COMMAND_1:
                    await device._process_notification(-1, bytes.fromhex(packet_2))

                case const.NEGOTIATION_COMMAND_2:
                    await device._process_notification(-1, bytes.fromhex(packet_3))

                case const.NEGOTIATION_COMMAND_3:
                    await device._process_notification(-1, bytes.fromhex(packet_4))

                case const.NEGOTIATION_COMMAND_4:
                    await device._process_notification(-1, bytes.fromhex(packet_5))

                # The device does not usually respond to stage 5
                case const.NEGOTIATION_COMMAND_5:
                    return

                # Check no other data is written
                case _:
                    assert False, "Module wrote unexpected data"

        # Use mocked bleak function
        mock_bleak_client.write_gatt_char.side_effect = write_gatt_char

        # Assert that the connection succeeds
        assert await device.connect(), "Expected connect to return True"

        # Assert that the correct shared secret is calculated
        assert (
            bytes.fromhex(secret)[:16] == device._shared_key
        ), "Negotiated key does not match expected"
        assert (
            bytes.fromhex(secret)[16:] == device._iv
        ), "Negotiated IV does not match expected"

        # Assert that the correct calls are made in the correct order
        mock_bleak_client.write_gatt_char.assert_has_calls(
            [
                mock.call(
                    const.UUID_COMMAND,
                    bytes.fromhex(const.NEGOTIATION_COMMAND_0),
                    response=True,
                ),
                mock.call(
                    const.UUID_COMMAND, bytes.fromhex(const.NEGOTIATION_COMMAND_1)
                ),
                mock.call(
                    const.UUID_COMMAND, bytes.fromhex(const.NEGOTIATION_COMMAND_2)
                ),
                mock.call(
                    const.UUID_COMMAND, bytes.fromhex(const.NEGOTIATION_COMMAND_3)
                ),
                mock.call(
                    const.UUID_COMMAND, bytes.fromhex(const.NEGOTIATION_COMMAND_4)
                ),
                mock.call(
                    const.UUID_COMMAND, bytes.fromhex(const.NEGOTIATION_COMMAND_5)
                ),
            ]
        )


@pytest.mark.parametrize(
    "payload,secret,iv,decrypted",
    [
        pytest.param(
            "5bc7c7b05cf74c1ba441a17a5568f4b25bc061d354f498e39ba509e2c7664ce36d6a9ee8280a40736b9b681f10ab6eb7c86bca4b88fe6fc39ca3391d7ede4e1c47b6b5f0e5ccc67c841a0eb0912039323c27f9e819244424914c9fb538e93a23bc9bfd0f4e9df1b59fec44b5236c75c6f45e42a1110152e56491f8381ae07e50113e3746ca9a16182bc8c9102bbb463eb42d27b1e6330feb3f76d21bf751fe4a1d469c64cd8c9bda426943d48fc7c583c665ea21c7ee23fdde9262d47727c9454d88dd30d291f9bc9b0936a66761846c729f898895d97c158c36e703626ea8499fbf2dc8962159f1b7380f5f84038240d5df00ce1a7eecb4f3ea0b7de9aac5b8637d78f0f3fcf6d600227148d5011bd765a99be6d6ab0e83b9ebe8dcb9ce5ba6",
            "23a6446c34efb9f9ab1dbc43ffc8e289",
            "fffdfed557f849c4e91bd7baec0c4814",
            "a10131a2050300000000a3050300000000a40302ffffa503020000a603025b00a703020000a803020000a903020000aa03020000ab03020000ac03020000ad03020000ae03025b00af03020000b003020100b103021b04b20302fc01b30302fc01b403021c00b503027b00b603021b04b7020101b8020100b9020125ba020100bb020164bc020164bd020100be020100bf020100c0020101c1020100c2020100c3020100c4020100c51100415a5653424a30453339323030303438c603024a01c70302a005c803022c01c903023c00ca03020000cb020101cc020100cd020102ce020132cf020100d0020100d1020100d2020100f7050301000000f815040101010100010000000000000000000000000000f90201020a0a0a0a0a0a0a0a0a0a",
            id="c300_telemetry",
        ),
        pytest.param(
            "403d9e7311afd074672804704798c421db698f11a5a0fc4bd793c127871c6eea7a970666c9b614c494e62b15770b1dba3dc98019e34cf0eb0ebecb5a2c5bc9ae39441d5e5acad73a645112b779312966513b53ba6f78c0f82cda624cce3b08a1a83416bd52fa4caf37e05cfaa9b37ddea75447be949ba10b892c320398fae0191c1290af0e79791c56c0d2217aafb9259b13cd2ccb9e4d520548eb416f4f96b9d852231578d4d516495564215c297fce97549986ef47058168d77afddc8ac5c0b59c9bfaf681a4cd60eca4bfad743731ca81849b83689e452e68f82fcab9fa2404f05f22b557b73705d16bab42b8045ffcc8083f9cb4fa4acda9997de1a40a2eac55b5dfbc70d882874c1db1990b76ae009bb1997ab507d347c84f3fd39d6f6c",
            "0c4d9db9ef376fcfe627b9b73089eda5",
            "14315d4bf67fb7eb299f2894ef7a059c",
            "a10131a2050300000000a3050300000000a40302d104a503020000a603020000a703020000a803020000a903020000aa03020000ab03020000ac03020000ad03020000ae03020000af03020000b003020300b103020000b203020100b30302a600b403020000b50302ff01b60302ff01b703020000b803029a00b903020000ba0302a600bb03020000bc020100bd020123be020100bf020101c0020100c1020164c2020100c3020164c4020100c5020100c6020100c7020100c8020100c9020100ca020100cb020100cc020100cd020100ce020100cf020100d0110041504339464530453237333030323735e5020100f7050301000000f815040202010100010000000000000000000000000000f9020102fd0b0041313736315f3330416801",
            id="c1000_telemetry",
        ),
        pytest.param(
            "a9fdb7f5f88e0d7ec2c3a36f9cb4f226",
            "cf9b34f93bc679b84c9754a9484a5699",
            "1cef242c586b23dbef195ba0f2ee02cb",
            "00a101310c0c0c0c0c0c0c0c0c0c0c0c",
            id="c1000_cmd_ack_ac_on",
        ),
        pytest.param(
            "2eb0fc833d00ca9e33491eab73ccfda202cfdedb86599ba5d0e3c2c059652818",
            "cf9b34f93bc679b84c9754a9484a5699",
            "1cef242c586b23dbef195ba0f2ee02cb",
            "a10131a2020101a3020100a4020100a5020103a6020101e50201000505050505",
            id="c1000_unknown",
        ),
    ],
)
def test_payload_decryption(payload: str, secret: str, iv: str, decrypted: str):
    """
    Test the decryption of a payload only. This does not test the
    splitting of a packet.

    :param payload: Payload to be decrypted.
    :param secret: AES secret payload is encrypted with.
    :param iv: IV used to encrypt payload.
    :param decrypted: Expected content of decrypted payload.
    """

    device = SolixBLEDevice(BLEDevice)
    device._shared_key = bytes.fromhex(secret)
    device._iv = bytes.fromhex(iv)

    decrypted_bytes = device._decrypt_payload(bytes.fromhex(payload))
    assert decrypted_bytes.hex() == decrypted, "Payloads do not match!"
