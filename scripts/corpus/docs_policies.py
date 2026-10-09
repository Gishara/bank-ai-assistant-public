"""Policies and standards."""

POLICIES = [
    dict(
        id="POL-SEC-001", title="Information Security Policy", department="security",
        access="internal", date="2025-06-01", author="E1007", tags=["security", "policy", "governance"],
        body="""
## Purpose
This policy sets the minimum security requirements for all information systems operated by the Bank. It applies to employees, contractors and third parties with access to Bank systems.

## Ownership
The Chief Information Security Officer owns this policy and reviews it every twelve months or after a material incident.

## Principles
- Information is protected according to its classification under POL-SEC-003.
- Access is granted on least privilege and reviewed quarterly (see POL-SEC-002).
- Every production change follows the change management policy (POL-OPS-002).
- Security events are logged centrally and retained for seven years.

## Third parties
Vendors that process customer data or sit in a payment path must pass a security assessment before go-live and every two years after. Contracts must include incident notification within 24 hours and a right to audit.

## Cryptography
Cryptographic keys that protect cardholder data or PINs are generated and stored only in hardware security modules. Key management procedures are defined in POL-SEC-009, which is restricted to Cryptography Services and Internal Audit.

## Exceptions
Exceptions require written approval from the CISO, a compensating control, and an expiry date no later than twelve months.
""",
    ),
    dict(
        id="POL-SEC-002", title="Access Control Policy", department="security",
        access="internal", date="2025-06-01", author="E1007", tags=["security", "access", "iam"],
        body="""
## Scope
Covers access to applications, infrastructure, data stores and administrative consoles.

## Roles
Access is granted through roles, not individual permissions. Each role has a business owner who approves membership.

## Privileged access
- Production administrative access requires multi-factor authentication and a just-in-time elevation request.
- Elevation lasts at most four hours and is logged.
- Shared administrator accounts are prohibited.

## Reviews
Role owners recertify membership every quarter. Access not recertified is removed automatically after 14 days.

## Leavers
Access is revoked on the employee's last working day. Certificates, API keys and service credentials owned by a leaver are transferred to a named owner before departure.

## AI assistants
Internal AI assistants must enforce the same role-based access as the systems they query. An assistant must never return content that the requesting user could not open directly.
""",
    ),
    dict(
        id="POL-SEC-003", title="Data Classification and Handling Standard", department="security",
        access="public", date="2025-03-15", author="E1007", tags=["security", "data-classification", "policy"],
        body="""
## Classification levels
| Level | Description | Examples |
|---|---|---|
| Public | Approved for release outside the Bank | Product brochures, published rates |
| Internal | For all staff; low impact if disclosed | Runbooks, architecture overviews, most incident reports |
| Confidential | Limited to staff with a business need | Fraud thresholds, security incidents, database recovery procedures |
| Restricted | Named individuals only; severe impact if disclosed | Cryptographic key procedures, HSM operations, customer PIN data |

## Handling
- Internal and above must not be pasted into external AI tools or public file sharing.
- Confidential documents are shared by link with access control, never as attachments.
- Restricted material is never stored outside its system of record.

## Labelling
Every document carries its classification in its metadata. Systems that index documents, including search and AI assistants, must preserve and enforce this label.
""",
    ),
    dict(
        id="POL-OPS-001", title="Incident Management Policy", department="platform",
        access="internal", date="2025-09-01", author="E1011", tags=["operations", "incident", "policy", "severity"],
        body="""
## Severity levels
| Severity | Definition | Response |
|---|---|---|
| SEV1 | Tier 1 customer-facing service unavailable or more than 25% of transactions failing for over 15 minutes | Incident commander within 10 minutes; CTO and communications notified |
| SEV2 | Tier 1 service degraded, or a tier 2 service unavailable | Incident commander within 15 minutes |
| SEV3 | Limited customer impact or a workaround exists | Owning team handles in business hours |
| SEV4 | Internal impact only | Ticket |

## Roles
The incident commander coordinates and decides; they do not debug. The Major Incident Manager on rota acts as commander for SEV1 and SEV2.

## Post-incident review
SEV1 and SEV2 incidents need a written report within five business days, covering timeline, root cause, contributing factors and action items with owners and due dates. Reports are blameless.

## Recurrence
An incident whose root cause matches an earlier incident within twelve months is flagged as recurring. Recurring incidents are reviewed at the monthly reliability review, and their open action items are escalated to the department head.

## Regulatory notification
Payment outages above 60 minutes affecting retail customers must be reported to the regulator by Compliance within 24 hours.
""",
    ),
    dict(
        id="POL-OPS-002", title="Change Management Policy", department="platform",
        access="internal", date="2025-09-01", author="E1016", tags=["operations", "change", "policy"],
        body="""
## Change types
- **Standard**: pre-approved, low risk, repeatable (for example certificate renewal from the inventory, HSM session ceiling increase).
- **Normal**: assessed by the Change Advisory Board weekly.
- **Emergency**: approved by the incident commander and one senior engineer during an incident; reviewed at the next CAB.

## Freeze periods
No normal changes to payment systems from the 25th of each month to the 2nd of the next, or during the week before Sinhala and Tamil New Year, Vesak and Christmas.

## Pricing and fees
Any change that can alter a customer or merchant fee is a normal change, even if the technical change is small.

## Evidence
Each change records a rollback plan, the test evidence, and the service owner's approval.
""",
    ),
    dict(
        id="POL-AI-001", title="Acceptable Use of Generative AI Assistants", department="security",
        access="public", date="2026-05-20", author="E1007", tags=["ai", "policy", "acceptable-use"],
        body="""
## Approved tools
Staff may use the Bank's internal AI assistant for work. External consumer AI tools must not receive Internal, Confidential or Restricted information.

## Your responsibilities
- Check answers against the cited source before acting on them.
- Do not use the assistant to make credit, investment or employment decisions about individuals.
- Do not ask the assistant for content you are not authorized to access. Attempts are logged.

## Assistant behaviour the Bank guarantees
- Answers cite the internal documents they rely on.
- The assistant refuses requests outside your role and does not reveal restricted material.
- Administrative actions taken through the assistant require human approval.
- Conversations are logged for security monitoring and quality improvement.

## Customer communication
Text drafted by the assistant for customers must be reviewed by a person before it is sent.
""",
    ),
    dict(
        id="POL-RSK-004", title="Fraud Monitoring Thresholds", department="risk",
        access="confidential", date="2026-02-28", author="E1006", tags=["fraud", "risk", "thresholds", "cards"],
        body="""
## Scoring thresholds
| Channel | Decline above | Step-up between | Approve below |
|---|---|---|---|
| Card not present | 820 | 640–820 | 640 |
| POS chip and PIN | 900 | 760–900 | 760 |
| Contactless | 860 | 700–860 | 700 |
| Instant transfer | 800 | 600–800 | 600 |

## Fallback policy when the provider is unavailable
If the external score is unavailable or slower than 800 ms, the local rules engine decides. In fallback mode:
- card-not-present transactions above LKR 150,000 are declined,
- contactless transactions are approved up to the contactless limit,
- all other transactions follow local rules.
Fallback mode is logged and reported to Fraud Analytics daily.

## Review
Thresholds are reviewed monthly against the false positive rate and confirmed fraud losses.
""",
    ),
    dict(
        id="POL-SEC-009", title="Cryptographic Key Management and HSM Operations", department="security",
        access="restricted", date="2026-01-10", author="E1008", tags=["security", "cryptography", "hsm", "keys"],
        body="""
## Key custodians
Master keys are split into three components held by three custodians from different teams. No custodian may hold more than one component of the same key.

## Key ceremonies
Key loading takes place in the secure room with two custodians and an Internal Audit witness. Ceremony scripts and logs are stored in the restricted vault.

## HSM administration
- Administrative access to HSM appliances requires two-person authorization.
- Session pool limits are operational settings and can be changed by Cryptography Services on-call as a standard change.
- Firmware updates are tested in the non-production cluster for 30 days.

## Key rotation
Zone master keys rotate every two years; PIN encryption keys every year.

## Compromise
A suspected key compromise is a SEV1 security incident. The CISO decides on key revocation within one hour.
""",
    ),
    dict(
        id="POL-HR-002", title="Flexible and Remote Work Policy", department="hr",
        access="public", date="2025-01-15", author="E1017", tags=["hr", "remote-work", "policy"],
        body="""
## Eligibility
Technology staff may work remotely up to three days a week with manager approval. On-call engineers must be reachable within 10 minutes and have a stable connection.

## Equipment
The Bank provides a laptop and a hardware security key. Personal devices may not access production systems.

## Core hours
Core collaboration hours are 10:00 to 15:00 Sri Lanka time.

## Security
Remote work follows the Information Security Policy. Work from public Wi-Fi requires the corporate VPN.
""",
    ),
]
