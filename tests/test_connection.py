"""Tests for the automatic reconnection to devices.

.. moduleauthor:: Harvey Lelliott (flip-dots) <harveylelliott@duck.com>

"""

import asyncio
from typing import Union
from unittest.mock import patch

import pytest
from bleak import BLEDevice
from helpers import NEGOTIATION_RESPONSES, MockDevice

from SolixBLE import SolixBLEDevice, const

MOCK_DEVICE_NAME = "Mock Device"
MOCK_DEVICE_ADDRESS = "AA:BB:CC:DD:EE:FF"
MOCK_BLE_DEVICE = BLEDevice(MOCK_DEVICE_ADDRESS, MOCK_DEVICE_NAME, {})


@pytest.mark.asyncio
async def test_automatic_retry():
    """
    Test the automatic retrying of a lost connection when the
    reconnection happens within the timeout.

    This test expects the module to connect the the mock device
    and then the mock device drops the connection and we expect
    the module to automatically reconnect and not run any callbacks.
    """

    async with MockDevice() as mock_bluetooth:

        device = SolixBLEDevice(MOCK_BLE_DEVICE)

        def my_callback(*args, **kwargs):
            """We do not expect this callback to be triggered."""
            assert False

        # We first expect a negotiation
        for expected, response in NEGOTIATION_RESPONSES.items():
            mock_bluetooth.expect_ordered(
                bytes.fromhex(expected),
                bytes.fromhex(response) if response is not None else None,
            )

        # We expect the negotiations to succeed
        assert await device.connect(), "Expected connect to return True"
        await asyncio.sleep(0.5)
        assert device.connected, "Expected connected to be True"
        assert device.negotiated, "Expected connected to be True"
        mock_bluetooth.check_assertions()

        # We then add our callback that should not be run as we should
        # silently reconnect
        device.add_callback(my_callback)

        for expected, response in NEGOTIATION_RESPONSES.items():
            mock_bluetooth.expect_ordered(
                bytes.fromhex(expected),
                bytes.fromhex(response) if response is not None else None,
            )

        # We then trigger a disconnect from the device
        mock_bluetooth.disconnect()
        await asyncio.sleep(0.5)
        assert not device.connected, "Expected connected to be False"
        assert not device.negotiated, "Expected connected to be False"

        # Set .is_connected to True
        mock_bluetooth.allow_connect()

        # We expect to have been automatically reconnected
        await asyncio.sleep(5)
        assert device.connected, "Expected connected to be True"
        assert device.negotiated, "Expected connected to be True"
        mock_bluetooth.check_assertions()


@pytest.mark.asyncio
@patch("SolixBLE.device.DISCONNECT_TIMEOUT", 5)
@patch("SolixBLE.device.RECONNECT_DELAY", 1)
async def test_automatic_retry_timeout():
    """
    Test the automatic retrying of a lost connection when
    the reconnection takes longer than the timeout.

    This test expects the module to connect the the mock device
    and then the mock device drops the connection and we expect
    callbacks to be run as the module will not be able to establish
    the connection within the silent reconnect timeout and then
    we allow a reconnect and expect the module to automatically
    reconnect and run callbacks again on successful connection.
    """

    async with MockDevice() as mock_bluetooth:

        device = SolixBLEDevice(MOCK_BLE_DEVICE)

        num_calls = 0

        def my_callback(*args, **kwargs):
            """We expect this to be triggered on timeout limit and on reconnect."""
            nonlocal num_calls
            num_calls = num_calls + 1

        # We first expect a negotiation
        for expected, response in NEGOTIATION_RESPONSES.items():
            mock_bluetooth.expect_ordered(
                bytes.fromhex(expected),
                bytes.fromhex(response) if response is not None else None,
            )

        # We expect the negotiations to succeed
        assert await device.connect(), "Expected connect to return True"
        await asyncio.sleep(0.5)
        assert device.connected, "Expected connected to be True"
        assert device.negotiated, "Expected connected to be True"
        mock_bluetooth.check_assertions()

        # We then add our callback that should be run both when the timeout
        # is exceeded and again when we successfully reconnect
        device.add_callback(my_callback)

        # We then trigger a disconnect from the device
        mock_bluetooth.disconnect()
        await asyncio.sleep(7)
        assert not device.connected, "Expected connected to be False"
        assert not device.negotiated, "Expected connected to be False"

        # Expect callback to be triggered due to timeout limit being
        # exceeded
        assert num_calls == 1

        # Set .is_connected to True
        mock_bluetooth.allow_connect()

        # We then expect a renegotiation
        for expected, response in NEGOTIATION_RESPONSES.items():
            mock_bluetooth.expect_ordered(
                bytes.fromhex(expected),
                bytes.fromhex(response) if response is not None else None,
            )

        # We expect to have been automatically reconnected
        await asyncio.sleep(7)
        assert device.connected, "Expected connected to be True"
        assert device.negotiated, "Expected connected to be True"
        mock_bluetooth.check_assertions()

        # Expect callback to have been triggered again due to
        # successful reconnection after running callbacks due to
        # disconnection
        assert num_calls == 2


@pytest.mark.asyncio
async def test_disconnect(fast_timeouts, fast_sleep):
    """
    Test the mock device is disconnected and no automatic
    reconnection attempts are executed when disconnect is called.

    We also expect no callbacks to be run and multiple calls
    to disconnect to do nothing.
    """

    async with MockDevice() as mock_bluetooth:

        device = SolixBLEDevice(MOCK_BLE_DEVICE)

        async def assert_still_disconnected():
            """Assert that device is still disconnected."""
            for i in range(0, 100):
                await asyncio.sleep(1)
                assert (
                    not device.connected
                ), f"Expected connected to be False after {i} seconds"
                assert (
                    not device.negotiated
                ), f"Expected negotiated to be False after {i} seconds"
                assert (
                    device._client is None
                ), f"Expected client to be None after {i} seconds"

        def my_callback(*args, **kwargs):
            """We expect this to not be called."""
            assert False

        # We first expect a negotiation
        for expected, response in NEGOTIATION_RESPONSES.items():
            mock_bluetooth.expect_ordered(
                bytes.fromhex(expected),
                bytes.fromhex(response) if response is not None else None,
            )

        # We expect the negotiations to succeed
        assert await device.connect(), "Expected connect to return True"
        await asyncio.sleep(5)
        assert device.connected, "Expected connected to be True"
        assert device.negotiated, "Expected negotiated to be True"
        mock_bluetooth.check_assertions()

        # We then add our callback that should not be run when we call
        # disconnect
        device.add_callback(my_callback)

        # We then call disconnect and expect to remain disconnected and that
        # disconnect on the client was called
        await device.disconnect()
        await assert_still_disconnected()
        mock_bluetooth._current_mock_bleak_client.disconnect.assert_called_once()

        # We call disconnect again and expect no changes (still disconnected)
        await device.disconnect()
        await assert_still_disconnected()
