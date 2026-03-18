-- Embedding coverage ratio
SELECT
  (SELECT COUNT(*) FROM song)     AS total_songs,
  (SELECT COUNT(*) FROM embedding) AS songs_with_embeddings,
  (SELECT (COUNT(*) * 1.0)
     FROM embedding) / NULLIF((SELECT COUNT(*) FROM song), 0) AS embedding_coverage_ratio;
