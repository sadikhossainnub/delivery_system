// Copyright (c) 2024, primetechbd and contributors
// For license information, please see license.txt
//
// Client script for the Sales Order form — courier integration buttons.

frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		// Only act on submitted Sales Orders
		if (frm.doc.docstatus !== 1) return;

		if (frm.doc.delivery_order_ref) {
			// Already booked — show tracking buttons
			delivery_system.add_tracking_buttons(frm);
		} else {
			// Not yet booked — show "Send to Courier" button
			delivery_system.add_send_button(frm);
		}

		// Render the courier_status badge
		if (frm.doc.courier_status) {
			delivery_system.render_courier_badge(frm);
		}
	},
});
