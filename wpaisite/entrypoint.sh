#!/bin/sh
# Refresh the AI Site Bridge plugin from the image on every container start,
# so a Coolify redeploy always ships the latest plugin version. The stock
# wordpress entrypoint only copies files into the volume on FIRST boot.
set -e

if [ -d /var/www/html/wp-content/plugins ]; then
	rm -rf /var/www/html/wp-content/plugins/ai-site-bridge
	cp -a /usr/src/ai-site-bridge /var/www/html/wp-content/plugins/ai-site-bridge
	chown -R www-data:www-data /var/www/html/wp-content/plugins/ai-site-bridge
fi

exec docker-entrypoint.sh "$@"
