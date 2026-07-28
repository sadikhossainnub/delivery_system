// Copyright (c) 2024, primetechbd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Courier Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Download User Guide (PDF)"), () => {
			window.open("/api/method/delivery_system.api.download_user_guide");
		}, __("Help"));
	},
});

frappe.ui.form.on("Courier Account", {
	form_render(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.webhook_secret) {
			row.webhook_secret = frappe.utils.get_random(32);
		}
		if (!row.webhook_url) {
			row.webhook_url = window.location.origin + "/api/method/delivery_system.webhook.steadfast_webhook";
		}
		frm.refresh_field("courier_accounts");
	}
});
