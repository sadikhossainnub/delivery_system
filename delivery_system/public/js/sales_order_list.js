// Copyright (c) 2024, primetechbd and contributors
// For license information, please see license.txt
//
// List view bulk action: "Send Selected to Courier" for Sales Order list.

frappe.listview_settings["Sales Order"] = frappe.listview_settings["Sales Order"] || {};

const _original_onload = frappe.listview_settings["Sales Order"].onload;
frappe.listview_settings["Sales Order"].onload = function (listview) {
	if (_original_onload) _original_onload(listview);

	listview.page.add_actions_menu_item(__("Send Selected to Courier"), () => {
		const selected = listview.get_checked_items(true); // returns array of names
		if (!selected || !selected.length) {
			frappe.msgprint(__("Please select at least one Sales Order."));
			return;
		}
		frappe.confirm(
			__("Send {0} Sales Order(s) to courier?", [selected.length]),
			() => {
				frappe.show_progress(__("Booking with courier..."), 20, 100);
				frappe.call({
					method: "delivery_system.api.bulk_send_to_courier",
					args: {
						reference_doctype: "Sales Order",
						names: selected,
					},
					callback(r) {
						frappe.hide_progress();
						if (r.message) {
							const results = r.message;
							const succeeded = results.filter(x => x.success).length;
							const failed = results.filter(x => !x.success).length;
							frappe.msgprint({
								title: __("Bulk Send Results"),
								message: __("{0} succeeded, {1} failed.", [succeeded, failed]),
								indicator: failed ? "orange" : "green",
							});
							listview.refresh();
						}
					},
				});
			}
		);
	}, true);
};
