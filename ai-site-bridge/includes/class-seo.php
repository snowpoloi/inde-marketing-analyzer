<?php
/**
 * SEO: head tag injection for rendered pages and the multilingual sitemap.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class AISB_SEO {

	/**
	 * Inject/replace SEO tags in the document head of a rendered page.
	 *
	 * @param DOMDocument $doc      Parsed page document.
	 * @param WP_Post     $post     Imported page.
	 * @param string      $slug     Routing slug.
	 * @param string      $lang     Current language code.
	 * @param array       $resolved Resolved string map (skey => value).
	 */
	public static function inject_head( DOMDocument $doc, $post, $slug, $lang, array $resolved ) {
		$head = $doc->getElementsByTagName( 'head' )->item( 0 );
		if ( ! $head ) {
			return;
		}

		$title = isset( $resolved[ md5( $slug . '|seo_title' ) ] ) ? $resolved[ md5( $slug . '|seo_title' ) ] : '';
		$desc  = isset( $resolved[ md5( $slug . '|seo_desc' ) ] ) ? $resolved[ md5( $slug . '|seo_desc' ) ] : '';
		$seo   = get_post_meta( $post->ID, '_aisb_seo', true );
		$seo   = is_array( $seo ) ? $seo : array();

		$canonical = AISB_Plugin::url_for( $slug, $lang );

		// <title>
		if ( '' !== $title ) {
			$title_node = $doc->getElementsByTagName( 'title' )->item( 0 );
			if ( ! $title_node ) {
				$title_node = $doc->createElement( 'title' );
				$head->appendChild( $title_node );
			}
			while ( $title_node->firstChild ) {
				$title_node->removeChild( $title_node->firstChild );
			}
			$title_node->appendChild( $doc->createTextNode( $title ) );
		}

		self::set_meta( $doc, $head, 'name', 'description', $desc );
		if ( ! empty( $seo['noindex'] ) ) {
			self::set_meta( $doc, $head, 'name', 'robots', 'noindex, nofollow' );
		}

		// Canonical.
		self::set_link( $doc, $head, 'canonical', $canonical );

		// Open Graph.
		self::set_meta( $doc, $head, 'property', 'og:title', $title );
		self::set_meta( $doc, $head, 'property', 'og:description', $desc );
		self::set_meta( $doc, $head, 'property', 'og:url', $canonical );
		self::set_meta( $doc, $head, 'property', 'og:type', 'website' );
		if ( ! empty( $seo['og_image'] ) ) {
			self::set_meta( $doc, $head, 'property', 'og:image', $seo['og_image'] );
		}

		// hreflang alternates.
		$default = AISB_Plugin::default_lang();
		foreach ( array_keys( AISB_Plugin::languages() ) as $code ) {
			self::add_hreflang( $doc, $head, $code, AISB_Plugin::url_for( $slug, $code ) );
		}
		self::add_hreflang( $doc, $head, 'x-default', AISB_Plugin::url_for( $slug, $default ) );

		// <html lang="">
		$html_el = $doc->getElementsByTagName( 'html' )->item( 0 );
		if ( $html_el ) {
			$html_el->setAttribute( 'lang', $lang );
		}
	}

	private static function set_meta( DOMDocument $doc, DOMNode $head, $attr, $key, $value ) {
		if ( '' === (string) $value ) {
			return;
		}
		foreach ( $doc->getElementsByTagName( 'meta' ) as $meta ) {
			if ( strtolower( (string) $meta->getAttribute( $attr ) ) === $key ) {
				$meta->setAttribute( 'content', $value );
				return;
			}
		}
		$meta = $doc->createElement( 'meta' );
		$meta->setAttribute( $attr, $key );
		$meta->setAttribute( 'content', $value );
		$head->appendChild( $meta );
	}

	private static function set_link( DOMDocument $doc, DOMNode $head, $rel, $href ) {
		foreach ( $doc->getElementsByTagName( 'link' ) as $link ) {
			if ( strtolower( (string) $link->getAttribute( 'rel' ) ) === $rel ) {
				$link->setAttribute( 'href', $href );
				return;
			}
		}
		$link = $doc->createElement( 'link' );
		$link->setAttribute( 'rel', $rel );
		$link->setAttribute( 'href', $href );
		$head->appendChild( $link );
	}

	private static function add_hreflang( DOMDocument $doc, DOMNode $head, $lang, $href ) {
		$link = $doc->createElement( 'link' );
		$link->setAttribute( 'rel', 'alternate' );
		$link->setAttribute( 'hreflang', $lang );
		$link->setAttribute( 'href', $href );
		$head->appendChild( $link );
	}

	/* ------------------------------------------------------------ sitemap */

	public static function maybe_render_sitemap() {
		if ( ! get_query_var( 'aisb_sitemap' ) ) {
			return;
		}
		global $wp_query;
		$wp_query->is_404 = false;
		status_header( 200 );
		header( 'Content-Type: application/xml; charset=utf-8' );

		$languages = array_keys( AISB_Plugin::languages() );
		$default   = AISB_Plugin::default_lang();

		echo '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
		echo '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">' . "\n";

		foreach ( AISB_Store::get_pages() as $page ) {
			$slug = AISB_Store::page_slug( $page->ID );
			if ( ! $slug ) {
				continue;
			}
			$seo = get_post_meta( $page->ID, '_aisb_seo', true );
			if ( is_array( $seo ) && ! empty( $seo['noindex'] ) ) {
				continue;
			}
			$lastmod = get_post_modified_time( 'c', true, $page );

			foreach ( $languages as $lang ) {
				echo "\t<url>\n";
				echo "\t\t<loc>" . esc_url( AISB_Plugin::url_for( $slug, $lang ) ) . "</loc>\n";
				echo "\t\t<lastmod>" . esc_html( $lastmod ) . "</lastmod>\n";
				foreach ( $languages as $alt ) {
					echo "\t\t" . '<xhtml:link rel="alternate" hreflang="' . esc_attr( $alt ) . '" href="'
						. esc_url( AISB_Plugin::url_for( $slug, $alt ) ) . '"/>' . "\n";
				}
				echo "\t\t" . '<xhtml:link rel="alternate" hreflang="x-default" href="'
					. esc_url( AISB_Plugin::url_for( $slug, $default ) ) . '"/>' . "\n";
				echo "\t</url>\n";
			}
		}
		echo '</urlset>';
		exit;
	}
}
