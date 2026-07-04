<?php
/**
 * Main plugin orchestrator: post type, routing, query vars, REST webhook.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class AISB_Plugin {

	const CPT = 'aisb_page';

	/** @var AISB_Plugin */
	private static $instance = null;

	public static function instance() {
		if ( null === self::$instance ) {
			self::$instance = new self();
		}
		return self::$instance;
	}

	private function __construct() {
		add_action( 'init', array( $this, 'register_post_type' ) );
		add_action( 'init', array( $this, 'register_rewrites' ) );
		add_filter( 'query_vars', array( $this, 'query_vars' ) );
		add_action( 'template_redirect', array( 'AISB_SEO', 'maybe_render_sitemap' ), 0 );
		add_action( 'template_redirect', array( 'AISB_Renderer', 'maybe_render' ), 1 );
		add_action( 'rest_api_init', array( $this, 'register_rest' ) );

		if ( is_admin() ) {
			AISB_Admin::init();
		}
	}

	/* ---------------------------------------------------------- settings */

	public static function settings() {
		$settings = get_option( 'aisb_settings', array() );
		return is_array( $settings ) ? $settings : array();
	}

	public static function setting( $key, $default = '' ) {
		$settings = self::settings();
		return isset( $settings[ $key ] ) ? $settings[ $key ] : $default;
	}

	/** All configured languages as [ code => label ]. */
	public static function languages() {
		$out = array();
		foreach ( (array) self::setting( 'languages', array() ) as $lang ) {
			if ( ! empty( $lang['code'] ) ) {
				$out[ $lang['code'] ] = ! empty( $lang['label'] ) ? $lang['label'] : $lang['code'];
			}
		}
		if ( empty( $out ) ) {
			$out['en'] = 'English';
		}
		return $out;
	}

	public static function default_lang() {
		$default   = self::setting( 'default_lang', 'en' );
		$languages = self::languages();
		return isset( $languages[ $default ] ) ? $default : key( $languages );
	}

	/** Language codes other than the default one. */
	public static function extra_langs() {
		$langs = array_keys( self::languages() );
		return array_values( array_diff( $langs, array( self::default_lang() ) ) );
	}

	public static function front_slug() {
		$front = self::setting( 'front_slug', 'home' );
		return $front ? $front : 'home';
	}

	/** Public URL for an imported page in a given language. */
	public static function url_for( $slug, $lang = '' ) {
		$path = ( $slug === self::front_slug() ) ? '' : trailingslashit( $slug );
		if ( $lang && $lang !== self::default_lang() ) {
			$path = trailingslashit( $lang ) . $path;
		}
		return home_url( '/' . $path );
	}

	/* ----------------------------------------------------------- routing */

	public function register_post_type() {
		register_post_type( self::CPT, array(
			'label'               => __( 'AI Site Pages', 'ai-site-bridge' ),
			'public'              => false,
			'show_ui'             => false,
			'exclude_from_search' => true,
			'supports'            => array( 'title' ),
		) );
	}

	public function query_vars( $vars ) {
		$vars[] = 'aisb_page';
		$vars[] = 'aisb_lang';
		$vars[] = 'aisb_sitemap';
		return $vars;
	}

	public function register_rewrites() {
		add_rewrite_rule( '^aisb-sitemap\.xml$', 'index.php?aisb_sitemap=1', 'top' );

		$slugs = (array) get_option( 'aisb_slugs', array() );
		$langs = self::extra_langs();
		$front = self::front_slug();

		foreach ( $langs as $lang ) {
			add_rewrite_rule(
				'^' . preg_quote( $lang, '#' ) . '/?$',
				'index.php?aisb_page=' . rawurlencode( $front ) . '&aisb_lang=' . rawurlencode( $lang ),
				'top'
			);
		}

		foreach ( $slugs as $slug ) {
			$pattern = str_replace( '#', '\#', preg_quote( $slug, '#' ) );
			add_rewrite_rule(
				'^' . $pattern . '/?$',
				'index.php?aisb_page=' . rawurlencode( $slug ),
				'top'
			);
			foreach ( $langs as $lang ) {
				add_rewrite_rule(
					'^' . preg_quote( $lang, '#' ) . '/' . $pattern . '/?$',
					'index.php?aisb_page=' . rawurlencode( $slug ) . '&aisb_lang=' . rawurlencode( $lang ),
					'top'
				);
			}
		}
	}

	/* ------------------------------------------------------ REST webhook */

	public function register_rest() {
		register_rest_route( 'aisb/v1', '/sync', array(
			'methods'             => 'POST',
			'callback'            => array( $this, 'handle_webhook' ),
			'permission_callback' => '__return_true',
		) );
	}

	/**
	 * GitHub push webhook (or manual POST). Authenticated either by
	 * X-Hub-Signature-256 (GitHub HMAC) or a ?secret= query parameter.
	 */
	public function handle_webhook( WP_REST_Request $request ) {
		$secret = self::setting( 'webhook_secret' );
		if ( ! $secret ) {
			return new WP_Error( 'aisb_no_secret', 'Webhook secret is not configured.', array( 'status' => 403 ) );
		}

		$ok        = false;
		$signature = $request->get_header( 'x-hub-signature-256' );
		if ( $signature ) {
			$expected = 'sha256=' . hash_hmac( 'sha256', $request->get_body(), $secret );
			$ok       = hash_equals( $expected, $signature );
		} elseif ( $request->get_param( 'secret' ) ) {
			$ok = hash_equals( $secret, (string) $request->get_param( 'secret' ) );
		}

		if ( ! $ok ) {
			return new WP_Error( 'aisb_bad_secret', 'Invalid webhook signature or secret.', array( 'status' => 403 ) );
		}

		$result = AISB_Importer::sync();
		if ( is_wp_error( $result ) ) {
			return new WP_Error( 'aisb_sync_failed', $result->get_error_message(), array( 'status' => 500 ) );
		}
		return rest_ensure_response( $result );
	}
}
