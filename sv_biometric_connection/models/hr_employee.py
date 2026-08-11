# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    """Inherit the HR Employee model to add biometric device ID fields"""
    _inherit = 'hr.employee'

    device_id_num = fields.Char(
        string='Biometric Device ID',
        help="Enter the unique ID assigned to the employee on the biometric device",
        tracking=True
    )

    @api.constrains('device_id_num')
    def _check_unique_device_pair(self):
        for rec in self.filtered(lambda r: r.device_id_num):
            duplicate = self.search([
                ('device_id_num', '=', rec.device_id_num),
                ('id', '!=', rec.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    f"Biometric Device ID '{rec.device_id_num}' is already assigned to another employee."
                )
