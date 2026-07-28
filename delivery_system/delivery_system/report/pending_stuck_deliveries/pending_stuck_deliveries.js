// Copyright (c) 2024, primetechbd and contributors
// For license information, please see license.txt

frappe.query_reports["Pending Stuck Deliveries"] = {
	filters: [
		{
			fieldname: "min_days_pending",
			label: __("Minimum Days Pending"),
			fieldtype: "Int",
			default: 3,
			reqd: 1,
		},
		{
			fieldname: "courier_provider",
			label: __("Courier Provider"),
			fieldtype: "Link",
			options: "Courier Provider",
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
		if (column.fieldname === "days_pending" && data && data.days_pending >= 5) {
			value = `<span style="color:red; font-weight:bold;">${data.days_pending} days</span>`;
		}
		return value;
	},
};
