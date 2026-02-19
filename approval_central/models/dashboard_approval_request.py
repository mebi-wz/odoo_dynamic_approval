from odoo import models, fields

class DashboardApprovalRequest(models.Model):
    _name = 'dashboard.approval.request'
    _auto = False
    _description = 'Approval Dashboard Summary'

    res_model = fields.Char("Model")
    module_name = fields.Char("Module")
    status = fields.Selection([
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string="Status")
    count = fields.Integer("Count")
    def open_filtered_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Filtered Approvals',
            'res_model': 'approval.request',
            'view_mode': 'list,form',
            'domain': [
                ('res_model', '=', self.res_model),
                ('status', '=', self.status)
            ],
            'target': 'current',
        }