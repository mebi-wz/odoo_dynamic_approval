from odoo import api

def send_notification_to_users(env, users, message, title='Approval Required'):
    bus = env['bus.bus']
    for user in users:
        if not user or not user.partner_id:
            continue
        bus.sendone(
            (env.cr.dbname, 'res.partner', user.partner_id.id),
            {
                'type': 'simple_notification',
                'title': title,
                'message': message,
                'sticky': True,
                'tag': 'approval_notification',
            }
        )
