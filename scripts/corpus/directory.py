"""Employee directory and service catalog.

This is the single source of truth for people and services. The corpus
documents reference these ids, and the MCP server serves the same data, so a
question like "who owns the service that failed in INC-2026-0412?" can be
answered by joining a document with an MCP lookup.
"""

EMPLOYEES = [
    # id, name, title, department, team, on_call
    ("E1001", "Nadeesha Perera", "Head of Payments Engineering", "payments", "Payments Engineering", False),
    ("E1002", "Kasun Jayawardena", "SRE Lead", "platform", "Site Reliability", True),
    ("E1003", "Dilani Fernando", "Senior Engineer, Card Platform", "payments", "Card Platform", True),
    ("E1004", "Ruwan Wickramasinghe", "Integration Engineer, Payment Switch", "payments", "Switch Integration", True),
    ("E1005", "Tharindu Silva", "Database Engineering Lead", "platform", "Data Platform", True),
    ("E1006", "Ishara Gunasekara", "Fraud Analytics Lead", "risk", "Fraud Analytics", False),
    ("E1007", "Chamari Rathnayake", "Chief Information Security Officer", "security", "Information Security", False),
    ("E1008", "Malith Herath", "Security Engineer, PKI and Cryptography", "security", "Cryptography Services", True),
    ("E1009", "Sanduni Abeysekara", "Product Manager, Digital Payments", "product", "Digital Payments", False),
    ("E1010", "Nuwan Bandara", "Mobile Engineering Lead", "product", "Digital Channels", True),
    ("E1011", "Amaya de Silva", "Major Incident Manager", "platform", "Service Management", True),
    ("E1012", "Pradeep Kumara", "Core Banking Integration Engineer", "platform", "Core Integration", True),
    ("E1013", "Hiruni Weerasinghe", "Compliance Officer, Payments", "risk", "Compliance", False),
    ("E1014", "Lahiru Mendis", "Site Reliability Engineer", "platform", "Site Reliability", True),
    ("E1015", "Shehani Karunaratne", "Product Manager, Cards", "product", "Cards", False),
    ("E1016", "Janaka Dissanayake", "Enterprise Architect", "platform", "Architecture Office", False),
    ("E1017", "Kavindi Senanayake", "HR Business Partner, Technology", "hr", "People", False),
    ("E1018", "Asela Rajapaksha", "Network Engineer", "platform", "Network Services", True),
]

SERVICES = [
    # id, name, owner_team, owner_id, tier, depends_on, runbooks, description
    ("card-auth-service", "Card Authorization Service", "Card Platform", "E1003", 1,
     ["hsm-gateway", "fraud-scoring-client", "core-banking-adapter"], ["RB-PAY-001", "RB-RSK-001"],
     "Authorizes debit and credit card transactions from POS, e-commerce and ATM channels."),
    ("hsm-gateway", "HSM Gateway", "Cryptography Services", "E1008", 1,
     [], ["RB-PAY-001"],
     "Brokers PIN verification and cryptogram validation requests to the hardware security modules."),
    ("payment-switch-connector", "National Payment Switch Connector", "Switch Integration", "E1004", 1,
     ["core-banking-adapter"], ["RB-SEC-002"],
     "Sends and receives interbank instant transfers through the national payment switch."),
    ("eod-settlement-batch", "End-of-Day Settlement Batch", "Payments Engineering", "E1001", 1,
     ["ledger-db"], ["RB-PAY-003"],
     "Nightly batch that posts card and transfer settlements to the general ledger."),
    ("fraud-scoring-client", "Fraud Scoring Client", "Fraud Analytics", "E1006", 1,
     [], ["RB-RSK-001"],
     "Calls the external VeriScore fraud API and applies the Bank's rule overlays."),
    ("core-banking-adapter", "Core Banking Adapter", "Core Integration", "E1012", 1,
     ["ledger-db"], ["RB-PLT-004"],
     "Translates channel requests into core banking ledger operations."),
    ("ledger-db", "Ledger Database Cluster", "Data Platform", "E1005", 1,
     [], ["RB-PLT-004"],
     "PostgreSQL primary with two synchronous replicas holding account balances and postings."),
    ("mobile-banking-api", "Mobile Banking API", "Digital Channels", "E1010", 1,
     ["identity-service", "core-banking-adapter", "notification-service"], ["RB-DIG-001"],
     "Backend for the retail mobile banking app."),
    ("identity-service", "Identity Service", "Information Security", "E1008", 1,
     [], ["RB-DIG-001"],
     "Issues and validates customer session tokens and step-up authentication."),
    ("qr-payments-service", "QR Payments Service", "Digital Payments", "E1009", 2,
     ["payment-switch-connector", "core-banking-adapter"], [],
     "Merchant-presented QR payments for retail customers."),
    ("merchant-settlement-portal", "Merchant Settlement Portal", "Digital Payments", "E1009", 2,
     ["ledger-db"], [],
     "Web portal where merchants view settlements and download statements."),
    ("notification-service", "Notification Service", "Site Reliability", "E1014", 3,
     [], [],
     "Sends SMS and push notifications, including one-time passwords."),
]
