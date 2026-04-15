"""evaluator.py — Core evaluate_ticket() function.

Glues the prompt builders and the Anthropic client together. Takes a
ticket and (optional) ban record, calls the model, parses the JSON
response, and returns a dict matching the support_tickets_with_ai
schema. Implementation lands in Step 5.
"""
