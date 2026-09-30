#!/bin/sh
set -eu

# No implicit public-network membership on first boot.
case "${YACY_NETWORK_MODE:-}" in
  webportal|freeworld) ;;
  *) echo 'Set YACY_NETWORK_MODE to webportal or explicitly approved freeworld' >&2; exit 2 ;;
esac

cd /opt/yacy_search_server
mkdir -p DATA/SETTINGS
if [ ! -s DATA/SETTINGS/yacy.conf ]; then
  cp -f defaults/yacy.init DATA/SETTINGS/yacy.conf
fi
config_file=DATA/SETTINGS/yacy.conf
sed -i \
  -e "s|^network.unit.definition[[:space:]]*=.*|network.unit.definition=defaults/yacy.network.${YACY_NETWORK_MODE}.unit|" \
  -e 's|^upnp.enabled[[:space:]]*=.*|upnp.enabled=false|' \
  -e 's|^server.https[[:space:]]*=.*|server.https=false|' \
  -e 's|^update.process[[:space:]]*=.*|update.process=manual|' \
  -e 's|^javastart_Xmx[[:space:]]*=.*|javastart_Xmx=Xmx768m|' \
  -e 's|^adminAccountForLocalhost[[:space:]]*=.*|adminAccountForLocalhost=false|' \
  "$config_file"

# The mounted defaults retain the operator's random admin hash. Refuse the
# image's well-known password rather than silently starting an admin service.
if grep -q 'adminAccountBase64MD5=MD5:8cffbc0d66567a0987a4aba1ec46d63c' "$config_file"; then
  echo 'Set a private adminAccountBase64MD5 hash in DATA/SETTINGS/yacy.conf before startup' >&2
  exit 2
fi
exec /bin/sh ./startYACY.sh -f
