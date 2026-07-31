// Copyright (c) 2024, primetechbd and contributors
// For license information, please see license.txt
//
// Client script for the Delivery Order form.

frappe.ui.form.on("Delivery Order", {
	refresh(frm) {
		// Show courier action buttons on submitted docs
		if (frm.doc.docstatus === 1) {
			_add_refresh_status_btn(frm);

			if (!["delivered", "cancelled", "partial_delivered"].includes(frm.doc.delivery_status)) {
				_add_return_request_btn(frm);
			}
		}

		// Colour-code the delivery_status indicator
		_render_status_indicator(frm);
	},

	reference_name(frm) {
		if (frm.doc.reference_doctype && frm.doc.reference_name) {
			frappe.db.get_doc(frm.doc.reference_doctype, frm.doc.reference_name).then((ref_doc) => {
				if (!frm.doc.recipient_name) {
					frm.set_value("recipient_name", ref_doc.customer_name || ref_doc.customer || "");
				}
				if (!frm.doc.recipient_phone) {
					const phone = ref_doc.customer_mobile_no || ref_doc.contact_mobile || ref_doc.mobile_no || "";
					if (phone) frm.set_value("recipient_phone", phone);
				}
				if (!frm.doc.recipient_address) {
					const addr = ref_doc.shipping_address || ref_doc.customer_address || "";
					const strip_func = (window.delivery_system && window.delivery_system.strip_html) || (frappe.utils && frappe.utils.strip_html) || function(s){ return s || ""; };
					if (addr) frm.set_value("recipient_address", strip_func(addr));
				}
				if (frm.doc.cod_amount === undefined || frm.doc.cod_amount === null || frm.doc.cod_amount === "") {
					frappe.call({
						method: "delivery_system.api.get_ref_cod_amount",
						args: {
							reference_doctype: frm.doc.reference_doctype,
							reference_name: frm.doc.reference_name
						},
						callback(r) {
							if (r.message !== undefined) {
								frm.set_value("cod_amount", r.message);
							} else {
								const cod = (window.delivery_system && window.delivery_system.get_cod_amount)
									? window.delivery_system.get_cod_amount(ref_doc)
									: (ref_doc.grand_total || ref_doc.rounded_total || 0);
								frm.set_value("cod_amount", cod);
							}
						}
					});
				}
			});
		}
	},
});

function _add_refresh_status_btn(frm) {
	frm.add_custom_button(__("Refresh Status"), () => {
		frappe.show_progress(__("Syncing status..."), 30, 100);
		frappe.call({
			method: "delivery_system.api.sync_single_status",
			args: { delivery_order_name: frm.doc.name },
			callback(r) {
				frappe.hide_progress();
				if (r.message) {
					const { status, previous_status } = r.message;
					frappe.show_alert({
						message: previous_status === status
							? __("Status unchanged: {0}", [status])
							: __("Status updated: {0} → {1}", [previous_status, status]),
						indicator: status === "delivered" ? "green" : "orange",
					}, 5);
					frm.reload_doc();
				}
			},
		});
	}, __("Courier"));
}

function _add_return_request_btn(frm) {
	frm.add_custom_button(__("Request Return"), () => {
		frappe.prompt(
			[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason for return"), reqd: 0 }],
			({ reason }) => {
				frappe.call({
					method: "delivery_system.api.request_return",
					args: { delivery_order_name: frm.doc.name, reason: reason || "" },
					callback(r) {
						frappe.show_alert({ message: __("Return request submitted."), indicator: "blue" }, 4);
						frm.reload_doc();
					},
				});
			},
			__("Request Return"),
			__("Submit")
		);
	}, __("Courier"));
}

function _render_status_indicator(frm) {
	const status = frm.doc.delivery_status;
	if (!status) return;

	const colour_map = {
		pending: "orange",
		in_review: "yellow",
		delivered_approval_pending: "blue",
		partial_delivered_approval_pending: "blue",
		cancelled_approval_pending: "pink",
		delivered: "green",
		partial_delivered: "teal",
		cancelled: "red",
		hold: "grey",
		unknown: "grey",
	};

	const colour = colour_map[status] || "grey";
	const label = frappe.utils.to_title_case(status.replace(/_/g, " "));
	frm.page.set_indicator(label, colour);
}
