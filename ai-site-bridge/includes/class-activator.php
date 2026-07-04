<?php
/**
 * Activation / deactivation: database tables and default settings.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class AISB_Activator {

	public static function activate() {
		self::create_tables();
		self::ensure_defaults();
		flush_rewrite_rules();
	}

	public static function deactivate() {
		flush_rewrite_rules();
	}

	public static function create_tables() {
		global $wpdb;
		require_once ABSPATH . 'wp-admin/includes/upgrade.php';

		$charset = $wpdb->get_charset_collate();

		$strings = "CREATE TABLE {$wpdb->prefix}aisb_strings (
			id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
			page_id bigint(20) unsigned NOT NULL,
			skey char(32) NOT NULL,
			context varchar(32) NOT NULL DEFAULT 'text',
			original longtext,
			edited longtext,
			updated_at datetime DEFAULT NULL,
			PRIMARY KEY  (id),
			UNIQUE KEY page_key (page_id,skey),
			KEY page (page_id)
		) $charset;";

		$translations = "CREATE TABLE {$wpdb->prefix}aisb_translations (
			id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
			string_id bigint(20) unsigned NOT NULL,
			lang varchar(12) NOT NULL,
			value longtext,
			updated_at datetime DEFAULT NULL,
			PRIMARY KEY  (id),
			UNIQUE KEY str_lang (string_id,lang),
			KEY lang (lang)
		) $charset;";

		dbDelta( $strings );
		dbDelta( $translations );
	}

	public static function ensure_defaults() {
		$settings = get_option( 'aisb_settings' );
		if ( ! is_array( $settings ) ) {
			$settings = array();
		}
		$settings = wp_parse_args( $settings, array(
			'github_repo'    => '',
			'github_branch'  => 'main',
			'github_token'   => '',
			'build_dir'      => '',
			'languages'      => array( array( 'code' => 'en', 'label' => 'English' ) ),
			'default_lang'   => 'en',
			'front_slug'     => 'home',
			'show_switcher'  => 1,
			'webhook_secret' => wp_generate_password( 32, false, false ),
		) );
		update_option( 'aisb_settings', $settings );

		if ( ! is_array( get_option( 'aisb_slugs' ) ) ) {
			update_option( 'aisb_slugs', array() );
		}
		if ( ! is_array( get_option( 'aisb_zones' ) ) ) {
			update_option( 'aisb_zones', array() );
		}
	}
}
