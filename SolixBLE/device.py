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
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDH,
    SECP256R1,
    EllipticCurvePublicKey,
    derive_private_key,
)
from cryptography.hazmat.primitives.padding import PKCS7

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
    NEGOTIATION_RESPONSE_TIMEOUT,
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
        self._p46: bytes | None = None
        self._p242: bytes | None = None
        self._data: dict[str, bytes] | None = None
        self._last_data_timestamp: datetime | None = None
        self._last_packet_timestamp: datetime | None = None
        self._negotiation_timestamp: float | None = None
        self._state_changed_callbacks: list[Callable[[], None]] = []
        self._reconnect_task: asyncio.Task | None = None
        self._expect_disconnect: bool = True
        self._connection_attempts: int = 0
        self._shared_key: bytes | None = None
        self._iv: bytes | None = None

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
                self._reset_session()

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
        try:
            _LOGGER.debug(f"Subscribing to notifications from device '{self.name}'!")
            await self._client.start_notify(UUID_TELEMETRY, self._process_notification)
        except BleakError:
            _LOGGER.exception(f"Error subscribing/negotiating with '{self.name}'!")
            return False

        # Negotiate
        try:
            async with asyncio.timeout(NEGOTIATION_TIMEOUT):

                # While negotiations have not completed
                while not self.negotiated:

                    # If we have not received any packet from the device in
                    # any stage then restart negotiations from the start
                    if (
                        self._last_data_timestamp is None
                        or (time.time() - self._last_packet_timestamp)
                        > NEGOTIATION_RESPONSE_TIMEOUT
                    ):

                        _LOGGER.debug(
                            f"Sending negotiation initiation request to '{self.name}'..."
                        )
                        await self._client.write_gatt_char(
                            UUID_COMMAND,
                            bytes.fromhex(NEGOTIATION_COMMAND_0),
                            response=True,
                        )

                    # Wait at this long to see if we get any response to
                    # our initial request in stage 0
                    await asyncio.sleep(NEGOTIATION_RESPONSE_TIMEOUT)

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
        self._expect_disconnect = True
        self._connection_attempts = 0
        self._reset_session()

        # If there is a client disconnect and throw it away
        if self._client:
            await self._client.disconnect()
            self._client = None

    @property
    def connected(self) -> bool:
        """Connected to device.

        This does not mean that an encrypted connection has been
        established or that any data values have been populated,
        use the available property to determine that.

        :returns: True/False if connected to device.
        """
        return self._client is not None and self._client.is_connected

    @property
    def negotiated(self) -> bool:
        """Has an encrypted session been successfully negotiated.

        This does not mean that any data values have been populated,
        use the available property to determine that.

        :returns: True/False if session has been negotiated and connected.
        """
        return (
            self.connected
            and self._shared_key is not None
            and self._iv is not None
            and self._negotiation_timestamp is not None
        )

    @property
    def available(self) -> bool:
        """Connected to device and data is available.

        :returns: True/False if the device is connected and sending telemetry.
        """
        return self.negotiated and self._data is not None

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
    def last_update(self) -> datetime | None:
        """Timestamp of last telemetry data update from device.

        :returns: Timestamp of last update or None.
        """
        return self._last_data_timestamp

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

    def _split_packet(self, packet: bytes) -> tuple[bytes, bytes, bytes]:
        """Validate packet and split into pattern, command, and payload bytes."""

        packet_copy = bytearray(packet)

        # Validate header is correct
        packet_header = bytes([packet_copy.pop(0), packet_copy.pop(0)])
        if packet_header != bytes.fromhex("ff09"):
            raise ValueError("Packet does not start with FF09!")

        # Validate encoded length is correct
        packet_length = int.from_bytes(
            bytes([packet_copy.pop(0), packet_copy.pop(0)]), byteorder="little"
        )
        if packet_length != len(packet):
            raise ValueError(
                f"Packet length is encoded as {packet_length} but its length was {len(packet)}!"
            )

        # Validate checksum is correct
        packet_checksum = packet_copy.pop(-1).to_bytes()
        if packet_checksum != self._checksum(packet[:-1]):
            raise ValueError(
                f"Packet checksum is encoded as {packet_checksum.hex()} but it is actually {self._checksum(packet[:-1]).hex()}!"
            )

        # Extract pattern
        packet_pattern = bytes(
            [packet_copy.pop(0), packet_copy.pop(0), packet_copy.pop(0)]
        )

        # Extract command
        packet_cmd = bytes([packet_copy.pop(0), packet_copy.pop(0)])

        # Telemetry packets have an extra field which must be popped
        if packet_pattern.hex() == "03010f" and packet_cmd.hex() == "c402":
            special_value = bytes([packet_copy.pop(0)])
            _LOGGER.debug(f"Special value: {special_value.hex()}")

        # Extract payload
        packet_payload = bytes(packet_copy)

        return packet_pattern, packet_cmd, packet_payload

    def _parse_payload(self, payload: bytearray) -> dict[str, bytes]:
        """Parse payload bytes into parameters."""

        parsed_data: dict[str, bytes] = {}
        remaining_data = bytearray(payload)

        # Packets sometimes start with 00 and we must strip that
        if remaining_data.startswith(bytes.fromhex("00")):
            remaining_data.pop(0)

        while len(remaining_data) != 0:
            try:
                param_id = bytes([remaining_data.pop(0)]).hex()
                param_len = remaining_data.pop(0)
                param_data = bytes([remaining_data.pop(0) for _ in range(0, param_len)])
                parsed_data[param_id] = param_data

                # If we have reached PKCS7 padding then we have
                # reached the end of the payload
                if len(remaining_data) < 16 and remaining_data == bytearray(
                    len(remaining_data) * len(remaining_data).to_bytes(1)
                ):
                    break

            except IndexError:
                _LOGGER.exception(
                    f"Unexpected end of packet! Data may be missing or invalid! Payload: '{payload.hex()}'"
                )

        return parsed_data

    def _parameters_to_str(self, parameters: dict[str, bytes]) -> str:
        return {k: v.hex() for k, v in parameters.items()}

    def _log_diff(self, old: dict[str, bytes], new: dict[str, bytes]) -> None:
        """Log any differences between parameters."""
        differences = {
            k: {
                "bytes": f"""{old[k]} -> {new[k]}""",
                "hex": f"""{old[k].hex()} -> {new[k].hex()}""",
                "uint": f"""{int.from_bytes(old[k][1:], byteorder="little")} -> {int.from_bytes(new[k][1:], byteorder="little")}""",
                "int": f"""{int.from_bytes(old[k][1:], byteorder="little", signed=True)} -> {int.from_bytes(new[k][1:], byteorder="little", signed=True)}""",
            }
            for k in old.keys() & new.keys()
            if new[k] != old[k]
        }
        _LOGGER.debug(
            f"Parameter changes: \n{json.dumps(differences, indent=4, sort_keys=True)}"
        )

    def _decrypt_payload(self, payload: bytes) -> bytes:
        """Decrypt telemetry packet using negotiated shared secret and IV."""
        cipher = AES.new(self._shared_key, AES.MODE_CBC, iv=self._iv)
        return cipher.decrypt(payload)

    async def _process_telemetry(
        self, cmd: bytes, parameters: dict[str, bytes]
    ) -> None:
        """Process telemetry data from the device."""

        state_changed = self._data is None or parameters != self._data

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                f"Telemetry parameters: {self._parameters_to_str(parameters)}"
            )

            # Print state update if changes and last is not none
            if state_changed and self._data is not None:
                _LOGGER.debug("Parameters have changed since previous update!")
                self._log_diff(self._data, parameters)

        # Update internal parameters
        self._data = parameters
        self._last_data_timestamp = datetime.now()

        # Run callbacks if state changed
        if state_changed:

            _LOGGER.debug(self)
            self._run_state_changed_callbacks()

    async def _process_notification(self, handle: int, data: bytearray) -> None:
        """Process a notification from the device."""

        # Split packet into pattern, command, and payload
        _LOGGER.debug(
            f"Received notification from '{self.name}'. length: {len(data)}, packet: '{data.hex()}'"
        )
        self._last_packet_timestamp = time.time()
        pattern, cmd, payload = self._split_packet(data)
        _LOGGER.debug(f"Pattern: {pattern.hex()}")
        _LOGGER.debug(f"CMD: {cmd.hex()}")
        _LOGGER.debug(f"Payload: {payload.hex()}")
        _LOGGER.debug(f"Payload length: {len(payload)}")

        match pattern.hex():

            # Encryption negotiation
            case "030001":
                parameters = self._parse_payload(payload)
                return await self._process_negotiation(cmd, parameters)

            # Encrypted messages
            case "03010f":

                match cmd.hex():

                    # Telemetry messages
                    case "c402":

                        # Anker devices seem to split data across multiple
                        # packets so we need to wait until we have both
                        # packets before we. can decrypt all of the data
                        if len(payload) == 46:
                            self._p46 = payload

                        # If we receive a big packet it invalidates the
                        # last small one
                        if len(payload) == 242:
                            self._p242 = payload
                            self._p46 = None

                        if self._p46 is None or self._p242 is None:
                            _LOGGER.debug("Missing other payload!")
                            return

                        new_payload = self._p242 + self._p46
                        _LOGGER.debug(f"Merged payload: {new_payload.hex()}")
                        decrypted_payload = self._decrypt_payload(new_payload)
                        _LOGGER.debug(f"Decrypted payload: {decrypted_payload.hex()}")
                        parameters = self._parse_payload(decrypted_payload)
                        return await self._process_telemetry(cmd, parameters)

                    # Unknown messages
                    case _:
                        _LOGGER.debug(f"Received unknown message of type: {cmd.hex()}")
                        try:
                            decrypted_payload = self._decrypt_payload(new_payload)
                            _LOGGER.debug(
                                f"Decrypted payload: {decrypted_payload.hex()}"
                            )
                            parameters = self._parse_payload(decrypted_payload)
                            _LOGGER.debug(f"Parameters: {self._parameters_to_str}")
                        except Exception:
                            _LOGGER.exception(
                                "Exception decrypting unknown message type"
                            )

            case _:
                _LOGGER.warning(
                    f"Unexpected packet type '{pattern}' sent by device! Packet: {data.hex()}"
                )

    async def _process_negotiation(
        self, cmd: bytes, parameters: dict[str, bytes]
    ) -> None:
        """Negotiate encryption with the device."""

        match cmd.hex():

            # There is a "stage 0" in which we automatically send a negotiation
            # request as soon as we establish the initial connection. That
            # should lead to the power station sending a response landing us
            # in stage 1.

            # Negotiation stage 1
            case "0801":
                _LOGGER.debug(
                    "Entered negotiation stage 1 due to response from device!"
                )
                _LOGGER.debug(f"Parameters: {self._parameters_to_str(parameters)}")
                _LOGGER.debug("Sending stage 1 response message...")
                return await self._client.write_gatt_char(
                    UUID_COMMAND, bytes.fromhex(NEGOTIATION_COMMAND_1)
                )

            # Negotiation stage 2
            case "0803":
                _LOGGER.debug(
                    "Entered negotiation stage 2 due to response from device!"
                )
                _LOGGER.debug(f"Parameters: {self._parameters_to_str(parameters)}")
                _LOGGER.debug("Sending stage 2 response message...")
                return await self._client.write_gatt_char(
                    UUID_COMMAND, bytes.fromhex(NEGOTIATION_COMMAND_2)
                )

            # Negotiation stage 3
            case "0829":
                _LOGGER.debug(
                    "Entered negotiation stage 3 due to response from device!"
                )
                _LOGGER.debug(f"Parameters: {self._parameters_to_str(parameters)}")
                self._negotiation_timestamp = time.time()
                _LOGGER.debug("Sending stage 3 response message...")
                return await self._client.write_gatt_char(
                    UUID_COMMAND, bytes.fromhex(NEGOTIATION_COMMAND_3)
                )

            # Negotiation stage 4
            case "0805":
                _LOGGER.debug(
                    "Entered negotiation stage 4 due to response from device!"
                )
                _LOGGER.debug(f"Parameters: {self._parameters_to_str(parameters)}")
                _LOGGER.debug("Sending stage 4 response message...")
                return await self._client.write_gatt_char(
                    UUID_COMMAND, bytes.fromhex(NEGOTIATION_COMMAND_4)
                )

            # Negotiation stage 5
            case "0821":
                _LOGGER.debug(
                    "Entered negotiation stage 5 due to response from device!"
                )
                _LOGGER.debug(f"Parameters: {self._parameters_to_str(parameters)}")

                # Extract public key of device from payload
                device_public_key_bytes = bytes.fromhex("04") + parameters["a1"]
                _LOGGER.debug(f"Public key of device: {device_public_key_bytes.hex()}")
                device_public_key = EllipticCurvePublicKey.from_encoded_point(
                    SECP256R1(), device_public_key_bytes
                )

                # Calculate the shared secret
                # The first half of the shared secret is the encryption key
                # and the second half is the IV
                private_value = int.from_bytes(
                    bytes.fromhex(PRIVATE_KEY), byteorder="big"
                )
                private_key = derive_private_key(private_value, SECP256R1())
                shared_secret = private_key.exchange(ECDH(), device_public_key)
                self._shared_key = shared_secret[:16]
                self._iv = shared_secret[16:]
                _LOGGER.debug(f"Shared secret: {shared_secret.hex()}")
                _LOGGER.debug(f"AES key: {self._shared_key.hex()}")
                _LOGGER.debug(f"AES IV: {self._iv.hex()}")

                _LOGGER.debug("Sending stage 5 response message...")
                return await self._client.write_gatt_char(
                    UUID_COMMAND, bytes.fromhex(NEGOTIATION_COMMAND_5)
                )

            case _:
                _LOGGER.warning(
                    f"Received unexpected negotiation request response from device! cmd: '{cmd}', parameters: '{self._parameters_to_str(parameters)}'"
                )

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
        :raises ConnectionError: If not connected/negotiated to device.
        """
        if not self.negotiated:
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
        padder = PKCS7(128).padder()
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
        self._reset_session()

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

    def _reset_session(self):
        """Reset negotiated variables and data."""
        self._p46 = None
        self._p242 = None
        self._data = None
        self._shared_key = None
        self._iv = None
        self._last_packet_timestamp = None
        self._last_data_timestamp = None
        self._negotiation_timestamp = None

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
