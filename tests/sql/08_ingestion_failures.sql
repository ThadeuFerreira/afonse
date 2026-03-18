
-- Latest ingestion failures (most useful when debugging pipelines)
SELECT
  f.id,
  f.stage,
  COALESCE(s.title, f.raw_title)   AS title,
  COALESCE(a.name,  f.raw_artist) AS artist,
  f.retry_count,
  f.error_message
FROM ingestionfailure f
LEFT JOIN song s   ON s.id = f.song_id
LEFT JOIN artist a ON a.id = s.artist_id
ORDER BY f.id DESC
LIMIT 100;

-- Latest ingestion failures (most useful when debugging pipelines)
SELECT
  f.id,
  f.stage,
  COALESCE(s.title, f.raw_title)   AS title,
  COALESCE(a.name,  f.raw_artist) AS artist,
  f.retry_count,
  f.error_message
FROM ingestionfailure f
LEFT JOIN song s   ON s.id = f.song_id
LEFT JOIN artist a ON a.id = s.artist_id
ORDER BY f.id DESC
LIMIT 100;
