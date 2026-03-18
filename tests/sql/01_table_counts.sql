-- Row counts per table (quick health check)
SELECT 'artist'            AS table_name, COUNT(*) AS row_count FROM artist;
SELECT 'album'             AS table_name, COUNT(*) AS row_count FROM album;
SELECT 'song'              AS table_name, COUNT(*) AS row_count FROM song;
SELECT 'lyrics'            AS table_name, COUNT(*) AS row_count FROM lyrics;
SELECT 'chart'             AS table_name, COUNT(*) AS row_count FROM chart;
SELECT 'vocabularyindex'  AS table_name, COUNT(*) AS row_count FROM vocabularyindex;
SELECT 'embedding'         AS table_name, COUNT(*) AS row_count FROM embedding;
SELECT 'ingestionfailure' AS table_name, COUNT(*) AS row_count FROM ingestionfailure;
