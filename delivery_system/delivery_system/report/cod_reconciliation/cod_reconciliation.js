// Copyright (c) 2024, primetechbd and contributors
// For license information, please see license.txt

frappe.query_reports["COD Reconciliation"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype": "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "reconciliation_status",
			label: __("Reconciliation Status"),
			fieldtype": "Select",
			options: "\nMatched\nUnmatched\nPartial",
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype": "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
	],
	onload(report) {
		report.page.add_inner_button(__("Mark Manually Reconciled"), () => {
			const selected_rows = report.get_checked_items ? report.get_checked_items() : [];

			frappe.prompt(
				[
					{
						fieldname: "delivery_order",
						fieldtype: "Link",
						label: __("Delivery Order"),
						options: "Delivery Order",
						reqd: 1,
					},
					{
						fieldname: "payment_id",
						fieldtype: "Data",
						label: __("Payment / Reference ID"),
						default: "MANUAL",
					},
				],
				({ delivery_order, payment_id }) => {
					frappe.call({
						method: "delivery_system.api.mark_manually_reconciled",
						args: {
							delivery_order_name: delivery_order,
							payment_id: payment_id,
						},
						callback(r) {
							if (r.message && r.message.success) {
								frappe.show_alert({
									message: __("{0} marked as reconciled.", [delivery_order]),
									indicator: "green",
								});
								report.refresh();
							}
						},
					});
				},
				__("Mark Manually Reconciled"),
				__("Save")
			);
		});
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "reconciliation_status" && data) {
			const status = data.reconciliation_status;
			let color = "grey";
			if (status === "Matched") color = "green";
			else if (status === "Partial") color = "orange";
			else if (status === "Unmatched") color = "red";
			value = `<span class="indicator-pill ${color}">${status}</span>`;
		}
		return value;
	},
};
