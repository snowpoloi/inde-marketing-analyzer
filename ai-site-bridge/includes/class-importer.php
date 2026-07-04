<?php
/**
 * GitHub sync: download the repo, locate the static build, copy assets
 * into uploads and import every HTML page.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class AISB_Importer {

	const BUILD_CANDIDATES = array( 'dist', 'build', 'out', 'public', '' );

	/**
	 * Run a full sync from the configured GitHub repository.
	 *
	 * @return array|WP_Error Import report.
	 */
	public static function sync() {
		$repo   = trim( (string) AISB_Plugin::setting( 'github_repo' ) );
		$branch = trim( (string) AISB_Plugin::setting( 'github_branch', 'main' ) );

		if ( ! preg_match( '#^[\w.\-]+/[\w.\-]+$#', $repo ) ) {
			return new WP_Error( 'aisb_repo', 'Set a GitHub repository as "owner/name" in the AI Site Bridge settings.' );
		}

		$zip = self::download_zipball( $repo, $branch ? $branch : 'main' );
		if ( is_wp_error( $zip ) ) {
			return $zip;
		}

		$extracted = self::extract( $zip );
		@unlink( $zip );
		if ( is_wp_error( $extracted ) ) {
			return $extracted;
		}

		$build_dir = self::locate_build_dir( $extracted );
		if ( is_wp_error( $build_dir ) ) {
			self::rrmdir( $extracted );
			return $build_dir;
		}

		$report = self::import_build( $build_dir );
		self::rrmdir( $extracted );

		if ( ! is_wp_error( $report ) ) {
			update_option( 'aisb_last_sync', array(
				'time'   => current_time( 'mysql' ),
				'repo'   => $repo,
				'branch' => $branch,
				'report' => $report,
			) );
			flush_rewrite_rules( false );
		}
		return $report;
	}

	/* --------------------------------------------------- GitHub download */

	private static function download_zipball( $repo, $branch ) {
		$url     = sprintf( 'https://api.github.com/repos/%s/zipball/%s', $repo, rawurlencode( $branch ) );
		$headers = array(
			'User-Agent' => 'AI-Site-Bridge/' . AISB_VERSION,
			'Accept'     => 'application/vnd.github+json',
		);
		$token = trim( (string) AISB_Plugin::setting( 'github_token' ) );
		if ( $token ) {
			$headers['Authorization'] = 'Bearer ' . $token;
		}

		$response = wp_remote_get( $url, array( 'headers' => $headers, 'timeout' => 120 ) );
		if ( is_wp_error( $response ) ) {
			return $response;
		}
		$code = wp_remote_retrieve_response_code( $response );
		if ( 200 !== $code ) {
			return new WP_Error( 'aisb_github', sprintf(
				'GitHub returned HTTP %d for %s@%s. Check the repository name, branch and token.',
				$code, $repo, $branch
			) );
		}

		$tmp = wp_tempnam( 'aisb-repo.zip' );
		if ( ! $tmp ) {
			return new WP_Error( 'aisb_tmp', 'Could not create a temporary file.' );
		}
		file_put_contents( $tmp, wp_remote_retrieve_body( $response ) );
		return $tmp;
	}

	private static function extract( $zip_path ) {
		global $wp_filesystem;
		if ( ! function_exists( 'WP_Filesystem' ) ) {
			require_once ABSPATH . 'wp-admin/includes/file.php';
		}
		WP_Filesystem();

		$dest = trailingslashit( get_temp_dir() ) . 'aisb-extract-' . wp_generate_password( 8, false, false );
		wp_mkdir_p( $dest );

		$result = unzip_file( $zip_path, $dest );
		if ( is_wp_error( $result ) ) {
			self::rrmdir( $dest );
			return $result;
		}

		// GitHub zipballs contain a single top-level "owner-repo-sha" folder.
		$entries = array_values( array_diff( scandir( $dest ), array( '.', '..' ) ) );
		if ( 1 === count( $entries ) && is_dir( $dest . '/' . $entries[0] ) ) {
			return $dest . '/' . $entries[0];
		}
		return $dest;
	}

	private static function locate_build_dir( $root ) {
		$override = trim( (string) AISB_Plugin::setting( 'build_dir' ), '/ ' );
		$candidates = $override ? array( $override ) : self::BUILD_CANDIDATES;

		foreach ( $candidates as $candidate ) {
			$dir = $candidate ? $root . '/' . $candidate : $root;
			if ( is_file( $dir . '/index.html' ) ) {
				return $dir;
			}
		}
		return new WP_Error( 'aisb_no_build', implode( ' ', array(
			'No static build (index.html) found in the repository.',
			'Commit your build output (dist/) to the synced branch — the plugin ships a ready GitHub Action',
			'(templates/aisb-build.yml) that builds and pushes an "aisb-build" branch on every design change.',
		) ) );
	}

	/* ------------------------------------------------------------ import */

	public static function import_build( $build_dir ) {
		$uploads = wp_upload_dir();
		if ( ! empty( $uploads['error'] ) ) {
			return new WP_Error( 'aisb_uploads', $uploads['error'] );
		}
		$site_dir = trailingslashit( $uploads['basedir'] ) . 'aisb-site';
		$site_url = trailingslashit( $uploads['baseurl'] ) . 'aisb-site';

		// Replace the previous copy of the build.
		self::rrmdir( $site_dir );
		wp_mkdir_p( $site_dir );
		self::rcopy( $build_dir, $site_dir );

		// Discover pages and derive routing slugs.
		$html_files = self::find_html_files( $build_dir );
		if ( empty( $html_files ) ) {
			return new WP_Error( 'aisb_no_pages', 'No HTML pages found in the build.' );
		}

		$slug_map = array();
		foreach ( $html_files as $rel ) {
			$slug_map[ $rel ] = self::slug_for_path( $rel );
		}

		$front_slug = AISB_Plugin::front_slug();
		$imported   = array();
		$errors     = array();

		foreach ( $html_files as $rel ) {
			$slug   = $slug_map[ $rel ];
			$html   = file_get_contents( $build_dir . '/' . $rel );
			$parsed = AISB_Parser::parse_page(
				$html,
				$slug,
				( dirname( $rel ) === '.' ) ? '' : dirname( $rel ),
				$site_url,
				$slug_map,
				$front_slug
			);
			if ( is_wp_error( $parsed ) ) {
				$errors[] = $parsed->get_error_message();
				continue;
			}
			$result = self::upsert_page( $slug, $rel, $parsed );
			if ( is_wp_error( $result ) ) {
				$errors[] = $result->get_error_message();
				continue;
			}
			$imported[] = $slug;
		}

		// Retire pages that no longer exist in the build.
		$active_slugs = array_values( $slug_map );
		foreach ( AISB_Store::get_pages() as $page ) {
			$slug = AISB_Store::page_slug( $page->ID );
			if ( $slug && ! in_array( $slug, $active_slugs, true ) ) {
				wp_update_post( array( 'ID' => $page->ID, 'post_status' => 'draft' ) );
			}
		}

		update_option( 'aisb_slugs', $active_slugs );

		return array(
			'pages'  => $imported,
			'count'  => count( $imported ),
			'errors' => $errors,
		);
	}

	private static function upsert_page( $slug, $source_path, array $parsed ) {
		$existing = AISB_Store::get_page_by_slug( $slug );
		$title    = $parsed['title'] ? $parsed['title'] : $slug;

		$postarr = array(
			'post_type'   => AISB_Plugin::CPT,
			'post_status' => 'publish',
			'post_title'  => $title,
			'post_name'   => sanitize_title( str_replace( '/', '-', $slug ) ),
		);
		if ( $existing ) {
			$postarr['ID'] = $existing->ID;
			$post_id       = wp_update_post( $postarr, true );
		} else {
			$post_id = wp_insert_post( $postarr, true );
		}
		if ( is_wp_error( $post_id ) ) {
			return $post_id;
		}

		update_post_meta( $post_id, '_aisb_slug', $slug );
		update_post_meta( $post_id, '_aisb_source', $source_path );
		update_post_meta( $post_id, '_aisb_html', $parsed['html'] );
		update_post_meta( $post_id, '_aisb_hash', md5( $parsed['html'] ) );

		// Keep user-set og_image / noindex across re-imports.
		$seo = get_post_meta( $post_id, '_aisb_seo', true );
		if ( ! is_array( $seo ) ) {
			update_post_meta( $post_id, '_aisb_seo', array( 'og_image' => '', 'noindex' => 0 ) );
		}

		foreach ( $parsed['strings'] as $skey => $string ) {
			AISB_Store::upsert_string( $post_id, $skey, $string['context'], $string['original'] );
		}
		AISB_Store::delete_missing( $post_id, array_keys( $parsed['strings'] ) );

		return $post_id;
	}

	/* ------------------------------------------------------------- utils */

	private static function find_html_files( $dir ) {
		$out      = array();
		$iterator = new RecursiveIteratorIterator(
			new RecursiveDirectoryIterator( $dir, FilesystemIterator::SKIP_DOTS )
		);
		foreach ( $iterator as $file ) {
			/** @var SplFileInfo $file */
			if ( strtolower( $file->getExtension() ) !== 'html' ) {
				continue;
			}
			$rel = ltrim( str_replace( '\\', '/', substr( $file->getPathname(), strlen( $dir ) ) ), '/' );
			// Skip common non-page files.
			if ( preg_match( '#(^|/)(404|200)\.html$#', $rel ) ) {
				continue;
			}
			$out[] = $rel;
		}
		sort( $out );
		return $out;
	}

	/** 'index.html' => 'home', 'about.html' / 'about/index.html' => 'about', 'a/b.html' => 'a/b'. */
	private static function slug_for_path( $rel ) {
		$path = preg_replace( '#\.html$#', '', $rel );
		if ( 'index' === $path ) {
			return 'home';
		}
		$path = preg_replace( '#/index$#', '', $path );
		$path = trim( $path, '/' );
		$segments = array_map( 'sanitize_title', explode( '/', $path ) );
		$slug     = implode( '/', array_filter( $segments ) );
		return $slug ? $slug : 'home';
	}

	private static function rcopy( $src, $dst ) {
		$dir = opendir( $src );
		wp_mkdir_p( $dst );
		while ( false !== ( $entry = readdir( $dir ) ) ) {
			if ( '.' === $entry || '..' === $entry ) {
				continue;
			}
			$from = $src . '/' . $entry;
			$to   = $dst . '/' . $entry;
			if ( is_dir( $from ) ) {
				self::rcopy( $from, $to );
			} else {
				copy( $from, $to );
			}
		}
		closedir( $dir );
	}

	private static function rrmdir( $dir ) {
		if ( ! is_dir( $dir ) ) {
			return;
		}
		foreach ( array_diff( scandir( $dir ), array( '.', '..' ) ) as $entry ) {
			$path = $dir . '/' . $entry;
			is_dir( $path ) ? self::rrmdir( $path ) : @unlink( $path );
		}
		@rmdir( $dir );
	}
}
