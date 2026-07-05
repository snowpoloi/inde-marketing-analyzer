<?php
/**
 * Front-end renderer: serves imported pages with edited content,
 * translations, SEO tags, dynamic zones and the language switcher.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class AISB_Renderer {

	public static function maybe_render() {
		if ( get_query_var( 'aisb_sitemap' ) ) {
			return;
		}

		$slug = (string) get_query_var( 'aisb_page' );
		$lang = (string) get_query_var( 'aisb_lang' );

		if ( '' === $slug && ( is_front_page() || is_home() ) ) {
			$slug = AISB_Plugin::front_slug();
			// Only take over the front page when that page was actually imported.
			if ( ! AISB_Store::get_page_by_slug( $slug ) ) {
				return;
			}
		}
		if ( '' === $slug ) {
			return;
		}

		$post = AISB_Store::get_page_by_slug( $slug );
		if ( ! $post ) {
			return;
		}

		$languages = AISB_Plugin::languages();
		if ( '' === $lang || ! isset( $languages[ $lang ] ) ) {
			$lang = AISB_Plugin::default_lang();
		}

		global $wp_query;
		$wp_query->is_404 = false;
		status_header( 200 );
		header( 'Content-Type: text/html; charset=utf-8' );

		echo self::render( $post, $slug, $lang ); // phpcs:ignore WordPress.Security.EscapeOutput
		exit;
	}

	public static function render( $post, $slug, $lang ) {
		$html = get_post_meta( $post->ID, '_aisb_html', true );
		if ( ! $html ) {
			return '<!-- AISB: page has no imported HTML -->';
		}

		$doc = AISB_Parser::load_dom( $html );
		if ( ! $doc ) {
			return $html;
		}

		$default  = AISB_Plugin::default_lang();
		$resolved = AISB_Store::resolve_map( $post->ID, $lang, $default );
		$xpath    = new DOMXPath( $doc );

		self::apply_strings( $doc, $xpath, $resolved );
		self::apply_images( $xpath, $resolved );
		$has_zones = self::apply_zones( $doc, $xpath, $slug );

		if ( AISB_Plugin::setting( 'strip_js', 1 ) ) {
			self::strip_design_js( $xpath );
		}

		AISB_SEO::inject_head( $doc, $post, $slug, $lang, $resolved );

		if ( $has_zones ) {
			self::append_style( $doc, AISB_Zones::css() );
		}
		if ( $lang !== $default ) {
			self::prefix_links( $xpath, $lang );
		}
		if ( AISB_Plugin::setting( 'show_switcher', 1 ) && count( AISB_Plugin::languages() ) > 1 ) {
			self::append_switcher( $doc, $slug, $lang );
		}

		return AISB_Parser::save_dom( $doc );
	}

	/* ------------------------------------------------------- application */

	private static function apply_strings( DOMDocument $doc, DOMXPath $xpath, array $resolved ) {
		foreach ( $xpath->query( '//*[@data-aisb-k]' ) as $node ) {
			/** @var DOMElement $node */
			$key = $node->getAttribute( 'data-aisb-k' );
			if ( isset( $resolved[ $key ] ) && '' !== (string) $resolved[ $key ] ) {
				AISB_Parser::set_inner_html( $node, wp_kses_post( $resolved[ $key ] ) );
			}
		}
	}

	private static function apply_images( DOMXPath $xpath, array $resolved ) {
		foreach ( $xpath->query( '//img[@data-aisb-ks or @data-aisb-ka]' ) as $img ) {
			/** @var DOMElement $img */
			$src_key = $img->getAttribute( 'data-aisb-ks' );
			if ( $src_key && isset( $resolved[ $src_key ] ) && '' !== (string) $resolved[ $src_key ] ) {
				$img->setAttribute( 'src', $resolved[ $src_key ] );
			}
			$alt_key = $img->getAttribute( 'data-aisb-ka' );
			if ( $alt_key && isset( $resolved[ $alt_key ] ) ) {
				$img->setAttribute( 'alt', $resolved[ $alt_key ] );
			}
		}
	}

	private static function apply_zones( DOMDocument $doc, DOMXPath $xpath, $slug ) {
		$applied = false;
		foreach ( AISB_Zones::for_page( $slug ) as $zone ) {
			$query = null;

			// Explicit data-aisb-zone markers win; CSS selectors otherwise.
			if ( ! empty( $zone['selector'] ) && 0 === strpos( $zone['selector'], '@' ) ) {
				$marker = substr( $zone['selector'], 1 );
				$query  = "//*[@data-aisb-zone='" . $marker . "']";
			} elseif ( ! empty( $zone['selector'] ) ) {
				$query = AISB_Zones::selector_to_xpath( $zone['selector'] );
			}
			if ( ! $query ) {
				continue;
			}

			$nodes = @$xpath->query( $query );
			if ( ! $nodes || ! $nodes->length ) {
				continue;
			}
			$rendered = AISB_Zones::render( $zone );
			foreach ( $nodes as $node ) {
				AISB_Parser::set_inner_html( $node, $rendered );
				$applied = true;
			}
		}
		return $applied;
	}

	/**
	 * Freeze the design: remove the SPA's JavaScript so it cannot re-mount
	 * over the imported static markup (and crash on missing backends).
	 * External scripts (analytics etc.) and JSON-LD are kept.
	 */
	private static function strip_design_js( DOMXPath $xpath ) {
		$uploads = wp_upload_dir();
		$marker  = trailingslashit( $uploads['baseurl'] ) . 'aisb-site';

		foreach ( iterator_to_array( $xpath->query( '//script' ) ) as $script ) {
			/** @var DOMElement $script */
			$src  = (string) $script->getAttribute( 'src' );
			$type = strtolower( (string) $script->getAttribute( 'type' ) );
			if ( 'application/ld+json' === $type ) {
				continue;
			}
			$is_app_bundle = ( '' !== $src && false !== strpos( $src, $marker ) ) || 'module' === $type;
			$is_inline     = ( '' === $src );
			if ( $is_app_bundle || $is_inline ) {
				$script->parentNode->removeChild( $script );
			}
		}

		// Script preloads are useless once the scripts are gone.
		foreach ( iterator_to_array( $xpath->query( "//link[@rel='modulepreload' or @rel='preload' or @rel='prefetch']" ) ) as $link ) {
			/** @var DOMElement $link */
			$as   = strtolower( (string) $link->getAttribute( 'as' ) );
			$href = (string) $link->getAttribute( 'href' );
			if ( 'script' === $as || preg_match( '/\.m?js(\?|$)/', $href ) ) {
				$link->parentNode->removeChild( $link );
			}
		}
	}

	/** Prefix internal links with the current language ("/about/" => "/en/about/"). */
	private static function prefix_links( DOMXPath $xpath, $lang ) {
		$known_langs = array_keys( AISB_Plugin::languages() );
		$home_path   = rtrim( (string) wp_parse_url( home_url( '/' ), PHP_URL_PATH ), '/' );

		foreach ( $xpath->query( '//a[@href]' ) as $link ) {
			/** @var DOMElement $link */
			$href = $link->getAttribute( 'href' );
			if ( '' === $href || '#' === $href[0] || preg_match( '#^(https?:)?//|^(mailto:|tel:|javascript:)#i', $href ) ) {
				continue;
			}
			if ( '/' !== $href[0] ) {
				continue;
			}
			$path = $href;
			if ( $home_path && 0 === strpos( $path, $home_path . '/' ) ) {
				$path = substr( $path, strlen( $home_path ) );
			}
			// Skip WP internals, files and already-prefixed links.
			$first = strtok( ltrim( $path, '/' ), '/?#' );
			if ( in_array( $first, $known_langs, true ) || 0 === strpos( (string) $first, 'wp-' ) || false !== strpos( (string) $first, '.' ) ) {
				continue;
			}
			$link->setAttribute( 'href', rtrim( $home_path, '/' ) . '/' . $lang . $path );
		}
	}

	/* ---------------------------------------------------------- injectors */

	private static function append_style( DOMDocument $doc, $css ) {
		$head = $doc->getElementsByTagName( 'head' )->item( 0 );
		if ( ! $head ) {
			return;
		}
		$style = $doc->createElement( 'style' );
		$style->appendChild( $doc->createTextNode( $css ) );
		$head->appendChild( $style );
	}

	private static function append_switcher( DOMDocument $doc, $slug, $current ) {
		$body = $doc->getElementsByTagName( 'body' )->item( 0 );
		if ( ! $body ) {
			return;
		}

		$css = '.aisb-switcher{position:fixed;bottom:18px;right:18px;z-index:99999;display:flex;gap:2px;'
			. 'background:rgba(20,20,20,.85);backdrop-filter:blur(6px);border-radius:2em;padding:4px;'
			. 'font:600 12px/1 system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.25)}'
			. '.aisb-switcher a{color:#fff;text-decoration:none;padding:7px 12px;border-radius:2em;opacity:.65;text-transform:uppercase}'
			. '.aisb-switcher a:hover{opacity:1}'
			. '.aisb-switcher a.on{background:#fff;color:#111;opacity:1}';
		self::append_style( $doc, $css );

		$nav = $doc->createElement( 'nav' );
		$nav->setAttribute( 'class', 'aisb-switcher' );
		$nav->setAttribute( 'aria-label', 'Language' );
		foreach ( AISB_Plugin::languages() as $code => $label ) {
			$a = $doc->createElement( 'a', $code );
			$a->setAttribute( 'href', AISB_Plugin::url_for( $slug, $code ) );
			$a->setAttribute( 'title', $label );
			if ( $code === $current ) {
				$a->setAttribute( 'class', 'on' );
			}
			$nav->appendChild( $a );
		}
		$body->appendChild( $nav );
	}
}
