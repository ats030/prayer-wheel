#!/bin/sh
set -e

# Static game app (できた！, port 8525). Uses the local node_modules http-server
# binary so the process survives session logout via systemd (same arrangement
# as exam-trainer.sh / writing.sh).

exec /home/ats030/app/dekita/node_modules/.bin/http-server \
  /home/ats030/app/dekita -p 8525 -a 0.0.0.0 --silent
