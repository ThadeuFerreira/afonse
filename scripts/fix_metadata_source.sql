-- =============================================================================
-- fix_metadata_source.sql
--
-- Root cause
-- ----------
-- enrich_metadata() only wrote metadata_source on success.  Songs where both
-- Spotify and MusicBrainz failed were left with metadata_source = NULL.
-- On every subsequent run the entire failed set was re-queued (thousands of
-- songs), because the filter is:  WHERE metadata_source IS NULL
--
-- Fix
-- ---
-- 1. Songs that have lyrics: mark as 'lyrics_only'.
--    Lyrics confirm the song is real; API metadata just wasn't available.
--    These will be excluded from future enrich_metadata runs.
--
-- 2. Songs without lyrics that have a recorded metadata failure in
--    ingestionfailure: mark as 'failed', matching the new pipeline behaviour.
--
-- 3. Songs without lyrics and without any recorded failure are left alone —
--    they are genuinely un-attempted and should still be processed.
--
-- Usage
-- -----
--   sqlite3 data/music.db < scripts/fix_metadata_source.sql
--
-- Safe to run multiple times (WHERE metadata_source IS NULL is idempotent).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Diagnostic: counts before the fix
-- ---------------------------------------------------------------------------
SELECT 'BEFORE — NULL metadata_source total'        AS label,
       COUNT(*)                                      AS count
FROM   song
WHERE  metadata_source IS NULL

UNION ALL

SELECT 'BEFORE — NULL metadata_source WITH lyrics'  AS label,
       COUNT(*)                                      AS count
FROM   song s
WHERE  s.metadata_source IS NULL
  AND  EXISTS (SELECT 1 FROM lyrics l WHERE l.song_id = s.id)

UNION ALL

SELECT 'BEFORE — NULL metadata_source WITHOUT lyrics, with failure record' AS label,
       COUNT(*) AS count
FROM   song s
WHERE  s.metadata_source IS NULL
  AND  NOT EXISTS (SELECT 1 FROM lyrics        l WHERE l.song_id = s.id)
  AND  EXISTS     (SELECT 1 FROM ingestionfailure f
                   WHERE f.song_id = s.id AND f.stage = 'metadata');

-- ---------------------------------------------------------------------------
-- Fix 1: songs with lyrics → 'lyrics_only'
-- ---------------------------------------------------------------------------
UPDATE song
SET    metadata_source = 'lyrics_only'
WHERE  metadata_source IS NULL
  AND  EXISTS (SELECT 1 FROM lyrics l WHERE l.song_id = song.id);

-- ---------------------------------------------------------------------------
-- Fix 2: songs without lyrics, with a recorded metadata failure → 'failed'
-- ---------------------------------------------------------------------------
UPDATE song
SET    metadata_source = 'failed'
WHERE  metadata_source IS NULL
  AND  NOT EXISTS (SELECT 1 FROM lyrics        l WHERE l.song_id = song.id)
  AND  EXISTS     (SELECT 1 FROM ingestionfailure f
                   WHERE f.song_id = song.id AND f.stage = 'metadata');

-- ---------------------------------------------------------------------------
-- Diagnostic: counts after the fix
-- ---------------------------------------------------------------------------
SELECT 'AFTER — NULL metadata_source remaining (un-attempted)'  AS label,
       COUNT(*)                                                  AS count
FROM   song
WHERE  metadata_source IS NULL

UNION ALL

SELECT 'AFTER — lyrics_only'  AS label, COUNT(*) AS count
FROM   song WHERE metadata_source = 'lyrics_only'

UNION ALL

SELECT 'AFTER — failed'       AS label, COUNT(*) AS count
FROM   song WHERE metadata_source = 'failed'

UNION ALL

SELECT 'AFTER — enriched (spotify / musicbrainz)' AS label, COUNT(*) AS count
FROM   song
WHERE  metadata_source NOT IN ('failed', 'lyrics_only')
  AND  metadata_source IS NOT NULL;
