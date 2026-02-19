from odoo import models, fields

class SuccessMessageWizard(models.TransientModel):
    _name = 'popup'
    _description = 'popup'

    message = fields.Text(string="Message", readonly=True)