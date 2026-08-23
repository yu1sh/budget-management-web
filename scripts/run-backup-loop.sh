#!/bin/sh
set -eu
while true; do
  now=$(date +%s)
  next=$(date -d 'tomorrow 03:00' +%s)
  today=$(date -d 'today 03:00' +%s)
  if [ "$now" -lt "$today" ]; then next=$today; fi
  sleep $((next-now))
  python manage.py backup_data
done
