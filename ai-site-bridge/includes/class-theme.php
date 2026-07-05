<?php
/**
 * Companion theme: generates the "AI Site Bridge Theme" from the imported
 * design so WordPress-served pages (WooCommerce products/cart/checkout,
 * blog posts, search, 404) share the AI builder's look — same header,
 * footer, fonts and CSS.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class AISB_Theme {

	const THEME_SLUG = 'aisb-theme';

	/* ==================================================== chrome capture */

	/**
	 * Extract the design "chrome" (head assets, header, footer, body class)
	 * from the imported front page and store it. Runs after every sync.
	 */
	public static function refresh_chrome() {
		$front = AISB_Store::get_page_by_slug( AISB_Plugin::front_slug() );
		if ( ! $front ) {
			return false;
		}
		$html = get_post_meta( $front->ID, '_aisb_html', true );
		if ( ! $html ) {
			return false;
		}
		$doc = AISB_Parser::load_dom( $html );
		if ( ! $doc ) {
			return false;
		}

		$chrome = array(
			'page_id'    => $front->ID,
			'head'       => self::extract_head_assets( $doc ),
			'header'     => '',
			'footer'     => '',
			'body_class' => '',
		);

		$body = $doc->getElementsByTagName( 'body' )->item( 0 );
		if ( $body ) {
			$chrome['body_class'] = trim( (string) $body->getAttribute( 'class' ) );

			// First <header> in the document, or first <nav> as fallback.
			$header = $doc->getElementsByTagName( 'header' )->item( 0 );
			if ( ! $header ) {
				$nav = $doc->getElementsByTagName( 'nav' )->item( 0 );
				if ( $nav ) {
					$chrome['header'] = '<header>' . $doc->saveHTML( $nav ) . '</header>';
				}
			} else {
				$chrome['header'] = $doc->saveHTML( $header );
			}

			// Last <footer> in the document.
			$footers = $doc->getElementsByTagName( 'footer' );
			if ( $footers->length ) {
				$chrome['footer'] = $doc->saveHTML( $footers->item( $footers->length - 1 ) );
			}
		}

		update_option( 'aisb_chrome', $chrome );
		return true;
	}

	/**
	 * Collect stylesheet links, font links, inline styles and the viewport
	 * meta from the design head. Scripts are intentionally excluded: the
	 * design JS expects the SPA markup and would break WP-generated pages.
	 */
	private static function extract_head_assets( DOMDocument $doc ) {
		$head = $doc->getElementsByTagName( 'head' )->item( 0 );
		if ( ! $head ) {
			return '';
		}
		$out = '';
		foreach ( $head->childNodes as $node ) {
			if ( XML_ELEMENT_NODE !== $node->nodeType ) {
				continue;
			}
			$tag = strtolower( $node->nodeName );
			if ( 'style' === $tag ) {
				$out .= $doc->saveHTML( $node ) . "\n";
			} elseif ( 'link' === $tag ) {
				/** @var DOMElement $node */
				$rel = strtolower( (string) $node->getAttribute( 'rel' ) );
				if ( in_array( $rel, array( 'stylesheet', 'preconnect', 'preload', 'dns-prefetch' ), true ) ) {
					$out .= $doc->saveHTML( $node ) . "\n";
				}
			}
		}
		return $out;
	}

	/* ==================================================== runtime output */

	private static function chrome() {
		$chrome = get_option( 'aisb_chrome' );
		return is_array( $chrome ) ? $chrome : array();
	}

	/** Printed inside <head> by the generated theme. */
	public static function print_head_assets() {
		$chrome = self::chrome();
		if ( ! empty( $chrome['head'] ) ) {
			echo $chrome['head']; // phpcs:ignore WordPress.Security.EscapeOutput -- design-owned markup captured at import.
		}
	}

	public static function print_header() {
		$chrome = self::chrome();
		if ( empty( $chrome['header'] ) ) {
			self::print_fallback_header();
			return;
		}
		echo self::apply_overrides( $chrome['header'], $chrome ); // phpcs:ignore WordPress.Security.EscapeOutput
	}

	public static function print_footer() {
		$chrome = self::chrome();
		if ( empty( $chrome['footer'] ) ) {
			return;
		}
		echo self::apply_overrides( $chrome['footer'], $chrome ); // phpcs:ignore WordPress.Security.EscapeOutput
	}

	/** Design body classes applied on theme pages for consistent styling. */
	public static function body_classes( $classes ) {
		$chrome = self::chrome();
		if ( ! empty( $chrome['body_class'] ) ) {
			foreach ( preg_split( '/\s+/', $chrome['body_class'] ) as $class ) {
				if ( '' !== $class ) {
					$classes[] = sanitize_html_class( $class );
				}
			}
		}
		return $classes;
	}

	/**
	 * Apply content overrides (edited strings, images) to a chrome fragment
	 * so theme pages always show the same texts as the imported pages.
	 */
	private static function apply_overrides( $fragment, array $chrome ) {
		if ( empty( $chrome['page_id'] ) ) {
			return $fragment;
		}
		$default  = AISB_Plugin::default_lang();
		$resolved = AISB_Store::resolve_map( (int) $chrome['page_id'], $default, $default );
		if ( empty( $resolved ) ) {
			return $fragment;
		}

		$doc = AISB_Parser::load_dom( '<div id="aisb-chrome-wrap">' . $fragment . '</div>' );
		if ( ! $doc ) {
			return $fragment;
		}
		$xpath = new DOMXPath( $doc );

		foreach ( $xpath->query( '//*[@data-aisb-k]' ) as $node ) {
			/** @var DOMElement $node */
			$key = $node->getAttribute( 'data-aisb-k' );
			if ( isset( $resolved[ $key ] ) && '' !== (string) $resolved[ $key ] ) {
				AISB_Parser::set_inner_html( $node, wp_kses_post( $resolved[ $key ] ) );
			}
		}
		foreach ( $xpath->query( '//img[@data-aisb-ks or @data-aisb-ka]' ) as $img ) {
			/** @var DOMElement $img */
			$src_key = $img->getAttribute( 'data-aisb-ks' );
			if ( $src_key && ! empty( $resolved[ $src_key ] ) ) {
				$img->setAttribute( 'src', $resolved[ $src_key ] );
			}
			$alt_key = $img->getAttribute( 'data-aisb-ka' );
			if ( $alt_key && isset( $resolved[ $alt_key ] ) ) {
				$img->setAttribute( 'alt', $resolved[ $alt_key ] );
			}
		}

		$wrap = $doc->getElementById( 'aisb-chrome-wrap' );
		if ( ! $wrap ) {
			return $fragment;
		}
		$out = '';
		foreach ( $wrap->childNodes as $child ) {
			$out .= $doc->saveHTML( $child );
		}
		return $out;
	}

	private static function print_fallback_header() {
		echo '<header style="padding:1rem 2rem;display:flex;justify-content:space-between;align-items:center">';
		echo '<a href="' . esc_url( home_url( '/' ) ) . '" style="font-weight:700;text-decoration:none;color:inherit">'
			. esc_html( get_bloginfo( 'name' ) ) . '</a>';
		echo '</header>';
	}

	/* ==================================================== theme generator */

	public static function is_generated() {
		return is_dir( trailingslashit( get_theme_root() ) . self::THEME_SLUG );
	}

	public static function is_active() {
		return get_stylesheet() === self::THEME_SLUG;
	}

	/**
	 * Write (or refresh) the companion theme into wp-content/themes/.
	 *
	 * @return true|WP_Error
	 */
	public static function generate() {
		$dir = trailingslashit( get_theme_root() ) . self::THEME_SLUG;
		if ( ! wp_mkdir_p( $dir ) ) {
			return new WP_Error( 'aisb_theme_dir', sprintf( 'Could not create theme directory: %s', $dir ) );
		}

		$files = self::theme_files();
		foreach ( $files as $name => $contents ) {
			if ( false === file_put_contents( $dir . '/' . $name, $contents ) ) {
				return new WP_Error( 'aisb_theme_write', sprintf( 'Could not write theme file: %s', $name ) );
			}
		}
		return true;
	}

	private static function theme_files() {
		$version = gmdate( 'Y.m.d.Hi' );

		$style = <<<CSS
/*
Theme Name: AI Site Bridge Theme
Description: Companion theme generated by the AI Site Bridge plugin. Wraps WordPress-served pages (WooCommerce, blog, search, 404) in your AI builder design — same header, footer, fonts and styles as the imported site. Regenerated automatically on every design sync.
Version: {$version}
Author: AI Site Bridge
Text Domain: aisb-theme
*/

.aisb-content {
	max-width: 1160px;
	margin: 0 auto;
	padding: 2.5rem 1.25rem 4rem;
}

.aisb-content a {
	color: inherit;
}

.aisb-entry-title {
	font-size: 2rem;
	line-height: 1.2;
	margin: 0 0 1.25rem;
}

.aisb-entry-content > * + * {
	margin-top: 1em;
}

.aisb-entry-content img {
	max-width: 100%;
	height: auto;
}

.aisb-post-list {
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
	gap: 1.5rem;
	list-style: none;
	margin: 0;
	padding: 0;
}

.aisb-post-card {
	display: flex;
	flex-direction: column;
	gap: .5rem;
}

.aisb-post-card img {
	width: 100%;
	height: auto;
	border-radius: .5rem;
}

.aisb-post-card h2 {
	font-size: 1.1rem;
	margin: 0;
}

.aisb-post-card h2 a {
	text-decoration: none;
}

.aisb-post-meta {
	font-size: .85em;
	opacity: .6;
}

/* Keep WooCommerce components on the design's typography. */
.woocommerce,
.woocommerce button.button,
.woocommerce a.button,
.woocommerce input {
	font-family: inherit;
}
CSS;

		$functions = <<<'PHP'
<?php
/**
 * AI Site Bridge Theme — generated by the AI Site Bridge plugin.
 * Safe to run with the plugin deactivated (falls back to a minimal shell).
 */

add_action( 'after_setup_theme', function () {
	add_theme_support( 'title-tag' );
	add_theme_support( 'post-thumbnails' );
	add_theme_support( 'woocommerce' );
	add_theme_support( 'html5', array( 'search-form', 'gallery', 'caption', 'style', 'script' ) );
} );

add_action( 'wp_enqueue_scripts', function () {
	wp_enqueue_style( 'aisb-theme', get_stylesheet_uri(), array(), wp_get_theme()->get( 'Version' ) );
} );

add_filter( 'body_class', function ( $classes ) {
	if ( class_exists( 'AISB_Theme' ) ) {
		$classes = AISB_Theme::body_classes( $classes );
	}
	return $classes;
} );
PHP;

		$header = <<<'PHP'
<!doctype html>
<html <?php language_attributes(); ?>>
<head>
<meta charset="<?php bloginfo( 'charset' ); ?>">
<meta name="viewport" content="width=device-width, initial-scale=1">
<?php
if ( class_exists( 'AISB_Theme' ) ) {
	AISB_Theme::print_head_assets();
}
wp_head();
?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>
<?php
if ( class_exists( 'AISB_Theme' ) ) {
	AISB_Theme::print_header();
} else {
	echo '<header style="padding:1rem 2rem"><a href="' . esc_url( home_url( '/' ) ) . '" style="font-weight:700;text-decoration:none;color:inherit">' . esc_html( get_bloginfo( 'name' ) ) . '</a></header>';
}
?>
<main class="aisb-content">
PHP;

		$footer = <<<'PHP'
</main>
<?php
if ( class_exists( 'AISB_Theme' ) ) {
	AISB_Theme::print_footer();
}
wp_footer();
?>
</body>
</html>
PHP;

		$index = <<<'PHP'
<?php get_header(); ?>

<?php if ( have_posts() ) : ?>
	<?php if ( is_archive() || is_search() ) : ?>
		<h1 class="aisb-entry-title"><?php
			if ( is_search() ) {
				printf( esc_html__( 'Search results for "%s"', 'aisb-theme' ), get_search_query() );
			} else {
				the_archive_title();
			}
		?></h1>
	<?php endif; ?>
	<ul class="aisb-post-list">
		<?php while ( have_posts() ) : the_post(); ?>
			<li class="aisb-post-card">
				<?php if ( has_post_thumbnail() ) : ?>
					<a href="<?php the_permalink(); ?>"><?php the_post_thumbnail( 'medium_large' ); ?></a>
				<?php endif; ?>
				<h2><a href="<?php the_permalink(); ?>"><?php the_title(); ?></a></h2>
				<div class="aisb-post-meta"><?php echo esc_html( get_the_date() ); ?></div>
				<div><?php echo esc_html( wp_trim_words( get_the_excerpt(), 24 ) ); ?></div>
			</li>
		<?php endwhile; ?>
	</ul>
	<?php the_posts_pagination(); ?>
<?php else : ?>
	<p><?php esc_html_e( 'Nothing found.', 'aisb-theme' ); ?></p>
<?php endif; ?>

<?php get_footer(); ?>
PHP;

		$single = <<<'PHP'
<?php get_header(); ?>

<?php while ( have_posts() ) : the_post(); ?>
	<article <?php post_class(); ?>>
		<h1 class="aisb-entry-title"><?php the_title(); ?></h1>
		<div class="aisb-post-meta"><?php echo esc_html( get_the_date() ); ?></div>
		<?php if ( has_post_thumbnail() ) : ?>
			<p><?php the_post_thumbnail( 'large' ); ?></p>
		<?php endif; ?>
		<div class="aisb-entry-content"><?php the_content(); ?></div>
	</article>
	<?php comments_template(); ?>
<?php endwhile; ?>

<?php get_footer(); ?>
PHP;

		$page = <<<'PHP'
<?php get_header(); ?>

<?php while ( have_posts() ) : the_post(); ?>
	<article <?php post_class(); ?>>
		<h1 class="aisb-entry-title"><?php the_title(); ?></h1>
		<div class="aisb-entry-content"><?php the_content(); ?></div>
	</article>
<?php endwhile; ?>

<?php get_footer(); ?>
PHP;

		$notfound = <<<'PHP'
<?php get_header(); ?>

<h1 class="aisb-entry-title"><?php esc_html_e( 'Page not found', 'aisb-theme' ); ?></h1>
<p><?php esc_html_e( 'The page you are looking for does not exist.', 'aisb-theme' ); ?></p>
<p><a href="<?php echo esc_url( home_url( '/' ) ); ?>">&larr; <?php esc_html_e( 'Back to the homepage', 'aisb-theme' ); ?></a></p>

<?php get_footer(); ?>
PHP;

		$woocommerce = <<<'PHP'
<?php get_header(); ?>

<?php woocommerce_content(); ?>

<?php get_footer(); ?>
PHP;

		return array(
			'style.css'       => $style,
			'functions.php'   => $functions,
			'header.php'      => $header,
			'footer.php'      => $footer,
			'index.php'       => $index,
			'single.php'      => $single,
			'page.php'        => $page,
			'archive.php'     => $index,
			'search.php'      => $index,
			'404.php'         => $notfound,
			'woocommerce.php' => $woocommerce,
		);
	}
}
