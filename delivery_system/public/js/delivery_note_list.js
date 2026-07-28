// Copyright (c) 2024, primetechbd and contributors
// For license information, please see license.txt
//
// List view bulk action: "Send Selected to Courier" for Delivery Note list.

frappe.listview_settings["Delivery Note"] = frappe.listview_settings["Delivery Note"] || {};

const _original_onload_dn = frappe.listview_settings["Delivery Note"].onload;
frappe.listview_settings["Delivery Note"].onload = function (listview) {
	if (_original_onload_dn) _original_onload_dn(listview);

	listview.page.add_actions_menu_item(__("Send Selected to Courier"), () => {
		const selected = listview.get_checked_items(true);
		if (!selected || !selected.length) {
			frappe.msgprint(__("Please select at least one Delivery Note."));
			return;
		}
		frappe.confirm(
			__("Send {0} Delivery Note(s) to courier?", [selected.length]),
			() => {
				frappe.show_progress(__("Booking with courier..."), 20, 100);
				frappe.call({
					method: "delivery_system.api.bulk_send_to_courier",
					args: {
						reference_doctype: "Delivery Note",
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
