import os
import json
import base64
import requests
import frappe
from datetime import datetime
from frappe.utils import nowdate
from icici_integration.icici_apis.otp_api import encrypt_data, encrypt_key, decrypt_data


def make_payment(doc_name, otp, UNIQUEID):
    icici = frappe.get_doc("ICICI Settings")
    AGGR_ID = icici.aggr_id
    AGGR_NAME = icici.aggr_name
    CORP_ID = icici.corp_id
    USER_ID = icici.user_id
    URN = icici.urn
    PAYMENT_API_URL = icici.payment_url
    API_KEY = icici.api_key
    debit_account_no = icici.debit_account_no
    debit_account = icici.debit_account
    ifsc_code = icici.ifsc_code
    mode_of_payment = icici.mode_of_payment

    # Get Purchase Invoice
    purchase_invoice = frappe.get_doc("Purchase Invoice", doc_name)
    total_amt = float(purchase_invoice.rounded_total)

    # Generate session key and IV
    SESSION_KEY = os.urandom(16)
    IV = os.urandom(16)

    # Prepare payload for ICICI
    payload_json = json.dumps({
        "AGGRID": AGGR_ID,
        "AGGRNAME": AGGR_NAME,
        "CORPID": CORP_ID,
        "USERID": USER_ID,
        "URN": URN,
        "UNIQUEID": UNIQUEID,
        "DEBITACC": debit_account_no,
        "CREDITACC": credit_account,
        "IFSC": ifsc_code,
        "AMOUNT": total_amt,
        "CURRENCY": "INR",
        "TXNTYPE": "OWN",
        "PAYEENAME": purchase_invoice.supplier_name,
        "REMARKS": f"Payment for PI: {doc_name}",
        "OTP": otp,
        "CUSTOMERINDUCED": "N"
    })

    # Encrypt data
    encrypted_data = encrypt_data(payload_json, SESSION_KEY, IV)
    encrypted_key = encrypt_key(SESSION_KEY)

    api_payload = {
        "requestId": UNIQUEID,
        "service": "LOP",
        "encryptedKey": encrypted_key,
        "oaepHashingAlgorithm": "NONE",
        "iv": base64.b64encode(IV).decode('utf-8'),
        "encryptedData": encrypted_data,
        "clientInfo": "",
        "optionalParam": ""
    }

    # Send request to ICICI
    response = requests.post(
        PAYMENT_API_URL,
        headers={
            'Content-Type': 'application/json',
            'accept': '*/*',
            'APIKEY': API_KEY
        },
        data=json.dumps(api_payload)
    )

    if response and response.status_code == 200:
        try:
            response_data = response.json()
            decrypted_data = decrypt_data(response_data["encryptedData"], response_data["encryptedKey"])
            decrypted_data_json = json.loads(decrypted_data)

            # Save logs and create payment entry
            update_on_payment_log(doc_name, UNIQUEID, api_payload, decrypted_data_json, "Success")
            create_payment_entry(doc_name, total_amt, debit_account, mode_of_payment)

        except Exception as e:
            update_on_payment_log(doc_name, UNIQUEID, api_payload, response, "Failed")
            frappe.log_error(frappe.get_traceback(), "ICICI Payment Decryption Error")
            frappe.throw("Payment succeeded, but failed to decrypt ICICI response.")
    else:
        update_on_payment_log(doc_name, UNIQUEID, api_payload, response, "Failed")
        frappe.log_error(response.text, "ICICI Payment API Error")
        frappe.throw(f"Payment API request failed with status {response.status_code}")


def update_on_payment_log(doc_name, UNIQUEID, payment_payload, payment_response, payment_transaction_status):
    # Update Payment Log with payload and response
    pay_log = frappe.get_doc("Payment Log", {
        'purchase_invoice': doc_name,
        'uniqueid': UNIQUEID
    })

    pay_log.payment_payload = json.dumps(payment_payload, indent=2)
    pay_log.payment_response = json.dumps(payment_response, indent=2)
    pay_log.payment_transaction_status = payment_transaction_status
    pay_log.save(ignore_permissions=True)


def create_payment_entry(doc_name, amount, debit_account, mode_of_payment):
    pi = frappe.get_doc("Purchase Invoice", doc_name)
    payment_entry = frappe.new_doc("Payment Entry")
    payment_entry.payment_type = "Pay"
    payment_entry.company = pi.company
    payment_entry.posting_date = nowdate()
    payment_entry.party_type = "Supplier"
    payment_entry.party = pi.supplier
    payment_entry.party_name = pi.supplier_name
    payment_entry.mode_of_payment = mode_of_payment
    payment_entry.paid_from = debit_account
    payment_entry.paid_to = pi.credit_to
    payment_entry.paid_amount = amount
    payment_entry.received_amount = amount
    payment_entry.reference_no = f"ICICI-{doc_name}"
    payment_entry.reference_date = nowdate()

    # Add Purchase Invoice reference
    payment_entry.append("references", {
        "reference_doctype": "Purchase Invoice",
        "reference_name": doc_name,
        "total_amount": pi.rounded_total,
        "outstanding_amount": pi.outstanding_amount,
        "allocated_amount": amount
    })

    payment_entry.flags.ignore_permissions = True
    payment_entry.save()
    payment_entry.submit()