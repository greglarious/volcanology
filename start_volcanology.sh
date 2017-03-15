#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PID_FILE=/var/log/volcanology.pid
CONFIG_FILE=$1
nohup python ${SCRIPT_DIR}/volcanology/__init__.py config/${CONFIG_FILE}& echo $! > ${PID_FILE}&
