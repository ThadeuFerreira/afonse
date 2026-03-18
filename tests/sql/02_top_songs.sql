-- Recent/popular songs with quick coverage indicators
SELECT
  s.id,
  s.title,
  a.name AS artist,
  s.release_year,
  s.genre,
  s.popularity,
  (SELECT COUNT(*) FROM lyrics l WHERE l.song_id = s.id)      AS has_lyrics_rows,
  (SELECT COUNT(*) FROM chart  c WHERE c.song_id = s.id)      AS chart_rows,
  (SELECT 1 FROM embedding e WHERE e.song_id = s.id LIMIT 1)  AS has_embedding
FROM song s
JOIN artist a ON a.id = s.artist_id
ORDER BY
  s.release_year DESC,
  s.popularity DESC
LIMIT 25;
