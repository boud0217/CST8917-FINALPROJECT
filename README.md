# CST8917 Final Assignment — Serverless Expense Approval System

| | |
|---|---|
| **Student** | Dolsom BOUDA |
| **Student Number** | 041246719 |
| **Course** | CST8917 — Serverless Applications |
| **Professor** | Ramy Mohamed |
| **Semester** | Winter 2026 |

---

## Overview

This project implements a serverless expense approval system using two different Azure orchestration approaches. Both versions process the same business logic: validate an expense request, auto-approve if under $100, request manager approval if $100 or more, and escalate if no response is received within the timeout period.

- **Version A** — Azure Durable Functions (Human Interaction pattern)
- **Version B** — Azure Logic Apps + Service Bus

---

## Repository Structure

```
CST8917_Final_Assignment/
├── README.md
├── version-a-durable-functions/
│   ├── function_app.py
│   ├── host.json
│   ├── requirements.txt
│   ├── local.settings.example.json
│   ├── client.html
│   └── test-durable.http
├── version-b-logic-apps/
│   ├── function_app.py
│   ├── host.json
│   ├── requirements.txt
│   ├── local.settings.example.json
│   ├── client.html
│   ├── test-expense.http
│   └── screenshots/
└── presentation/
```

---

## Version A — Azure Durable Functions

### Architecture

```
client.html
    │
    ▼
POST /api/expenses  (HTTP Client Trigger)
    │
    ▼
expense_orchestrator  (Orchestrator)
    │
    ├── validate_expense  (Activity)
    │       │
    │       ├── Invalid → return rejected
    │       └── Valid
    │               │
    │               ├── amount < $100 → auto-approve
    │               └── amount >= $100
    │                       │
    │                       ├── wait for ManagerDecision event (2 min timer)
    │                       │       ├── approved → return approved
    │                       │       ├── rejected → return rejected
    │                       │       └── timeout  → return escalated
    │                       └── send_notification  (Activity)
    │
    ▼
GET /api/expenses/{instanceId}/status  (HTTP Trigger)
POST /api/expenses/{instanceId}/decision  (HTTP Trigger)
```

### Functions

| Function | Trigger | Purpose |
|---|---|---|
| `start_expense` | HTTP POST `/api/expenses` | Starts the orchestration |
| `expense_orchestrator` | Orchestration | Chains all activities and handles the Human Interaction pattern |
| `validate_expense` | Activity | Validates required fields and category |
| `send_notification` | Activity | Simulates email notification to employee |
| `get_status` | HTTP GET `/api/expenses/{instanceId}/status` | Returns current orchestration status and output |
| `manager_response` | HTTP POST `/api/expenses/{instanceId}/decision` | Raises external event to resume orchestration |

### Workflow

1. Employee submits expense via `POST /api/expenses`
2. Orchestrator validates the expense
3. If amount < $100 → auto-approved immediately
4. If amount >= $100 → orchestrator waits for a `ManagerDecision` external event with a 2-minute timer
5. Manager approves or rejects via `POST /api/expenses/{instanceId}/decision`
6. If no response within 2 minutes → escalated
7. Employee is notified of the outcome

### Deployment

```bash
cd version-a-durable-functions
pip install -r requirements.txt
func start  # local testing

func azure functionapp publish func-expense-approval-a  # Azure deployment
```

### Configuration

| Setting | Value |
|---|---|
| `AzureWebJobsStorage` | Azure Storage connection string |
| Hub name | `ExpenseApprovalHub` (defined in `host.json`) |

---

## Version B — Logic Apps + Service Bus

### Architecture

```
client.html
    │
    ▼
Service Bus Queue (expense-requests)
    │
    ▼
Logic App (logic-expense-approval)
    │
    ├── Decode Message (Compose)
    ├── Validate Expense (HTTP → func-expense-approval-b)
    ├── Parse Validation Response
    │
    ├── Is Expense Valid?
    │       ├── NO  → Publish Validation Failed → Notify Employee
    │       └── YES
    │               │
    │               ├── Requires Manager Approval?
    │               │       ├── NO  → Publish Auto Approved → Notify Employee
    │               │       └── YES
    │               │               │
    │               │               ├── Request Manager Approval (Send Approval Email)
    │               │               ├── Manager Decision?
    │               │               │       ├── Approve → Publish Approved → Notify Employee
    │               │               │       └── Reject  → Publish Rejected → Notify Employee
    │               │               └── Timeout (2 min) → Publish Escalated → Notify Employee
    │
    ▼
Service Bus Topic (expense-outcomes)
    ├── Subscription: approved  (filter: status = 'approved')
    ├── Subscription: rejected  (filter: status = 'rejected')
    └── Subscription: escalated (filter: status = 'escalated')
```

