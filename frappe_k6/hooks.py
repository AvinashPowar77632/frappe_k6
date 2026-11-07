app_name = "frappe_k6"
app_title = "Frappe K6"
app_publisher = "Avinash"
app_description = "K6 grafna dynamic"
app_email = "avinashpowar9370@gmail.com"
app_license = "mit"

after_install = "frappe_k6.install.after_install"

add_to_apps_screen = [
    {
        "name": "frappe_k6",
        "logo": "/assets/frappe_k6/images/k6-logo.svg",
        "title": "K6 Monitor",
        "route": "/k6-monitor",
        "has_permission": "frappe_k6.security.has_k6_access",
    },
    {
        "name": "frappe_k6_api_builder",
        "logo": "/assets/frappe_k6/images/k6-logo.svg",
        "title": "API Builder",
        "route": "/api-builder",
        "has_permission": "frappe_k6.security.has_k6_access",
    },
]

doctype_js = {
    "Monitor Settings":  "public/js/monitor_settings.js",
    "Load Test Config":  "public/js/load_test_config.js",
    "Remote Server":     "frappe_k6/doctype/remote_server/remote_server.js",
}


scheduler_events = {
    "all": [
        "frappe_k6.tasks.sync_running_tests",
    ],
    "daily": [
        "frappe_k6.tasks.cleanup_old_reports",
    ],
    "cron": {
        # Grafana Cloud mode: push Frappe metrics every minute (no agent needed)
        "* * * * *": [
            "frappe_k6.grafana_cloud.push_system_metrics",
            "frappe_k6.slow_query.flush_slow_queries",
        ],
    },
}

# Slow Query Log: time every frappe.db.sql call while enabled in Monitor Settings
before_request = ["frappe_k6.slow_query.on_request_start"]
before_job = ["frappe_k6.slow_query.on_job_start"]

# Retention for Slow Query Log (editable in Log Settings)
default_log_clearing_doctypes = {
    "Slow Query Log": 7,
}

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "frappe_k6",
# 		"logo": "/assets/frappe_k6/logo.png",
# 		"title": "Frappe K6",
# 		"route": "/frappe_k6",
# 		"has_permission": "frappe_k6.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/frappe_k6/css/frappe_k6.css"
# app_include_js = "/assets/frappe_k6/js/frappe_k6.js"

# include js, css files in header of web template
# web_include_css = "/assets/frappe_k6/css/frappe_k6.css"
# web_include_js = "/assets/frappe_k6/js/frappe_k6.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "frappe_k6/public/scss/website"

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
# app_include_icons = "frappe_k6/public/icons.svg"

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

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "frappe_k6.utils.jinja_methods",
# 	"filters": "frappe_k6.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "frappe_k6.install.before_install"
# after_install = "frappe_k6.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "frappe_k6.uninstall.before_uninstall"
# after_uninstall = "frappe_k6.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "frappe_k6.utils.before_app_install"
# after_app_install = "frappe_k6.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "frappe_k6.utils.before_app_uninstall"
# after_app_uninstall = "frappe_k6.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "frappe_k6.notifications.get_notification_config"

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
# 		"frappe_k6.tasks.all"
# 	],
# 	"daily": [
# 		"frappe_k6.tasks.daily"
# 	],
# 	"hourly": [
# 		"frappe_k6.tasks.hourly"
# 	],
# 	"weekly": [
# 		"frappe_k6.tasks.weekly"
# 	],
# 	"monthly": [
# 		"frappe_k6.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "frappe_k6.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "frappe_k6.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "frappe_k6.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "frappe_k6.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["frappe_k6.utils.before_request"]
# after_request = ["frappe_k6.utils.after_request"]

# Job Events
# ----------
# before_job = ["frappe_k6.utils.before_job"]
# after_job = ["frappe_k6.utils.after_job"]

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
# 	"frappe_k6.auth.validate"
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

