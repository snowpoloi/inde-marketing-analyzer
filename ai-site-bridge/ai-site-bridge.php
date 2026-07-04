<?php
/**
 * Plugin Name:       AI Site Bridge
 * Plugin URI:        https://github.com/snowpoloi/inde-marketing-analyzer
 * Description:       Import sites built with AI builders (Lovable, Bolt, v0, Emergent, ...) into WordPress and manage content, SEO, translations and WooCommerce zones from the WP admin.
 * Version:           0.1.0
 * Requires at least: 6.0
 * Requires PHP:      7.4
 * Author:            Inde
 * License:           GPL-2.0-or-later
 * Text Domain:       ai-site-bridge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'AISB_VERSION', '0.1.0' );
define( 'AISB_FILE', __FILE__ );
define( 'AISB_DIR', plugin_dir_path( __FILE__ ) );
define( 'AISB_URL', plugin_dir_url( __FILE__ ) );

require_once AISB_DIR . 'includes/class-activator.php';
require_once AISB_DIR . 'includes/class-store.php';
require_once AISB_DIR . 'includes/class-parser.php';
require_once AISB_DIR . 'includes/class-importer.php';
require_once AISB_DIR . 'includes/class-zones.php';
require_once AISB_DIR . 'includes/class-seo.php';
require_once AISB_DIR . 'includes/class-renderer.php';
require_once AISB_DIR . 'includes/class-admin.php';
require_once AISB_DIR . 'includes/class-plugin.php';

register_activation_hook( __FILE__, array( 'AISB_Activator', 'activate' ) );
register_deactivation_hook( __FILE__, array( 'AISB_Activator', 'deactivate' ) );

add_action( 'plugins_loaded', array( 'AISB_Plugin', 'instance' ) );
