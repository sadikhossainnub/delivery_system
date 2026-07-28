// Copyright (c) 2024, primetechbd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Courier Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Download User Guide (PDF)"), () => {
			window.open("/api/method/delivery_system.api.download_user_guide");
		}, __("Help"));
	},
});
