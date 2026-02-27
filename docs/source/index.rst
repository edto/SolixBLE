Welcome to SolixBLE's documentation!
====================================

.. image:: https://img.shields.io/pypi/v/SolixBLE.svg
    :target: https://pypi.python.org/pypi/SolixBLE

.. image:: https://readthedocs.org/projects/solixble/badge/?version=latest
    :target: https://solixble.readthedocs.io/en/latest/?badge=latest
    :alt: Documentation Status
      
.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
    :target: https://github.com/psf/black
    :alt: Black

Unofficial Python module for monitoring Anker Solix power stations

 - 👌 Free software: MIT license
 - 🍝 Sauce: https://github.com/flip-dots/SolixBLE
 - 📦 PIP: https://pypi.org/project/SolixBLE/

This Python module enables you to monitor Anker Solix devices directly
from your computer, without the need for any cloud services or Anker app.
It leverages the Bleak library to interact with Bluetooth Anker Solix power stations.
No pairing is required in order to receive telemetry data.


.. note::

   This project is under active development.


Device support
--------------

======================= ======== ========== ========= ========= ============
Parameter               C300(X)  C300(X) DC C1000(X)  C1000 G2  F2000 (767)
======================= ======== ========== ========= ========= ============
AC Timer.               ✅        ❌          ✅        ❌         ❌
DC Timer.               ✅        ❌          ❌        ❌         ❌
Time remaining.         ✅        ✅          ✅        ❌         ✅
AC Power in.            ✅        N/A         ✅        ✅         ✅
AC Power out.           ✅        N/A         ✅        ✅         ✅
USB Power out.          ✅        ✅          ✅        ✅         ✅       
DC Power Out.           ✅        ✅          ❌        ✅         ✅
DC Power In.            ✅        ✅          ✅        ✅         ✅
DC Power In status.     ✅        ✅          ✅        ✅         ❌
Total Power In.         ✅        ✅          ✅        ❌         ❌
Total Power Out.        ✅        ✅          ✅        ✅         ❌
Firmware version        ✅        ❌          ✅        ❌         ✅
Expansion firmware      N/A       N/A         ✅        N/A        ✅
AC on/off state         ✅        N/A         ✅        ✅         ❌
Temperature             ✅        ✅          ✅        ✅         ✅
Expansion temperature   N/A       N/A         ✅        N/A       ✅
Charging status         ✅        ✅          ❌        ❌         ❌
Battery percentage      ✅        ✅          ✅        ✅         ✅
Expansion percentage    N/A       N/A         ✅        N/A       ✅
Battery health          ❌        ✅           ✅       ✅         ✅
Expansion health        N/A       N/A         ✅        N/A       ✅
Expansion num           N/A       N/A         ✅        N/A       ✅
USB Port status         ✅        ✅          ❌        ✅         ❌
DC Port status          ✅        ❌          ❌        ✅         ❌
Light status            ✅        ✅          ❌        N/A        ❌
Serial number           ✅        ❌          ✅        ✅         ✅
======================= ======== ========== ========= ========= ============


Contents
--------

.. toctree::

   Home <self>
   examples
   usage
   api
   limitations
   new_devices
   source
