<?php
/**
 * Data access: imported pages, string catalog, translations.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class AISB_Store {

	public static function strings_table() {
		global $wpdb;
		return $wpdb->prefix . 'aisb_strings';
	}

	public static function translations_table() {
		global $wpdb;
		return $wpdb->prefix . 'aisb_translations';
	}

	/* ------------------------------------------------------------- pages */

	/** All imported pages (published). */
	public static function get_pages() {
		return get_posts( array(
			'post_type'      => AISB_Plugin::CPT,
			'post_status'    => 'publish',
			'posts_per_page' => -1,
			'orderby'        => 'title',
			'order'          => 'ASC',
		) );
	}

	/** Find an imported page by its routing slug (may contain slashes). */
	public static function get_page_by_slug( $slug ) {
		$posts = get_posts( array(
			'post_type'      => AISB_Plugin::CPT,
			'post_status'    => 'publish',
			'posts_per_page' => 1,
			'meta_key'       => '_aisb_slug',
			'meta_value'     => $slug,
		) );
		return $posts ? $posts[0] : null;
	}

	public static function page_slug( $post_id ) {
		return (string) get_post_meta( $post_id, '_aisb_slug', true );
	}

	/* ----------------------------------------------------------- strings */

	/**
	 * Insert or refresh a catalog string. Existing edits/translations are
	 * preserved because rows are keyed by (page_id, skey).
	 */
	public static function upsert_string( $page_id, $skey, $context, $original ) {
		global $wpdb;
		$table = self::strings_table();
		$wpdb->query( $wpdb->prepare(
			"INSERT INTO {$table} (page_id, skey, context, original, updated_at)
			 VALUES (%d, %s, %s, %s, %s)
			 ON DUPLICATE KEY UPDATE original = VALUES(original), context = VALUES(context)",
			$page_id, $skey, $context, $original, current_time( 'mysql' )
		) );
	}

	/** Remove catalog rows (and their translations) that vanished from a re-import. */
	public static function delete_missing( $page_id, array $keep_keys ) {
		global $wpdb;
		$strings      = self::strings_table();
		$translations = self::translations_table();

		if ( empty( $keep_keys ) ) {
			$wpdb->query( $wpdb->prepare( "DELETE FROM {$strings} WHERE page_id = %d", $page_id ) );
		} else {
			$placeholders = implode( ',', array_fill( 0, count( $keep_keys ), '%s' ) );
			$params       = array_merge( array( $page_id ), $keep_keys );
			$wpdb->query( $wpdb->prepare(
				"DELETE FROM {$strings} WHERE page_id = %d AND skey NOT IN ({$placeholders})",
				$params
			) );
		}

		// Orphaned translations.
		$wpdb->query( "DELETE t FROM {$translations} t LEFT JOIN {$strings} s ON s.id = t.string_id WHERE s.id IS NULL" );
	}

	/** All catalog rows for a page, in insertion order. */
	public static function get_strings( $page_id ) {
		global $wpdb;
		$table = self::strings_table();
		return $wpdb->get_results( $wpdb->prepare(
			"SELECT * FROM {$table} WHERE page_id = %d ORDER BY id ASC",
			$page_id
		) );
	}

	public static function save_edit( $string_id, $value ) {
		global $wpdb;
		$table = self::strings_table();
		$wpdb->update(
			$table,
			array( 'edited' => ( '' === $value ) ? null : $value, 'updated_at' => current_time( 'mysql' ) ),
			array( 'id' => (int) $string_id )
		);
	}

	public static function save_translation( $string_id, $lang, $value ) {
		global $wpdb;
		$table = self::translations_table();
		if ( '' === $value ) {
			$wpdb->delete( $table, array( 'string_id' => (int) $string_id, 'lang' => $lang ) );
			return;
		}
		$wpdb->query( $wpdb->prepare(
			"INSERT INTO {$table} (string_id, lang, value, updated_at)
			 VALUES (%d, %s, %s, %s)
			 ON DUPLICATE KEY UPDATE value = VALUES(value), updated_at = VALUES(updated_at)",
			$string_id, $lang, $value, current_time( 'mysql' )
		) );
	}

	/** Translations for a page in one language: [ string_id => value ]. */
	public static function get_translations( $page_id, $lang ) {
		global $wpdb;
		$strings      = self::strings_table();
		$translations = self::translations_table();
		$rows         = $wpdb->get_results( $wpdb->prepare(
			"SELECT t.string_id, t.value FROM {$translations} t
			 INNER JOIN {$strings} s ON s.id = t.string_id
			 WHERE s.page_id = %d AND t.lang = %s",
			$page_id, $lang
		) );
		$map = array();
		foreach ( $rows as $row ) {
			$map[ (int) $row->string_id ] = $row->value;
		}
		return $map;
	}

	/**
	 * Resolve the final value of every string on a page for a language:
	 * translation > edited > original. Returns [ skey => value ].
	 */
	public static function resolve_map( $page_id, $lang, $default_lang ) {
		$rows         = self::get_strings( $page_id );
		$translations = ( $lang && $lang !== $default_lang )
			? self::get_translations( $page_id, $lang )
			: array();

		$map = array();
		foreach ( $rows as $row ) {
			$value = null !== $row->edited ? $row->edited : $row->original;
			if ( isset( $translations[ (int) $row->id ] ) && '' !== $translations[ (int) $row->id ] ) {
				$value = $translations[ (int) $row->id ];
			}
			$map[ $row->skey ] = $value;
		}
		return $map;
	}
}
