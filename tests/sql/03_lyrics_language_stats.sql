-- Lyrics coverage by language
SELECT
  language,
  COUNT(*) AS songs_with_lyrics,
  SUM(word_count) AS total_word_count,
  AVG(word_count) AS avg_word_count
FROM lyrics
GROUP BY language
ORDER BY songs_with_lyrics DESC;
