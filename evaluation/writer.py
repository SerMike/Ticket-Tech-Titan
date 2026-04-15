"""writer.py — Persists evaluation results to support_tickets_with_ai.

Connects to PostgreSQL and writes the dict returned by evaluate_ticket()
into the support_tickets_with_ai table, handling re-evaluations via
UPSERT on ticket_id. Implementation lands in Step 7.
"""
