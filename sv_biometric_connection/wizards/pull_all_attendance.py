from odoo import fields, models
from odoo.exceptions import ValidationError
import math

class PullAllAttendance(models.TransientModel):
    _name = 'pull.all.attendance'
    _description = 'Pull Attendance Records'

    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)

    def action_pull_attendance(self):
        """Triggered when the 'Pull All Attendance Data' button is clicked"""
        self.ensure_one()
        start_date = self.start_date
        end_date = self.end_date
        if not start_date or not end_date:
            raise ValidationError("Please select the date range required to pull attendance data!")

        # Batch calculation
        Device = self.env['biometric.device.details']
        total_devices = Device.search_count([])
        batch_size = 1
        total_batches = math.ceil(total_devices / batch_size)

        for batch_index in range(total_batches):
            # Create a queue job for each device batch
            Device.with_delay(priority=10, max_retries=1).job_run_download_batch_by_date(
                batch_index, batch_size, start_date, end_date
            )

        # Trigger the sync job after the download batches are queued
        Device.with_delay(priority=12, max_retries=1).cron_queue_sync_attendance_by_date(
            start_date, end_date
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Initializing attendance synchronization jobs!',
                'message': f'Successfully created {total_batches} batch jobs to pull attendance from {start_date} to {end_date}.',
                'type': 'success',
                'sticky': False,
            },
        }
