// Copyright (c) 2024, primetechbd and contributors
// For license information, please see license.txt

frappe.query_reports["Courier Delivery Status"] = {
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
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "courier_provider",
			label: __("Courier Provider"),
			fieldtype: "Link",
			options: "Courier Provider",
		},
		{
			fieldname: "delivery_status",
			label: __("Delivery Status"),
			fieldtype": "Select",
			options: "\npending\nin_review\ndelivered_approval_pending\npartial_delivered_approval_pending\ncancelled_approval_pending\ndelivered\npartial_delivered\ncancelled\nhold\nunknown",
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype": "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "delivery_status" && data) {
			const status = data.delivery_status;
			let color = "grey";
			if (status === "delivered") color = "green";
			else if (status === "cancelled") color = "red";
			else if (["pending", "in_review"].includes(status)) color = "orange";
			else if (status === "hold") color = "grey";
			value = `<span class="indicator-pill ${color}">${frappe.utils.to_title_case(status.replace(/_/g, " "))}</span>`;
		}
		return value;
	},
};
