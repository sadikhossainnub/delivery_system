// Copyright (c) 2024, primetechbd and contributors
// Courier Payout — List View: adds "Import Payout" toolbar button

frappe.listview_settings["Courier Payout"] = {
	onload: function (listview) {
		listview.page.add_button(__("Import Payout"), function () {
			frappe.set_route("import-courier-payout");
		}, { icon: "upload", type: "primary" });
	},
};

