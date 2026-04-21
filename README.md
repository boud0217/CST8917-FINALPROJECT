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

### 1. Development Complexity

**Version A (Durable Functions)** requires writing all orchestration logic in Python code. The developer must understand the Durable Functions programming model, including the constraints of deterministic orchestrators, activity functions, external events, and durable timers. The Human Interaction pattern requires careful handling of `task_any()` to race the approval event against the timer. This is more complex to write but keeps all logic in one place — `function_app.py`.

**Version B (Logic Apps)** offloads orchestration to a visual designer. The Azure Function only handles validation and the manager callback. The Logic App handles branching, waiting, timeouts, and email sending through pre-built connectors. This is easier to build for someone unfamiliar with code but harder to version-control since the workflow is defined in the Azure Portal.

**Winner: Version B** for development speed, **Version A** for code maintainability.

### 2. Scalability

**Version A** scales automatically with Azure Functions Consumption plan. Each orchestration instance runs independently with state stored in Azure Storage. Durable Functions can handle thousands of concurrent orchestrations with no configuration changes.

**Version B** scales at the Logic App level (Consumption plan runs are independent) and at the Service Bus level (queues and topics handle high throughput natively). However, the Logic App has a maximum run duration and action limits per month on the Consumption plan.

**Winner: Version A** for high-volume scenarios, **Version B** for moderate workloads.

### 3. Maintainability

**Version A** is fully code-based, making it easy to version-control, test, and review. Changes to the workflow require code modifications and redeployment but are traceable through Git history.

**Version B** splits logic between code (the Azure Function) and the visual Logic App designer. The Logic App definition is stored as JSON in Azure but is not easily readable or reviewable in a standard code review. Changes to the workflow require portal access and are harder to track.

**Winner: Version A** for long-term maintainability.

### 4. Monitoring and Observability

**Version A** provides built-in orchestration status through the Durable Functions management endpoints (`/status`). Each instance has a full history of events, activity calls, and outputs queryable via the SDK or REST API.

**Version B** provides run history in the Logic App portal with a visual step-by-step view of each run, showing inputs and outputs at every action. This is significantly more accessible for non-developers to understand what happened in a workflow run.

**Winner: Version B** for operational visibility.

### 5. Cost

**Version A** costs are based on Azure Functions executions and Azure Storage transactions (for Durable state). Based on a realistic scenario of 1,000 expense requests/month:

| Component | Version A | Version B |
|---|---|---|
| Azure Functions | $0.00 | $0.00 |
| Storage Account | $0.12 | $0.12 |
| Logic Apps actions | — | $0.20 |
| Logic App connectors | — | $0.50 |
| Service Bus Standard | — | $9.81 |
| **Total/month** | **~$0.12** | **~$10.63** |

Version A stays within the free tier for both Functions (under 1M executions) and Storage (minimal transactions). Version B's dominant cost is the **Service Bus Standard tier fixed fee (~$9.81/month)** required for topic subscriptions with SQL filters — this cost applies regardless of usage volume. At 1,000 requests/month, Version B costs roughly **88x more** than Version A.

**Winner: Version A** for cost efficiency at low to medium volume.

### 6. Integration Capabilities

**Version A** requires custom code for every integration. Sending emails, connecting to databases, or calling third-party APIs all require writing Python code and managing dependencies.

**Version B** has access to over 400 Logic Apps connectors including Office 365, Outlook, Teams, Salesforce, SAP, and more. The approval email with built-in Approve/Reject buttons is a single action in the designer, no custom code required.

**Winner: Version B** for integration breadth.

---

## Recommendation

For a production expense approval system, **Version B (Logic Apps + Service Bus)** is the recommended approach for most organizations.

The primary reason is integration capability. A real expense approval system needs to send emails, integrate with HR systems, connect to ERP platforms, and potentially notify teams via Microsoft Teams or Slack. Logic Apps provides all of these through pre-built connectors with no custom code. The built-in approval email connector alone eliminates the need for a custom callback function and significantly reduces development time.

The visual workflow designer also makes Version B more accessible to business analysts and operations teams who need to understand, audit, or modify the approval process without developer involvement. Run history in the portal provides clear visibility into every step of every workflow execution.

Version A is the better choice when the team is Python-first, when the workflow logic is highly complex or algorithmic, when cost is a primary concern at scale, or when strict version control and code review processes are required. Durable Functions also excels in scenarios requiring fan-out/fan-in patterns or very long-running workflows (days or weeks) that go beyond Logic Apps limits.

In summary: use **Version B** when integration, accessibility, and operational visibility are priorities. Use **Version A** when code control, cost efficiency, and complex orchestration logic are priorities.

---

## AI Disclosure

This project was developed with the assistance of Amazon Q Developer. Amazon Q was used to assist writing README, presentation and comments in the code, and help debug issues during development. All architectural decisions, coding, testing, and final review were performed by the student.

---

## References

- [Azure Durable Functions documentation](https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-overview)
- [Human Interaction pattern — Durable Functions](https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-overview?tabs=python-v2#human)
- [Azure Logic Apps documentation](https://learn.microsoft.com/en-us/azure/logic-apps/logic-apps-overview)
- [Azure Service Bus documentation](https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-messaging-overview)
- [azure-functions-durable Python SDK](https://pypi.org/project/azure-functions-durable/)
- [Service Bus REST API](https://learn.microsoft.com/en-us/rest/api/servicebus/)
