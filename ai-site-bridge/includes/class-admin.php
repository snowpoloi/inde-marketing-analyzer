<?php
/**
 * Admin UI: dashboard/sync, content editor, translations, zones, settings.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class AISB_Admin {

	public static function init() {
		add_action( 'admin_menu', array( __CLASS__, 'menu' ) );
		add_action( 'admin_enqueue_scripts', array( __CLASS__, 'assets' ) );

		add_action( 'admin_post_aisb_sync', array( __CLASS__, 'handle_sync' ) );
		add_action( 'admin_post_aisb_save_content', array( __CLASS__, 'handle_save_content' ) );
		add_action( 'admin_post_aisb_save_translations', array( __CLASS__, 'handle_save_translations' ) );
		add_action( 'admin_post_aisb_save_zone', array( __CLASS__, 'handle_save_zone' ) );
		add_action( 'admin_post_aisb_delete_zone', array( __CLASS__, 'handle_delete_zone' ) );
		add_action( 'admin_post_aisb_save_settings', array( __CLASS__, 'handle_save_settings' ) );
		add_action( 'admin_post_aisb_generate_theme', array( __CLASS__, 'handle_generate_theme' ) );
	}

	public static function menu() {
		add_menu_page(
			'AI Site Bridge', 'AI Site Bridge', 'manage_options',
			'aisb', array( __CLASS__, 'page_dashboard' ), 'dashicons-superhero-alt', 58
		);
		add_submenu_page( 'aisb', __( 'Dashboard', 'ai-site-bridge' ), __( 'Dashboard', 'ai-site-bridge' ), 'manage_options', 'aisb', array( __CLASS__, 'page_dashboard' ) );
		add_submenu_page( 'aisb', __( 'Content & SEO', 'ai-site-bridge' ), __( 'Content & SEO', 'ai-site-bridge' ), 'manage_options', 'aisb-content', array( __CLASS__, 'page_content' ) );
		add_submenu_page( 'aisb', __( 'Translations', 'ai-site-bridge' ), __( 'Translations', 'ai-site-bridge' ), 'manage_options', 'aisb-translations', array( __CLASS__, 'page_translations' ) );
		add_submenu_page( 'aisb', __( 'Zones', 'ai-site-bridge' ), __( 'Zones', 'ai-site-bridge' ), 'manage_options', 'aisb-zones', array( __CLASS__, 'page_zones' ) );
		add_submenu_page( 'aisb', __( 'Settings', 'ai-site-bridge' ), __( 'Settings', 'ai-site-bridge' ), 'manage_options', 'aisb-settings', array( __CLASS__, 'page_settings' ) );
	}

	public static function assets( $hook ) {
		if ( false === strpos( $hook, 'aisb' ) ) {
			return;
		}
		wp_enqueue_style( 'aisb-admin', AISB_URL . 'admin/css/admin.css', array(), AISB_VERSION );
	}

	/* ------------------------------------------------------------ helpers */

	private static function guard() {
		if ( ! current_user_can( 'manage_options' ) ) {
			wp_die( esc_html__( 'Insufficient permissions.', 'ai-site-bridge' ) );
		}
	}

	private static function redirect( $page, array $extra = array() ) {
		$url = add_query_arg( array_merge( array( 'page' => $page ), $extra ), admin_url( 'admin.php' ) );
		wp_safe_redirect( $url );
		exit;
	}

	private static function notice() {
		if ( ! empty( $_GET['aisb_msg'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification
			printf(
				'<div class="notice notice-%s is-dismissible"><p>%s</p></div>',
				! empty( $_GET['aisb_err'] ) ? 'error' : 'success', // phpcs:ignore
				esc_html( sanitize_text_field( wp_unslash( $_GET['aisb_msg'] ) ) ) // phpcs:ignore
			);
		}
	}

	private static function context_label( $context ) {
		$labels = array(
			'text'      => __( 'Text', 'ai-site-bridge' ),
			'img_src'   => __( 'Image URL', 'ai-site-bridge' ),
			'img_alt'   => __( 'Image alt', 'ai-site-bridge' ),
			'seo_title' => __( 'SEO title', 'ai-site-bridge' ),
			'seo_desc'  => __( 'SEO description', 'ai-site-bridge' ),
		);
		return isset( $labels[ $context ] ) ? $labels[ $context ] : $context;
	}

	/* -------------------------------------------------------- dashboard */

	public static function page_dashboard() {
		self::guard();
		$settings  = AISB_Plugin::settings();
		$last_sync = get_option( 'aisb_last_sync' );
		$pages     = AISB_Store::get_pages();
		?>
		<div class="wrap aisb-wrap">
			<h1>AI Site Bridge</h1>
			<?php self::notice(); ?>
			<p class="description">
				<?php esc_html_e( 'Design in your AI builder (Lovable, Bolt, v0, ...) — manage content, SEO, translations and WooCommerce from WordPress.', 'ai-site-bridge' ); ?>
			</p>

			<div class="aisb-cards">
				<div class="aisb-panel">
					<h2><?php esc_html_e( 'GitHub Sync', 'ai-site-bridge' ); ?></h2>
					<?php if ( empty( $settings['github_repo'] ) ) : ?>
						<p><?php esc_html_e( 'No repository configured yet.', 'ai-site-bridge' ); ?>
							<a href="<?php echo esc_url( admin_url( 'admin.php?page=aisb-settings' ) ); ?>"><?php esc_html_e( 'Open Settings', 'ai-site-bridge' ); ?></a></p>
					<?php else : ?>
						<p><strong><?php echo esc_html( $settings['github_repo'] ); ?></strong>
							@ <code><?php echo esc_html( $settings['github_branch'] ); ?></code></p>
						<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
							<input type="hidden" name="action" value="aisb_sync">
							<?php wp_nonce_field( 'aisb_sync' ); ?>
							<?php submit_button( __( 'Sync now', 'ai-site-bridge' ), 'primary', 'submit', false ); ?>
						</form>
					<?php endif; ?>
					<?php if ( is_array( $last_sync ) ) : ?>
						<p class="description">
							<?php
							printf(
								/* translators: 1: datetime, 2: page count */
								esc_html__( 'Last sync: %1$s — %2$d pages imported.', 'ai-site-bridge' ),
								esc_html( $last_sync['time'] ),
								isset( $last_sync['report']['count'] ) ? (int) $last_sync['report']['count'] : 0
							);
							?>
						</p>
					<?php endif; ?>
				</div>

				<div class="aisb-panel">
					<h2><?php esc_html_e( 'Companion theme', 'ai-site-bridge' ); ?></h2>
					<p class="description"><?php esc_html_e( 'Generates a WordPress theme from your imported design (same header, footer, fonts and CSS) so WooCommerce pages, blog posts, search and 404 match the rest of the site.', 'ai-site-bridge' ); ?></p>
					<?php if ( ! AISB_Theme::is_generated() ) : ?>
						<p><em><?php esc_html_e( 'Not generated yet.', 'ai-site-bridge' ); ?></em></p>
					<?php elseif ( AISB_Theme::is_active() ) : ?>
						<p><strong style="color:#1d6f42">&#10003; <?php esc_html_e( 'Generated and active.', 'ai-site-bridge' ); ?></strong></p>
					<?php else : ?>
						<p><strong><?php esc_html_e( 'Generated, but not active.', 'ai-site-bridge' ); ?></strong>
							<a href="<?php echo esc_url( admin_url( 'themes.php' ) ); ?>"><?php esc_html_e( 'Activate it in Appearance → Themes.', 'ai-site-bridge' ); ?></a></p>
					<?php endif; ?>
					<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
						<input type="hidden" name="action" value="aisb_generate_theme">
						<?php wp_nonce_field( 'aisb_generate_theme' ); ?>
						<?php submit_button( AISB_Theme::is_generated() ? __( 'Regenerate theme', 'ai-site-bridge' ) : __( 'Generate theme', 'ai-site-bridge' ), 'secondary', 'submit', false, empty( $pages ) ? array( 'disabled' => 'disabled' ) : array() ); ?>
					</form>
					<?php if ( empty( $pages ) ) : ?>
						<p class="description"><?php esc_html_e( 'Run a sync first — the theme is built from the imported design.', 'ai-site-bridge' ); ?></p>
					<?php endif; ?>
				</div>

				<div class="aisb-panel">
					<h2><?php esc_html_e( 'Auto-sync webhook', 'ai-site-bridge' ); ?></h2>
					<p class="description"><?php esc_html_e( 'Add this as a GitHub webhook (content type: application/json, secret below) to re-import automatically on every push.', 'ai-site-bridge' ); ?></p>
					<code class="aisb-code"><?php echo esc_html( rest_url( 'aisb/v1/sync' ) ); ?></code>
					<p><strong><?php esc_html_e( 'Secret:', 'ai-site-bridge' ); ?></strong>
						<code><?php echo esc_html( $settings['webhook_secret'] ); ?></code></p>
				</div>
			</div>

			<h2><?php esc_html_e( 'Imported pages', 'ai-site-bridge' ); ?></h2>
			<?php if ( empty( $pages ) ) : ?>
				<p><?php esc_html_e( 'Nothing imported yet. Configure GitHub sync in Settings and press "Sync now".', 'ai-site-bridge' ); ?></p>
			<?php else : ?>
				<table class="widefat striped aisb-table">
					<thead><tr>
						<th><?php esc_html_e( 'Page', 'ai-site-bridge' ); ?></th>
						<th><?php esc_html_e( 'Slug', 'ai-site-bridge' ); ?></th>
						<th><?php esc_html_e( 'URL', 'ai-site-bridge' ); ?></th>
						<th></th>
					</tr></thead>
					<tbody>
					<?php foreach ( $pages as $page ) :
						$slug = AISB_Store::page_slug( $page->ID );
						$url  = AISB_Plugin::url_for( $slug );
						?>
						<tr>
							<td><strong><?php echo esc_html( $page->post_title ); ?></strong></td>
							<td><code><?php echo esc_html( $slug ); ?></code></td>
							<td><a href="<?php echo esc_url( $url ); ?>" target="_blank"><?php echo esc_html( $url ); ?></a></td>
							<td><a class="button button-small" href="<?php echo esc_url( add_query_arg( array( 'page' => 'aisb-content', 'aisb_pid' => $page->ID ), admin_url( 'admin.php' ) ) ); ?>"><?php esc_html_e( 'Edit content', 'ai-site-bridge' ); ?></a></td>
						</tr>
					<?php endforeach; ?>
					</tbody>
				</table>
				<p class="description">
					<?php esc_html_e( 'Sitemap:', 'ai-site-bridge' ); ?>
					<a href="<?php echo esc_url( home_url( '/aisb-sitemap.xml' ) ); ?>" target="_blank"><?php echo esc_html( home_url( '/aisb-sitemap.xml' ) ); ?></a>
				</p>
			<?php endif; ?>
		</div>
		<?php
	}

	public static function handle_sync() {
		self::guard();
		check_admin_referer( 'aisb_sync' );
		$result = AISB_Importer::sync();
		if ( is_wp_error( $result ) ) {
			self::redirect( 'aisb', array( 'aisb_msg' => $result->get_error_message(), 'aisb_err' => 1 ) );
		}
		$msg = sprintf( __( 'Sync complete: %d pages imported.', 'ai-site-bridge' ), (int) $result['count'] );
		if ( ! empty( $result['errors'] ) ) {
			$msg .= ' ' . __( 'Some pages failed:', 'ai-site-bridge' ) . ' ' . implode( '; ', $result['errors'] );
		}
		self::redirect( 'aisb', array( 'aisb_msg' => $msg ) );
	}

	public static function handle_generate_theme() {
		self::guard();
		check_admin_referer( 'aisb_generate_theme' );

		if ( ! AISB_Theme::refresh_chrome() ) {
			self::redirect( 'aisb', array(
				'aisb_msg' => __( 'Could not read the imported front page — run a sync first.', 'ai-site-bridge' ),
				'aisb_err' => 1,
			) );
		}
		$result = AISB_Theme::generate();
		if ( is_wp_error( $result ) ) {
			self::redirect( 'aisb', array( 'aisb_msg' => $result->get_error_message(), 'aisb_err' => 1 ) );
		}
		$msg = AISB_Theme::is_active()
			? __( 'Theme regenerated from the current design.', 'ai-site-bridge' )
			: __( 'Theme generated. Activate "AI Site Bridge Theme" in Appearance → Themes.', 'ai-site-bridge' );
		self::redirect( 'aisb', array( 'aisb_msg' => $msg ) );
	}

	/* ---------------------------------------------------- content & SEO */

	public static function page_content() {
		self::guard();
		$pid = isset( $_GET['aisb_pid'] ) ? (int) $_GET['aisb_pid'] : 0; // phpcs:ignore
		?>
		<div class="wrap aisb-wrap">
			<h1><?php esc_html_e( 'Content & SEO', 'ai-site-bridge' ); ?></h1>
			<?php self::notice(); ?>
			<?php
			if ( $pid ) {
				self::render_content_editor( $pid );
			} else {
				self::render_page_picker( 'aisb-content' );
			}
			?>
		</div>
		<?php
	}

	private static function render_page_picker( $target_page ) {
		$pages = AISB_Store::get_pages();
		if ( empty( $pages ) ) {
			echo '<p>' . esc_html__( 'No imported pages yet — run a sync first.', 'ai-site-bridge' ) . '</p>';
			return;
		}
		echo '<div class="aisb-picker">';
		foreach ( $pages as $page ) {
			$url = add_query_arg( array( 'page' => $target_page, 'aisb_pid' => $page->ID ), admin_url( 'admin.php' ) );
			printf(
				'<a class="aisb-pick" href="%s"><strong>%s</strong><span>/%s</span></a>',
				esc_url( $url ),
				esc_html( $page->post_title ),
				esc_html( AISB_Store::page_slug( $page->ID ) )
			);
		}
		echo '</div>';
	}

	private static function render_content_editor( $pid ) {
		$post = get_post( $pid );
		if ( ! $post || AISB_Plugin::CPT !== $post->post_type ) {
			echo '<p>' . esc_html__( 'Page not found.', 'ai-site-bridge' ) . '</p>';
			return;
		}
		$strings = AISB_Store::get_strings( $pid );
		$seo     = get_post_meta( $pid, '_aisb_seo', true );
		$seo     = is_array( $seo ) ? $seo : array( 'og_image' => '', 'noindex' => 0 );
		$slug    = AISB_Store::page_slug( $pid );
		?>
		<p>
			<a href="<?php echo esc_url( admin_url( 'admin.php?page=aisb-content' ) ); ?>">&larr; <?php esc_html_e( 'All pages', 'ai-site-bridge' ); ?></a>
			&nbsp;|&nbsp; <strong><?php echo esc_html( $post->post_title ); ?></strong> (<code>/<?php echo esc_html( $slug ); ?></code>)
			&nbsp;|&nbsp; <a href="<?php echo esc_url( AISB_Plugin::url_for( $slug ) ); ?>" target="_blank"><?php esc_html_e( 'View page', 'ai-site-bridge' ); ?></a>
		</p>
		<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
			<input type="hidden" name="action" value="aisb_save_content">
			<input type="hidden" name="pid" value="<?php echo (int) $pid; ?>">
			<?php wp_nonce_field( 'aisb_save_content_' . $pid ); ?>

			<h2><?php esc_html_e( 'SEO extras', 'ai-site-bridge' ); ?></h2>
			<table class="form-table">
				<tr>
					<th><?php esc_html_e( 'Open Graph image URL', 'ai-site-bridge' ); ?></th>
					<td><input type="url" class="regular-text" name="og_image" value="<?php echo esc_attr( $seo['og_image'] ); ?>"></td>
				</tr>
				<tr>
					<th><?php esc_html_e( 'Hide from search engines', 'ai-site-bridge' ); ?></th>
					<td><label><input type="checkbox" name="noindex" value="1" <?php checked( ! empty( $seo['noindex'] ) ); ?>> <?php esc_html_e( 'noindex, nofollow', 'ai-site-bridge' ); ?></label></td>
				</tr>
			</table>
			<p class="description"><?php esc_html_e( 'SEO title and meta description are edited below with the rest of the content (and can be translated per language).', 'ai-site-bridge' ); ?></p>

			<h2><?php esc_html_e( 'Content', 'ai-site-bridge' ); ?></h2>
			<?php if ( empty( $strings ) ) : ?>
				<p><?php esc_html_e( 'No editable strings were detected on this page.', 'ai-site-bridge' ); ?></p>
			<?php else : ?>
				<table class="widefat striped aisb-table aisb-strings">
					<thead><tr>
						<th class="aisb-col-ctx"><?php esc_html_e( 'Type', 'ai-site-bridge' ); ?></th>
						<th><?php esc_html_e( 'Original (from design)', 'ai-site-bridge' ); ?></th>
						<th><?php esc_html_e( 'Override (leave empty to keep original)', 'ai-site-bridge' ); ?></th>
					</tr></thead>
					<tbody>
					<?php foreach ( $strings as $row ) : ?>
						<tr>
							<td><span class="aisb-ctx aisb-ctx-<?php echo esc_attr( $row->context ); ?>"><?php echo esc_html( self::context_label( $row->context ) ); ?></span></td>
							<td class="aisb-original"><?php echo esc_html( wp_html_excerpt( (string) $row->original, 400, '…' ) ); ?></td>
							<td><textarea name="s[<?php echo (int) $row->id; ?>]" rows="2"><?php echo esc_textarea( (string) $row->edited ); ?></textarea></td>
						</tr>
					<?php endforeach; ?>
					</tbody>
				</table>
			<?php endif; ?>
			<?php submit_button( __( 'Save content', 'ai-site-bridge' ) ); ?>
		</form>
		<?php
	}

	public static function handle_save_content() {
		self::guard();
		$pid = isset( $_POST['pid'] ) ? (int) $_POST['pid'] : 0;
		check_admin_referer( 'aisb_save_content_' . $pid );

		$seo = array(
			'og_image' => isset( $_POST['og_image'] ) ? esc_url_raw( wp_unslash( $_POST['og_image'] ) ) : '',
			'noindex'  => empty( $_POST['noindex'] ) ? 0 : 1,
		);
		update_post_meta( $pid, '_aisb_seo', $seo );

		if ( isset( $_POST['s'] ) && is_array( $_POST['s'] ) ) {
			foreach ( wp_unslash( $_POST['s'] ) as $string_id => $value ) { // phpcs:ignore
				AISB_Store::save_edit( (int) $string_id, wp_kses_post( trim( (string) $value ) ) );
			}
		}
		self::redirect( 'aisb-content', array( 'aisb_pid' => $pid, 'aisb_msg' => __( 'Content saved.', 'ai-site-bridge' ) ) );
	}

	/* ------------------------------------------------------ translations */

	public static function page_translations() {
		self::guard();
		$extra = AISB_Plugin::extra_langs();
		$pid   = isset( $_GET['aisb_pid'] ) ? (int) $_GET['aisb_pid'] : 0; // phpcs:ignore
		$lang  = isset( $_GET['aisb_lang'] ) ? sanitize_text_field( wp_unslash( $_GET['aisb_lang'] ) ) : ''; // phpcs:ignore
		if ( ! in_array( $lang, $extra, true ) ) {
			$lang = $extra ? $extra[0] : '';
		}
		?>
		<div class="wrap aisb-wrap">
			<h1><?php esc_html_e( 'Translations', 'ai-site-bridge' ); ?></h1>
			<?php self::notice(); ?>

			<?php if ( ! $extra ) : ?>
				<p>
					<?php esc_html_e( 'Only the default language is configured.', 'ai-site-bridge' ); ?>
					<a href="<?php echo esc_url( admin_url( 'admin.php?page=aisb-settings' ) ); ?>"><?php esc_html_e( 'Add languages in Settings.', 'ai-site-bridge' ); ?></a>
				</p>
			<?php elseif ( ! $pid ) : ?>
				<?php self::render_page_picker( 'aisb-translations' ); ?>
			<?php else :
				$post = get_post( $pid );
				if ( ! $post || AISB_Plugin::CPT !== $post->post_type ) {
					echo '<p>' . esc_html__( 'Page not found.', 'ai-site-bridge' ) . '</p>';
					echo '</div>';
					return;
				}
				$strings      = AISB_Store::get_strings( $pid );
				$translations = AISB_Store::get_translations( $pid, $lang );
				$languages    = AISB_Plugin::languages();
				?>
				<p>
					<a href="<?php echo esc_url( admin_url( 'admin.php?page=aisb-translations' ) ); ?>">&larr; <?php esc_html_e( 'All pages', 'ai-site-bridge' ); ?></a>
					&nbsp;|&nbsp; <strong><?php echo esc_html( $post->post_title ); ?></strong>
				</p>
				<p class="aisb-langtabs">
					<?php foreach ( $extra as $code ) :
						$url = add_query_arg( array( 'page' => 'aisb-translations', 'aisb_pid' => $pid, 'aisb_lang' => $code ), admin_url( 'admin.php' ) );
						?>
						<a class="button <?php echo $code === $lang ? 'button-primary' : ''; ?>" href="<?php echo esc_url( $url ); ?>">
							<?php echo esc_html( isset( $languages[ $code ] ) ? $languages[ $code ] : $code ); ?>
						</a>
					<?php endforeach; ?>
				</p>

				<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
					<input type="hidden" name="action" value="aisb_save_translations">
					<input type="hidden" name="pid" value="<?php echo (int) $pid; ?>">
					<input type="hidden" name="lang" value="<?php echo esc_attr( $lang ); ?>">
					<?php wp_nonce_field( 'aisb_save_translations_' . $pid ); ?>

					<table class="widefat striped aisb-table aisb-strings">
						<thead><tr>
							<th class="aisb-col-ctx"><?php esc_html_e( 'Type', 'ai-site-bridge' ); ?></th>
							<th><?php esc_html_e( 'Source', 'ai-site-bridge' ); ?></th>
							<th><?php echo esc_html( sprintf( __( 'Translation (%s)', 'ai-site-bridge' ), $lang ) ); ?></th>
						</tr></thead>
						<tbody>
						<?php foreach ( $strings as $row ) :
							if ( 'img_src' === $row->context ) {
								continue; // Image files usually stay identical across languages.
							}
							$source = null !== $row->edited ? $row->edited : $row->original;
							$value  = isset( $translations[ (int) $row->id ] ) ? $translations[ (int) $row->id ] : '';
							?>
							<tr>
								<td><span class="aisb-ctx aisb-ctx-<?php echo esc_attr( $row->context ); ?>"><?php echo esc_html( self::context_label( $row->context ) ); ?></span></td>
								<td class="aisb-original"><?php echo esc_html( wp_html_excerpt( (string) $source, 400, '…' ) ); ?></td>
								<td><textarea name="t[<?php echo (int) $row->id; ?>]" rows="2"><?php echo esc_textarea( $value ); ?></textarea></td>
							</tr>
						<?php endforeach; ?>
						</tbody>
					</table>
					<?php submit_button( __( 'Save translations', 'ai-site-bridge' ) ); ?>
				</form>
			<?php endif; ?>
		</div>
		<?php
	}

	public static function handle_save_translations() {
		self::guard();
		$pid = isset( $_POST['pid'] ) ? (int) $_POST['pid'] : 0;
		check_admin_referer( 'aisb_save_translations_' . $pid );

		$lang = isset( $_POST['lang'] ) ? sanitize_text_field( wp_unslash( $_POST['lang'] ) ) : '';
		if ( in_array( $lang, AISB_Plugin::extra_langs(), true ) && isset( $_POST['t'] ) && is_array( $_POST['t'] ) ) {
			foreach ( wp_unslash( $_POST['t'] ) as $string_id => $value ) { // phpcs:ignore
				AISB_Store::save_translation( (int) $string_id, $lang, wp_kses_post( trim( (string) $value ) ) );
			}
		}
		self::redirect( 'aisb-translations', array(
			'aisb_pid'  => $pid,
			'aisb_lang' => $lang,
			'aisb_msg'  => __( 'Translations saved.', 'ai-site-bridge' ),
		) );
	}

	/* ------------------------------------------------------------- zones */

	public static function page_zones() {
		self::guard();
		$zones = AISB_Zones::all();
		$pages = AISB_Store::get_pages();
		$edit_id = isset( $_GET['aisb_zone'] ) ? sanitize_text_field( wp_unslash( $_GET['aisb_zone'] ) ) : ''; // phpcs:ignore
		$editing = array( 'id' => '', 'page' => 'all', 'selector' => '', 'type' => 'products', 'args' => array( 'limit' => 8, 'columns' => 4, 'category' => '', 'orderby' => 'date' ) );
		foreach ( $zones as $zone ) {
			if ( $zone['id'] === $edit_id ) {
				$editing = wp_parse_args( $zone, $editing );
				$editing['args'] = wp_parse_args( (array) $editing['args'], array( 'limit' => 8, 'columns' => 4, 'category' => '', 'orderby' => 'date' ) );
			}
		}
		?>
		<div class="wrap aisb-wrap">
			<h1><?php esc_html_e( 'Dynamic Zones', 'ai-site-bridge' ); ?></h1>
			<?php self::notice(); ?>
			<p class="description">
				<?php esc_html_e( 'A zone replaces part of the imported design with live WordPress content — WooCommerce products or blog posts. Target it with a CSS selector (e.g. "#products", "section.shop-grid") or with "@name" if the element in your AI builder carries data-aisb-zone="name".', 'ai-site-bridge' ); ?>
			</p>

			<div class="aisb-cards">
				<div class="aisb-panel">
					<h2><?php echo $editing['id'] ? esc_html__( 'Edit zone', 'ai-site-bridge' ) : esc_html__( 'Add zone', 'ai-site-bridge' ); ?></h2>
					<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
						<input type="hidden" name="action" value="aisb_save_zone">
						<input type="hidden" name="zone_id" value="<?php echo esc_attr( $editing['id'] ); ?>">
						<?php wp_nonce_field( 'aisb_save_zone' ); ?>
						<table class="form-table">
							<tr>
								<th><?php esc_html_e( 'Page', 'ai-site-bridge' ); ?></th>
								<td>
									<select name="zone_page">
										<option value="all" <?php selected( $editing['page'], 'all' ); ?>><?php esc_html_e( 'All pages', 'ai-site-bridge' ); ?></option>
										<?php foreach ( $pages as $page ) :
											$slug = AISB_Store::page_slug( $page->ID ); ?>
											<option value="<?php echo esc_attr( $slug ); ?>" <?php selected( $editing['page'], $slug ); ?>>/<?php echo esc_html( $slug ); ?></option>
										<?php endforeach; ?>
									</select>
								</td>
							</tr>
							<tr>
								<th><?php esc_html_e( 'Selector', 'ai-site-bridge' ); ?></th>
								<td>
									<input type="text" class="regular-text" name="zone_selector" value="<?php echo esc_attr( $editing['selector'] ); ?>" placeholder="#products, section.shop, @products">
								</td>
							</tr>
							<tr>
								<th><?php esc_html_e( 'Type', 'ai-site-bridge' ); ?></th>
								<td>
									<select name="zone_type">
										<option value="products" <?php selected( $editing['type'], 'products' ); ?>><?php esc_html_e( 'WooCommerce products', 'ai-site-bridge' ); ?></option>
										<option value="blog" <?php selected( $editing['type'], 'blog' ); ?>><?php esc_html_e( 'Blog posts', 'ai-site-bridge' ); ?></option>
									</select>
								</td>
							</tr>
							<tr>
								<th><?php esc_html_e( 'Items / Columns', 'ai-site-bridge' ); ?></th>
								<td>
									<input type="number" name="zone_limit" min="1" max="48" value="<?php echo (int) $editing['args']['limit']; ?>" class="small-text">
									/
									<input type="number" name="zone_columns" min="1" max="6" value="<?php echo (int) $editing['args']['columns']; ?>" class="small-text">
								</td>
							</tr>
							<tr>
								<th><?php esc_html_e( 'Category (slug)', 'ai-site-bridge' ); ?></th>
								<td><input type="text" class="regular-text" name="zone_category" value="<?php echo esc_attr( $editing['args']['category'] ); ?>"></td>
							</tr>
							<tr>
								<th><?php esc_html_e( 'Order by', 'ai-site-bridge' ); ?></th>
								<td>
									<select name="zone_orderby">
										<?php foreach ( array( 'date', 'title', 'price', 'popularity', 'rand' ) as $orderby ) : ?>
											<option value="<?php echo esc_attr( $orderby ); ?>" <?php selected( $editing['args']['orderby'], $orderby ); ?>><?php echo esc_html( $orderby ); ?></option>
										<?php endforeach; ?>
									</select>
								</td>
							</tr>
						</table>
						<?php submit_button( $editing['id'] ? __( 'Update zone', 'ai-site-bridge' ) : __( 'Add zone', 'ai-site-bridge' ) ); ?>
					</form>
				</div>

				<div class="aisb-panel">
					<h2><?php esc_html_e( 'Configured zones', 'ai-site-bridge' ); ?></h2>
					<?php if ( empty( $zones ) ) : ?>
						<p><?php esc_html_e( 'No zones yet.', 'ai-site-bridge' ); ?></p>
					<?php else : ?>
						<table class="widefat striped">
							<thead><tr>
								<th><?php esc_html_e( 'Page', 'ai-site-bridge' ); ?></th>
								<th><?php esc_html_e( 'Selector', 'ai-site-bridge' ); ?></th>
								<th><?php esc_html_e( 'Type', 'ai-site-bridge' ); ?></th>
								<th></th>
							</tr></thead>
							<tbody>
							<?php foreach ( $zones as $zone ) : ?>
								<tr>
									<td><code><?php echo esc_html( $zone['page'] ); ?></code></td>
									<td><code><?php echo esc_html( $zone['selector'] ); ?></code></td>
									<td><?php echo esc_html( $zone['type'] ); ?></td>
									<td>
										<a class="button button-small" href="<?php echo esc_url( add_query_arg( array( 'page' => 'aisb-zones', 'aisb_zone' => $zone['id'] ), admin_url( 'admin.php' ) ) ); ?>"><?php esc_html_e( 'Edit', 'ai-site-bridge' ); ?></a>
										<a class="button button-small" href="<?php echo esc_url( wp_nonce_url( add_query_arg( array( 'action' => 'aisb_delete_zone', 'zone_id' => $zone['id'] ), admin_url( 'admin-post.php' ) ), 'aisb_delete_zone' ) ); ?>"
											onclick="return confirm('<?php echo esc_js( __( 'Delete this zone?', 'ai-site-bridge' ) ); ?>')"><?php esc_html_e( 'Delete', 'ai-site-bridge' ); ?></a>
									</td>
								</tr>
							<?php endforeach; ?>
							</tbody>
						</table>
					<?php endif; ?>
				</div>
			</div>
		</div>
		<?php
	}

	public static function handle_save_zone() {
		self::guard();
		check_admin_referer( 'aisb_save_zone' );
		AISB_Zones::save( array(
			'id'       => isset( $_POST['zone_id'] ) ? sanitize_text_field( wp_unslash( $_POST['zone_id'] ) ) : '',
			'page'     => isset( $_POST['zone_page'] ) ? sanitize_text_field( wp_unslash( $_POST['zone_page'] ) ) : 'all',
			'selector' => isset( $_POST['zone_selector'] ) ? sanitize_text_field( wp_unslash( $_POST['zone_selector'] ) ) : '',
			'type'     => ( isset( $_POST['zone_type'] ) && 'blog' === $_POST['zone_type'] ) ? 'blog' : 'products',
			'args'     => array(
				'limit'    => isset( $_POST['zone_limit'] ) ? max( 1, (int) $_POST['zone_limit'] ) : 8,
				'columns'  => isset( $_POST['zone_columns'] ) ? max( 1, min( 6, (int) $_POST['zone_columns'] ) ) : 4,
				'category' => isset( $_POST['zone_category'] ) ? sanitize_text_field( wp_unslash( $_POST['zone_category'] ) ) : '',
				'orderby'  => isset( $_POST['zone_orderby'] ) ? sanitize_text_field( wp_unslash( $_POST['zone_orderby'] ) ) : 'date',
			),
		) );
		self::redirect( 'aisb-zones', array( 'aisb_msg' => __( 'Zone saved.', 'ai-site-bridge' ) ) );
	}

	public static function handle_delete_zone() {
		self::guard();
		check_admin_referer( 'aisb_delete_zone' );
		if ( isset( $_GET['zone_id'] ) ) {
			AISB_Zones::delete( sanitize_text_field( wp_unslash( $_GET['zone_id'] ) ) );
		}
		self::redirect( 'aisb-zones', array( 'aisb_msg' => __( 'Zone deleted.', 'ai-site-bridge' ) ) );
	}

	/* ---------------------------------------------------------- settings */

	public static function page_settings() {
		self::guard();
		$settings = AISB_Plugin::settings();
		$pages    = AISB_Store::get_pages();
		$lang_lines = array();
		foreach ( (array) $settings['languages'] as $lang ) {
			if ( ! empty( $lang['code'] ) ) {
				$lang_lines[] = $lang['code'] . '|' . ( isset( $lang['label'] ) ? $lang['label'] : $lang['code'] );
			}
		}
		?>
		<div class="wrap aisb-wrap">
			<h1><?php esc_html_e( 'AI Site Bridge — Settings', 'ai-site-bridge' ); ?></h1>
			<?php self::notice(); ?>
			<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
				<input type="hidden" name="action" value="aisb_save_settings">
				<?php wp_nonce_field( 'aisb_save_settings' ); ?>

				<h2><?php esc_html_e( 'GitHub sync', 'ai-site-bridge' ); ?></h2>
				<table class="form-table">
					<tr>
						<th><?php esc_html_e( 'Repository (owner/name)', 'ai-site-bridge' ); ?></th>
						<td><input type="text" class="regular-text" name="github_repo" value="<?php echo esc_attr( $settings['github_repo'] ); ?>" placeholder="myuser/my-lovable-site"></td>
					</tr>
					<tr>
						<th><?php esc_html_e( 'Branch', 'ai-site-bridge' ); ?></th>
						<td>
							<input type="text" name="github_branch" value="<?php echo esc_attr( $settings['github_branch'] ); ?>" placeholder="aisb-build">
							<p class="description"><?php esc_html_e( 'Use the branch that contains the BUILT site (e.g. "aisb-build" produced by the bundled GitHub Action), or any branch with a committed dist/ folder.', 'ai-site-bridge' ); ?></p>
						</td>
					</tr>
					<tr>
						<th><?php esc_html_e( 'Access token', 'ai-site-bridge' ); ?></th>
						<td>
							<input type="password" class="regular-text" name="github_token" value="<?php echo esc_attr( $settings['github_token'] ); ?>" autocomplete="off">
							<p class="description"><?php esc_html_e( 'Only needed for private repositories (fine-grained token with "Contents: read").', 'ai-site-bridge' ); ?></p>
						</td>
					</tr>
					<tr>
						<th><?php esc_html_e( 'Build directory', 'ai-site-bridge' ); ?></th>
						<td>
							<input type="text" name="build_dir" value="<?php echo esc_attr( $settings['build_dir'] ); ?>" placeholder="auto (dist, build, out, ...)">
						</td>
					</tr>
				</table>

				<h2><?php esc_html_e( 'Languages', 'ai-site-bridge' ); ?></h2>
				<table class="form-table">
					<tr>
						<th><?php esc_html_e( 'Languages (one per line: code|Label)', 'ai-site-bridge' ); ?></th>
						<td>
							<textarea name="languages" rows="4" class="regular-text" placeholder="el|Ελληνικά&#10;en|English"><?php echo esc_textarea( implode( "\n", $lang_lines ) ); ?></textarea>
						</td>
					</tr>
					<tr>
						<th><?php esc_html_e( 'Default language code', 'ai-site-bridge' ); ?></th>
						<td><input type="text" name="default_lang" value="<?php echo esc_attr( $settings['default_lang'] ); ?>" class="small-text"></td>
					</tr>
					<tr>
						<th><?php esc_html_e( 'Show language switcher', 'ai-site-bridge' ); ?></th>
						<td><label><input type="checkbox" name="show_switcher" value="1" <?php checked( ! empty( $settings['show_switcher'] ) ); ?>> <?php esc_html_e( 'Floating switcher on the site', 'ai-site-bridge' ); ?></label></td>
					</tr>
				</table>

				<h2><?php esc_html_e( 'Routing', 'ai-site-bridge' ); ?></h2>
				<table class="form-table">
					<tr>
						<th><?php esc_html_e( 'Front page', 'ai-site-bridge' ); ?></th>
						<td>
							<select name="front_slug">
								<?php if ( empty( $pages ) ) : ?>
									<option value="home">home</option>
								<?php else : ?>
									<?php foreach ( $pages as $page ) :
										$slug = AISB_Store::page_slug( $page->ID ); ?>
										<option value="<?php echo esc_attr( $slug ); ?>" <?php selected( $settings['front_slug'], $slug ); ?>>/<?php echo esc_html( $slug ); ?></option>
									<?php endforeach; ?>
								<?php endif; ?>
							</select>
							<p class="description"><?php esc_html_e( 'The imported page served at the site root.', 'ai-site-bridge' ); ?></p>
						</td>
					</tr>
				</table>

				<?php submit_button( __( 'Save settings', 'ai-site-bridge' ) ); ?>
			</form>
		</div>
		<?php
	}

	public static function handle_save_settings() {
		self::guard();
		check_admin_referer( 'aisb_save_settings' );

		$settings = AISB_Plugin::settings();

		$settings['github_repo']   = isset( $_POST['github_repo'] ) ? sanitize_text_field( wp_unslash( $_POST['github_repo'] ) ) : '';
		$settings['github_branch'] = isset( $_POST['github_branch'] ) ? sanitize_text_field( wp_unslash( $_POST['github_branch'] ) ) : 'main';
		$settings['github_token']  = isset( $_POST['github_token'] ) ? trim( (string) wp_unslash( $_POST['github_token'] ) ) : '';
		$settings['build_dir']     = isset( $_POST['build_dir'] ) ? sanitize_text_field( wp_unslash( $_POST['build_dir'] ) ) : '';
		$settings['front_slug']    = isset( $_POST['front_slug'] ) ? sanitize_text_field( wp_unslash( $_POST['front_slug'] ) ) : 'home';
		$settings['show_switcher'] = empty( $_POST['show_switcher'] ) ? 0 : 1;
		$settings['default_lang']  = isset( $_POST['default_lang'] ) ? sanitize_key( wp_unslash( $_POST['default_lang'] ) ) : 'en';

		$languages = array();
		$raw       = isset( $_POST['languages'] ) ? (string) wp_unslash( $_POST['languages'] ) : '';
		foreach ( explode( "\n", $raw ) as $line ) {
			$line = trim( $line );
			if ( '' === $line ) {
				continue;
			}
			$bits  = array_map( 'trim', explode( '|', $line, 2 ) );
			$code  = sanitize_key( $bits[0] );
			if ( '' === $code ) {
				continue;
			}
			$languages[] = array(
				'code'  => $code,
				'label' => isset( $bits[1] ) && '' !== $bits[1] ? sanitize_text_field( $bits[1] ) : $code,
			);
		}
		if ( empty( $languages ) ) {
			$languages = array( array( 'code' => 'en', 'label' => 'English' ) );
		}
		$settings['languages'] = $languages;

		update_option( 'aisb_settings', $settings );
		flush_rewrite_rules( false );

		self::redirect( 'aisb-settings', array( 'aisb_msg' => __( 'Settings saved.', 'ai-site-bridge' ) ) );
	}
}
