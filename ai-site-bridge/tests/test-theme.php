<?php
// Standalone smoke test for AISB_Theme — run: php tests/test-theme.php (no WordPress needed).
error_reporting( E_ALL & ~E_DEPRECATED );

define( 'ABSPATH', '/tmp/' );

$GLOBALS['opts'] = array();

class WP_Error {
	private $msg;
	public function __construct( $code = '', $msg = '' ) { $this->msg = $msg; }
	public function get_error_message() { return $this->msg; }
}
function is_wp_error( $x ) { return $x instanceof WP_Error; }
function trailingslashit( $s ) { return rtrim( $s, '/' ) . '/'; }
function get_option( $k, $d = false ) { return isset( $GLOBALS['opts'][ $k ] ) ? $GLOBALS['opts'][ $k ] : $d; }
function update_option( $k, $v ) { $GLOBALS['opts'][ $k ] = $v; return true; }
function get_post_meta( $id, $key, $single ) { return $GLOBALS['home_html']; }
function wp_kses_post( $s ) { return $s; }
function esc_url( $s ) { return $s; }
function esc_html( $s ) { return htmlspecialchars( $s, ENT_QUOTES ); }
function sanitize_html_class( $s ) { return preg_replace( '/[^A-Za-z0-9_-]/', '', $s ); }
function home_url( $p = '' ) { return 'https://site.test' . $p; }
function get_bloginfo( $k ) { return 'Test Site'; }
function wp_mkdir_p( $d ) { return is_dir( $d ) || mkdir( $d, 0777, true ); }
function get_theme_root() { return sys_get_temp_dir() . '/aisb-theme-test'; }

class AISB_Plugin {
	const CPT = 'aisb_page';
	public static function front_slug() { return 'home'; }
	public static function default_lang() { return 'en'; }
}
class AISB_Store {
	public static function get_page_by_slug( $slug ) { return (object) array( 'ID' => 1 ); }
	public static function resolve_map( $id, $lang, $default ) { return isset( $GLOBALS['resolved'] ) ? $GLOBALS['resolved'] : array(); }
}

require __DIR__ . '/../includes/class-parser.php';
require __DIR__ . '/../includes/class-theme.php';

$fail = 0;
function check( $label, $cond ) {
	global $fail;
	echo ( $cond ? 'PASS' : 'FAIL' ) . "  $label\n";
	if ( ! $cond ) { $fail = 1; }
}

$key = md5( 'home|brand' );
$GLOBALS['home_html'] = <<<HTML
<!DOCTYPE html>
<html><head>
<title>Home</title>
<link rel="stylesheet" href="https://site.test/wp-content/uploads/aisb-site/assets/index.css">
<link rel="preconnect" href="https://fonts.gstatic.com">
<style>:root{--brand:#123}</style>
<script src="https://site.test/wp-content/uploads/aisb-site/assets/app.js"></script>
</head>
<body class="bg-white antialiased">
<header class="site-head"><nav><span data-aisb-k="{$key}">Ακμή</span><a href="/about/">About</a></nav></header>
<main><p>content</p></main>
<footer class="site-foot"><p>© 2026 Ακμή</p></footer>
</body></html>
HTML;

// --- chrome extraction -------------------------------------------------
check( 'refresh_chrome succeeds', true === AISB_Theme::refresh_chrome() );
$chrome = $GLOBALS['opts']['aisb_chrome'];
check( 'header fragment captured', false !== strpos( $chrome['header'], 'site-head' ) );
check( 'footer fragment captured', false !== strpos( $chrome['footer'], 'site-foot' ) );
check( 'head keeps stylesheet link', false !== strpos( $chrome['head'], 'index.css' ) );
check( 'head keeps preconnect + inline style', false !== strpos( $chrome['head'], 'preconnect' ) && false !== strpos( $chrome['head'], '--brand:#123' ) );
check( 'head excludes scripts', false === strpos( $chrome['head'], 'app.js' ) );
check( 'body class captured', 'bg-white antialiased' === $chrome['body_class'] );

// --- runtime output with overrides --------------------------------------
$GLOBALS['resolved'] = array( $key => 'ΑΚΜΗ <strong>2.0</strong>' );
ob_start();
AISB_Theme::print_header();
$header_out = ob_get_clean();
check( 'header override applied', false !== strpos( $header_out, 'ΑΚΜΗ <strong>2.0</strong>' ) );
check( 'header keeps nav link', false !== strpos( $header_out, 'href="/about/"' ) );

ob_start();
AISB_Theme::print_footer();
$footer_out = ob_get_clean();
check( 'footer rendered with greek intact', false !== strpos( $footer_out, '© 2026 Ακμή' ) );

$classes = AISB_Theme::body_classes( array( 'existing' ) );
check( 'body classes merged', in_array( 'bg-white', $classes, true ) && in_array( 'antialiased', $classes, true ) );

// --- theme generation ---------------------------------------------------
$result = AISB_Theme::generate();
check( 'theme generated', true === $result );
$dir = get_theme_root() . '/' . AISB_Theme::THEME_SLUG;
$expected = array( 'style.css', 'functions.php', 'header.php', 'footer.php', 'index.php', 'single.php', 'page.php', 'archive.php', 'search.php', '404.php', 'woocommerce.php' );
foreach ( $expected as $file ) {
	check( "theme file exists: $file", is_file( "$dir/$file" ) );
}
check( 'style.css has theme header', false !== strpos( file_get_contents( "$dir/style.css" ), 'Theme Name: AI Site Bridge Theme' ) );

// Lint every generated PHP file.
foreach ( glob( "$dir/*.php" ) as $php_file ) {
	exec( 'php -l ' . escapeshellarg( $php_file ) . ' 2>&1', $out_lines, $code );
	check( 'generated file lints: ' . basename( $php_file ), 0 === $code );
}

check( 'is_generated() true after generate', AISB_Theme::is_generated() );

exit( $fail );