### Azure Resources

| Resource | Name |
|---|---|
| Function App | `func-expense-approval-b` |
| Service Bus Namespace | `sb-expense-approval` |
| Service Bus Queue | `expense-requests` |
| Service Bus Topic | `expense-outcomes` |
| Topic Subscriptions | `approved`, `rejected`, `escalated` |
| Logic App | `logic-expense-approval` |

### Functions

| Function | Trigger | Purpose |
|---|---|---|
| `validate_expense` | HTTP POST `/api/validate-expense` | Validates expense fields and returns `valid` + `requiresApproval` |
| `manager_decision` | HTTP GET/POST `/api/manager-decision` | Receives manager click and forwards decision to Logic App callback URL |

### Workflow

1. Employee submits expense via client.html → message sent to `expense-requests` queue
2. Logic App triggers on new queue message
3. Message is base64-decoded and sent to `validate-expense` function
4. If invalid → message published to `expense-outcomes` topic with `status=rejected`
5. If valid and amount < $100 → auto-approved, message published with `status=approved`
6. If valid and amount >= $100 → approval email sent to manager with Approve/Reject buttons
7. Manager clicks a button → Logic App resumes
8. If no response within 2 minutes → message published with `status=escalated`
9. Employee receives email notification in all cases

### Deployment

```bash
cd version-b-logic-apps
pip install -r requirements.txt
func start  # local testing

func azure functionapp publish func-expense-approval-b  # Azure deployment
```

### Configuration

| Setting | Value |
|---|---|
| `AzureWebJobsStorage` | Azure Storage connection string |

---

## Comparison Analysis

### 1. Development Experience

**Version A (Durable Functions)** required writing all orchestration logic in Python code. Understanding the Durable Functions programming model, deterministic orchestrators, activity functions, external events, and durable timers, took significant effort. The Human Interaction pattern required careful use of `task_any()` to race the approval event against the timer. Debugging was done locally using `func start` and Azurite, which gave immediate feedback. However, the constraint that orchestrators must be deterministic caused subtle bugs (such as `approval_event.result` returning a JSON string instead of a dict) that were only caught at runtime.

**Version B (Logic Apps)** offloaded orchestration to a visual designer. The Azure Function only handles validation and the manager callback. Building the Logic App was faster initially, but the portal-based workflow introduced friction: renaming actions, configuring run-after conditions for timeout handling, and fixing base64-decoded Service Bus messages all required trial and error in the portal with no local testing capability.

**Winner: Version B** for development speed, **Version A** for confidence that the logic is correct.

### 2. Testability

**Version A** can be fully tested locally using `func start` and Azurite. The `test-durable.http` file covers all 6 scenarios and can be re-run at any time without touching Azure. The orchestration state is inspectable via the `/status` endpoint. Automated tests could be written using pytest with mocked activity functions.

**Version B** cannot be tested locally end-to-end. The Logic App requires Azure Portal access and a live Service Bus connection. The validation function can be tested locally, but the full workflow — including branching, approval email, and timeout, can only be tested against the deployed Azure resources. There is no way to write automated tests for the Logic App itself.

**Winner: Version A** for testability.

### 3. Error Handling

**Version A** gives full control over error handling in Python code. Activity functions can raise exceptions, the orchestrator can catch them, and Durable Functions has built-in retry policies configurable per activity call. If an activity fails, the orchestration instance moves to a Failed state with a full stack trace queryable via the status endpoint.

**Version B** handles errors through the Logic App "Configure run after" settings. Each action can be configured to run after success, failure, timeout, or skipped states. This is flexible but requires manual configuration per action in the portal. The timeout escalation path required setting "has timed out" on the run-after of the escalation action. Error details are visible in the run history but cannot be programmatically queried.

**Winner: Version A** for control over retries and recovery, **Version B** for visibility into errors.

### 4. Human Interaction Pattern

**Version A** implements the Human Interaction pattern natively using `context.wait_for_external_event()` combined with `context.create_timer()` and `context.task_any()`. The orchestrator pauses execution and resumes when the manager POSTs to the `/decision` endpoint. This is the most natural implementation — the pattern is a first-class concept in Durable Functions.

