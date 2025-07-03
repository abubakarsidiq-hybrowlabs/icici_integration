frappe.ui.form.on('Purchase Invoice', {
    refresh: function(frm) {
        if (frm.doc.docstatus === 1 && frm.doc.status != "Paid") {
            frm.add_custom_button('Make Payment', () => {
                send_otp_to_mobile_number(frm);
            });

            setTimeout(() => {
                let button = frm.page.wrapper.find('button:contains("Make Payment")');
                button.css({
                    'background-color': '#007bff',
                    'color': 'white',
                    'border': '1px solid #007bff',
                    'border-radius': '4px'
                });
            }, 100);
        }
    }
});

function send_otp_to_mobile_number(frm) {
    frappe.call({
        method: 'icici_integration.icici_apis.otp_api.send_otp',
        freeze: true,
        freeze_message: 'Sending OTP to registered mobile number...',
        args: {
            doc_name: frm.doc.name
        },
        callback: function(r) {
            if (r.message === "Success") {
                let UNIQUEID = r.message.UNIQUEID;
                frappe.show_alert({ message: __('OTP Sent Successfully'), indicator: 'green' });
                show_payment_otp_dialog(frm, UNIQUEID);
            } else {
                frappe.msgprint({
                    title: __('OTP Sending Failed'),
                    message: r.message || 'An unexpected error occurred.',
                    indicator: 'red'
                });
            }
        }
    });
}

function show_payment_otp_dialog(frm) {
    let dialog = new frappe.ui.Dialog({
        title: 'Enter OTP to Proceed with Payment',
        fields: [
            {
                label: 'OTP',
                fieldname: 'otp',
                fieldtype: 'Data',
                reqd: 1
            }
        ],
        primary_action_label: 'Pay Now',
        primary_action(values) {
            if (!values.otp) {
                frappe.msgprint(__('Please enter OTP'));
                return;
            }

            dialog.set_primary_action(__('Processing...'), null, true);

            frappe.call({
                method: 'icici_integration.icici_apis.paymnet_api.make_payment',
                args: {
                    doc_name: frm.doc.name,
                    otp: values.otp,
                    UNIQUEID: UNIQUEID
                },
                freeze: true,
                freeze_message: 'Processing Payment...',
                callback: function(r) {
                    dialog.set_primary_action('Pay Now', () => {}); // re-enable button
                    if (r.message === "Success") {
                        frappe.msgprint(__('Payment Successful'));
                        dialog.hide();
                        frm.reload_doc();
                    } else {
                        frappe.msgprint({
                            title: __('Payment Failed'),
                            message: r.message || 'OTP verification failed or payment was declined.',
                            indicator: 'red'
                        });
                    }
                }
            });
        },
        secondary_action_label: 'Resend OTP',
        secondary_action() {
            dialog.hide();
            send_otp_to_mobile_number(frm);
        }
    });

    dialog.show();
}
