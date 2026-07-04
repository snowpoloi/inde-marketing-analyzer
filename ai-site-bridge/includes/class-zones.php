<?php
/**
 * Dynamic zones: replace a section of the imported design with live
 * WordPress content (WooCommerce products, blog posts).
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class AISB_Zones {

	public static function all() {
		$zones = get_option( 'aisb_zones', array() );
		return is_array( $zones ) ? $zones : array();
	}

	public static function save( array $zone ) {
		$zones = self::all();
		if ( empty( $zone['id'] ) ) {
			$zone['id'] = uniqid( 'z' );
			$zones[]    = $zone;
		} else {
			$found = false;
			foreach ( $zones as $i => $existing ) {
				if ( $existing['id'] === $zone['id'] ) {
					$zones[ $i ] = $zone;
					$found       = true;
					break;
				}
			}
			if ( ! $found ) {
				$zones[] = $zone;
			}
		}
		update_option( 'aisb_zones', array_values( $zones ) );
	}

	public static function delete( $id ) {
		$zones = array_values( array_filter( self::all(), function ( $zone ) use ( $id ) {
			return $zone['id'] !== $id;
		} ) );
		update_option( 'aisb_zones', $zones );
	}

	/** Zones that apply to a given page slug. */
	public static function for_page( $slug ) {
		return array_values( array_filter( self::all(), function ( $zone ) use ( $slug ) {
			return empty( $zone['page'] ) || 'all' === $zone['page'] || $zone['page'] === $slug;
		} ) );
	}

	/* ---------------------------------------------------------- rendering */

	public static function render( array $zone ) {
		$args = isset( $zone['args'] ) && is_array( $zone['args'] ) ? $zone['args'] : array();
		switch ( isset( $zone['type'] ) ? $zone['type'] : '' ) {
			case 'products':
				return self::render_products( $args );
			case 'blog':
				return self::render_blog( $args );
		}
		return '<!-- AISB: unknown zone type -->';
	}

	private static function render_products( array $args ) {
		if ( ! class_exists( 'WooCommerce' ) || ! function_exists( 'wc_get_products' ) ) {
			return '<!-- AISB: WooCommerce is not active -->';
		}

		$limit   = isset( $args['limit'] ) ? max( 1, (int) $args['limit'] ) : 8;
		$columns = isset( $args['columns'] ) ? max( 1, min( 6, (int) $args['columns'] ) ) : 4;

		$query = array(
			'status'  => 'publish',
			'limit'   => $limit,
			'orderby' => ! empty( $args['orderby'] ) ? $args['orderby'] : 'date',
			'order'   => 'DESC',
		);
		if ( ! empty( $args['category'] ) ) {
			$query['category'] = array_map( 'trim', explode( ',', $args['category'] ) );
		}

		$products = wc_get_products( $query );
		if ( empty( $products ) ) {
			return '<div class="aisb-zone aisb-empty">' . esc_html__( 'No products found.', 'ai-site-bridge' ) . '</div>';
		}

		$html = '<div class="aisb-zone aisb-products" style="--aisb-cols:' . (int) $columns . '">';
		foreach ( $products as $product ) {
			/** @var WC_Product $product */
			$link = get_permalink( $product->get_id() );
			$html .= '<div class="aisb-card">';
			$html .= '<a class="aisb-card-media" href="' . esc_url( $link ) . '">' . $product->get_image( 'woocommerce_thumbnail' ) . '</a>';
			$html .= '<a class="aisb-card-title" href="' . esc_url( $link ) . '">' . esc_html( $product->get_name() ) . '</a>';
			$html .= '<div class="aisb-card-price">' . wp_kses_post( $product->get_price_html() ) . '</div>';
			$html .= '<a class="aisb-card-btn" href="' . esc_url( $product->add_to_cart_url() ) . '">' . esc_html( $product->add_to_cart_text() ) . '</a>';
			$html .= '</div>';
		}
		$html .= '</div>';
		return $html;
	}

	private static function render_blog( array $args ) {
		$limit = isset( $args['limit'] ) ? max( 1, (int) $args['limit'] ) : 6;
		$columns = isset( $args['columns'] ) ? max( 1, min( 6, (int) $args['columns'] ) ) : 3;

		$query = new WP_Query( array(
			'post_type'      => 'post',
			'post_status'    => 'publish',
			'posts_per_page' => $limit,
			'category_name'  => ! empty( $args['category'] ) ? $args['category'] : '',
		) );
		if ( ! $query->have_posts() ) {
			return '<div class="aisb-zone aisb-empty">' . esc_html__( 'No posts found.', 'ai-site-bridge' ) . '</div>';
		}

		$html = '<div class="aisb-zone aisb-blog" style="--aisb-cols:' . (int) $columns . '">';
		foreach ( $query->posts as $post ) {
			$link  = get_permalink( $post );
			$thumb = get_the_post_thumbnail( $post, 'medium_large' );
			$html .= '<div class="aisb-card">';
			if ( $thumb ) {
				$html .= '<a class="aisb-card-media" href="' . esc_url( $link ) . '">' . $thumb . '</a>';
			}
			$html .= '<a class="aisb-card-title" href="' . esc_url( $link ) . '">' . esc_html( get_the_title( $post ) ) . '</a>';
			$html .= '<div class="aisb-card-meta">' . esc_html( get_the_date( '', $post ) ) . '</div>';
			$html .= '<div class="aisb-card-excerpt">' . esc_html( wp_trim_words( get_the_excerpt( $post ), 24 ) ) . '</div>';
			$html .= '</div>';
		}
		$html .= '</div>';
		wp_reset_postdata();
		return $html;
	}

	/**
	 * Minimal, design-inheriting CSS injected only on pages with zones.
	 * Fonts and colors are inherited from the imported design.
	 */
	public static function css() {
		return '.aisb-zone{display:grid;grid-template-columns:repeat(var(--aisb-cols,4),1fr);gap:1.5rem;margin:1rem 0}'
			. '@media(max-width:900px){.aisb-zone{grid-template-columns:repeat(2,1fr)}}'
			. '@media(max-width:560px){.aisb-zone{grid-template-columns:1fr}}'
			. '.aisb-card{display:flex;flex-direction:column;gap:.5rem;font:inherit;color:inherit}'
			. '.aisb-card-media img{width:100%;height:auto;display:block;border-radius:.5rem;object-fit:cover}'
			. '.aisb-card-title{font-weight:600;text-decoration:none;color:inherit}'
			. '.aisb-card-price{opacity:.85}'
			. '.aisb-card-meta{font-size:.85em;opacity:.6}'
			. '.aisb-card-excerpt{font-size:.92em;opacity:.8}'
			. '.aisb-card-btn{display:inline-block;align-self:flex-start;padding:.5em 1.1em;border:1px solid currentColor;'
			. 'border-radius:2em;text-decoration:none;color:inherit;font-size:.9em}'
			. '.aisb-card-btn:hover{opacity:.7}'
			. '.aisb-empty{opacity:.6;padding:1rem 0;display:block}';
	}

	/* --------------------------------------------- selector => XPath */

	/**
	 * Convert a simple CSS selector to XPath. Supports tag, #id, .class,
	 * attribute-free compounds ("section.products"), descendant (space)
	 * and child (>) combinators — enough to target sections of a build.
	 */
	public static function selector_to_xpath( $selector ) {
		$selector = trim( (string) $selector );
		if ( '' === $selector ) {
			return null;
		}
		$tokens = preg_split( '/\s+/', str_replace( '>', ' > ', $selector ) );
		$xpath  = '';
		$axis   = '//';

		foreach ( $tokens as $token ) {
			if ( '' === $token ) {
				continue;
			}
			if ( '>' === $token ) {
				$axis = '/';
				continue;
			}
			if ( ! preg_match( '/^([a-zA-Z][\w-]*)?((?:[#.][\w-]+)*)$/', $token, $m ) ) {
				return null; // Unsupported selector syntax.
			}
			$tag        = ! empty( $m[1] ) ? strtolower( $m[1] ) : '*';
			$predicates = '';
			if ( ! empty( $m[2] ) ) {
				preg_match_all( '/([#.])([\w-]+)/', $m[2], $parts, PREG_SET_ORDER );
				foreach ( $parts as $part ) {
					if ( '#' === $part[1] ) {
						$predicates .= "[@id='" . $part[2] . "']";
					} else {
						$predicates .= "[contains(concat(' ',normalize-space(@class),' '),' " . $part[2] . " ')]";
					}
				}
			}
			$xpath .= $axis . $tag . $predicates;
			$axis   = '//';
		}
		return $xpath ? $xpath : null;
	}
}
