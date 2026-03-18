-- Songs that exist but don't have an embedding row
SELECT
  s.id,
  s.title,
  a.name AS artist,
  s.release_year,
  s.genre
FROM song s
JOIN artist a ON a.id = s.artist_id
LEFT JOIN embedding e ON e.song_id = s.id
WHERE e.song_id IS NULL
ORDER BY s.release_year DESC
LIMIT 200;
