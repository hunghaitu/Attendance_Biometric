# -*- coding: utf-8 -*-
{
    "name": "Biometric Device Integration",
    "version": "18.0.1.0.0",
    "category": "Human Resources",
    "summary": "Integrating Biometric Device With HR",
    "description": """This module integrates Odoo with the biometric device.
    Supports synchronization with hr_attendance and handles data queuing efficiently.
    """,
    "author": "Quang",
    "website": "https://www.facebook.com/quang.nguyenhuy.2005",
    "price": 60.00,
    "currency": "USD",
    "license": "OPL-1",
    "depends": [
        "base",
        "queue_job",
        "mail",
        "hr",
        "hr_attendance",
    ],
    "external_dependencies": {
        "python": ["pyzk"],
    },
    "data": [
        "security/ir.model.access.csv",
        "data/cron_download.xml",
        "views/biometric_device_details_views.xml",
        "views/hr_employee_views.xml",
        "views/zk_machine_attendance.xml",
        "views/ir_logging.xml",
        "wizards/pull_all_attendance.xml",
        "views/biometric_device_attendance_menus.xml",
    ],
    "images": [
        "static/description/screenshot.png",
    ],
    "assets": {
        "web.assets_backend": [],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
