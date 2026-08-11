# -*- coding: utf-8 -*-
import datetime
import logging
import pytz
import socket
import time
import math
from functools import wraps
from collections import defaultdict
from dateutil.relativedelta import relativedelta
from psycopg2.extras import execute_values

from odoo import api, fields, models, _, registry, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Datetime

_logger = logging.getLogger(__name__)
try:
    from zk import ZK
except ImportError:
    _logger.error("Please Install pyzk library.")


def log_exception_to_ir_logging(env, message, func_name="unknown", path=__name__, device_id=False, err_name='biometric_error', pull_hand=False, success_record=0, failed_record=0):
    dbname = env.cr.dbname
    with registry(dbname).cursor() as cr:
        new_env = api.Environment(cr, env.uid, env.context)
        new_env['ir.logging'].sudo().create({
            'name': err_name,
            'pull_hand': pull_hand,
            'device_id': device_id,
            'type': 'server',
            'level': 'ERROR',
            'dbname': dbname,
            'message': message,
            'success_record': success_record,
            'failed_record': failed_record,
            'path': path,
            'func': func_name,
            'line': '0',
        })
        cr.commit()


def timing_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        elapsed_time = end_time - start_time
        print(f"Function '{func.__name__}' executed in {elapsed_time:.4f} seconds.")
        return result

    return wrapper


