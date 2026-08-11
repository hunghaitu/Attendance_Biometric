# Odoo 18 Biometric Device Attendance Integration via Queue Job

This module provides a robust, enterprise-grade integration between Odoo HR Attendance and physical biometric attendance devices (such as **ZKTeco, Ronald Jack**, etc.). Engineered specifically for multi-device environments, it leverages **Queue Jobs** to parallelize data synchronization, eliminating server timeouts and data loss.

## 🚀 Key Features
* **Multi-Brand Hardware Support:** Connects seamlessly with standard network-based biometric devices (ZKTeco, Ronald Jack, and similar communication protocols).
* **Queue Job Architecture:** Breaks massive synchronization tasks into optimized background batches to handle enterprises with numerous high-traffic devices.
* **Smart Automation & Scheduled Cron:** Silently updates attendance records every 60 minutes in the background, automatically pulling and syncing logs from the previous day.
* **On-Demand Manual Pull Wizard:** Allows HR managers to explicitly fetch/re-calculate missing logs by selecting a specific dynamic date range (**Start Date** to **End Date**).
* **Advanced Logging System:** Extends the standard `ir.logging` backend to track **Total Records**, **Successful Syncs**, and target **Failed Records** filtered by hardware device.

## 📁 Repository Structure
```text
Attendance_Biometric/ (Branch: 18.0)
├── sv_biometric_connection/     # Core Odoo Module folder
│   ├── models/
│   ├── views/
│   ├── static/description/      # Contains module dashboard index.html and icon.png
│   └── __manifest__.py
├── odoo.conf.example            # Sample Odoo configuration file for reference
└── README.md                    # Project documentation
