#!/bin/bash
#
# Script name   : run.sh
# Description   : Script for executing patched Anker app and starting Frida.
# Author        : Harvey Lelliott (@flip-dots)
# Date          : 23/03/26
# Usage         : ./run.sh [ADB device (e.g 192.168.1.1:1234)]
# 
# License       : MIT
# Revision      : 1.0.0
#
set -euxo pipefail


##################################
# Environment and arg validation #
##################################
echo "Checking environment/tools..."

# Validate arguments
if [ $# -lt 1 ]; then
  echo "Missing device argument (e.g 192.168.1.1:1234)!"
  exit 2
fi

# The device for use with ADB
DEVICE=$1

# The timestamp to use for log file
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

# Check tools
command -v adb >/dev/null 2>&1 || { echo >&2 "adb is required!"; exit 1; }
command -v frida >/dev/null 2>&1 || { echo >&2 "frida is required!"; exit 1; }


################
# Folder setup #
################
echo "Setting up folders..."

# The current folder
WORKING_FOLDER=$(pwd)

# Folder to put all data in
LOG_FOLDER="${WORKING_FOLDER}/logs"
mkdir -p $LOG_FOLDER


#############
# Execution #
#############
echo "Starting execution..."

# Port forward the port used by Frida gadget
adb -s $DEVICE forward tcp:49152 tcp:49152

# In 5 seconds open the app (non-blocking)
(sleep 5 && adb -s $DEVICE shell monkey -p com.anker.charging 1 && echo "Restarted app!") &

# Open the app and execute the Frida script
adb -s $DEVICE shell monkey -p com.anker.charging 1 \
    && frida -H 127.0.0.1:49152 -n Gadget -l frida.js \
    2>&1 | tee -a "${LOG_FOLDER}/${TIMESTAMP}.log"

echo "Done!"
