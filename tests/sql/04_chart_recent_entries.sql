-- Latest chart entries (across all songs/charts)
SELECT
  c.chart_name,
  c."date",
  c."rank",
  s.title,
  a.name AS artist,
  s.release_year
FROM chart c
JOIN song s   ON s.id = c.song_id
JOIN artist a ON a.id = s.artist_id
ORDER BY c."date" DESC, c."rank" ASC
LIMIT 100;
