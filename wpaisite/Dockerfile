# wpaisite — WordPress with the AI Site Bridge plugin baked in.
# Build context is the repository root (see docker-compose.yml) so the
# plugin folder can be copied straight from the repo.

FROM wordpress:php8.3-apache

# The official image copies /usr/src/wordpress into the web root on first
# run, so the plugin lands in wp-content/plugins automatically.
COPY ai-site-bridge /usr/src/wordpress/wp-content/plugins/ai-site-bridge

# Allow bigger uploads (theme/plugin zips, media from the AI design).
RUN { \
	echo 'upload_max_filesize = 64M'; \
	echo 'post_max_size = 64M'; \
	echo 'memory_limit = 256M'; \
	echo 'max_execution_time = 300'; \
} > /usr/local/etc/php/conf.d/wpaisite.ini
