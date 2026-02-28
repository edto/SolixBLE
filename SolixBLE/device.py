"""Base device implementation of SolixBLE module.

.. moduleauthor:: Harvey Lelliott (flip-dots) <harveylelliott@duck.com>

"""

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime

from bleak import BleakClient, BleakError
from bleak.backends.client import BaseBleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection
from Crypto.Cipher import AES
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.asymmetric import ec

from .const import (
    BASE_TIMESTAMP,
    DEFAULT_METADATA_INT,
    DEFAULT_METADATA_STRING,
    DISCONNECT_TIMEOUT,
    NEGOTIATION_COMMAND_0,
    NEGOTIATION_COMMAND_1,
    NEGOTIATION_COMMAND_2,
    NEGOTIATION_COMMAND_3,
    NEGOTIATION_COMMAND_4,
    NEGOTIATION_COMMAND_5,
    NEGOTIATION_TIMEOUT,
    PRIVATE_KEY,
    RECONNECT_ATTEMPTS_MAX,
    RECONNECT_DELAY,
    UUID_COMMAND,
    UUID_TELEMETRY,
)

_LOGGER = logging.getLogger(__name__)


class SolixBLEDevice:
    """Solix BLE device object."""

    def __init__(self, ble_device: BLEDevice) -> None:
        """Initialise device object. Does not connect automatically."""

        _LOGGER.debug(
            f"Initializing Solix device '{ble_device.name}' with"
            f"address '{ble_device.address}' and details '{ble_device.details}'"
        )

        self._ble_device: BLEDevice = ble_device
        self._client: BleakClient | None = None
        self._data: dict[str, bytes] | None = None
        self._last_data_timestamp: datetime | None = None
        self._supports_telemetry: bool = False
        self._state_changed_callbacks: list[Callable[[], None]] = []
        self._reconnect_task: asyncio.Task | None = None
        self._expect_disconnect: bool = True
        self._connection_attempts: int = 0
        self._number_of_received_packets: int = 0
        self._shared_key: bytes | None = None
        self._iv: bytes | None = None
        self._negotiation_timestamp: float | None = None

    def add_callback(self, function: Callable[[], None]) -> None:
        """Register a callback to be run on state updates.

        Triggers include changes to pretty much anything, including,
        battery percentage, output power, solar, connection status, etc.

        :param function: Function to run on state changes.
        """
        self._state_changed_callbacks.append(function)

    def remove_callback(self, function: Callable[[], None]) -> None:
        """Remove a registered state change callback.

        :param function: Function to remove from callbacks.
        :raises ValueError: If callback does not exist.
        """
        self._state_changed_callbacks.remove(function)

    async def connect(self, max_attempts: int = 3, run_callbacks: bool = True) -> bool:
        """Connect to device.

        This will connect to the device, determine if it is supported
        and subscribe to status updates, returning True if successful.

        :param max_attempts: Maximum number of attempts to try to connect (default=3).
        :param run_callbacks: Execute registered callbacks on successful connection (default=True).
        """

        # If we are not connected then connect
        if not self.connected:
            self._connection_attempts += 1
            _LOGGER.debug(
                f"Connecting to '{self.name}' with address '{self.address}'..."
            )

            try:

                # If we have an old client get rid of it
                if self._client is not None and self._client.is_connected:
                    _LOGGER.debug(
                        f"Disposing of old client '{self._client}' in order to connect to '{self.name}'!"
                    )
                    self._expect_disconnect = True
                    await self._client.disconnect()
                    self._client = None

                # Reset negotiated details
                self._supports_telemetry = False
                self._number_of_received_packets = 0
                self._shared_key = None
                self._iv = None
                self._negotiation_timestamp = None

                # Make new client and connect
                self._client = await establish_connection(
                    BleakClient,
                    device=self._ble_device,
                    name=self.address,
                    max_attempts=max_attempts,
                    use_services_cache=False,
                    disconnected_callback=self._disconnect_callback,
                )
                await asyncio.sleep(3)

            except BleakError:
                _LOGGER.exception(
                    f"Error establishing initial connection to '{self.name}'!"
                )

        # If we are still not connected then we have failed
        if not self.connected:
            _LOGGER.error(
                f"Failed to establish initial connection to '{self.name}' on attempt {self._connection_attempts}!"
            )
            return False

        _LOGGER.debug(
            f"Established initial connection to '{self.name}' on attempt {self._connection_attempts}!"
        )

        # If we are not subscribed to telemetry then check that
        # we can and then subscribe
        if not self.available:
            _LOGGER.debug(f"Setting up session for '{self.name}'...")
            try:
                await self._determine_services()
                await self._subscribe_to_services()
            except BleakError:
                _LOGGER.exception(f"Error subscribing/negotiating with '{self.name}'!")
                return False

        # Send negotiation initiation requests until the device responds
        while self._number_of_received_packets == 0:
            await asyncio.sleep(3)
            _LOGGER.debug(
                f"Sending negotiations initiation request to '{self.name}'..."
            )
            await self._client.write_gatt_char(
                UUID_COMMAND, bytes.fromhex(NEGOTIATION_COMMAND_0), response=True
            )
            _LOGGER.debug(f"Sent negotiation initiation request to '{self.name}'!")
            await asyncio.sleep(3)

        # Wait for negotiations to finish and catch and print any errors
        _LOGGER.debug(f"Device '{self.name}' responded to negotiation request...")
        _LOGGER.debug(f"Waiting for negotiations with '{self.name}' to finish...")
        try:
            async with asyncio.timeout(NEGOTIATION_TIMEOUT):
                while not self.available:
                    await asyncio.sleep(1)
        except TimeoutError:
            _LOGGER.exception(f"Timed out attempting to negotiate with '{self.name}'!")
            return False

        # If negotiations succeeded
        _LOGGER.debug(f"Negotiations with '{self.name}' succeeded!")
        self._expect_disconnect = False
        self._connection_attempts = 0

        # Execute callbacks if enabled
        if run_callbacks:
            self._run_state_changed_callbacks()

        return True

    async def disconnect(self) -> None:
        """Disconnect from device and reset internal state.

        Disconnects from device and does not execute callbacks.
        """
        self._supports_telemetry = False
        self._expect_disconnect = True
        self._connection_attempts = 0
        self._number_of_received_packets = 0
        self._shared_key = None
        self._iv = None
        self._negotiation_timestamp = None

        # If there is a client disconnect and throw it away
        if self._client:
            await self._client.disconnect()
            self._client = None

    @property
    def connected(self) -> bool:
        """Connected to device.

        :returns: True/False if connected to device.
        """
        return self._client is not None and self._client.is_connected

    @property
    def available(self) -> bool:
        """Connected to device and receiving data from it.

        :returns: True/False if the device is connected and sending telemetry.
        """
        return (
            self.connected
            and self.supports_telemetry
            and self._shared_key is not None
            and self._iv is not None
            and self._negotiation_timestamp is not None
            and self._data is not None
        )

    @property
    def address(self) -> str:
        """MAC address of device.

        :returns: The Bluetooth MAC address of the device.
        """
        return self._ble_device.address

    @property
    def name(self) -> str:
        """Bluetooth name of the device.

        :returns: The name of the device or default string value.
        """
        return self._ble_device.name or DEFAULT_METADATA_STRING

    @property
    def supports_telemetry(self) -> bool:
        """Device supports the libraries telemetry standard.

        :returns: True/False if telemetry supported.
        """
        return self._supports_telemetry

    @property
    def last_update(self) -> datetime | None:
        """Timestamp of last telemetry data update from device.

        :returns: Timestamp of last update or None.
        """
        return self._last_data_timestamp

    async def _determine_services(self) -> None:
        """Determine GATT services available on the device."""

        # Print services
        for service in self._client.services:
            _LOGGER.debug("[Service] %s", service)

            for char in service.characteristics:
                if "read" in char.properties:
                    try:
                        value = await self._client.read_gatt_char(char.uuid)
                        extra = f", Value: {value}"
                    except Exception as e:
                        extra = f", Error: {e}"
                else:
                    extra = ""

                _LOGGER.debug(
                    "  [Characteristic] %s (%s)%s",
                    char,
                    ",".join(char.properties),
                    extra,
                )

                for descriptor in char.descriptors:
                    try:
                        value = await self._client.read_gatt_descriptor(
                            descriptor.handle
                        )
                        _LOGGER.debug(
                            "    [Descriptor] %s, Value: %r", descriptor, value
                        )
                    except Exception as e:
                        _LOGGER.debug("    [Descriptor] %s, Error: %s", descriptor, e)

        # Populate supported services
        self._supports_telemetry = bool(
            self._client.services.get_characteristic(UUID_TELEMETRY)
        )
        if not self._supports_telemetry:
            _LOGGER.warning(
                f"Device '{self.name}' does not support the telemetry characteristic!"
            )

    def _parse_int(
        self, key: str, begin: int = None, end: int = None, signed: bool = False
    ) -> int:
        """Parse an integer at the specified key in the telemetry data.

        :param key: Key of parameter the int is in (e.g a1, a2, a3, ...).
        :param begin: Slice bytes from this index when parsing integer from bytes at the key.
        :param begin: Slice bytes to this index when parsing integer from bytes at the key.
        :param signed: If the integer is signed.
        :returns: Integer or default int value if no data.
        :raises KeyError: If key does not exist.
        :raises IndexError: If slices invalid.
        """
        if self._data is None:
            return DEFAULT_METADATA_INT
        int_bytes = self._data[key][begin:end]
        return int.from_bytes(int_bytes, byteorder="little", signed=signed)

    def _parse_string(self, key: str, begin: int = None, end: int = None) -> str:
        """Parse ASCII text at the specified key in the telemetry data.

        :param key: Key of parameter the string is in (e.g a1, a2, a3, ...).
        :param begin: Slice bytes from this index when parsing string from bytes at the key.
        :param begin: Slice bytes to this index when parsing string from bytes at the key.
        :returns: String of parsed data from telemetry or default str if no data.
        :raises UnicodeDecodeError: If bytes are not ASCII text.
        """
        return (
            self._data[key][begin:end].decode("ascii")
            if self._data
            else DEFAULT_METADATA_STRING
        )

    def _parse_telemetry_bytes(self, data: bytearray) -> dict[str, bytes]:
        """Parse a decrypted telemetry message bytes into parameters."""

        parsed_data: dict[str, bytes] = {}
        remaining_data = bytearray(data)
        while len(remaining_data) != 0:
            try:
                param_id = bytes([remaining_data.pop(0)]).hex()
                param_len = remaining_data.pop(0)
                param_data = bytes([remaining_data.pop(0) for _ in range(0, param_len)])
                parsed_data[param_id] = param_data
            except IndexError:
                _LOGGER.exception(
                    "Unexpected end of packet! Data may be missing or invalid!"
                )

        return parsed_data

    def _parse_telemetry(self, data: bytearray) -> None:
        """Update internal values using the telemetry data.

        :param data: Bytes from status update message.
        """
        parsed_data = self._parse_telemetry_bytes(data)

        # If debugging and we have a previous status update to compare against
        if _LOGGER.isEnabledFor(logging.DEBUG) and self._data is not None:
            if parsed_data == self._data:
                _LOGGER.debug(f"No changes from previous status update")
            else:
                _LOGGER.debug(f"Changes detected compared to previous status update!")
                differences = {
                    k: {
                        "bytes": f"""{self._data[k]} -> {parsed_data[k]}""",
                        "hex": f"""{self._data[k].hex()} -> {parsed_data[k].hex()}""",
                        "uint": f"""{int.from_bytes(self._data[k][1:], byteorder="little")} -> {int.from_bytes(parsed_data[k][1:], byteorder="little")}""",
                        "int": f"""{int.from_bytes(self._data[k][1:], byteorder="little", signed=True)} -> {int.from_bytes(parsed_data[k][1:], byteorder="little", signed=True)}""",
                    }
                    for k in self._data.keys() & parsed_data.keys()
                    if self._data[k] != parsed_data[k]
                }
                _LOGGER.debug(
                    f"Data changes: \n{json.dumps(differences, indent=4, sort_keys=True)}"
                )

        # Update internal data store
        self._data = parsed_data
        self._last_data_timestamp = datetime.now()

    async def _process_telemetry_update(self, handle: int, data: bytearray) -> None:
        """Update internal state and run callbacks"""

        # Parse data
        _LOGGER.debug(f"Received notification from '{self.name}'. Data: {data.hex()}")
        self._number_of_received_packets = self._number_of_received_packets + 1

        # If we do not have a shared key then we are still negotiating
        if self._shared_key is None:
            return await self._negotiate_encryption(data)

        # If we are expecting a particular size and the data is not that size then the
        # data we received is not the telemetry data we want
        if (
            self._EXPECTED_TELEMETRY_LENGTH != 0
            and len(data) != self._EXPECTED_TELEMETRY_LENGTH
        ):
            _LOGGER.debug(
                f"Data is not telemetry data. The size is wrong ({len(data)} != {self._EXPECTED_TELEMETRY_LENGTH}). Data: '{data.hex()}'"
            )
            return

        if len(data) < 100:
            _LOGGER.debug(
                f"Data is not telemetry data. It is too small. We expect > 100 but got '{len(data)}'. Data: '{data.hex()}'"
            )
            return

        _LOGGER.debug("Decrypting telemetry packet...")
        data = self._decrypt_packet(data)
        _LOGGER.debug(f"Decrypted telemetry packet str: {data}")
        _LOGGER.debug(f"Decrypted telemetry packet hex: {data.hex()}")

        old_data = self._data
        self._parse_telemetry(data)
        if _LOGGER.isEnabledFor(logging.DEBUG):
            pretty_data = {
                key: {
                    "bytes": f"""{value}""",
                    "hex": f"""{value.hex()}""",
                    "uint": f"""{int.from_bytes(value[1:], byteorder="little")}""",
                    "int": f"""{int.from_bytes(value[1:], byteorder="little", signed=True)}""",
                }
                for key, value in self._data.items()
            }
            _LOGGER.debug(
                f"Parsed telemetry packet: \n{json.dumps(pretty_data, indent=4, sort_keys=True)}"
            )

        # Print status update
        _LOGGER.debug(self)

        # Run callbacks if changed
        if data != old_data:
            self._run_state_changed_callbacks()

    async def _negotiate_encryption(self, data: bytearray) -> None:
        """Negotiate encryption with the device."""

        if self._number_of_received_packets == 1:
            _LOGGER.debug("Sending negotiation response 1...")
            await self._client.write_gatt_char(
                UUID_COMMAND, bytes.fromhex(NEGOTIATION_COMMAND_1)
            )
        elif self._number_of_received_packets == 2:
            _LOGGER.debug("Sending negotiation response 2...")
            await self._client.write_gatt_char(
                UUID_COMMAND, bytes.fromhex(NEGOTIATION_COMMAND_2)
            )
        elif self._number_of_received_packets == 3:
            _LOGGER.debug("Sending negotiation response 3...")
            self._negotiation_timestamp = time.time()
            await self._client.write_gatt_char(
                UUID_COMMAND, bytes.fromhex(NEGOTIATION_COMMAND_3)
            )
        elif self._number_of_received_packets == 4:
            _LOGGER.debug("Sending negotiation response 4...")
            await self._client.write_gatt_char(
                UUID_COMMAND, bytes.fromhex(NEGOTIATION_COMMAND_4)
            )

        # This step is special. We can calculate the shared secret at this point
        elif self._number_of_received_packets == 5:
            _LOGGER.debug("Calculating shared secret...")

            # The first half of the shared secret is the AES key
            # and the second half is the IV
            full_shared_secret = self._calculate_shared_secret(data)
            self._shared_key = full_shared_secret[:16]
            self._iv = full_shared_secret[16:]
            _LOGGER.debug(f"AES key: {self._shared_key.hex()}")
            _LOGGER.debug(f"AES IV: {self._iv.hex()}")
            _LOGGER.debug("Sending negotiation response 5...")
            await self._client.write_gatt_char(
                UUID_COMMAND, bytes.fromhex(NEGOTIATION_COMMAND_5)
            )

        else:
            raise Exception("Negotiation failed!")

    def _calculate_shared_secret(self, data: bytes) -> bytes:
        """Perform ECDH calculation to get shared secret."""

        # Get public key of power station
        device_public_key_bytes = bytes.fromhex("04") + data[12:-1]
        _LOGGER.debug(f"Public key of power station: {device_public_key_bytes.hex()}")
        power_station_public_key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), device_public_key_bytes
        )

        # Derive private key
        private_value = int.from_bytes(bytes.fromhex(PRIVATE_KEY), byteorder="big")
        private_key = ec.derive_private_key(private_value, ec.SECP256R1())

        # Calculate shared secret, only the first half of it is used as the AES key
        full_shared_secret = private_key.exchange(ec.ECDH(), power_station_public_key)
        _LOGGER.debug(f"Full shared secret: {full_shared_secret.hex()}")
        return full_shared_secret

    def _decrypt_packet(self, data: bytes) -> bytes:
        """Decrypt telemetry packet using negotiated shared secret and IV."""
        encrypted_payload = data[10:-3]
        cipher = AES.new(self._shared_key, AES.MODE_CBC, iv=self._iv)
        return cipher.decrypt(encrypted_payload)

    def _checksum(self, packet: bytes) -> bytes:
        """Calculate the checksum byte for a packet."""
        checksum_value = 0
        for b in packet:
            checksum_value = checksum_value ^ b
        return checksum_value.to_bytes(1)

    async def _send_command(self, cmd: bytes, payload: bytes) -> None:
        """Send a command to the device.

        :param cmd: 2 bytes containing command type.
        :param payload: Variable number of bytes containing arguments.
        :raises ConnectionError: If not connected to device.
        """
        if not self.available:
            raise ConnectionError("Not connected to device")

        # Commands include a timestamp in the payload to prevent replay attacks
        # and that timestamp is set during negotiations
        time_passed = int(time.time() - self._negotiation_timestamp)
        base_timestamp = int.from_bytes(
            bytes.fromhex(BASE_TIMESTAMP), byteorder="little"
        )
        new_timestamp = (base_timestamp + time_passed).to_bytes(
            length=4, byteorder="little"
        )
        new_payload = payload + bytes.fromhex("fe0503") + new_timestamp
        await self._send_encrypted_packet(cmd, new_payload)

    async def _send_encrypted_packet(self, cmd: bytes, payload: bytes) -> None:
        """Send an encrypted packet using negotiated shared secret and IV."""
        _LOGGER.debug(
            f"Building packet with cmd: {cmd.hex()} and payload: {payload.hex()}"
        )

        # Pad payload
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(payload)
        padded_data += padder.finalize()

        # Encrypt payload
        cipher = AES.new(self._shared_key, AES.MODE_CBC, iv=self._iv)
        encrypted_payload = cipher.encrypt(padded_data)

        # Calculate length of message
        length = 2 + 2 + 3 + 2 + len(encrypted_payload) + 1
        length_bytes = length.to_bytes(length=2, byteorder="little")

        # Build packet
        packet = (
            bytes.fromhex("ff09")
            + length_bytes
            + bytes.fromhex("03000f")
            + cmd
            + encrypted_payload
        )
        packet = packet + self._checksum(packet)
        _LOGGER.debug(f"Sending encrypted packet: {packet.hex()}")

        # Send packet
        await self._client.write_gatt_char(UUID_COMMAND, packet)

    def _run_state_changed_callbacks(self) -> None:
        """Execute all registered callbacks for a state change."""
        for function in self._state_changed_callbacks:
            function()

    async def _subscribe_to_services(self) -> None:
        """Subscribe to state updates from device."""
        if self._supports_telemetry:

            # Subscribe to service which device uses to send us data
            await self._client.start_notify(
                UUID_TELEMETRY, self._process_telemetry_update
            )
            _LOGGER.debug(f"Subscribed to notifications from device '{self.name}'!")
        else:
            _LOGGER.warning(
                f"Device '{self.name}' does not support telemetry characteristic!"
            )

    async def _reconnect(self) -> None:
        """Re-connect to device and run state change callbacks on timeout/failure."""
        _LOGGER.debug(f"Attempting to re-connect to '{self.name}'!")
        try:
            async with asyncio.timeout(DISCONNECT_TIMEOUT):
                await self.disconnect()
                await asyncio.sleep(RECONNECT_DELAY)
                await self.connect(run_callbacks=False)
                if self.available:
                    _LOGGER.debug(f"Successfully re-connected to '{self.name}'!")
                else:
                    _LOGGER.warning(f"Failed to re-connect to '{self.name}'!")

        except TimeoutError:
            _LOGGER.exception(f"Timed out attempting to re-connect to '{self.name}'!")
            self._run_state_changed_callbacks()

    def _disconnect_callback(self, client: BaseBleakClient) -> None:
        """Re-connect on unexpected disconnect and run callbacks on failure.

        This function will re-connect if this is not an expected
        disconnect and if it fails to re-connect it will run
        state changed callbacks. If the re-connect is successful then
        no callbacks are executed.

        :param client: Bleak client.
        """

        # Ignore disconnect callbacks from old clients
        if client != self._client:
            _LOGGER.debug(
                f"Disconnect of '{self.name}' came from other client. Ignoring..."
            )
            return

        # Reset internal state
        self._supports_telemetry = False
        self._number_of_received_packets = 0
        self._shared_key = None
        self._iv = None

        # If we expected the disconnect then we don't try to reconnect.
        if self._expect_disconnect:
            _LOGGER.debug(f"Received expected disconnect from '{client}'.")
            return

        # Else we did not expect the disconnect and must re-connect if
        # there are attempts remaining
        _LOGGER.info(f"Unexpected disconnect from '{client}'!")
        if (
            RECONNECT_ATTEMPTS_MAX == -1
            or self._connection_attempts < RECONNECT_ATTEMPTS_MAX
        ):
            # Try and reconnect
            self._reconnect_task = asyncio.create_task(self._reconnect())

        else:
            _LOGGER.warning(
                f"Maximum re-connect attempts to '{client}' exceeded. Auto re-connect disabled!"
            )

    def __str__(self) -> str:
        """Return string representation of device state."""
        self_str = f"{self.__class__.__name__}(\n"
        for name, value in {
            prop_name.upper(): prop.fget(self)
            for prop_name, prop in inspect.getmembers(type(self))
            if isinstance(prop, property)
        }.items():
            self_str += f"    {name}: {value},\n"
        self_str += ")"
        return self_str
