-- Examples of songs that include a specific vocabulary word.
-- Edit the literal 'dream' to whatever word you want.
-- 1) Frequency of the word in the vocabulary index
SELECT
  word,
  COUNT(*) AS vocab_rows,
  COUNT(DISTINCT song_id) AS distinct_songs
FROM vocabularyindex
WHERE word = 'dream'
GROUP BY word;
-- 2) Example songs for that word
SELECT
  s.id,
  s.title,
  a.name AS artist,
  s.release_year,
  s.genre,
  l.language AS lyrics_language
FROM vocabularyindex v
JOIN song s   ON s.id = v.song_id
JOIN artist a ON a.id = s.artist_id
LEFT JOIN lyrics l ON l.song_id = s.id
WHERE v.word = 'dream'
ORDER BY s.release_year DESC
LIMIT 50;
