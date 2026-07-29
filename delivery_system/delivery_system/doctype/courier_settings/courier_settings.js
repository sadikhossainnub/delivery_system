// Copyright (c) 2024, primetechbd and contributors
// For license information, please see license.txt

frappe.ui.form.on("Courier Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Download User Guide (PDF)"), () => {
			window.open("/api/method/delivery_system.api.download_user_guide");
		}, __("Help"));

		frm.add_custom_button(__("Test Connection"), () => {
			frappe.call({
				method: "delivery_system.api.test_courier_connection",
				args: {},
				freeze: true,
				freeze_message: __("Testing connection to Steadfast..."),
				callback(r) {
					if (r.message && r.message.success) {
						frappe.msgprint({
							title: __("Connection Successful ✓"),
							indicator: "green",
							message: __("Steadfast API connected successfully.<br><b>Balance:</b> {0}", [
								r.message.balance !== undefined ? "৳ " + r.message.balance : "N/A",
							]),
						});
					} else {
						frappe.msgprint({
							title: __("Connection Failed ✗"),
							indicator: "red",
							message: __(
								"<b>Error:</b> {0}<br><br>Please check your API Key and Secret Key in the Courier Accounts table below.",
								[r.message ? r.message.error : __("Unknown error")]
							),
						});
					}
				},
			});
		}, __("Diagnostics"));
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
