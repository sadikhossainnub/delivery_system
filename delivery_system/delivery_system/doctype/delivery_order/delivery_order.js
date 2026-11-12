// Copyright (c) 2026, primetechbd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Delivery Order", {
	refresh(frm) {
		if (frm.is_new()) return;

		// 1. Sync Status button
		if (frm.doc.consignment_id) {
			frm.add_custom_button(__("Sync Courier Status"), () => {
				frappe.call({
					method: "delivery_system.api.sync_single_status",
					args: {
						delivery_order_name: frm.doc.name,
					},
					freeze: true,
					freeze_message: __("Syncing status with courier..."),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __("Status synced: {0}", [r.message?.status || frm.doc.delivery_status]),
								indicator: "green",
							});
							frm.reload_doc();
						}
					},
				});
			}, __("Actions"));
		}

		// 2. Post / Retry Clearing Payment Entry button
		const isDelivered = ["delivered", "partial_delivered"].includes(frm.doc.delivery_status);
		const notPosted = !frm.doc.clearing_entry_posted;
		const hasCod = flt(frm.doc.cod_amount) > 0;

		if (isDelivered && hasCod && notPosted) {
			frm.add_custom_button(__("Post Payment Entry"), () => {
				frappe.confirm(
					__("Create Payment Entry against Sales Invoice for COD amount {0}?", [
						format_currency(frm.doc.cod_amount),
					]),
					() => {
						frappe.call({
							method: "delivery_system.accounting.retry_clearing_entry",
							args: {
								delivery_order_name: frm.doc.name,
								force: false,
							},
							freeze: true,
							freeze_message: __("Creating Payment Entry..."),
							callback(r) {
								if (r.message && r.message.success) {
									frappe.show_alert({
										message: __("Payment Entry {0} created successfully!", [
											r.message.payment_entry,
										]),
										indicator: "green",
									});
									frm.reload_doc();
								} else {
									frappe.msgprint({
										title: __("Payment Entry Failed"),
										indicator: "red",
										message: r.message?.error || __("Failed to create Payment Entry. Check Error Logs."),
									});
								}
							},
						});
					}
				);
			}).addClass("btn-primary");
		}

		// 3. Quick shortcut to created Payment Entry
		if (frm.doc.clearing_payment_entry) {
			frm.add_custom_button(__("View Payment Entry"), () => {
				frappe.set_route("Form", "Payment Entry", frm.doc.clearing_payment_entry);
			}, __("Accounting"));
		}
	},
});
