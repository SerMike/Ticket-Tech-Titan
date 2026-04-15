"""prompts.py — System prompt and user-prompt builders for ticket evaluation.

Houses the system prompt that defines the model's role, the priority
buckets, the auto-deny rule, and the required JSON output schema.
Also exposes a builder that formats a ticket + ban record into the
user-message body. Implementation lands in Step 4.
"""
