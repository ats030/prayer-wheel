#!/bin/bash
cd /home/ats030/app/dekita || exit 1
exec node test-server.cjs
