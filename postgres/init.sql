-- Local demo only. Supply managed credentials in deployment.
CREATE ROLE audit_reader LOGIN PASSWORD 'audit_readonly';
CREATE TABLE tenants (id SERIAL PRIMARY KEY, name TEXT NOT NULL, domain TEXT UNIQUE);
CREATE TABLE users (id SERIAL PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), name TEXT, email TEXT);
INSERT INTO tenants(name, domain) VALUES ('Demo', 'example.invalid');
INSERT INTO users(tenant_id,name,email) VALUES (1,'Demo','demo@example.invalid');
GRANT CONNECT ON DATABASE audit_db TO audit_reader;
GRANT USAGE ON SCHEMA public TO audit_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO audit_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO audit_reader;
ALTER ROLE audit_reader SET default_transaction_read_only = on;
