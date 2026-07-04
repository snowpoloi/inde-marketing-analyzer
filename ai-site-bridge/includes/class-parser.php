<?php
/**
 * Static HTML parser: turns a built page from an AI builder into an
 * annotated template with a translatable string catalog.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class AISB_Parser {

	/** Tags whose inner HTML is treated as one translatable string. */
	const TEXT_TAGS = array(
		'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'a', 'button', 'span',
		'figcaption', 'blockquote', 'td', 'th', 'dt', 'dd', 'label', 'legend',
		'summary', 'em', 'strong', 'small', 'cite', 'div',
	);

	/** Child tags that do not disqualify an element from being one string. */
	const INLINE_OK = array(
		'a', 'b', 'i', 'em', 'strong', 'span', 'small', 'sup', 'sub', 'br',
		'u', 'mark', 'code', 'abbr', 'time', 'svg', 'img', 'wbr',
	);

	const MAX_STRING_LENGTH = 5000;

	/**
	 * Parse one page.
	 *
	 * @param string $html           Raw page HTML.
	 * @param string $slug           Routing slug for this page.
	 * @param string $page_dir       Directory of the page inside the build (''=root).
	 * @param string $asset_base_url Public URL of the copied build directory.
	 * @param array  $slug_map       [ source path => slug ] for internal link rewriting.
	 * @param string $front_slug     Slug used as the site front page.
	 *
	 * @return array|WP_Error { html, title, meta_desc, strings: [skey => [context, original]] }
	 */
	public static function parse_page( $html, $slug, $page_dir, $asset_base_url, $slug_map, $front_slug ) {
		$doc = self::load_dom( $html );
		if ( ! $doc ) {
			return new WP_Error( 'aisb_parse', 'Could not parse HTML for page: ' . $slug );
		}

		self::rewrite_urls( $doc, $page_dir, $asset_base_url, $slug_map, $front_slug );

		$strings = array();
		$seen    = array();
		$body    = $doc->getElementsByTagName( 'body' )->item( 0 );
		if ( $body ) {
			self::walk( $body, $doc, $slug, $strings, $seen );
		}

		// SEO defaults from the document head.
		$title = '';
		$nodes = $doc->getElementsByTagName( 'title' );
		if ( $nodes->length ) {
			$title = trim( $nodes->item( 0 )->textContent );
		}
		$meta_desc = '';
		foreach ( $doc->getElementsByTagName( 'meta' ) as $meta ) {
			if ( strtolower( (string) $meta->getAttribute( 'name' ) ) === 'description' ) {
				$meta_desc = trim( (string) $meta->getAttribute( 'content' ) );
				break;
			}
		}

		// SEO strings live in the same catalog so they are translatable too.
		$strings[ md5( $slug . '|seo_title' ) ] = array( 'context' => 'seo_title', 'original' => $title );
		$strings[ md5( $slug . '|seo_desc' ) ]  = array( 'context' => 'seo_desc', 'original' => $meta_desc );

		return array(
			'html'      => self::save_dom( $doc ),
			'title'     => $title,
			'meta_desc' => $meta_desc,
			'strings'   => $strings,
		);
	}

	/* ------------------------------------------------------------ DOM IO */

	public static function load_dom( $html ) {
		if ( '' === trim( (string) $html ) ) {
			return null;
		}
		$doc = new DOMDocument();
		libxml_use_internal_errors( true );
		// The XML prolog forces UTF-8 interpretation; it is stripped on save.
		$loaded = $doc->loadHTML( '<?xml encoding="utf-8"?>' . $html );
		libxml_clear_errors();
		return $loaded ? $doc : null;
	}

	public static function save_dom( DOMDocument $doc ) {
		foreach ( iterator_to_array( $doc->childNodes ) as $node ) {
			if ( XML_PI_NODE === $node->nodeType ) {
				$doc->removeChild( $node );
			}
		}
		return self::decode_multibyte_entities( $doc->saveHTML() );
	}

	/**
	 * saveHTML() entity-encodes every non-ASCII character (&Kappa; ...),
	 * which bloats non-English pages. Decode only entities that resolve to
	 * multibyte characters; ASCII-significant ones (&lt; &amp; ...) stay
	 * encoded so markup cannot be injected.
	 */
	private static function decode_multibyte_entities( $html ) {
		return preg_replace_callback(
			'/&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);/',
			function ( $match ) {
				$decoded = html_entity_decode( $match[0], ENT_QUOTES | ENT_HTML5, 'UTF-8' );
				if ( '' === $decoded || ord( $decoded[0] ) < 128 ) {
					return $match[0];
				}
				return $decoded;
			},
			$html
		);
	}

	public static function inner_html( DOMNode $node ) {
		$html = '';
		foreach ( $node->childNodes as $child ) {
			$html .= $node->ownerDocument->saveHTML( $child );
		}
		return $html;
	}

	public static function set_inner_html( DOMNode $node, $html ) {
		while ( $node->firstChild ) {
			$node->removeChild( $node->firstChild );
		}
		if ( '' === (string) $html ) {
			return;
		}
		$tmp = new DOMDocument();
		libxml_use_internal_errors( true );
		$tmp->loadHTML( '<?xml encoding="utf-8"?><div>' . $html . '</div>' );
		libxml_clear_errors();
		$container = $tmp->getElementsByTagName( 'div' )->item( 0 );
		if ( ! $container ) {
			return;
		}
		foreach ( iterator_to_array( $container->childNodes ) as $child ) {
			$node->appendChild( $node->ownerDocument->importNode( $child, true ) );
		}
	}

	/* --------------------------------------------------- string harvest */

	/**
	 * Depth-first walk. Elements that qualify as "one translatable string"
	 * are annotated with data-aisb-k and not descended into.
	 */
	private static function walk( DOMNode $node, DOMDocument $doc, $slug, array &$strings, array &$seen ) {
		if ( XML_ELEMENT_NODE !== $node->nodeType ) {
			return;
		}
		/** @var DOMElement $node */
		$tag = strtolower( $node->nodeName );

		if ( in_array( $tag, array( 'script', 'style', 'noscript' ), true ) ) {
			return;
		}

		if ( 'img' === $tag ) {
			self::annotate_image( $node, $slug, $strings, $seen );
			return;
		}

		if ( self::is_translatable( $node, $tag ) ) {
			$original = trim( self::inner_html( $node ) );
			if ( '' !== $original && mb_strlen( $original ) <= self::MAX_STRING_LENGTH ) {
				$key = self::make_key( $slug, $tag . '|' . $original, $seen );
				$node->setAttribute( 'data-aisb-k', $key );
				$strings[ $key ] = array( 'context' => 'text', 'original' => $original );
				return; // Do not descend into an annotated element.
			}
		}

		foreach ( iterator_to_array( $node->childNodes ) as $child ) {
			self::walk( $child, $doc, $slug, $strings, $seen );
		}
	}

	private static function annotate_image( DOMElement $img, $slug, array &$strings, array &$seen ) {
		$src = (string) $img->getAttribute( 'src' );
		$alt = (string) $img->getAttribute( 'alt' );

		if ( '' !== $src ) {
			$key = self::make_key( $slug, 'img_src|' . $src, $seen );
			$img->setAttribute( 'data-aisb-ks', $key );
			$strings[ $key ] = array( 'context' => 'img_src', 'original' => $src );
		}
		$key = self::make_key( $slug, 'img_alt|' . $src . '|' . $alt, $seen );
		$img->setAttribute( 'data-aisb-ka', $key );
		$strings[ $key ] = array( 'context' => 'img_alt', 'original' => $alt );
	}

	private static function is_translatable( DOMElement $node, $tag ) {
		if ( ! in_array( $tag, self::TEXT_TAGS, true ) ) {
			return false;
		}
		if ( $node->hasAttribute( 'data-aisb-zone' ) ) {
			return false;
		}

		$has_text = false;
		foreach ( $node->childNodes as $child ) {
			if ( XML_TEXT_NODE === $child->nodeType && '' !== trim( $child->textContent ) ) {
				$has_text = true;
			} elseif ( XML_ELEMENT_NODE === $child->nodeType ) {
				if ( ! in_array( strtolower( $child->nodeName ), self::INLINE_OK, true ) ) {
					return false;
				}
			}
		}
		return $has_text;
	}

	/**
	 * Deterministic string key: identical content across re-imports keeps
	 * its key, so edits and translations survive a design re-sync.
	 */
	private static function make_key( $slug, $material, array &$seen ) {
		$key = md5( $slug . '|' . $material );
		if ( isset( $seen[ $key ] ) ) {
			$seen[ $key ]++;
			$key = md5( $key . '|' . $seen[ $key ] );
		} else {
			$seen[ $key ] = 1;
		}
		return $key;
	}

	/* ------------------------------------------------------ URL rewriting */

	private static function rewrite_urls( DOMDocument $doc, $page_dir, $asset_base_url, $slug_map, $front_slug ) {
		$xpath = new DOMXPath( $doc );
		$nodes = $xpath->query( '//*[@src or @href or @srcset or @poster]' );

		foreach ( $nodes as $node ) {
			/** @var DOMElement $node */
			foreach ( array( 'src', 'href', 'poster' ) as $attr ) {
				if ( ! $node->hasAttribute( $attr ) ) {
					continue;
				}
				$value = $node->getAttribute( $attr );
				$new   = self::rewrite_url( $value, $page_dir, $asset_base_url, $slug_map, $front_slug );
				if ( $new !== $value ) {
					$node->setAttribute( $attr, $new );
				}
			}
			if ( $node->hasAttribute( 'srcset' ) ) {
				$parts = explode( ',', $node->getAttribute( 'srcset' ) );
				foreach ( $parts as $i => $part ) {
					$bits = preg_split( '/\s+/', trim( $part ), 2 );
					if ( empty( $bits[0] ) ) {
						continue;
					}
					$bits[0]     = self::rewrite_url( $bits[0], $page_dir, $asset_base_url, $slug_map, $front_slug );
					$parts[ $i ] = implode( ' ', $bits );
				}
				$node->setAttribute( 'srcset', implode( ', ', $parts ) );
			}
		}
	}

	private static function rewrite_url( $url, $page_dir, $asset_base_url, $slug_map, $front_slug ) {
		$url = trim( (string) $url );
		if ( '' === $url ) {
			return $url;
		}
		// Leave external / special URLs untouched.
		if ( preg_match( '#^(https?:)?//#i', $url ) || preg_match( '#^(mailto:|tel:|data:|javascript:|\#)#i', $url ) ) {
			return $url;
		}

		$path     = $url;
		$suffix   = '';
		$hash_pos = strcspn( $path, '?#' );
		if ( $hash_pos < strlen( $path ) ) {
			$suffix = substr( $path, $hash_pos );
			$path   = substr( $path, 0, $hash_pos );
		}

		$resolved = self::resolve_path( $path, $page_dir );

		// Internal page link?
		$target = self::match_slug( $resolved, $slug_map );
		if ( null !== $target ) {
			$pretty = ( $target === $front_slug ) ? '/' : '/' . trailingslashit( $target );
			return $pretty . $suffix;
		}

		// Everything else is a build asset.
		return rtrim( $asset_base_url, '/' ) . '/' . ltrim( $resolved, '/' ) . $suffix;
	}

	/** Resolve a possibly relative path against the page's directory. */
	private static function resolve_path( $path, $page_dir ) {
		if ( 0 === strpos( $path, '/' ) ) {
			$combined = ltrim( $path, '/' );
		} else {
			$combined = ( '' !== $page_dir ? trailingslashit( $page_dir ) : '' ) . $path;
		}
		$parts = array();
		foreach ( explode( '/', $combined ) as $segment ) {
			if ( '' === $segment || '.' === $segment ) {
				continue;
			}
			if ( '..' === $segment ) {
				array_pop( $parts );
				continue;
			}
			$parts[] = $segment;
		}
		return implode( '/', $parts );
	}

	/** Match a resolved path to an imported page slug, or null. */
	private static function match_slug( $resolved, $slug_map ) {
		$candidates = array( $resolved );
		if ( '' === $resolved ) {
			$candidates[] = 'index.html';
		} else {
			$candidates[] = rtrim( $resolved, '/' ) . '.html';
			$candidates[] = trailingslashit( rtrim( $resolved, '/' ) ) . 'index.html';
		}
		foreach ( $candidates as $candidate ) {
			if ( isset( $slug_map[ $candidate ] ) ) {
				return $slug_map[ $candidate ];
			}
		}
		return null;
	}
}
