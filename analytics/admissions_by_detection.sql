-- admissions_by_detection.sql
--
-- Analytics queries that cross the LLM-derived admission flags
-- (admitted_cheating, admitted_exploit) against the internal ban
-- database's detection_method.
--
-- Business questions answered:
--   Q1. Of players who admitted to cheating, which detection methods
--       originally caught them? (Detection effectiveness by method.)
--   Q2. How does admission rate vary across detection methods? (Are
--       any methods so unambiguous that players stop denying?)
--   Q3. Are there cases where a player admitted but we have NO ban
--       record? (Detection gap — we missed a real cheater.)
--   Q4. Are there admissions paired with soft-signal detections? (Our
--       soft signals caught real cheaters we might have released.)
--   Q5. Cheating vs. exploit admissions split — which is more common,
--       and do they map to different detection methods?
--
-- Each query is standalone; run whichever one you need. The file is
-- safe to execute top-to-bottom against `support_tickets_with_ai`.


-- ---------------------------------------------------------------------------
-- Q1. Admissions by detection method
-- ---------------------------------------------------------------------------
-- Of the players who admitted to cheating OR exploiting, what detection
-- method flagged them? Tells us which detection methods are producing
-- self-confirmed catches.
SELECT
    COALESCE(b.detection_method, '(no ban record)') AS detection_method,
    COUNT(*) FILTER (WHERE a.admitted_cheating)     AS admitted_cheating,
    COUNT(*) FILTER (WHERE a.admitted_exploit)      AS admitted_exploit,
    COUNT(*) FILTER (WHERE a.admitted_cheating
                        OR a.admitted_exploit)      AS any_admission
FROM support_tickets_with_ai a
LEFT JOIN ban_database b ON a.user_id = b.user_id
WHERE a.admitted_cheating OR a.admitted_exploit
GROUP BY b.detection_method
ORDER BY any_admission DESC;


-- ---------------------------------------------------------------------------
-- Q2. Admission rate by detection method
-- ---------------------------------------------------------------------------
-- What fraction of tickets tied to each detection method result in an
-- admission? Low admission rates against a "confirmed" detection method
-- may indicate players who know appeals get denied anyway; high rates
-- against a soft signal may indicate the signal is actually reliable.
SELECT
    COALESCE(b.detection_method, '(no ban record)') AS detection_method,
    COUNT(*) AS total_tickets,
    COUNT(*) FILTER (WHERE a.admitted_cheating
                        OR a.admitted_exploit) AS with_admission,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE a.admitted_cheating
                                    OR a.admitted_exploit)
        / NULLIF(COUNT(*), 0),
        1
    ) AS admission_rate_pct
FROM support_tickets_with_ai a
LEFT JOIN ban_database b ON a.user_id = b.user_id
GROUP BY b.detection_method
ORDER BY total_tickets DESC;


-- ---------------------------------------------------------------------------
-- Q3. Detection gap — admissions with NO ban record
-- ---------------------------------------------------------------------------
-- These are the most interesting for the detection team: a player
-- admitted to cheating or exploiting, but our ban_database has no row
-- for them. Either our detection missed them, or the ban was
-- unintentionally reversed. Each row here deserves a root-cause review.
SELECT
    a.ticket_id,
    a.user_id,
    a.admitted_cheating,
    a.admitted_exploit,
    a.confidence_score,
    a.ai_summary
FROM support_tickets_with_ai a
LEFT JOIN ban_database b ON a.user_id = b.user_id
WHERE (a.admitted_cheating OR a.admitted_exploit)
  AND b.user_id IS NULL
ORDER BY a.ticket_id;


-- ---------------------------------------------------------------------------
-- Q4. Admissions against soft-signal detections
-- ---------------------------------------------------------------------------
-- When a player admits AND the original detection was a soft signal
-- (stat_anomaly, manual_review, new_detection_method), it means the
-- soft signal correctly caught a real cheater. These cases validate
-- soft-signal tuning and argue against dismissing them.
SELECT
    a.ticket_id,
    a.user_id,
    b.detection_method,
    a.admitted_cheating,
    a.admitted_exploit,
    a.ai_category,
    a.ai_summary
FROM support_tickets_with_ai a
JOIN ban_database b ON a.user_id = b.user_id
WHERE (a.admitted_cheating OR a.admitted_exploit)
  AND b.detection_method IN (
      'stat_anomaly',
      'manual_review',
      'new_detection_method'
  )
ORDER BY b.detection_method, a.ticket_id;


-- ---------------------------------------------------------------------------
-- Q5. Cheating vs. exploit admission totals
-- ---------------------------------------------------------------------------
-- Headline counts for the data-science team's distinction between
-- cheating (third-party software, mods, aimbots, scripts) and
-- exploiting (bug abuse, stat padding, win trading, glitch abuse).
SELECT
    COUNT(*) FILTER (WHERE admitted_cheating AND NOT admitted_exploit) AS cheating_only,
    COUNT(*) FILTER (WHERE admitted_exploit AND NOT admitted_cheating) AS exploit_only,
    COUNT(*) FILTER (WHERE admitted_cheating AND admitted_exploit)     AS both,
    COUNT(*) FILTER (WHERE admitted_cheating OR admitted_exploit)      AS any_admission,
    COUNT(*)                                                            AS total_evaluated
FROM support_tickets_with_ai;
