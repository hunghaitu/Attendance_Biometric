from odoo import models, fields, api


class QueueJob(models.Model):
    _inherit = 'queue.job'

    @api.model
    def _cron_cleanup_stuck_jobs(self):
        today = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        stuck_jobs = self.search([
            ('state', 'in', ['started', 'failed']),
            ('date_created', '<', today)
        ])

        if stuck_jobs:
            stuck_jobs.write({
                'state': 'done',
                'date_done': fields.Datetime.now()
            })
