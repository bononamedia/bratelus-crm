# Bratelus CRM

Bratelus CRM is a multi-tenant dispatch and field-service platform for service companies. Each workspace represents a brand and keeps its CRM records, workforce, jobs, configuration, and live field telemetry isolated from other tenants.

## Current capabilities

- Workspace-aware access for platform superadmins, company admins, and employees
- CRM accounts, contacts, properties, payment methods, leads, and custom fields
- Live dispatch board with job assignment and worker GPS locations through Redis
- Workforce profiles, skills, service zones, and employee work views
- Finance and reporting foundations
- Workspace setup for email domains, mailbox connections, and draggable module layouts
- REST and mobile endpoints for jobs, workers, clock-in/out, evidence, and telemetry

## Stack

- Django 5 and Django REST Framework
- PostgreSQL 15
- Redis 7, Celery, Channels, and Daphne
- Docker Compose
- Cloudflare R2-compatible object storage

## Local setup

1. Copy `.env.example` to `.env` and replace every placeholder.
2. Build and start the services:

   ```bash
   docker compose up --build -d
   ```

3. Apply migrations and create an administrator:

   ```bash
   docker compose exec web python manage.py migrate
   docker compose exec web python manage.py createsuperuser
   ```

4. Open `http://localhost:8000`.

## Production notes

Production secrets belong only in the server `.env` file or a managed secret store. Never commit `.env`, private keys, mailbox passwords, Twilio credentials, database dumps, deployment bundles, or customer data.

Workspace email connection records store a secret reference rather than a raw mailbox password. OAuth flows, encrypted secret storage, and provider validation are planned integration work.

## Project status

This product is under active development. The web application is the current operational surface; the same APIs and permissions will support the planned iPhone and Android applications.

