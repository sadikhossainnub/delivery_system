// Copyright (c) 2024, primetechbd and contributors
// For license information, please see license.txt
//
// Client script for the Delivery Note form — courier integration buttons.
// Mirrors the Sales Order script exactly.

frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;

		if (frm.doc.delivery_order_ref) {
			delivery_system.add_tracking_buttons(frm);
		} else {
			delivery_system.add_send_button(frm);
		}

		if (frm.doc.courier_status) {
			delivery_system.render_courier_badge(frm);
		}
	},
});
