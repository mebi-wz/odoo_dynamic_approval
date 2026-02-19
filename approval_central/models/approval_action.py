from odoo import models, fields, api
from odoo.exceptions import ValidationError
class ApprovalAction(models.Model):
    _name = 'approval.action'
    _description = 'Global Approval Actions'

    name = fields.Char(string='Action Name', required=True, unique=True)
    code = fields.Char(string='Action Code', required=True, unique=True,
                       help="Unique code to identify the action in the workflow")
