Limitations
===========

Bluetooth and Wi-Fi
-------------------

.. note::
    It is not currently possible to use Bluetooth and Wi-Fi at the same time.
    
Setting up Wi-Fi causes power stations to stop transmitting on Bluetooth, and turning the Bluetooth
connection back on by pressing the connection button causes it to disconnect from Wi-Fi.
It may be possible to send a special command to the power station to use both at the same time, but this has not been experimented with.


Bluetooth connection
--------------------

It has been observed that some devices (e.g C300) will stop advertising if they are not connected
for a significant period of time, this means the device will be undiscoverable and it will not be, 
possible to connect to it. This behavior has been observed even with the connection light blinking.
The solution to this issue (as it often is with software issues) is to turn the device off then on again.


Updates
-------

Anker devices only send telemetry updates when something changes. This means that if nothing is
plugged in to your device or it is drawing a constant load, you may not see any updates for 
a significant period of time. The same thing applies for initialization, the values will only
be populated when the first telemetry update is received. This can be solved by plugging in
a device with a variable load or some devices support requesting a status update (C300, C800, C1000).
If you wish to add support for requesting status updates for your device, see the 
:doc:`app decoding <app_decoding>` section.


Device support
--------------

.. note::
    Not all devices are supported and support for devices is reliant on the work done by `anker-solix-api <https://github.com/thomluther/anker-solix-api>`_
    and device owners adding support themselves. See :doc:`new_devices` for information on how to add support for a device.

Each power station encodes different information in the telemetry data, including in different orders,
this requires investigation work to decode what each value and command does on a per device basis.
I only have a C300X and C1000X to test with, so I am reliant on others adding support and 
the large database of the `anker-solix-api <https://github.com/thomluther/anker-solix-api>`_ project.
See :doc:`new_devices` for information on how to add support.
