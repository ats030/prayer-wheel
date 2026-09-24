#!/bin/sh
set -e
cd /home/ats030/app/tokusan-map
export TOKUSAN_DB_PATH=/home/ats030/app/tokusan-map/frontend/tokusan.db
exec /home/ats030/app/tokusan-map/app-server
