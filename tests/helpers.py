"""Helpers for the test.

.. moduleauthor:: Harvey Lelliott (flip-dots) <harveylelliott@duck.com>

"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Union
from unittest import mock

from bleak import BleakClient

from SolixBLE import const

_LOGGER = logging.getLogger(__name__)


NEGOTIATION_RESPONSES: dict[str, Union[str, None]] = {
    const.NEGOTIATION_COMMAND_0: "ff090e00030001080100a1010152",
    const.NEGOTIATION_COMMAND_1: "ff091b00030001080300a10102a202fd00a30144a40101a50102ff",
    const.NEGOTIATION_COMMAND_2: "ff093800030001082900a10103a2054553503332a307302e302e302e33a41041504339464530453237333030323735a506f49d8a104e0c9a",
    const.NEGOTIATION_COMMAND_3: "ff090b00030001080500f2",
    const.NEGOTIATION_COMMAND_4: "ff094d00030001082100a140b2ade5cac4f4a0c1307e44a0e9c5363cb21e4c8485ee324c23be949fa5d5929a75e57da3207c948a0c366ca9ea1ab2cb8e57d2d046a6ebefe5d96adb5d4cb35039",
    const.NEGOTIATION_COMMAND_5: None,
}


@dataclass
class RequestResponse:
    """
    Internal data class used by MockDevice to keep track of which
    requests have been executed and what the correct response to
    the request is.
    """

    expected: bytes
    """
    The bytes expected by this request.
    """

    response: Union[bytes, None]
    """
    The bytes (if any) that should be sent in response to a matching request.
    """

    called: bool
    """
    Has this request been fulfilled.
    """


class MockDevice:
    """
    Class designed to emulate the behavior of an Anker device.

    This is designed to be used as a context manager and allows for the
    easy defining of expected requests and the appropriate responses as
    well as built in assertions for checking that all the requests were
    made.

    This implementation is a tad cursed to allow us to test some strange
    edge cases that seem to keep popping up.
    """

    def __init__(self) -> None:
        """Initialise mock device."""

        # Tuple used to keep track of all the bleak clients that have been
        # created. Each tuple contains the client, the clients disconnect
        # callbacks, and the clients notification callbacks
        self._mock_bleak_clients: list[
            tuple[BleakClient, list[Callable], list[Callable]]
        ] = []

        # This is the result of the mock.patch and used to return our
        # modified bleak client when establish connection is called
        self._establish = None

        # This is the function we are patching so instead of an actual
        # bleak client its getting our mocked one
        self._patcher = mock.patch("SolixBLE.device.establish_connection")

        # List of assertions (requests and responses) we expect to be made
        self._assertions: list[RequestResponse] = []

        # The most freshly created mock bleak client
        self._current_mock_bleak_client = None

        # The position of the next request we expect to get in the list
        # of assertions
        self._position = 0

        # The value that all our mocked bleak clients will return for
        # client.is_connected. This can be changed dynamically
        self._is_connected = True

    def new_connection_mock(self):
        """
        Executing this causes all new bleak clients created using
        establish_connection to be our mocked versions.
        """

        def custom_init(*args, **kwargs):
            """
            This function is used to create new mock bleak clients whenever
            establish_connection is called.
            """
            _LOGGER.debug(f"New mock bleak client created with '{args}', '{kwargs}'!")

            # We give it a name so we can tell the difference between them in logs
            mock_bleak_client = mock.AsyncMock(
                name=f"bleak_client_{len(self._mock_bleak_clients)}"
            )

            # Set functions/properties
            mock_bleak_client.write_gatt_char.side_effect = self.write_gatt_char
            mock_bleak_client.start_notify.side_effect = self.start_notify
            type(mock_bleak_client).is_connected = mock.PropertyMock(
                side_effect=lambda: self._is_connected
            )

            # Add it to the list of all bleak clients
            self._mock_bleak_clients.append(
                (mock_bleak_client, [kwargs["disconnected_callback"]], [])
            )

            # Set this as the most current bleak client and return it
            self._current_mock_bleak_client = mock_bleak_client
            return mock_bleak_client

        # Use custom_init to manufacture all new bleak clients
        self._establish.side_effect = custom_init

    async def __aenter__(self):
        """Enter the context. Patches establish_connection so all new clients are mocks."""
        self._establish = self._patcher.start()
        self.new_connection_mock()
        return self

    def new_connection_error(self, side_effect: Any):
        """
        Executing this causes all new bleak clients created using
        establish_connection to trigger this side effect.

        :param side_effect: Side effect to trigger (e.g exception).
        """

        self._establish.side_effect = side_effect

    def allow_connect(self):
        """
        Set is_connected of all mocked bleak clients to True.
        """
        self._is_connected = True

    def disconnect(self):
        """
        Set is_connected of all mocked bleak clients to False and
        trigger call on_disconnect callbacks.
        """
        self._is_connected = False
        for bleak_client, dc_callbacks, _ in self._mock_bleak_clients:
            for callback in dc_callbacks:
                callback(bleak_client)

    def expect_ordered(
        self, value: Union[bytes, None] = None, response: Union[bytes, None] = None
    ):
        """
        Expect an ordered request to be made to the mock device with
        the specified value and optionally respond with bytes.

        If an unexpected or out of order request is made an error will be
        raised.

        :param value: Expected bytes value or None to accept any.
        :param response: Optional bytes value to respond with.
        """
        self._assertions.append(RequestResponse(value, response, False))

    async def start_notify(self, uuid: bytes, callback: Callable):
        """
        Patched version of the bleak clients start_notify function
        which will add the callback to the currently active bleak
        client only.

        :param uuid: The UUID the module under test wants notifications of.
        :param callback: The callback the module under test wants executed.
        """
        for client, _, n_callbacks in self._mock_bleak_clients:
            if client is self._current_mock_bleak_client:
                n_callbacks.append(callback)

    async def send_data(self, data: bytes) -> None:
        """
        Write the specified data as a notification to all clients
        registered callbacks.

        :param data: Data to send.
        """

        for client, _, n_callbacks in self._mock_bleak_clients:
            for callback in n_callbacks:
                _LOGGER.debug(
                    f"Mock device sending '{data.hex()}' to client '{client}' for callback '{callback}'..."
                )
                # Handle is not used
                await callback(None, data)

                # Wait between sending
                await asyncio.sleep(0.1)

    async def write_gatt_char(
        self, char_specifier: str, data: bytes, response: bool = False
    ):
        """
        Patched version of the bleak clients write_gatt_char function
        which will raise an error if the data is not expected and
        will respond with the value to all bleak clients with callbacks
        set if a response is set.

        :param char_specifier: Not used, would be the UUID the module wants to write to.
        :param data: The data the module wants to write.
        :param response: Not used. Bool of if the module wants a response to its write.
        """
        _LOGGER.debug(f"Mock device has received data: '{data.hex()}'")

        # Find the request/response for this write
        request_response = None
        try:
            request_response = self._assertions[self._position]
        except IndexError:
            print(self._assertions)
            assert (
                False
            ), f"Received an unexpected request '{data.hex()}'. Number: {self._position+1}, Num expected: {len(self._assertions)}"

        if request_response.expected is not None:
            # Assert it matches
            assert (
                request_response.expected == data
            ), f"Expected bytes {request_response.expected.hex()}' but got '{data.hex()}'!"

        # Increment position
        self._position = self._position + 1
        request_response.called = True

        # Wait a little
        await asyncio.sleep(0.1)

        # If no response return
        if request_response.response is None:
            return

        # Respond with data to all clients on all callbacks
        await self.send_data(request_response.response)

    def check_assertions(self):
        """
        Check that all specified requests have been made by the module.
        """
        for i, item in enumerate(self._assertions):
            assert (
                item.called
            ), f"Request {i} with expected bytes '{item.expected.hex()}' was not called!"

    async def __aexit__(self, *exc):
        """
        Exit context. Stops patching establish_connection.
        """
        self._patcher.stop()
        return False
