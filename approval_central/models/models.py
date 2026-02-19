from odoo import models, fields, api
from odoo.exceptions import ValidationError,UserError


class ApprovalFlow(models.Model):
    _name = 'approval.flow'
    _description = 'Approval Workflow Flow'

    name = fields.Char(string='Flow Name', required=True)
    request_type = fields.Char(string='Request Type', required=True)
    request_model_id = fields.Many2one(
        'ir.model',
        string='Request Model',
        required=True,
        ondelete='cascade'
    )

    company_id = fields.Many2one('res.company', string='Company')
    active = fields.Boolean(default=True)
    step_ids = fields.One2many('approval.step', 'flow_id', string='Steps')
    created_by = fields.Many2one('res.users', string='Created By', default=lambda self: self.env.user)
    updated_by = fields.Many2one('res.users', string='Updated By')

    @api.model
    def create(self, vals):
        vals['created_by'] = self.env.user.id
        return super().create(vals)

    def write(self, vals):
        vals['updated_by'] = self.env.user.id
        return super().write(vals)


class ApprovalStep(models.Model):
    _name = 'approval.step'
    _description = 'Approval Workflow Step'
    _order = 'sequence'

    flow_id = fields.Many2one('approval.flow', string='Flow', required=True, ondelete='cascade')
    name = fields.Char(string='Step Name', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    role_id = fields.Many2one('res.groups', string='Approver Role')
    committee_approval = fields.Boolean(string="Committee Approval")
    required_approval_percent = fields.Float(
        string="Required Approval (%)",
        default=100.0,
        help="What percent of the assigned group must approve. Set to 100% for full approval, 60% for majority, etc."
    )
    is_organization=fields.Boolean(string='Is Organization', default=False)
    is_condition = fields.Boolean(string='Is Condition Step', default=False)
    condition_ids = fields.One2many('approval.condition', 'step_id', string='Conditions')
    company_id = fields.Many2one('res.company', string='Company')
    branch_id = fields.Many2one('account.analytic.account', string='Branch')
    fallback_branch_id = fields.Many2one('account.analytic.account', string='Fallback Branch')
    next_step_ids = fields.Many2many('approval.step', 'approval_step_next_rel', 'step_id', 'next_step_id', string='Next Steps', domain="[('flow_id', '=', flow_id)]")
    is_initiator = fields.Boolean(string='Is Initiator Step', default=False)
    is_final = fields.Boolean(string='Is Final Step', default=False)
    cross_branch = fields.Boolean(string='Is Cross Branch', default=False)
    action_ids = fields.One2many('approval.step.action', 'step_id', string='Actions')
    is_employee_step = fields.Boolean(
        string="Is Employee Step",
        default=False,
        help="Assign this step to the employee the request is for (not the creator)."
    )
    @api.constrains('is_condition', 'condition_ids')
    def _check_condition_steps(self):
        for step in self:
            if step.is_condition and not step.condition_ids:
                raise ValidationError("Condition steps must have at least one condition.")

    @api.constrains('required_approval_percent')
    def _check_percent_range(self):
        for rec in self:
            if rec.committee_approval and not (0 < rec.required_approval_percent <= 100):
                raise ValidationError("Required approval percentage must be between 1 and 100.")
    @api.constrains('role_id', 'is_initiator')
    def _check_role_for_non_initiator(self):
        for step in self:
            if not step.is_initiator and not step.role_id:
                if step.is_final| step.is_employee_step| step.is_condition:
                    continue
                raise ValidationError(
                    "You must select a User Group when the step is not an Initiator."
                )
class ApprovalHistory(models.Model):
    _name = 'approval.history'
    _description = 'Approval History Log'
 
    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee",
        compute="_compute_appraisal_info",
        store=False
    )
    appraisal_id = fields.Many2one(
        'employee.appraisal',
        string="Appraisal",
        compute="_compute_appraisal_info",
        store=False
    )

    request_id = fields.Many2one('approval.request', string='Approval Request', required=True, ondelete='cascade')
    step_id = fields.Many2one('approval.step', string='Step')
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    action_id = fields.Many2one(
        'approval.action',
        string='Action',
        required=True,
        ondelete='restrict'
    )
    comment = fields.Text(string='Comment')
    date = fields.Datetime(string='Action Date', default=fields.Datetime.now)

    def _compute_appraisal_info(self):
        """Find related appraisal & employee based on request link."""
        for rec in self:
            if rec.request_id and rec.request_id.res_model == 'employee.appraisal':
                appraisal = self.env['employee.appraisal'].browse(rec.request_id.res_id)
                rec.appraisal_id = appraisal
                rec.employee_id = appraisal.employee_id
            else:
                rec.appraisal_id = False
                rec.employee_id = False



class ApprovalStepAction(models.Model):
    _name = 'approval.step.action'
    _description = 'Approval Step Actions'

    step_id = fields.Many2one('approval.step', string='Step', required=True, ondelete='cascade')
    action_id = fields.Many2one(
        'approval.action',
        string='Action',
        required=True,
        ondelete='restrict'
    )
    next_step_id = fields.Many2one('approval.step', string='Next Step')
