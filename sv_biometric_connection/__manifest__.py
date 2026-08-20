# -*- coding: utf-8 -*-
{
    "name": "Odoo Biometric Attendance Integration | ZKTeco, Ronald Jack & Queue Job Sync",
    "version": "18.0.1.0.0",
    "category": "Human Resources/Attendance",
    "summary": "Biometric Attendance Device Integration with Odoo HR Attendance via Queue Job (ZKTeco, Ronald Jack, Auto Cron Sync)",
    "description": """
Odoo Biometric Attendance Device Integration (ZKTeco / Ronald Jack)
===================================================================
Seamlessly integrate Odoo 19 HR Attendance with Biometric Devices using Queue Job asynchronous processing.

Key Features:
-------------
* **Biometric Device Integration**: Connect ZKTeco, Ronald Jack, Hikvision, and other devices via pyzk.
* **Queue Job Performance**: Asynchronous background workers prevent HTTP timeouts and freezing UI during heavy data pulls.
* **Smart Auto Cron**: Automatic hourly attendance log downloads with 24-hour historical re-sync capability.
* **Manual Date Range Wizard**: Re-pull attendance logs for custom date ranges effortlessly.
* **Proven Enterprise Performance**: Tested on 80+ devices and over 1,000+ active employees.

Keywords: odoo biometric attendance, zkteco odoo, ronald jack odoo, hr attendance integration, queue job attendance, biometric device sync.
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
    'live_test_url': 'https://www.youtube.com/watch?v=SN_DwPqcj5Y',
    "installable": True,
    "auto_install": False,
    "application": True,
}
