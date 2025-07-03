import base64
import json
import requests
import os
import frappe
from datetime import datetime
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PUBLIC_KEY_FILE = os.path.join(BASE_DIR, "public_key.crt")
PRIVATE_KEY_FILE = os.path.join(BASE_DIR, "private_key.pem")


def encrypt_data(data: str, session_key: bytes, iv: bytes) -> str:
    cipher = AES.new(session_key, AES.MODE_CBC, iv)
    padded = pad(data.encode("utf-8"), AES.block_size)
    encrypted = cipher.encrypt(padded)
    return base64.b64encode(encrypted).decode("utf-8")


def encrypt_key(session_key: bytes) -> str:
    with open(PUBLIC_KEY_FILE, "rb") as f:
        pub_key = RSA.import_key(f.read())
    cipher_rsa = PKCS1_v1_5.new(pub_key)
    encrypted_key = cipher_rsa.encrypt(session_key)
    return base64.b64encode(encrypted_key).decode("utf-8")


def decrypt_data(encrypted_data, encrypted_key):
    with open(PRIVATE_KEY_FILE, "rb") as key_file:
        private_key = RSA.import_key(key_file.read())

    encrypted_key_bytes = base64.b64decode(encrypted_key)
    cipher = PKCS1_v1_5.new(private_key)
    session_key = cipher.decrypt(encrypted_key_bytes, None)

    iv = base64.b64decode(encrypted_data)[:16]
    encrypted_data_bytes = base64.b64decode(encrypted_data)[16:]
    cipher = AES.new(session_key, AES.MODE_CBC, iv)
    plaintext = unpad(cipher.decrypt(encrypted_data_bytes), AES.block_size)
    return plaintext.decode("utf-8")


@frappe.whitelist()
def send_otp(doc_name):
    try:
        counter = frappe.db.count("Payment Log", {"purchase_invoice": doc_name})
        icici = frappe.get_doc("ICICI Settings")

        AGGR_ID = icici.aggr_id
        AGGR_NAME = icici.aggr_name
        CORP_ID = icici.corp_id
        USER_ID = icici.user_id
        URN = icici.urn
        OTP_API_URL = icici.otp_url
        API_KEY = icici.api_key

        SESSION_KEY = os.urandom(16)
        IV = os.urandom(16)
        UNIQUEID = f"{doc_name}-{counter + 1}"

        payload = json.dumps({
            "AGGRID": AGGR_ID,
            "AGGRNAME": AGGR_NAME,
            "CORPID": CORP_ID,
            "USERID": USER_ID,
            "URN": URN,
            "UNIQUEID": UNIQUEID
        })

        encrypted_data = encrypt_data(payload, SESSION_KEY, IV)
        encrypted_key = encrypt_key(SESSION_KEY)

        request_body = {
            "requestId": "",
            "service": "LOP",
            "encryptedKey": encrypted_key,
            "oaepHashingAlgorithm": "NONE",
            "iv": base64.b64encode(IV).decode("utf-8"),
            "encryptedData": encrypted_data,
            "clientInfo": "",
            "optionalParam": ""
        }

        response = requests.post(
            OTP_API_URL,
            headers={
                "Content-Type": "application/json",
                "accept": "*/*",
                "APIKEY": API_KEY
            },
            data=json.dumps(request_body)
        )

        if response.status_code == 200:
            resp_json = response.json()
            decrypted_data = decrypt_data(resp_json["encryptedData"], resp_json["encryptedKey"])
            create_payment_log(doc_name, decrypted_data, request_body, SESSION_KEY, IV, UNIQUEID, "Success")
            return {"UNIQUEID": UNIQUEID}
        else:
            create_payment_log(doc_name, response.text, request_body, SESSION_KEY, IV, UNIQUEID, "Failed")
            frappe.log_error(title="OTP Send Failed", message=response.text)
            return response.text

    except Exception as e:
        frappe.log_error(title="OTP Exception", message=frappe.get_traceback())
        return str(e)


def create_payment_log(doc_name, message, otp_payload, SESSION_KEY, IV, UNIQUEID, STATUS):
    pay_log = frappe.new_doc("Payment Log")
    pay_log.purchase_invoice = doc_name
    pay_log.session_key = base64.b64encode(SESSION_KEY).decode("utf-8")
    pay_log.iv = base64.b64encode(IV).decode("utf-8")
    pay_log.uniqueid = UNIQUEID
    pay_log.otp_payload = json.dumps(otp_payload, indent=2)
    pay_log.otp_response = message
    pay_log.status = STATUS
    pay_log.insert(ignore_permissions=True)
