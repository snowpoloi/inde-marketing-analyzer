<?php
// Standalone smoke test — run: php tests/test-parser.php (no WordPress needed)
// Standalone smoke test for AISB_Parser + selector_to_xpath (WP functions stubbed).
error_reporting( E_ALL & ~E_DEPRECATED );

define( 'ABSPATH', '/tmp/' );

class WP_Error {
	private $msg;
	public function __construct( $code = '', $msg = '' ) { $this->msg = $msg; }
	public function get_error_message() { return $this->msg; }
}
function is_wp_error( $x ) { return $x instanceof WP_Error; }
function trailingslashit( $s ) { return rtrim( $s, '/' ) . '/'; }

require __DIR__ . '/../includes/class-parser.php';

$html = <<<HTML
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ακμή — Premium Olive Oil</title>
<meta name="description" content="Το καλύτερο ελαιόλαδο.">
<link rel="stylesheet" href="/assets/index-abc123.css">
<script type="module" src="./assets/index-abc123.js"></script>
</head>
<body>
<header>
  <nav>
    <a href="/">Home</a>
    <a href="/about">About us</a>
    <a href="about.html">About (html link)</a>
    <a href="https://instagram.com/x">Instagram</a>
  </nav>
</header>
<main>
  <h1>Premium <strong>Olive Oil</strong></h1>
  <p>Από τα βουνά της Κρήτης, με αγάπη.</p>
  <img src="/assets/hero.jpg" alt="Hero image" srcset="/assets/hero-400.jpg 400w, /assets/hero-800.jpg 800w">
  <section id="products" class="shop-grid">
    <div class="placeholder">Products go here</div>
  </section>
  <button>Buy now</button>
  <button>Buy now</button>
</main>
<script>console.log("do not extract this");</script>
</body>
</html>
HTML;

$slug_map = array( 'index.html' => 'home', 'about.html' => 'about' );
$result   = AISB_Parser::parse_page( $html, 'home', '', 'https://site.test/wp-content/uploads/aisb-site', $slug_map, 'home' );

if ( is_wp_error( $result ) ) {
	fwrite( STDERR, "PARSE FAILED: " . $result->get_error_message() . "\n" );
	exit( 1 );
}

$fail = 0;
function check( $label, $cond ) {
	global $fail;
	echo ( $cond ? 'PASS' : 'FAIL' ) . "  $label\n";
	if ( ! $cond ) { $fail = 1; }
}

$out = $result['html'];
$strings = $result['strings'];
$originals = array_map( function ( $s ) { return $s['original']; }, $strings );
$contexts  = array_map( function ( $s ) { return $s['context']; }, $strings );

check( 'title extracted', 'Ακμή — Premium Olive Oil' === $result['title'] );
check( 'meta description extracted', 'Το καλύτερο ελαιόλαδο.' === $result['meta_desc'] );
check( 'greek paragraph in catalog', in_array( 'Από τα βουνά της Κρήτης, με αγάπη.', $originals, true ) );
check( 'h1 with inline markup is ONE string', in_array( 'Premium <strong>Olive Oil</strong>', $originals, true ) );
check( 'nav link text in catalog', in_array( 'About us', $originals, true ) );
check( 'duplicate "Buy now" gets two distinct keys', 2 === count( array_keys( $originals, 'Buy now', true ) ) );
check( 'img_src entry exists', in_array( 'img_src', $contexts, true ) );
check( 'img_alt entry exists', in_array( 'img_alt', $contexts, true ) );
check( 'seo_title entry exists', in_array( 'seo_title', $contexts, true ) );
check( 'script content NOT extracted', ! in_array( 'console.log("do not extract this");', $originals, true ) );

check( 'css url rewritten to uploads', false !== strpos( $out, 'https://site.test/wp-content/uploads/aisb-site/assets/index-abc123.css' ) );
check( 'relative js url rewritten', false !== strpos( $out, 'https://site.test/wp-content/uploads/aisb-site/assets/index-abc123.js' ) );
check( 'img src rewritten', false !== strpos( $out, 'https://site.test/wp-content/uploads/aisb-site/assets/hero.jpg' ) );
check( 'srcset rewritten', false !== strpos( $out, 'https://site.test/wp-content/uploads/aisb-site/assets/hero-400.jpg 400w' ) );
check( 'link /about -> /about/', false !== strpos( $out, 'href="/about/"' ) );
check( 'link about.html -> /about/', substr_count( $out, 'href="/about/"' ) >= 2 );
check( 'root link stays /', false !== strpos( $out, 'href="/"' ) );
check( 'external link untouched', false !== strpos( $out, 'href="https://instagram.com/x"' ) );
check( 'elements annotated with data-aisb-k', substr_count( $out, 'data-aisb-k=' ) >= 5 );
check( 'greek chars survive round-trip', false !== strpos( $out, 'Κρήτης' ) );
check( 'no xml prolog in output', false === strpos( $out, '<?xml' ) );

// set_inner_html round trip (renderer path)
$doc = AISB_Parser::load_dom( $out );
$xp  = new DOMXPath( $doc );
$node = $xp->query( "//*[@data-aisb-k]" )->item( 0 );
AISB_Parser::set_inner_html( $node, 'Νέο <strong>κείμενο</strong>' );
$round = AISB_Parser::save_dom( $doc );
check( 'set_inner_html applies override with markup', false !== strpos( $round, 'Νέο <strong>κείμενο</strong>' ) );

// selector_to_xpath (zones)
function __( $s, $d = null ) { return $s; }
function esc_html__( $s, $d = null ) { return $s; }
function get_option( $k, $d = false ) { return $d; }
require __DIR__ . '/../includes/class-zones.php';

check( 'selector #products', "//*[@id='products']" === AISB_Zones::selector_to_xpath( '#products' ) );
check( 'selector section.shop-grid', "//section[contains(concat(' ',normalize-space(@class),' '),' shop-grid ')]" === AISB_Zones::selector_to_xpath( 'section.shop-grid' ) );
$q = AISB_Zones::selector_to_xpath( 'main > section#products' );
check( 'selector with child combinator resolves', null !== $q );
$zone_nodes = $xp->query( AISB_Zones::selector_to_xpath( '#products' ) );
check( 'zone selector finds the section in parsed doc', $zone_nodes && 1 === $zone_nodes->length );
AISB_Parser::set_inner_html( $zone_nodes->item( 0 ), '<div class="aisb-zone">PRODUCTS</div>' );
check( 'zone replacement works', false !== strpos( AISB_Parser::save_dom( $doc ), '<div class="aisb-zone">PRODUCTS</div>' ) );

exit( $fail );
