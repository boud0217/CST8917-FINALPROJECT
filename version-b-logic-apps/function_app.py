import azure.functions as func
import json
import logging
import requests

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

VALID_CATEGORIES = {"travel", "meals", "supplies", "equipment", "software", "other"}


@app.route(route="validate-expense", methods=["POST"])
def validate_expense(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("validate-expense called")

    try:
        expense = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"valid": False, "reason": "Invalid JSON in request body"}),
            mimetype="application/json",
            status_code=400,
        )

    required = ["employeeName", "employeeEmail", "amount", "category", "description", "managerEmail"]
    missing = [f for f in required if not expense.get(f)]
    if missing:
        return func.HttpResponse(
            json.dumps({
                "valid": False,
                "reason": f"Missing required fields: {', '.join(missing)}",
                "employeeName": expense.get("employeeName", "Unknown"),
                "employeeEmail": expense.get("employeeEmail", ""),
            }),
            mimetype="application/json",
            status_code=200,
        )

    if expense["category"].lower() not in VALID_CATEGORIES:
        return func.HttpResponse(
            json.dumps({
                "valid": False,
                "reason": f"Invalid category '{expense['category']}'. Valid: {', '.join(VALID_CATEGORIES)}",
                "employeeName": expense.get("employeeName", "Unknown"),
                "employeeEmail": expense.get("employeeEmail", ""),
            }),
            mimetype="application/json",
            status_code=200,
        )

    try:
        amount = float(expense["amount"])
    except (ValueError, TypeError):
        return func.HttpResponse(
            json.dumps({
                "valid": False,
                "reason": "Amount must be a number",
                "employeeName": expense.get("employeeName", "Unknown"),
                "employeeEmail": expense.get("employeeEmail", ""),
            }),
            mimetype="application/json",
            status_code=200,
        )

    return func.HttpResponse(
        json.dumps({
            "valid": True,
            "employeeName": expense["employeeName"],
            "employeeEmail": expense["employeeEmail"],
            "amount": amount,
            "category": expense["category"].lower(),
            "description": expense["description"],
            "managerEmail": expense["managerEmail"],
            "requiresApproval": amount >= 100,
        }),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# Manager callback — called when manager clicks approve/reject link in email
# Forwards the decision back to the Logic App via the callback URL
# ---------------------------------------------------------------------------

@app.route(route="manager-decision", methods=["GET", "POST"])
def manager_decision(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("manager-decision called via %s", req.method)

    # POST from Logic App HTTP Webhook subscription — extract callbackUrl from body
    if req.method == "POST":
        try:
            body = req.get_json()
            callback_url = body.get("callbackUrl")
        except ValueError:
            callback_url = None
        approved = req.params.get("approved", "false").lower() == "true"
        reason = req.params.get("reason", "Manager approved" if approved else "Manager rejected")
    else:
        # GET from manager clicking the link
        callback_url = req.params.get("callbackUrl")
        approved = req.params.get("approved", "false").lower() == "true"
        reason = req.params.get("reason", "Manager approved" if approved else "Manager rejected")

    if not callback_url:
        return func.HttpResponse(
            json.dumps({"error": "Missing callbackUrl parameter"}),
            mimetype="application/json",
            status_code=400,
        )

    try:
        response = requests.post(
            callback_url,
            json={"approved": approved, "reason": reason},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        return func.HttpResponse(
            json.dumps({"message": f"Decision '{reason}' sent to Logic App", "status": response.status_code}),
            mimetype="application/json",
            status_code=200,
        )
    except Exception as e:
        logging.error("Failed to send decision: %s", str(e))
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            mimetype="application/json",
            status_code=500,
        )
