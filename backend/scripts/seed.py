"""
Seed script for initial data: admin user, approval workflows, sample breaches, policies.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.db import (
    create_user,
    create_approval_workflow,
    create_policy,
    get_user_by_email,
    get_supabase,
)
from app.core.auth import hash_password


def seed_admin_user():
    existing = get_user_by_email("admin@vendorsols.com")
    if existing:
        print("  [skip] admin@vendorsols.com already exists")
        return
    user = create_user(
        {
            "email": "admin@vendorsols.com",
            "password_hash": hash_password("changeme123"),
            "full_name": "System Admin",
            "role": "admin",
            "department": "Information Security",
        }
    )
    print(f"  [created] admin user: {user.get('id')}")

    for email, name, role in [
        ("approver@vendorsols.com", "VP Security", "approver"),
        ("reviewer@vendorsols.com", "Risk Analyst", "reviewer"),
    ]:
        if not get_user_by_email(email):
            create_user(
                {
                    "email": email,
                    "password_hash": hash_password("changeme123"),
                    "full_name": name,
                    "role": role,
                    "department": "Information Security",
                }
            )
            print(f"  [created] {role} user: {email}")


def seed_approval_workflows():
    sb = get_supabase()
    existing = sb.table("approval_workflows").select("id").limit(1).execute()
    if existing.data:
        print("  [skip] approval workflows already seeded")
        return

    workflows = [
        ("Auto-Approve (Low Risk)", "auto_approve", [], "sequential", 0),
        (
            "Manager Approval",
            "manager",
            [
                {"role": "legal", "email": "legal@vendorsols.local", "order": 1},
                {"role": "finance", "email": "finance@vendorsols.local", "order": 1},
                {"role": "it", "email": "it@vendorsols.local", "order": 1},
            ],
            "parallel",
            48,
        ),
        (
            "VP Approval",
            "vp",
            [
                {"role": "legal", "email": "legal@vendorsols.local", "order": 1},
                {"role": "finance", "email": "finance@vendorsols.local", "order": 1},
                {"role": "it", "email": "it@vendorsols.local", "order": 1},
            ],
            "parallel",
            72,
        ),
        (
            "Executive Approval",
            "executive",
            [
                {"role": "legal", "email": "legal@vendorsols.local", "order": 1},
                {"role": "finance", "email": "finance@vendorsols.local", "order": 1},
                {"role": "it", "email": "it@vendorsols.local", "order": 1},
            ],
            "parallel",
            120,
        ),
        (
            "Board Approval",
            "board",
            [
                {"role": "legal", "email": "legal@vendorsols.local", "order": 1},
                {"role": "finance", "email": "finance@vendorsols.local", "order": 1},
                {"role": "it", "email": "it@vendorsols.local", "order": 1},
            ],
            "parallel",
            168,
        ),
    ]
    for name, tier, approvers, order, timeout in workflows:
        create_approval_workflow(
            {
                "name": name,
                "risk_tier": tier,
                "approvers": approvers,
                "approval_order": order,
                "timeout_hours": timeout,
            }
        )
        print(f"  [created] workflow: {name}")


def seed_breach_data():
    sb = get_supabase()
    existing = sb.table("breaches").select("id").limit(1).execute()
    if existing.data:
        print("  [skip] breach data already seeded")
        return

    breaches = [
        {
            "company_name": "Example Corp",
            "domain": "example.com",
            "breach_date": "2023-06-15",
            "records_exposed": 50000,
            "data_types": ["email", "passwords"],
            "severity": "high",
            "description": "Credential stuffing attack exposed user data.",
        },
        {
            "company_name": "TechCo Inc",
            "domain": "techco.io",
            "breach_date": "2022-11-03",
            "records_exposed": 120000,
            "data_types": ["email", "pii", "financial"],
            "severity": "critical",
            "description": "SQL injection led to full database exfiltration.",
        },
        {
            "company_name": "CloudSafe Ltd",
            "domain": "cloudsafe.dev",
            "breach_date": "2024-01-20",
            "records_exposed": 5000,
            "data_types": ["email"],
            "severity": "low",
            "description": "Misconfigured S3 bucket exposed customer emails.",
        },
    ]
    for breach in breaches:
        sb.table("breaches").insert(breach).execute()
        print(f"  [created] breach: {breach['company_name']}")


def seed_policies():
    policies = [
        {
            "title": "Vendor Security Assessment Policy",
            "category": "security",
            "content": "All vendors processing company data must undergo a security assessment. Vendors must provide SOC2 Type 2 or ISO 27001 certification. Certificate expiry must be monitored and renewed before expiration. Domain security must meet minimum TLS 1.2 standards. Breach history must be checked within the last 5 years.",
        },
        {
            "title": "Data Protection Compliance Policy",
            "category": "compliance",
            "content": "Vendors handling personal data must comply with GDPR Article 28 requirements. A Data Processing Agreement (DPA) is required for all vendors processing PII. HIPAA compliance is mandatory for vendors handling PHI. PCI DSS compliance is required for vendors processing payment card data. Privacy policies must be reviewed and verified.",
        },
        {
            "title": "Financial Due Diligence Policy",
            "category": "financial",
            "content": "Vendors with contracts over $100,000 must provide audited financial statements. Insurance coverage must meet minimum requirements: $1M general liability, $1M E&O. Credit ratings must be investment grade for contracts over $500,000. Business continuity plans are required for critical vendors. Bankruptcy records must be verified for all vendors.",
        },
    ]
    for p in policies:
        try:
            create_policy(
                {
                    "title": p["title"],
                    "category": p["category"],
                    "content": p["content"],
                    "source": "Vendorsols Internal",
                    "version": "1.0",
                    "is_active": True,
                }
            )
            print(f"  [created] policy: {p['title']}")
        except Exception as exc:
            print(f"  [skip] policy {p['title']}: {exc}")


def main():
    print("Vendorsols Phase 3 — Seeding initial data...")
    seed_admin_user()
    seed_approval_workflows()
    seed_breach_data()
    seed_policies()
    print("Seeding complete.")


if __name__ == "__main__":
    main()
