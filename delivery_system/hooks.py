app_name = "delivery_system"
app_title = "Delivery System"
app_publisher = "primetechbd"
app_description = "ERPNext Courier Integration for Bangladeshi courier services (Steadfast, Pathao, RedX, Paperfly)"
app_email = "sayedtkg@gmail.com"
app_license = "mit"
app_version = "1.0.0"

# Required apps — must have ERPNext installed
required_apps = ["erpnext"]

# ---------------------------------------------------------------------------
# App includes
# ---------------------------------------------------------------------------

# Load delivery_system_utils.js globally so SO/DN scripts can use it
app_include_js = [
	"/assets/delivery_system/js/delivery_system_utils.js",
]

# ---------------------------------------------------------------------------
# DocType-specific client scripts
# ---------------------------------------------------------------------------

doctype_js = {
	"Sales Order": "public/js/sales_order.js",
	"Delivery Note": "public/js/delivery_note.js",
	"Delivery Order": "public/js/delivery_order.js",
	"Courier Settings": "delivery_system/doctype/courier_settings/courier_settings.js",
}

doctype_list_js = {
	"Sales Order": "public/js/sales_order_list.js",
	"Delivery Note": "public/js/delivery_note_list.js",
}

# ---------------------------------------------------------------------------
# Fixtures (exported data to seed on install/migrate)
# ---------------------------------------------------------------------------

fixtures = [
	{
		"doctype": "Courier Provider",
		"filters": [["provider_code", "in", ["steadfast", "pathao", "redx", "paperfly", "ecourier"]]],
	}
]

# ---------------------------------------------------------------------------
# Scheduled Tasks
# ---------------------------------------------------------------------------

scheduler_events = {
	"cron": {
		# Sync pending delivery statuses every 30 minutes
		"*/30 * * * *": [
			"delivery_system.tasks.sync_pending_deliveries"
		],
	},
	"daily": [
		"delivery_system.tasks.notify_stuck_deliveries"
	],
}

# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Installation hooks
# ---------------------------------------------------------------------------

# Runs once when app is installed: creates Chart of Accounts, Mode of Payment,
# and Courier Settings rows for every ERPNext company.
after_install = "delivery_system.install.after_install"

# Runs on every `bench migrate`: keeps accounting setup in sync for new companies.
after_migrate = ["delivery_system.install.after_migrate"]

# ---------------------------------------------------------------------------
# Document Events
# ---------------------------------------------------------------------------

# doc_events = {
# 	"Sales Order": {
# 		"on_submit": "delivery_system.doc_events.sales_order.on_submit",
# 	},
# }

# ---------------------------------------------------------------------------
# Request Events
# ---------------------------------------------------------------------------

# before_request = ["delivery_system.utils.before_request"]
# after_request = ["delivery_system.utils.after_request"]

# ---------------------------------------------------------------------------
# User Data Protection
# ---------------------------------------------------------------------------

# user_data_fields = []

# ---------------------------------------------------------------------------
# Authentication and authorization
# ---------------------------------------------------------------------------

# auth_hooks = []

# ---------------------------------------------------------------------------
# Log clearing
# ---------------------------------------------------------------------------

default_log_clearing_doctypes = {
	"Delivery Order Log": 90,  # retain for 90 days
}


# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "delivery_system",
# 		"logo": "/assets/delivery_system/logo.png",
# 		"title": "Delivery System",
# 		"route": "/delivery_system",
# 		"has_permission": "delivery_system.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/delivery_system/css/delivery_system.css"
# app_include_js = "/assets/delivery_system/js/delivery_system.js"

# include js, css files in header of web template
# web_include_css = "/assets/delivery_system/css/delivery_system.css"
# web_include_js = "/assets/delivery_system/js/delivery_system.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "delivery_system/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "delivery_system/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "delivery_system.utils.jinja_methods",
# 	"filters": "delivery_system.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "delivery_system.install.before_install"
# after_install = "delivery_system.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "delivery_system.uninstall.before_uninstall"
# after_uninstall = "delivery_system.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "delivery_system.utils.before_app_install"
# after_app_install = "delivery_system.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "delivery_system.utils.before_app_uninstall"
# after_app_uninstall = "delivery_system.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "delivery_system.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"delivery_system.tasks.all"
# 	],
# 	"daily": [
# 		"delivery_system.tasks.daily"
# 	],
# 	"hourly": [
# 		"delivery_system.tasks.hourly"
# 	],
# 	"weekly": [
# 		"delivery_system.tasks.weekly"
# 	],
# 	"monthly": [
# 		"delivery_system.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "delivery_system.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "delivery_system.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "delivery_system.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["delivery_system.utils.before_request"]
# after_request = ["delivery_system.utils.after_request"]

# Job Events
# ----------
# before_job = ["delivery_system.utils.before_job"]
# after_job = ["delivery_system.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"delivery_system.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

