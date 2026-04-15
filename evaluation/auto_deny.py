"""auto_deny.py — Belt-and-suspenders enforcement of the auto-deny rule.

Defines the canonical list of confirmed detection methods that always
trigger Auto-Deny. Provides a post-evaluation override that runs after
the model returns, in case the model's category disagrees with the
ban record's detection method. Implementation lands in Step 6.
"""