class BiometricDeviceDetails(models.Model):
    _name = 'biometric.device.details'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Biometric Device Details'

    name = fields.Char(string='Name', required=True, help='Record Name')
    dns_domain = fields.Char(string='DNS Domain', help='DNS domain for multiple devices (e.g., company.ddns.net)')
    device_ip = fields.Char(string='Device IP', help='The IP address of the Device (leave empty if using DNS)')
    device_hostname = fields.Char(string='Device Hostname', help='Hostname of specific device (used with DNS domain)')
    port_number = fields.Integer(string='Port Number', required=True, default=4370, help="The Port Number of the Device")
    device_serial = fields.Char(string='Device Serial/ID', help='Unique identifier for this device')
    address_id = fields.Many2one('res.partner', string='Working Address', help='Working address of the partner')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.user.company_id.id, help='Current Company')

    connection_type = fields.Selection([
        ('ip', 'Direct IP'),
        ('dns', 'DNS Domain'),
        ('hostname', 'Hostname + DNS')
    ], string='Connection Type', default='ip', required=True)

    device_username = fields.Char(string='Device Username', help='Username for device authentication')
    device_password = fields.Char(string='Device Password', help='Password for device authentication')
    start_date = fields.Date('Start Date', help='Start date to pull attendance data')
    end_date = fields.Date('End Date', help='End date to pull attendance data')
    late_time_done = fields.Datetime(string='Last Sync Time', help='The time when the attendance was last synced', tracking=True)
    late_time_connect_fail = fields.Datetime(string='Last Failed Connection Time', help='The time when the last connection failed', tracking=True)
    responsible_user_id = fields.Many2one('res.users', string='Responsible User', help='User who receives notifications when connection is lost', tracking=True)

    def _get_local_tz(self):
        user_tz = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        try:
            return pytz.timezone(user_tz)
        except pytz.UnknownTimeZoneError:
            _logger.warning(f"Unknown timezone '{user_tz}', falling back to UTC.")
            return pytz.utc

    @api.constrains('connection_type', 'device_ip', 'dns_domain', 'device_hostname')
    def _check_connection_fields(self):
        for record in self:
            if record.connection_type == 'ip' and not record.device_ip:
                raise ValidationError(_("Device IP is required when using Direct IP connection."))
            if record.connection_type == 'dns' and not record.dns_domain:
                raise ValidationError(_("DNS Domain is required when using DNS connection."))
            if record.connection_type == 'hostname' and (not record.dns_domain or not record.device_hostname):
                raise ValidationError(_("Both DNS Domain and Device Hostname are required when using Hostname + DNS connection."))

    def _get_device_address(self):
        if self.connection_type == 'ip':
            return self.device_ip
        if self.connection_type == 'dns':
            return self.dns_domain
        if self.connection_type == 'hostname':
            return f"{self.device_hostname}.{self.dns_domain}" if self.device_hostname and self.dns_domain else self.dns_domain
        return self.device_ip

    def _resolve_hostname(self, hostname):
        try:
            ip = socket.gethostbyname(hostname)
            _logger.info(f"Resolved {hostname} to {ip}")
            return ip
        except socket.gaierror as e:
            _logger.error(f"Failed to resolve hostname {hostname}: {e}")
            raise UserError(_(f"Cannot resolve hostname {hostname}. Please check DNS settings.")) from e

    def device_connect(self, zk):
        try:
            conn = zk.connect()
            return conn
        except Exception as e:
            _logger.error(f"Device connection failed: {e} from {self.name}")
            return False

    def _create_zk_connection(self):
        device_address = self._get_device_address()
        if self.connection_type in ['dns', 'hostname']:
            try:
                resolved_ip = self._resolve_hostname(device_address)
                _logger.info(f"Using resolved IP {resolved_ip} for {device_address}")
                connection_address = resolved_ip
            except Exception:
                _logger.info(f"Using hostname directly: {device_address}")
                connection_address = device_address
        else:
            connection_address = device_address

        password = self.device_password if self.device_password else False
        zk = ZK(connection_address, port=self.port_number, timeout=30, password=password, ommit_ping=True)
        return zk

    def action_test_connection(self):
        try:
            zk = self._create_zk_connection()
            if zk.connect():
                zk.disconnect()
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': f'Successfully Connected to {self._get_device_address()}:{self.port_number}',
                        'type': 'success',
                        'sticky': False
                    }
                }
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': 'Failed to connect to device.',
                    'type': 'danger',
                    'sticky': False
                }
            }
        except Exception as error:
            _logger.error(f"Connection failed: {error} from {self.name}")
            raise ValidationError(f'Connection failed: {error} from {self.name}') from error

    def notify_responsible_connection_failed(self):
        self.ensure_one()
        self.late_time_connect_fail = fields.Datetime.now()

        if self.responsible_user_id:
            local_tz = self._get_local_tz()
            time_error_utc = self.late_time_connect_fail.replace(tzinfo=pytz.utc)
            time_error_local = time_error_utc.astimezone(local_tz)
            time_error_str = time_error_local.strftime("%Y-%m-%d %H:%M:%S")

            message = (
                f"⚠️ Biometric Device: {self.name} error at {time_error_str}. "
                f"Please check power supply, network cable, IP configuration or restart the device."
            )

            self.env['bus.bus']._sendone(
                self.responsible_user_id.partner_id,
                'simple_notification',
                {
                    'title': f'⚠️ Biometric Device {self.name} disconnected',
                    'message': message,
                    'sticky': False,
                    'type': 'danger',
                },
            )

        _logger.warning(f"[{self.name}] Connection failed — device unreachable.")
        self.env.cr.commit()

    def action_clear_attendance(self):
        for info in self:
            try:
                zk = info._create_zk_connection()
                conn = self.device_connect(zk)
                if conn:
                    conn.enable_device()
                    clear_data = zk.get_attendance()
                    if clear_data:
                        conn.clear_attendance()
                        self._cr.execute("DELETE FROM zk_machine_attendance")
                        conn.disconnect()
                    else:
                        raise UserError(_('Unable to clear Attendance log. Are you sure attendance log is not empty?'))
                else:
                    raise UserError(_('Unable to connect to Attendance Device. Please use Test Connection button to verify.'))
            except Exception as error:
                raise ValidationError(f'{error}') from error

    @timing_decorator
    def action_download_attendance(self):
        self.ensure_one()
        _logger.info(f"Downloading attendance from {self.name} ({self._get_device_address()})")

        try:
            zk = self._create_zk_connection()
        except NameError as exc:
            _logger.error(f"[{self.name}] Pyzk module not found. Error: {str(exc)}")
            return False

        conn = self.device_connect(zk)
        if not conn:
            _logger.info(f"[{self.name}] No attendance data found.")
            return True

        try:
            conn.disable_device()
            users = conn.get_users()
            attendance = conn.get_attendance()

            if not attendance:
                conn.enable_device()
                conn.disconnect()
                _logger.warning(f"No attendance data found on device {self.name}")
                return True

            device_users_map = {user.user_id: user.name for user in users}
            device_user_ids = list(set(each.user_id for each in attendance))

            employee_mapping = {}
            if device_user_ids:
                placeholders = ','.join(['%s'] * len(device_user_ids))
                query_employees = f"""
                    SELECT device_id_num, id 
                    FROM hr_employee 
                    WHERE device_id_num IN ({placeholders})
                """
                self.env.cr.execute(query_employees, device_user_ids)
                employee_mapping = dict(self.env.cr.fetchall())

            attendance_records = []
            unverified_users = []
            local_tz = self._get_local_tz()
            now_local = datetime.datetime.now(local_tz)
            start_today_local = datetime.datetime(now_local.year, now_local.month, now_local.day, 0, 0, 0)
            start_today_local = local_tz.localize(start_today_local)
            start_today_utc = start_today_local.astimezone(pytz.utc)
            end_utc = (start_today_local + datetime.timedelta(days=1)).astimezone(pytz.utc)

            for each in attendance:
                try:
                    atten_time = each.timestamp
                    local_dt = local_tz.localize(atten_time, is_dst=None)
                    utc_dt = local_dt.astimezone(pytz.utc)
                    if utc_dt < start_today_utc or utc_dt > end_utc:
                        continue

                    utc_dt_str = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
                    atten_time = datetime.datetime.strptime(utc_dt_str, "%Y-%m-%d %H:%M:%S")
                    formatted_time = fields.Datetime.to_string(atten_time)

                    if each.user_id in employee_mapping:
                        attendance_records.append({
                            'employee_id': employee_mapping[each.user_id],
                            'device_id': self.id,
                            'device_id_num': each.user_id,
                            'attendance_type': str(each.status),
                            'punch_type': str(each.punch),
                            'punching_time': formatted_time,
                            'address_id': self.address_id.id if self.address_id else None
                        })
                    else:
                        user_name = device_users_map.get(each.user_id, 'Unknown')
                        unverified_users.append((each.user_id, user_name))
                except Exception as err:
                    _logger.warning(f"Skipped invalid attendance record from device {self.name}: {err}")
                    continue

            for user_id, user_name in set(unverified_users):
                _logger.info(f"Employee unverified: {user_id} with name {user_name} in device {self.name}")

            if attendance_records:
                keys = [
                    (int(r['device_id_num']), r['punching_time'], str(r['punch_type']), int(r['device_id']))
                    for r in attendance_records
                ]

                existing_keys = set()
                if keys:
                    query = """
                        SELECT CONCAT(z.device_id_num, '|', z.punching_time, '|', z.punch_type, '|', z.device_id) AS key
                        FROM zk_machine_attendance z
                        INNER JOIN (
                            VALUES %s
                        ) AS t(device_id_num, punching_time, punch_type, device_id)
                        ON z.device_id_num = t.device_id_num
                        AND z.punching_time = t.punching_time
                        AND z.punch_type = t.punch_type
                        AND z.device_id = t.device_id
                    """
                    template = "(%s::integer, %s::timestamp, %s::varchar, %s::integer)"
                    execute_values(self.env.cr, query, keys, template=template, page_size=500)
                    existing_keys = {row[0] for row in self.env.cr.fetchall()}

                new_records = []
                for record in attendance_records:
                    key = f"{record['device_id_num']}|{record['punching_time']}|{record['punch_type']}|{record['device_id']}"
                    if key not in existing_keys:
                        new_records.append(record)

                if new_records:
                    insert_query = """
                        INSERT INTO zk_machine_attendance
                        (employee_id, device_id, device_id_num, attendance_type,
                        punch_type, punching_time, address_id, create_date, write_date,
                        create_uid, write_uid)
                        VALUES %s
                    """
                    current_time = fields.Datetime.now()
                    current_user_id = self.env.user.id
                    insert_vals = [
                        (
                            r['employee_id'], r['device_id'], r['device_id_num'], r['attendance_type'],
                            r['punch_type'], r['punching_time'], r['address_id'], current_time, current_time,
                            current_user_id, current_user_id,
                        )
                        for r in new_records
                    ]
                    execute_values(self.env.cr, insert_query, insert_vals, template=None, page_size=500)
                    _logger.info(f"Successfully inserted {len(new_records)} records from device {self.name}")
                    self.env.cr.commit()
                else:
                    _logger.info("No new attendance records to insert (all duplicates).")

            conn.enable_device()
            conn.disconnect()
            _logger.info(f"Successfully processed {len(attendance)} attendance records from {self.name}")
            return True
        except Exception as e:
            try:
                conn.enable_device()
                conn.disconnect()
            except Exception:
                pass
            _logger.error(f"Error during attendance download from {self.name}: {str(e)}")
            return True
        finally:
            try:
                conn.enable_device()
                conn.disconnect()
            except Exception:
                pass

    def action_restart_device(self):
        zk = self._create_zk_connection()
        conn = self.device_connect(zk)
        if conn:
            conn.restart()
            conn.disconnect()
        else:
            raise UserError(_('Unable to connect to restart device'))

    def sync_attendance_today(self):
        try:
            local_tz = self._get_local_tz()
            now = datetime.datetime.now(local_tz)
            today_date = now.date()

            start_local = local_tz.localize(datetime.datetime.combine(today_date, datetime.time.min))
            end_local = local_tz.localize(datetime.datetime.combine(today_date, datetime.time.max))
            start_utc = start_local.astimezone(pytz.utc)
            end_utc = end_local.astimezone(pytz.utc)

            zk_attendance = self.env['zk.machine.attendance'].search([
                ('punching_time', '>=', start_utc),
                ('punching_time', '<=', end_utc),
                ('employee_id', '!=', False),
            ])
            if not zk_attendance:
                return

            attendance_map = defaultdict(list)
            for rec in zk_attendance:
                attendance_map[rec.employee_id.id].append(rec.punching_time)

            emp_ids = list(attendance_map.keys())
            Attendance = self.env['hr.attendance']
            existing_attendance_records = Attendance.search([
                ('employee_id', 'in', emp_ids),
                ('check_in', '>=', start_utc),
                ('check_in', '<=', end_utc),
            ])

            att_map = {att.employee_id.id: att for att in existing_attendance_records}
            to_create = []
            to_update = []

            for emp_id, times in attendance_map.items():
                check_in = min(times).replace(second=0, microsecond=0)
                check_out = max(times).replace(second=0, microsecond=0)
                existing_att = att_map.get(emp_id)
                if existing_att:
                    new_check_in = check_in.replace(second=0, microsecond=0)
                    new_check_out = check_out.replace(second=0, microsecond=0)
                    if ((not existing_att.check_in or new_check_in != existing_att.check_in) or
                            (not existing_att.check_out or new_check_out != existing_att.check_out)):
                        to_update.append((existing_att, {
                            'check_in': new_check_in,
                            'check_out': new_check_out,
                        }))
                else:
                    to_create.append({
                        'employee_id': emp_id,
                        'check_in': check_in,
                        'check_out': check_out,
                    })

            BATCH_SIZE = 1000
            for i in range(0, len(to_update), BATCH_SIZE):
                batch = to_update[i:i + BATCH_SIZE]
                try:
                    with self.env.cr.savepoint():
                        for att, vals in batch:
                            att.write(vals)
                except Exception as e:
                    _logger.error(f"Error updating batch: {e}")

            for i in range(0, len(to_create), BATCH_SIZE):
                batch = to_create[i:i + BATCH_SIZE]
                try:
                    with self.env.cr.savepoint():
                        Attendance.create(batch)
                except Exception as e:
                    _logger.error(f"Error creating batch: {e}")
        except Exception as e:
            _logger.error(f"Error syncing attendance today: {str(e)}")

    @api.model
    def cron_queue_sync_attendance(self):
        self.with_delay().sync_attendance_today()

    def job_download_attendance(self, devices):
        for device in devices:
            _logger.info(f"Running job for device: {device.name}")
            device.action_download_attendance()

    @api.model
    def job_run_download_batch(self, batch_index=0, batch_size=1):
        offset = batch_index * batch_size
        devices = self.env['biometric.device.details'].search([], order='id asc', offset=offset, limit=batch_size)
        self.job_download_attendance(devices)

    @api.model
    def cron_queue_download_attendance(self):
        total_devices = self.env['biometric.device.details'].search_count([])
        batch_size = 1
        total_batches = math.ceil(total_devices / batch_size)

        for batch_index in range(total_batches):
            self.with_delay(priority=10, max_retries=1).job_run_download_batch(batch_index, batch_size)

    def set_queue_job_done(self):
        deadline = Datetime.now() - datetime.timedelta(minutes=20)
        stuck_jobs = self.env['queue.job'].search([
            ('state', '=', 'started'),
            ('model_name', '=', 'biometric.device.details'),
            ('date_created', '<', deadline),
        ])
        for job in stuck_jobs:
            job.button_done()
        _logger.info(f"Force-marked {len(stuck_jobs)} stuck jobs as done.")
        return True

    def sync_attendance_last_month(self):
        local_tz = self._get_local_tz()
        now_local = datetime.datetime.now(local_tz)
        end_local = local_tz.localize(datetime.datetime(now_local.year, now_local.month, now_local.day, 23, 59, 59))
        start_local = end_local - relativedelta(days=45)
        start_utc = start_local.astimezone(pytz.utc)
        end_utc = end_local.astimezone(pytz.utc)

        zk_attendance = self.env['zk.machine.attendance'].search([
            ('punching_time', '>=', start_utc),
            ('punching_time', '<=', end_utc),
            ('employee_id', '!=', False),
        ])
        if not zk_attendance:
            return

        attendance_map = defaultdict(list)
        for rec in zk_attendance:
            local_dt = rec.punching_time.astimezone(local_tz)
            date_key = (rec.employee_id.id, local_dt.date())
            attendance_map[date_key].append(rec.punching_time)

        all_keys = list(attendance_map.keys())
        emp_ids = list(set(emp_id for emp_id, _ in all_keys))

        Attendance = self.env['hr.attendance']
        existing_attendances = Attendance.search([
            ('employee_id', 'in', emp_ids),
            ('check_in', '>=', start_utc),
            ('check_in', '<=', end_utc),
        ])

        att_map = {}
        for att in existing_attendances:
            local_check_in = att.check_in.astimezone(local_tz).date()
            att_map[(att.employee_id.id, local_check_in)] = att

        to_create = []
        to_update = []

        for (emp_id, work_date), punch_times in attendance_map.items():
            check_in = min(punch_times)
            check_out = max(punch_times)

            existing_att = att_map.get((emp_id, work_date))
            if existing_att:
                new_check_in = check_in.replace(second=0, microsecond=0)
                new_check_out = check_out.replace(second=0, microsecond=0)
                if ((not existing_att.check_in or new_check_in != existing_att.check_in) or
                        (not existing_att.check_out or new_check_out != existing_att.check_out)):
                    to_update.append((existing_att, {
                        'check_in': new_check_in,
                        'check_out': new_check_out,
                    }))
            else:
                to_create.append({
                    'employee_id': emp_id,
                    'check_in': check_in,
                    'check_out': check_out,
                })

        BATCH_SIZE = 1000
        for i in range(0, len(to_update), BATCH_SIZE):
            batch = to_update[i:i + BATCH_SIZE]
            try:
                with self.env.cr.savepoint():
                    for att, vals in batch:
                        att.write(vals)
            except Exception as e:
                _logger.error(f"Error updating batch: {e}")

        for i in range(0, len(to_create), BATCH_SIZE):
            batch = to_create[i:i + BATCH_SIZE]
            try:
                with self.env.cr.savepoint():
                    Attendance.create(batch)
            except Exception as e:
                _logger.error(f"Error creating batch: {e}")

    @timing_decorator
    def action_download_attendance_last_days(self):
        self.ensure_one()
        _logger.info(f"Downloading last 2 days attendance from {self.name} ({self._get_device_address()})")

        try:
            zk = self._create_zk_connection()
        except NameError as exc:
            _logger.error(f"[{self.name}] Pyzk module not found. Error: {str(exc)}")
            return False

        conn = self.device_connect(zk)
        if not conn:
            _logger.info(f"[{self.name}] No attendance data found.")
            return True

        try:
            conn.disable_device()
            users = conn.get_users()
            attendance = conn.get_attendance()

            if not attendance:
                conn.enable_device()
                conn.disconnect()
                _logger.warning(f"No attendance data found on device {self.name}")
                return True

            device_users_map = {user.user_id: user.name for user in users}
            device_user_ids = list(set(each.user_id for each in attendance))

            employee_mapping = {}
            if device_user_ids:
                placeholders = ','.join(['%s'] * len(device_user_ids))
                query_employees = f"""
                    SELECT device_id_num, id 
                    FROM hr_employee 
                    WHERE device_id_num IN ({placeholders})
                """
                self.env.cr.execute(query_employees, device_user_ids)
                employee_mapping = dict(self.env.cr.fetchall())

            attendance_records = []
            unverified_users = []
            local_tz = self._get_local_tz()

            now_local = datetime.datetime.now(local_tz)
            start_yesterday_local = datetime.datetime(now_local.year, now_local.month, now_local.day, 0, 0, 0) - datetime.timedelta(days=1)
            start_yesterday_local = local_tz.localize(start_yesterday_local)
            start_yesterday_utc = start_yesterday_local.astimezone(pytz.utc)
            end_utc = (start_yesterday_local + datetime.timedelta(days=2)).astimezone(pytz.utc)

            for each in attendance:
                try:
                    atten_time = each.timestamp
                    local_dt = local_tz.localize(atten_time, is_dst=None)
                    utc_dt = local_dt.astimezone(pytz.utc)

                    if not start_yesterday_utc <= utc_dt <= end_utc:
                        continue

                    formatted_time = fields.Datetime.to_string(utc_dt)
                    if each.user_id in employee_mapping:
                        attendance_records.append({
                            'employee_id': employee_mapping[each.user_id],
                            'device_id': self.id,
                            'device_id_num': each.user_id,
                            'attendance_type': str(each.status),
                            'punch_type': str(each.punch),
                            'punching_time': formatted_time,
                            'address_id': self.address_id.id if self.address_id else None
                        })
                    else:
                        user_name = device_users_map.get(each.user_id, 'Unknown')
                        unverified_users.append((each.user_id, user_name))
                except Exception as err:
                    _logger.warning(f"Skipped invalid attendance record from device {self.name}: {err}")
                    continue

            for user_id, user_name in set(unverified_users):
                _logger.info(f"Employee unverified: {user_id} with name {user_name} in device {self.name}")

            if attendance_records:
                keys = [
                    (int(r['device_id_num']), r['punching_time'], str(r['punch_type']), int(r['device_id']))
                    for r in attendance_records
                ]

                existing_keys = set()
                if keys:
                    query = """
                        SELECT CONCAT(z.device_id_num, '|', z.punching_time, '|', z.punch_type, '|', z.device_id) AS key
                        FROM zk_machine_attendance z
                        INNER JOIN (
                            VALUES %s
                        ) AS t(device_id_num, punching_time, punch_type, device_id)
                        ON z.device_id_num = t.device_id_num
                        AND z.punching_time = t.punching_time
                        AND z.punch_type = t.punch_type
                        AND z.device_id = t.device_id
                    """
                    template = "(%s::integer, %s::timestamp, %s::varchar, %s::integer)"
                    execute_values(self.env.cr, query, keys, template=template, page_size=500)
                    existing_keys = {row[0] for row in self.env.cr.fetchall()}

                new_records = []
                for record in attendance_records:
                    key = f"{record['device_id_num']}|{record['punching_time']}|{record['punch_type']}|{record['device_id']}"
                    if key not in existing_keys:
                        new_records.append(record)

                if new_records:
                    insert_query = """
                        INSERT INTO zk_machine_attendance
                        (employee_id, device_id, device_id_num, attendance_type,
                        punch_type, punching_time, address_id, create_date, write_date,
                        create_uid, write_uid)
                        VALUES %s
                    """
                    current_time = fields.Datetime.now()
                    current_user_id = self.env.user.id
                    insert_vals = [
                        (
                            r['employee_id'], r['device_id'], r['device_id_num'], r['attendance_type'],
                            r['punch_type'], r['punching_time'], r['address_id'], current_time, current_time,
                            current_user_id, current_user_id,
                        )
                        for r in new_records
                    ]
                    execute_values(self.env.cr, insert_query, insert_vals, template=None, page_size=500)
                    _logger.info(f"Successfully inserted {len(new_records)} records from device {self.name}")
                    self.env.cr.commit()
                else:
                    _logger.info("No new attendance records to insert (all duplicates).")

            conn.enable_device()
            conn.disconnect()
            _logger.info(f"Successfully processed attendance from {self.name} (yesterday + today)")
            return True
        except Exception as e:
            try:
                conn.enable_device()
                conn.disconnect()
            except Exception:
                pass
            _logger.error(f"Error downloading attendance from {self.name}: {str(e)}")
            return True
        finally:
            try:
                conn.enable_device()
                conn.disconnect()
            except Exception:
                pass

    def job_download_attendance_last_day(self, devices):
        for device in devices:
            _logger.info(f"Running job for device: {device.name}")
            device.action_download_attendance_last_days()

    @api.model
    def job_run_download_batch_last_day(self, batch_index=0, batch_size=1):
        offset = batch_index * batch_size
        devices = self.env['biometric.device.details'].search([], order='id asc', offset=offset, limit=batch_size)
        self.job_download_attendance_last_day(devices)

    @api.model
    def cron_queue_download_attendance_last_day(self):
        total_devices = self.env['biometric.device.details'].search_count([])
        batch_size = 1
        total_batches = math.ceil(total_devices / batch_size)

        for batch_index in range(total_batches):
            self.with_delay(priority=10, max_retries=1).job_run_download_batch_last_day(batch_index, batch_size)

    def sync_attendance_yesterday_today(self):
        try:
            local_tz = self._get_local_tz()
            now = datetime.datetime.now(local_tz)
            today_date = now.date()
            yesterday_date = today_date - datetime.timedelta(days=1)

            start_local = local_tz.localize(datetime.datetime.combine(yesterday_date, datetime.time.min))
            end_local = local_tz.localize(datetime.datetime.combine(today_date, datetime.time.max))
            start_utc = start_local.astimezone(pytz.utc)
            end_utc = end_local.astimezone(pytz.utc)

            zk_attendance = self.env['zk.machine.attendance'].search([
                ('punching_time', '>=', start_utc),
                ('punching_time', '<=', end_utc),
                ('employee_id', '!=', False),
            ])
            if not zk_attendance:
                return

            attendance_map = defaultdict(lambda: defaultdict(list))
            for rec in zk_attendance:
                local_dt = rec.punching_time.astimezone(local_tz)
                work_date = local_dt.date()
                attendance_map[rec.employee_id.id][work_date].append(rec.punching_time)

            Attendance = self.env['hr.attendance']

            for emp_id, day_map in attendance_map.items():
                for work_date, times in day_map.items():
                    check_in = min(times).replace(second=0, microsecond=0)
                    check_out = max(times).replace(second=0, microsecond=0)

                    day_start_local = local_tz.localize(datetime.datetime.combine(work_date, datetime.time.min))
                    day_end_local = local_tz.localize(datetime.datetime.combine(work_date, datetime.time.max))
                    day_start_utc = day_start_local.astimezone(pytz.utc)
                    day_end_utc = day_end_local.astimezone(pytz.utc)

                    existing_att = Attendance.search([
                        ('employee_id', '=', emp_id),
                        ('check_in', '>=', day_start_utc),
                        ('check_in', '<=', day_end_utc),
                    ], limit=1)

                    if existing_att:
                        new_check_in = check_in.replace(second=0, microsecond=0)
                        new_check_out = check_out.replace(second=0, microsecond=0)
                        if ((not existing_att.check_in or new_check_in != existing_att.check_in) or
                                (not existing_att.check_out or new_check_out != existing_att.check_out)):
                            existing_att.write({
                                'check_in': new_check_in,
                                'check_out': new_check_out,
                            })
                    else:
                        Attendance.create({
                            'employee_id': emp_id,
                            'check_in': check_in,
                            'check_out': check_out,
                        })
        except Exception as e:
            _logger.error(f"Error syncing attendance yesterday & today: {str(e)}")

    @api.model
    def cron_queue_sync_attendance_yesterday_today(self):
        self.with_delay().sync_attendance_yesterday_today()

    @timing_decorator
    def action_download_attendance_by_date(self, start_date=None, end_date=None):
        self.ensure_one()
        _logger.info(f"Downloading attendance from {self.name} ({self._get_device_address()}). {start_date}, {end_date}")
        total_valid = 0
        total_invalid = 0
        total_existing = 0
        total_new = 0
        total_failed = 0
        try:
            zk = self._create_zk_connection()
        except NameError as exc:
            _logger.error(f"[{self.name}] Pyzk module not found. Error: {str(exc)}")
            return False
        conn = self.device_connect(zk)
        if not conn:
            _logger.info(f"[{self.name}] No attendance data found.")
            return True
        try:
            conn.disable_device()
            users = conn.get_users()
            attendance = conn.get_attendance()
            if not attendance:
                conn.enable_device()
                conn.disconnect()
                _logger.warning(f"No attendance data found on device {self.name}")
                return True

            device_users_map = {user.user_id: user.name for user in users}
            device_user_ids = list(set(each.user_id for each in attendance))

            employee_mapping = {}
            if device_user_ids:
                placeholders = ','.join(['%s'] * len(device_user_ids))
                query_employees = f"""
                        SELECT device_id_num, id 
                        FROM hr_employee 
                        WHERE device_id_num IN ({placeholders})
                    """
                self.env.cr.execute(query_employees, device_user_ids)
                employee_mapping = dict(self.env.cr.fetchall())

            attendance_records = []
            unverified_users = []
            local_tz = self._get_local_tz()
            now_local = datetime.datetime.now(local_tz)
            start_local = datetime.datetime(now_local.year, now_local.month, now_local.day, 0, 0, 0)
            if start_date:
                start_local = datetime.datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
            elif self.start_date:
                start_local = datetime.datetime(self.start_date.year, self.start_date.month, self.start_date.day, 0, 0, 0)
            end_local = datetime.datetime(now_local.year, now_local.month, now_local.day, 23, 59, 59)
            if end_date:
                end_local = datetime.datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)
            elif self.end_date:
                end_local = datetime.datetime(self.end_date.year, self.end_date.month, self.end_date.day, 23, 59, 59)

            start_utc = local_tz.localize(start_local).astimezone(pytz.utc)
            end_utc = local_tz.localize(end_local).astimezone(pytz.utc)

            for each in attendance:
                try:
                    atten_time = each.timestamp
                    local_dt = local_tz.localize(atten_time, is_dst=None)
                    utc_dt = local_dt.astimezone(pytz.utc)
                    if utc_dt < start_utc or utc_dt > end_utc:
                        continue

                    utc_dt_str = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
                    atten_time = datetime.datetime.strptime(utc_dt_str, "%Y-%m-%d %H:%M:%S")
                    formatted_time = fields.Datetime.to_string(atten_time)

                    if each.user_id in employee_mapping:
                        attendance_records.append({
                            'employee_id': employee_mapping[each.user_id],
                            'device_id': self.id,
                            'device_id_num': each.user_id,
                            'attendance_type': str(each.status),
                            'punch_type': str(each.punch),
                            'punching_time': formatted_time,
                            'address_id': self.address_id.id if self.address_id else None
                        })
                        total_valid += 1
                    else:
                        user_name = device_users_map.get(each.user_id, 'Unknown')
                        unverified_users.append((each.user_id, user_name))
                        total_invalid += 1
                except Exception as err:
                    total_failed += 1
                    _logger.warning(f"Skipped invalid attendance record from device {self.name}: {err}")
                    continue

            for user_id, user_name in set(unverified_users):
                _logger.info(f"Employee unverified: {user_id} with name {user_name} in device {self.name}")

            if attendance_records:
                keys = [
                    (int(r['device_id_num']), r['punching_time'], str(r['punch_type']), int(r['device_id']))
                    for r in attendance_records
                ]

                existing_keys = set()
                if keys:
                    query = """
                        SELECT CONCAT(z.device_id_num, '|', z.punching_time, '|', z.punch_type, '|', z.device_id) AS key
                        FROM zk_machine_attendance z
                        INNER JOIN (
                            VALUES %s
                        ) AS t(device_id_num, punching_time, punch_type, device_id)
                        ON z.device_id_num = t.device_id_num
                        AND z.punching_time = t.punching_time
                        AND z.punch_type = t.punch_type
                        AND z.device_id = t.device_id
                    """
                    template = "(%s::integer, %s::timestamp, %s::varchar, %s::integer)"
                    execute_values(self.env.cr, query, keys, template=template, page_size=500)
                    existing_keys = {row[0] for row in self.env.cr.fetchall()}

                total_existing = len(existing_keys)
                new_records = []
                for record in attendance_records:
                    key = f"{record['device_id_num']}|{record['punching_time']}|{record['punch_type']}|{record['device_id']}"
                    if key not in existing_keys:
                        new_records.append(record)
                total_new = len(new_records)

                if new_records:
                    insert_query = """
                        INSERT INTO zk_machine_attendance
                        (employee_id, device_id, device_id_num, attendance_type,
                        punch_type, punching_time, address_id, create_date, write_date,
                        create_uid, write_uid)
                        VALUES %s
                    """
                    current_time = fields.Datetime.now()
                    current_user_id = self.env.user.id
                    insert_vals = [
                        (
                            r['employee_id'], r['device_id'], r['device_id_num'], r['attendance_type'],
                            r['punch_type'], r['punching_time'], r['address_id'], current_time, current_time,
                            current_user_id, current_user_id,
                        )
                        for r in new_records
                    ]
                    execute_values(self.env.cr, insert_query, insert_vals, template=None, page_size=500)
                    _logger.info(f"Successfully inserted {len(new_records)} records from device {self.name}")
                    self.env.cr.commit()
                else:
                    _logger.info("No new attendance records to insert (all duplicates).")

            conn.enable_device()
            conn.disconnect()

            total_raw = total_valid + total_invalid
            success_record = total_existing + total_new
            current_time = fields.Datetime.now()

            end_message = (f"[{self.name}] DONE - {current_time} — Total records: {total_raw}, Valid: {total_valid}, "
                           f"Invalid (user_id not found): {total_invalid}, Existing: {total_existing}, "
                           f"Newly pulled: {total_new}, Failed: {total_failed}")
            _logger.info(end_message)

            log_exception_to_ir_logging(
                self.env, message=end_message, err_name='Pull Attendance Results', pull_hand=True,
                success_record=success_record, failed_record=total_failed,
                func_name="action_download_attendance_by_date", device_id=self.id
            )
            self.env.cr.commit()
            return True

        except Exception as e:
            try:
                conn.enable_device()
                conn.disconnect()
            except Exception:
                pass
            _logger.error(f"Error during attendance download from {self.name}: {str(e)}")
            end_message = f"[{self.name}] CRASHED - System Error: {str(e)}"
            log_exception_to_ir_logging(
                self.env, message=end_message, err_name='Pull Attendance Results', pull_hand=True,
                success_record=0, failed_record=0, func_name="action_download_attendance_by_date", device_id=self.id
            )
            return True
        finally:
            try:
                conn.enable_device()
                conn.disconnect()
            except Exception:
                pass

    def job_download_attendance_by_date(self, devices, start_date=None, end_date=None):
        for device in devices:
            _logger.info(f"Running job for device: {device.name}")
            device.action_download_attendance_by_date(start_date, end_date)

    @api.model
    def job_run_download_batch_by_date(self, batch_index=0, batch_size=1, start_date=None, end_date=None):
        offset = batch_index * batch_size
        devices = self.env['biometric.device.details'].search([], order='id asc', offset=offset, limit=batch_size)
        self.job_download_attendance_by_date(devices, start_date, end_date)

    def sync_attendance_by_date(self, start_date=None, end_date=None):
        try:
            local_tz = self._get_local_tz()

            if isinstance(start_date, (list, tuple)):
                start_date = None
            if isinstance(end_date, (list, tuple)):
                end_date = None

            if isinstance(start_date, str):
                start_date = fields.Date.from_string(start_date)
            elif not start_date:
                start_date = self.start_date if (self and self.start_date) else fields.Date.context_today(self)

            if isinstance(end_date, str):
                end_date = fields.Date.from_string(end_date)
            elif not end_date:
                end_date = self.end_date if (self and self.end_date) else start_date

            if start_date > end_date:
                raise ValueError(_("Start date cannot be greater than end date."))

            start_local_bound = local_tz.localize(datetime.datetime.combine(start_date, datetime.time.min))
            end_local_bound = local_tz.localize(datetime.datetime.combine(end_date, datetime.time.max))
            start_utc_bound = start_local_bound.astimezone(pytz.utc)
            end_utc_bound = end_local_bound.astimezone(pytz.utc)

            zk_attendance = self.env['zk.machine.attendance'].search([
                ('punching_time', '>=', start_utc_bound),
                ('punching_time', '<=', end_utc_bound),
                ('employee_id', '!=', False),
            ])
            if not zk_attendance:
                return True

            daily_zk_map = defaultdict(lambda: defaultdict(list))
            for rec in zk_attendance:
                punch_local = pytz.utc.localize(rec.punching_time).astimezone(local_tz)
                rec_date = punch_local.date()
                daily_zk_map[rec_date][rec.employee_id.id].append(rec.punching_time)

            all_emp_ids = list({rec.employee_id.id for rec in zk_attendance})

            Attendance = self.env['hr.attendance']
            existing_attendance_records = Attendance.search([
                ('employee_id', 'in', all_emp_ids),
                ('check_in', '>=', start_utc_bound),
                ('check_in', '<=', end_utc_bound),
            ])

            att_map = {}
            for att in existing_attendance_records:
                att_local = pytz.utc.localize(att.check_in).astimezone(local_tz)
                att_map[(att.employee_id.id, att_local.date())] = att

            to_create = []
            to_update = []

            current_date = start_date
            while current_date <= end_date:
                if current_date in daily_zk_map:
                    for emp_id, times in daily_zk_map[current_date].items():
                        check_in = min(times).replace(second=0, microsecond=0, tzinfo=None)
                        check_out = max(times).replace(second=0, microsecond=0, tzinfo=None)

                        existing_att = att_map.get((emp_id, current_date))
                        if existing_att:
                            old_check_in = existing_att.check_in.replace(second=0, microsecond=0, tzinfo=None) if existing_att.check_in else False
                            old_check_out = existing_att.check_out.replace(second=0, microsecond=0, tzinfo=None) if existing_att.check_out else False
                            if check_in != old_check_in or check_out != old_check_out:
                                to_update.append((existing_att, {
                                    'check_in': check_in,
                                    'check_out': check_out,
                                }))
                        else:
                            to_create.append({
                                'employee_id': emp_id,
                                'check_in': check_in,
                                'check_out': check_out,
                            })
                current_date += datetime.timedelta(days=1)

            BATCH_SIZE = 1000
            for i in range(0, len(to_update), BATCH_SIZE):
                batch = to_update[i:i + BATCH_SIZE]
                try:
                    with self.env.cr.savepoint():
                        for att, vals in batch:
                            att.write(vals)
                except Exception as e:
                    _logger.error(f"Error updating batch: {e}")

            for i in range(0, len(to_create), BATCH_SIZE):
                batch = to_create[i:i + BATCH_SIZE]
                try:
                    with self.env.cr.savepoint():
                        Attendance.create(batch)
                except Exception as e:
                    _logger.error(f"Error creating batch: {e}")

        except Exception as e:
            end_message = f"Error syncing attendance by date: {str(e)}"
            _logger.error(end_message)
            log_exception_to_ir_logging(
                self.env, message=end_message, err_name='Sync Attendance Results', pull_hand=True,
                func_name="sync_attendance_by_date", device_id=self.id if self else False
            )
        return True

    @api.model
    def cron_queue_sync_attendance_by_date(self, start_date=None, end_date=None):
        devices = self.env['biometric.device.details'].search([])
        str_start = start_date.strftime('%Y-%m-%d') if isinstance(start_date, (datetime.date, datetime.datetime)) else start_date
        str_end = end_date.strftime('%Y-%m-%d') if isinstance(end_date, (datetime.date, datetime.datetime)) else end_date

        for device in devices:
            device.with_delay(priority=12, max_retries=1).sync_attendance_by_date(
                start_date=str_start,
                end_date=str_end
            )

    def download_and_sync_attendance_by_date(self, start_date=None, end_date=None):
        self.action_download_attendance_by_date(start_date, end_date)
        self.sync_attendance_by_date(start_date, end_date)

    def _send_sync_message(self, end_message):
        partner_ids = []
        if self.responsible_user_id:
            partner_ids.append(self.responsible_user_id.partner_id.id)
        partner_ids.append(self.env.user.partner_id.id)
        partner_ids = list(set(partner_ids))
        odoobot_id = self.env.ref("base.partner_root").id
        _logger.info(f"_send_sync_message {self.name}: {end_message} - {partner_ids}, {odoobot_id} ")
        for partner in partner_ids:
            channel = self.env['discuss.channel'].with_user(SUPERUSER_ID).channel_get(partners_to=[partner])
            channel.message_post(body=end_message, author_id=odoobot_id)
