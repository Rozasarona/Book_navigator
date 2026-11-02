-- What was collected from each source
SELECT s.name, count(*) AS editions
FROM audio_editions ae JOIN sources s ON s.id = ae.source_id
GROUP BY s.name ORDER BY editions DESC;

-- Latest analysis findings
SELECT b.title, b.author, a.age_min, a.age_max,
       a.interest_tags_json, a.content_flags_json,
       a.enough_information, a.teaser
FROM books b JOIN book_analyses a ON a.book_id = b.id
ORDER BY a.created_at DESC;

-- Recommendation audit trail
SELECT p.child_name, b.title, r.score, r.status, r.rationale, r.week_key
FROM recommendations r
JOIN profiles p ON p.id = r.profile_id
JOIN books b ON b.id = r.book_id
ORDER BY r.created_at DESC;

