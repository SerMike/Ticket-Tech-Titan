-- schema.sql — CREATE TABLE statements for Ticket Tech Titan

-- 1. Lookup table for ticket dropdown categories
CREATE TABLE IF NOT EXISTS ticket_categories (
    category_id SERIAL PRIMARY KEY,
    category_name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT
);

-- 2. Raw incoming support tickets
CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id VARCHAR(50) PRIMARY KEY,
    user_name VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    ticket_issue_category VARCHAR(255) NOT NULL
        REFERENCES ticket_categories(category_name),
    ticket_title VARCHAR(500) NOT NULL,
    ticket_body TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'open',
    created_at TIMESTAMP NOT NULL
);

-- 3. Internal ban records
CREATE TABLE IF NOT EXISTS ban_database (
    user_id VARCHAR(255) PRIMARY KEY,
    ban_reason TEXT NOT NULL,
    detection_method VARCHAR(255) NOT NULL,
    ban_duration VARCHAR(100) NOT NULL,
    ban_date DATE NOT NULL
);

-- 4. LLM-generated evaluations of tickets
CREATE TABLE IF NOT EXISTS support_tickets_with_ai (
    id SERIAL PRIMARY KEY,
    ticket_id VARCHAR(50) NOT NULL
        REFERENCES support_tickets(ticket_id),
    user_id VARCHAR(255) NOT NULL
        REFERENCES ban_database(user_id),
    ai_summary TEXT,
    ai_category VARCHAR(255),
    admitted_cheating BOOLEAN,
    admitted_exploit BOOLEAN,
    confidence_score DECIMAL,
    ai_reasoning TEXT,
    processed_at TIMESTAMP DEFAULT NOW()
);

-- 5. Tracks status changes over time
CREATE TABLE IF NOT EXISTS ticket_status_history (
    id SERIAL PRIMARY KEY,
    ticket_id VARCHAR(50) NOT NULL
        REFERENCES support_tickets(ticket_id),
    old_status VARCHAR(50),
    new_status VARCHAR(50) NOT NULL,
    changed_at TIMESTAMP DEFAULT NOW()
);