**Version B** does not natively support the Human Interaction pattern. The closest built-in option is the **Send approval email** connector from the Approvals connector, which sends an email with Approve/Reject buttons and pauses the Logic App until the manager clicks. The timeout is configured via the action's Settings tab using ISO 8601 duration format (`PT2M`). This approach is simpler to configure but less flexible — the approval options are limited to what the connector provides.

**Winner: Version A** for flexibility, **Version B** for ease of setup.

### 5. Observability

**Version A** provides built-in orchestration status through the Durable Functions management endpoints (`/status`). Each instance has a full history of events, activity calls, and outputs queryable via the SDK or REST API. However, interpreting the raw JSON output requires developer knowledge.

**Version B** provides run history in the Logic App portal with a visual step-by-step view of each run, showing inputs and outputs at every action. This is significantly more accessible for non-developers to understand what happened in a workflow run. The condition branches, email content, and Service Bus messages are all visible inline.

**Winner: Version B** for operational visibility.

### 6. Cost

Based on the [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/), estimated costs at two volumes:

**Assumptions:**
- Version A: ~6 function executions per request, 128 MB memory, 500ms average duration
- Version B: ~2 function executions, ~12 Logic App actions, ~4 standard connector executions per request
- Service Bus Standard tier required for topic subscriptions (fixed monthly fee ~$9.81)

| Component | Version A (~100/day) | Version B (~100/day) | Version A (~10,000/day) | Version B (~10,000/day) |
|---|---|---|---|---|
| Azure Functions | $0.00 | $0.00 | $0.00 | $0.00 |
| Storage Account | $0.12 | $0.12 | $1.20 | $1.20 |
| Logic Apps actions | — | $0.20 | — | $19.80 |
| Logic App connectors | — | $0.50 | — | $49.50 |
| Service Bus Standard | — | $9.81 | — | $9.81 |
| **Total/month** | **~$0.12** | **~$10.63** | **~$1.20** | **~$80.31** |

At 100 expenses/day (~3,000/month), Version B costs roughly **88x more** than Version A, driven by the Service Bus Standard tier fixed fee. At 10,000 expenses/day (~300,000/month), Logic App action and connector costs dominate and Version B costs **67x more**.

**Winner: Version A** for cost efficiency at all volumes for this use case.

---

## Recommendation

For a production expense approval system, **Version B (Logic Apps + Service Bus)** is the recommended approach for most organizations despite its higher cost.

The primary reason is integration capability. A real expense approval system needs to send emails, integrate with HR systems, connect to ERP platforms, and potentially notify teams via Microsoft Teams or Slack. Logic Apps provides all of these through pre-built connectors with no custom code. The built-in approval email connector alone eliminates the need for a custom callback function and significantly reduces development time.

The visual workflow designer also makes Version B more accessible to business analysts and operations teams who need to understand, audit, or modify the approval process without developer involvement. Run history in the portal provides clear visibility into every step of every workflow execution, which is critical for compliance and auditing in a financial approval system.

Version A is the better choice when the team is Python-first, when the workflow logic is highly complex or algorithmic, when cost is a primary concern, or when strict version control and code review processes are required. Durable Functions also excels in scenarios requiring fan-out/fan-in patterns or very long-running workflows that go beyond Logic Apps limits.

In summary: use **Version B** when integration, accessibility, and operational visibility are priorities. Use **Version A** when code control, cost efficiency, and complex orchestration logic are priorities.

---

## AI Disclosure

This project was developed with the assistance of Amazon Q Developer (AI coding assistant by AWS). Amazon Q was used to generate boilerplate code, suggest implementation patterns, assist with Azure SDK usage, help debug issues during development, and assist in writing the README. All architectural decisions, testing, and final review were performed by the student.

---

## References

- [Azure Durable Functions documentation](https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-overview)
- [Human Interaction pattern — Durable Functions](https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-overview?tabs=python-v2#human)
- [Azure Logic Apps documentation](https://learn.microsoft.com/en-us/azure/logic-apps/logic-apps-overview)
- [Azure Service Bus documentation](https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-messaging-overview)
- [azure-functions-durable Python SDK](https://pypi.org/project/azure-functions-durable/)
- [Service Bus REST API](https://learn.microsoft.com/en-us/rest/api/servicebus/)
- [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/)
