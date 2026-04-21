import azure.functions as func
import azure.durable_functions as df  # pip: azure-functions-durable
import json
import logging
from datetime import timedelta

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

VALID_CATEGORIES = {"travel", "meals", "supplies", "equipment", "software", "other"}
TIMEOUT_MINUTES = 2  # short for testing; increase for production


# ---------------------------------------------------------------------------
# Activity: validate_expense
# ---------------------------------------------------------------------------

@app.activity_trigger(input_name="expense")
def validate_expense(expense: dict) -> dict:
    required = ["employeeName", "employeeEmail", "amount", "category", "description", "managerEmail"]
    missing = [f for f in required if not expense.get(f)]
    if missing:
        return {"valid": False, "reason": f"Missing required fields: {', '.join(missing)}"}
    if expense["category"].lower() not in VALID_CATEGORIES:
        return {"valid": False, "reason": f"Invalid category '{expense['category']}'. Valid: {', '.join(VALID_CATEGORIES)}"}
    return {"valid": True}


# ---------------------------------------------------------------------------
# Activity: send_notification
# ---------------------------------------------------------------------------

@app.activity_trigger(input_name="payload")
def send_notification(payload: dict) -> str:
    logging.info(
        "EMAIL to %s — Expense '%s' status: %s",
        payload["employeeEmail"],
        payload["description"],
        payload["status"],
    )
    return f"Notification sent to {payload['employeeEmail']}"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

@app.orchestration_trigger(context_name="context")
def expense_orchestrator(context: df.DurableOrchestrationContext):
    expense = context.get_input()

    # Step 1: Validate
    validation = yield context.call_activity("validate_expense", expense)
    if not validation["valid"]:
        return {"status": "rejected", "reason": validation["reason"]}

    amount = float(expense["amount"])

    # Step 2: Auto-approve if under $100
    if amount < 100:
        result = {"status": "approved", "reason": "Auto-approved: amount under $100"}
    else:
        # Step 3: Wait for manager approval with timeout
        expiry = context.current_utc_datetime + timedelta(minutes=TIMEOUT_MINUTES)
        approval_event = context.wait_for_external_event("ManagerDecision")
        timeout_event = context.create_timer(expiry)

        winner = yield context.task_any([approval_event, timeout_event])

        if winner == approval_event:
            timeout_event.cancel()
            decision = approval_event.result
            if isinstance(decision, str):
                decision = json.loads(decision)
            if decision.get("approved"):
                result = {"status": "approved", "reason": "Manager approved"}
            else:
                result = {"status": "rejected", "reason": decision.get("reason", "Manager rejected")}
        else:
            result = {"status": "escalated", "reason": "No manager response — auto-approved and flagged"}

    # Step 4: Notify employee
    yield context.call_activity("send_notification", {**expense, **result})

    return result


# ---------------------------------------------------------------------------
# Client: start_expense (HTTP trigger)
# ---------------------------------------------------------------------------

@app.route(route="expenses", methods=["POST"])
@app.durable_client_input(client_name="client")
async def start_expense(req: func.HttpRequest, client: df.DurableOrchestrationClient) -> func.HttpResponse:
    try:
        expense = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON"}),
            mimetype="application/json",
            status_code=400,
        )

    instance_id = await client.start_new("expense_orchestrator", client_input=expense)
    logging.info("Started orchestration %s", instance_id)

    # Poll for up to 5 seconds to catch immediate completions (validation errors, auto-approvals)
    import asyncio
    for _ in range(10):
        await asyncio.sleep(0.5)
        status = await client.get_status(instance_id)
        if status.runtime_status.value in ("Completed", "Failed", "Terminated"):
            return func.HttpResponse(
                json.dumps({"instanceId": instance_id, "output": status.output}),
                mimetype="application/json",
                status_code=200,
            )

    # Still running — waiting for manager decision
    return func.HttpResponse(
        json.dumps({"instanceId": instance_id, "message": "Awaiting manager decision. Use instanceId to approve or reject."}),
        mimetype="application/json",
        status_code=202,
    )


# ---------------------------------------------------------------------------
# Status check endpoint
# ---------------------------------------------------------------------------

@app.route(route="expenses/{instanceId}/status", methods=["GET"])
@app.durable_client_input(client_name="client")
async def get_status(req: func.HttpRequest, client: df.DurableOrchestrationClient) -> func.HttpResponse:
    instance_id = req.route_params["instanceId"]
    status = await client.get_status(instance_id)

    if status is None:
        return func.HttpResponse(
            json.dumps({"error": "Instance not found"}),
            mimetype="application/json",
            status_code=404,
        )

    return func.HttpResponse(
        json.dumps({
            "instanceId": instance_id,
            "runtimeStatus": status.runtime_status.value,
            "output": status.output,
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# Manager response: raise external event on the orchestration
# ---------------------------------------------------------------------------

@app.route(route="expenses/{instanceId}/decision", methods=["POST"])
@app.durable_client_input(client_name="client")
async def manager_response(req: func.HttpRequest, client: df.DurableOrchestrationClient) -> func.HttpResponse:
    instance_id = req.route_params["instanceId"]

    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON"}),
            mimetype="application/json",
            status_code=400,
        )

    approved = body.get("approved", False)
    reason = body.get("reason", "")

    status = await client.get_status(instance_id)
    if status is None or status.runtime_status.value not in ("Running", "Pending"):
        return func.HttpResponse(
            json.dumps({"error": "Orchestration not found or already completed"}),
            mimetype="application/json",
            status_code=404,
        )

    await client.raise_event(instance_id, "ManagerDecision", {"approved": approved, "reason": reason})

    return func.HttpResponse(
        json.dumps({"message": f"Decision sent to orchestration {instance_id}"}),
        mimetype="application/json",
        status_code=200,
    )
