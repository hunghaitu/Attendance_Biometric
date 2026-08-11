# -*- coding: utf-8 -*-
from odoo import fields, models, api

class IrLogging(models.Model):
    """Inherit the Odoo Logging model to track biometric sync metrics"""
    _inherit = 'ir.logging'

    device_id = fields.Many2one('biometric.device.details', string='Biometric Device')
    pull_hand = fields.Boolean(string='Manual Pull', default=False)
    success_record = fields.Float(string='Successful Records')
    failed_record = fields.Float(string='Failed Records')
    total_record = fields.Float(string='Total Records', compute='_compute_total_record')

    @api.depends('success_record', 'failed_record')
    def _compute_total_record(self):
        for record in self:
            # Optimized to handle cases where one of the values might be 0 or False
            record.total_record = (record.success_record or 0.0) + (record.failed_record or 0.0)
