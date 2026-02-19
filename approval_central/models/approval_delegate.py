from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import date

class ApprovalDelegate(models.Model):
    _name = 'approval.delegate'
    _description = 'Approval Delegation'

    original_user_id = fields.Many2one('res.users', string='Original User', required=True)
    delegate_user_id = fields.Many2one('res.users', string='Delegate User', required=True)
    start_date = fields.Date(string='Start Date', required=True, default=fields.Date.today)
    end_date = fields.Date(string='End Date', required=True)
    active = fields.Boolean(string='Active', default=True)

    @api.model
    def get_delegate(self, users):
        """Return users + valid delegates for today"""
        if not users:
            return self.env['res.users']

        today = fields.Date.today()
        users = users if users else self.env['res.users']

        # find delegations for all given users in one search
        delegations = self.search([
            ('original_user_id', 'in', users.ids),
            ('active', '=', True),
            ('start_date', '<=', today),
            ('end_date', '>=', today),
        ])

        # collect delegates + originals (always include original if no delegation)
        delegates = delegations.mapped('delegate_user_id')
        result = users | delegates
        return result
