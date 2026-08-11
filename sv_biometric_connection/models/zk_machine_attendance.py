# -*- coding: utf-8 -*-
from odoo import fields, models


class ZkMachineAttendance(models.Model):
    """Model to hold data from the biometric device"""
    _name = 'zk.machine.attendance'
    _description = 'Attendance'
    _order = 'punching_time desc'

    employee_id = fields.Many2one('hr.employee', string='Employee',required=True)
    device_id = fields.Many2one('biometric.device.details', string='Biometric Device')
    device_id_num = fields.Integer(string='Biometric Device ID',
                                help="The ID of the Biometric Device")
    punch_type = fields.Selection([('0', 'Check In'), ('1', 'Check Out'),
                                   ('2', 'Break Out'), ('3', 'Break In'),
                                   ('4', 'Overtime In'), ('5', 'Overtime Out'),
                                   ('255', 'Duplicate')],
                                  string='Punching Type',
                                  help='Punching type of the attendance')
    attendance_type = fields.Selection([('0', 'Finger'), ('1', 'Face'),
                                        ('2', 'Type_2'), ('3', 'Password'),
                                        ('4', 'Card'), ('255', 'Duplicate')],
                                       string='Category',
                                       help="Attendance detecting methods")
    punching_time = fields.Datetime(string='Punching Time',required=True,
                                    help="Punching time in the device")
    address_id = fields.Many2one('res.partner', string='Working Address',
                                 help="Working address of the employee")
