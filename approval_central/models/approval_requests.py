from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)
class ApprovalRequest(models.Model):
    _name = 'approval.request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Approval Request'

    flow_id = fields.Many2one('approval.flow', string='Workflow Flow', required=True)
    res_model = fields.Char(string='Resource Model', required=True)
    res_id = fields.Integer(string='Resource Record ID', required=True)
    current_step_id = fields.Many2one('approval.step', string='Current Step')
    status = fields.Selection([
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='pending', string='Status',tracking=True)
    requested_by = fields.Many2one('res.users', string='Requested By', default=lambda self: self.env.user)
    approver_ids = fields.Many2many('res.users', string='Current Approvers',
        store=True,)
    approved_date = fields.Datetime(string='Approved Date')
    rejected_date = fields.Datetime(string='Rejected Date')
    remarks = fields.Text(string='Remarks',tracking=True)
    module_name=fields.Char(string='Resource Module', required=True)
    completed_step_ids = fields.Many2many('approval.step', string='Completed Steps', readonly=True)
    step_progress = fields.Html(string="Step Progress", compute='_compute_step_progress', sanitize=False)
    branch_id = fields.Many2one('account.analytic.account', string='Branch',required=False)
    requested_for_id = fields.Many2one(
        'res.users',
        string='Requested For',
        help="Employee the request is about or should be reviewed by."
    )

    def process_action(self):
        self.ensure_one()
        if self.auto_process_initiator_step():
            return

        action_type = self.env.context.get('action_type')
        comment = self.env.context.get('comment', '')

        if not action_type:
            raise UserError("Invalid Operation: Action type is not provided.")
        action = self.env['approval.action'].search([('code', '=', action_type)], limit=1)
        if not action:
            raise UserError(f"No approval action found for code '{action_type}'")

        if self.status not in ['pending', 'rejected'] and action_type in ['approve', 'reject']:
            raise UserError(f"This request cannot be {action_type} in its current state.")

        step = self.current_step_id

        if not step:
            raise UserError("No current step defined.")

        approvers = self.approver_ids

        # Check if current user is among them
        if self.env.user not in approvers:
            raise UserError(f"You are not authorized to perform '{action_type}' on this request.")
        step_action = step.action_ids.filtered(lambda a: a.action_id.code == action_type)[:1]

        if not step_action:
            raise UserError(f"No '{action_type}' action defined for this step.")

        next_step = step_action.next_step_id
        if not next_step and not step.condition_ids and step.next_step_ids:
            for candidate in step.next_step_ids:
                candidate_checked = self._check_org_chart(candidate)
                if candidate_checked:
                    next_step = candidate_checked
                    break
        if action_type == 'approve':
            if step.committee_approval:
                ApprovalHistory = self.env['approval.history']

                approved_count = ApprovalHistory.search_count([
                    ('request_id', '=', self.id),
                    ('step_id', '=', step.id),
                    ('action_id', '=', action.id),
                ])

                total_approvers = len(step.role_id.users)
                if total_approvers == 0:
                    raise UserError("No users found in the approver group for this step.")

                required = round((step.required_approval_percent / 100.0) * total_approvers)
                required = max(required, 1)

                # Record current user's approval
                ApprovalHistory.create({
                    'request_id': self.id,
                    'step_id': step.id,
                    'action_id': action.id,
                    'user_id': self.env.uid,
                    'comment': comment,
                })

                # Remove current user from approver list immediately
                if self.env.uid in self.approver_ids.ids:
                    self.write({
                        'approver_ids': [(3, self.env.uid)]
                    })

                self._complete_user_activity()

                # Check if approval threshold is reached
                if approved_count + 1 >= required:

                    if step.id not in self.completed_step_ids.ids:
                        self.write({
                            'completed_step_ids': [(4, step.id)]
                        })

                    if next_step and next_step.is_final:
                        self.write({
                            'status': 'approved',
                            'approved_date': fields.Datetime.now(),
                            'approver_ids': [(6, 0, [])],
                        })

                    elif next_step and next_step.is_employee_step:
                        if not self.requested_for_id:
                            raise UserError("No 'Requested For' employee defined for this request.")

                        self.write({
                            'status': 'pending',
                            'current_step_id': next_step.id,
                            'approver_ids': [(6, 0, [self.requested_for_id.id])],
                        })

                        self.activity_schedule(
                            'mail.mail_activity_data_todo',
                            user_id=self.requested_for_id.id,
                            note="This request has been sent to you for review."
                        )

                    elif next_step:
                        self.write({
                            'current_step_id': next_step.id
                        })
                        self.auto_process_condition_steps(next_step)

                return True


            else:
                if step.id not in self.completed_step_ids.ids:
                    self.write({'completed_step_ids': [(4, step.id)]})

                next_step = self._check_org_chart(next_step)
                if next_step and next_step.is_final:
                    self.write({
                        'status': 'approved',
                        'approved_date': fields.Datetime.now(),
                        'approver_ids': [(6, 0, [])],
                    })
                elif next_step.is_employee_step:
                    if not self.requested_for_id:
                        raise UserError("No 'Requested For' employee defined for this request.")
                    self.write({
                        'status': 'pending',
                        'current_step_id': next_step.id,
                        'approver_ids': [(6, 0, [self.requested_for_id.id])],
                    })
                    self.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=self.requested_for_id.id,
                        note="This request has been sent to you for review."
                    )
                elif next_step:
                    self.write({'current_step_id': next_step.id})
                    # self._notify_approvers_via_activity(self.approver_ids)
                    self.auto_process_condition_steps(next_step)
        elif action_type == 'amend':
            initiator_step = self.flow_id.step_ids.filtered(lambda s: s.is_initiator)[:1]
            if not initiator_step:
                raise UserError("No initiator step defined in this workflow.")

            self.write({
                'status': 'pending',
                'current_step_id': initiator_step.id,
                'approver_ids': [(6, 0, [self.requested_by.id])] if self.requested_by else [(5, 0, 0)],
            })

            # Notify the requester
            if self.requested_by:
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=self.requested_by.id,
                    note="Your request has been returned for amendment."
                )

        elif action_type == 'reject':
            self.write({
                'status': 'rejected',
                'rejected_date': fields.Datetime.now(),
                'approver_ids': [(3, self.env.uid)],
            })
        elif action_type == 'to_employee':
            if not self.requested_for_id:
                raise UserError("No 'Requested For' employee defined for this request.")

            # Find the step action definition
            step_action = step.action_ids.filtered(lambda a: a.name == 'to_employee')
            if not step_action:
                raise UserError("No 'Send to Employee' action defined for this step.")

            next_step = step_action.next_step_id
            if not next_step:
                raise UserError("No next step is defined for 'Send to Employee'.")

            # Assign approver as the requested_for employee
            self.write({
                'status': 'pending',
                'current_step_id': next_step.id,
                'approver_ids': [(6, 0, [self.requested_for_id.id])],
            })

            # Notify employee
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=self.requested_for_id.id,
                note="This request has been sent to you for review."
            )


        elif action_type in ['revert']:
            self.write({
                'status': 'pending',
                'current_step_id': next_step.id if next_step else step.id,
            })

        self.env['approval.history'].create({
            'request_id': self.id,
            'step_id': step.id,
            'action_id': action.id,  # still points to approval.action
            'user_id': self.env.uid,
            'comment': comment,
        })

        self._complete_user_activity()

    def auto_process_initiator_step(self):
        self.ensure_one()
        step = self.current_step_id

        if not step or not step.is_initiator:
            return False

        next_step = None

        # ✅ Handle conditional branches
        if step.is_condition:
            for condition in step.condition_ids:
                if condition._evaluate_condition(self):
                    next_step = condition.next_step_id
                    break

        # ✅ Default to first defined action transition
        if not next_step and step.action_ids:
            next_step = step.action_ids[0].next_step_id

        # ✅ Check org chart candidates
        if not next_step and step.next_step_ids:
            for candidate in step.next_step_ids:
                candidate_checked = self._check_org_chart(candidate)
                if candidate_checked:
                    next_step = candidate_checked
                    break

        if not next_step:
            raise UserError("Unable to determine the next step from initiator.")

        next_step = self._check_org_chart(next_step)

        # ✅ Mark initiator step as completed
        if step.id not in self.completed_step_ids.ids:
            self.write({'completed_step_ids': [(4, step.id)]})

        # ✅ Get global action for "auto_initiate"
        action = self.env['approval.action'].search([('code', '=', 'auto_initiate')], limit=1)
        if not action:
            raise UserError("Global action 'auto_initiate' is not defined. Please create it in Approval Actions.")

        # ✅ Record history with proper action_id
        self.env['approval.history'].create({
            'request_id': self.id,
            'step_id': step.id,
            'user_id': self.env.uid,
            'action_id': action.id,  # Proper M2O reference
            'comment': 'Automatically advanced from initiator step.',
        })
        self._complete_user_activity()

        # ✅ Handle final step
        if next_step and next_step.is_final:
            self.write({
                'status': 'approved',
                'approved_date': fields.Datetime.now(),
                'current_step_id': next_step.id,
                'approver_ids': [(6, 0, [])],
            })
            self.write({'completed_step_ids': [(4, next_step.id)]})
        elif next_step.is_employee_step:
            if not self.requested_for_id:
                raise UserError("No 'Requested For' employee defined for this request.")
            self.write({
                'status': 'pending',
                'current_step_id': next_step.id,
                'approver_ids': [(6, 0, [self.requested_for_id.id])],
            })
        else:
            self.write({'current_step_id': next_step.id})
            self.auto_process_condition_steps(next_step)

        return True

    def auto_process_condition_steps(self, step):
        self.ensure_one()
        visited = set()

        while step and step.is_condition:
            if step.id in visited:
                raise UserError(f"Workflow loop detected at step {step.name}")
            visited.add(step.id)

            # ✅ Evaluate conditions
            next_step = None
            for condition in step.condition_ids:
                if condition._evaluate_condition(self):
                    next_step = condition.next_step_id
                    break

            if not next_step:
                raise UserError(f"No matching condition found for step: {step.name}")

            # ✅ Mark step as completed
            if step.id not in self.completed_step_ids.ids:
                self.write({'completed_step_ids': [(4, step.id)]})

            # ✅ Get global action for "auto_condition"
            action = self.env['approval.action'].search([('code', '=', 'auto_condition')], limit=1)
            if not action:
                raise UserError("Global action 'auto_condition' is not defined. Please create it in Approval Actions.")

            # ✅ Record history with proper action_id
            self.env['approval.history'].create({
                'request_id': self.id,
                'step_id': step.id,
                'user_id': self.env.uid,
                'action_id': action.id,
                'comment': 'Automatically advanced via conditional logic.',
            })
            self._complete_user_activity()

            # ✅ If final step reached → approve request
            if next_step.is_final:
                if next_step.id not in self.completed_step_ids.ids:
                    self.write({'completed_step_ids': [(4, next_step.id)]})
                self.write({
                    'status': 'approved',
                    'approved_date': fields.Datetime.now(),
                    'current_step_id': next_step.id,
                    'approver_ids': [(6, 0, [])],
                })
                return
            elif next_step.is_employee_step:
                if not self.requested_for_id:
                    raise UserError("No 'Requested For' employee defined for this request.")
                self.write({
                    'status': 'pending',
                    'current_step_id': next_step.id,
                    'approver_ids': [(6, 0, [self.requested_for_id.id])],
                })
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=self.requested_for_id.id,
                    note="This request has been sent to you for review."
                )

            # ✅ Otherwise move forward
            self.write({'current_step_id': next_step.id})
            step = next_step  # Continue loop

        # ✅ Handle organization chart step if it's not a condition
        if step and not step.is_condition:
            step = self._check_org_chart(step)
            if not step:
                return
            self.write({'current_step_id': step.id})

    def action_open_target_record(self):
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.res_model} Record',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    target_record_id = fields.Reference(
        selection=lambda self: [(model.model, model.name) for model in self.env['ir.model'].sudo().search([])],
        string="Target Record",
        compute='_compute_target_record',
        store=False,
    )

    @api.depends('res_model', 'res_id')
    def _compute_target_record(self):
        for rec in self:
            if rec.res_model and rec.res_id:
                # Check if the model exists and user has access (using sudo to avoid access errors)
                model_exists = self.env['ir.model'].sudo().search([('model', '=', rec.res_model)], limit=1)
                if model_exists:
                    try:
                        # Try to browse the target record with sudo
                        target = self.env[rec.res_model].sudo().browse(rec.res_id)
                        # Assign only if record exists
                        rec.target_record_id = f"{rec.res_model},{rec.res_id}" if target.exists() else False
                    except Exception:
                        rec.target_record_id = False
                else:
                    rec.target_record_id = False
            else:
                rec.target_record_id = False

    def _compute_step_progress(self):
        for rec in self:
            if not rec.flow_id or not rec.flow_id.step_ids:
                rec.step_progress = "<span>No steps defined.</span>"
                continue

            steps = rec.flow_id.step_ids.sorted(key=lambda s: s.sequence)
            completed_ids = set(rec.completed_step_ids.ids)
            current_step = rec.current_step_id
            current_id = current_step.id if current_step else None

            # Identify skipped steps (before current, but not completed)
            skipped_ids = []
            if current_step:
                skipped_ids = [s.id for s in steps if s.sequence < current_step.sequence and s.id not in completed_ids]

            total = len(steps)
            completed_count = len(completed_ids)
            progress_labels = ""

            # Determine next step
            next_step = None
            for i, step in enumerate(steps):
                if step.id == current_id and i + 1 < len(steps):
                    next_step = steps[i + 1]
                    break

            # Calculate percent complete including skipped as done
            effective_completed_count = completed_count + len(skipped_ids)
            if (
                    next_step
                    and next_step.is_final
                    and current_step
                    and current_step.id in completed_ids
            ):
                percent = 100
            else:
                percent = (effective_completed_count / total) * 100 if total else 0

            # Build label visuals with skipped step color
            for step in steps:
                if step.id in completed_ids:
                    color = "#28a745"  # green - completed
                elif step.id in skipped_ids:
                    color = "#dc3545"  # dark gray - skipped
                elif step.id == current_id:
                    color = "#ffc107"  # yellow - current
                else:
                    color = "#dee2e6"  # light gray - upcoming

                progress_labels += f'''
                  <div style="flex:1; text-align:center; font-size:12px; color:{color};">
                      {step.name}
                  </div>'''

            # Build the progress bar html
            progress_bar = f'''
              <div style="width:100%; margin-top:10px;">
                  <div style="position:relative; height:20px; background:#e9ecef; border-radius:10px;">
                      <div style="
                          height:100%;
                          width:{percent}%;
                          background:linear-gradient(90deg, #28a745, #85d684);
                          border-radius:10px;
                          transition:width 0.5s ease-in-out;">
                      </div>
                  </div>
                  <div style="display:flex; margin-top:5px;">
                      {progress_labels}
                  </div>
              </div>'''

            rec.step_progress = progress_bar



    def _compute_current_approvers(self):
        for rec in self:
                rec.approver_ids = rec.approver_ids

    def get_hierarchy_with_users_and_groups(self, job):
        hierarchy_data = []
        while job:
            employees = self.env['hr.employee'].sudo().search([('job_id', '=', job.id)])
            for employee in employees:
                user = employee.user_id
                user_groups = user.groups_id if user else self.env['res.groups'].browse()
                hierarchy_data.append({
                    'job': job,
                    'employee': employee,
                    'user': user,
                    'user_groups': user_groups,
                })
            job = job.parent_id
        return hierarchy_data

    def _check_org_chart(self, step):
        self.ensure_one()

        try:
            employee = self.env['hr.employee'].sudo().search([('user_id', '=', self.create_uid.id)], limit=1)
            if not employee:
                _logger.warning(f"No employee record found for user {self.create_uid.id}")
                return step

            hierarchy_info = self.get_hierarchy_with_users_and_groups(employee.job_id)
            flow_steps = list(step.flow_id.step_ids.sorted(key=lambda s: s.sequence))
            current_index = flow_steps.index(step)
            fallback_branch = step.fallback_branch_id.id if step.fallback_branch_id else False

            while current_index < len(flow_steps):
                current_step = flow_steps[current_index]

                if current_step.is_organization:
                    _logger.info(f"Checking org chart approvers for request {self.id}, step '{current_step.name}'")

                    hierarchy_users = self.env['res.users'].browse([
                        entry['user'].id for entry in hierarchy_info if entry.get('user')
                    ])

                    # ✅ Step should only apply if the role’s users are part of this hierarchy
                    matched_users = current_step.role_id.users & hierarchy_users

                    if not matched_users:
                        # 🚫 No one in hierarchy has this step's role → skip step
                        _logger.info(
                            f"Skipping step '{current_step.name}' — no hierarchy user has role '{current_step.role_id.name}'."
                        )

                        # Try to find the next organization step (higher-level approver)
                        next_steps = flow_steps[flow_steps.index(current_step) + 1:]
                        for next_step in next_steps:
                            if next_step.is_organization:
                                _logger.info(f"Moving to next organization step '{next_step.name}' for further check.")
                                return self._check_org_chart(next_step)  # recursion to continue hierarchy search
                        # ❌ No more organization steps left
                        raise UserError(
                            f"No valid approver found in organization chart for request {self.id}."
                        )

                    # ✅ Found hierarchy user(s) with matching role
                    delegated_approvers = self.env['approval.delegate'].get_delegate(matched_users)
                    if not delegated_approvers:
                        raise UserError(
                            f"Delegation missing for step '{current_step.name}' — role has hierarchy users but no delegates."
                        )

                    self.approver_ids = delegated_approvers
                    _logger.info(
                        f"Assigned approver(s) {', '.join(u.name for u in delegated_approvers)} "
                        f"for org step '{current_step.name}'."
                    )
                    return current_step

                elif current_step.is_employee_step:
                    if not self.requested_for_id:
                        raise UserError("No 'Requested For' employee defined for this request.")

                    # Clear old approvers and assign the employee
                    self.approver_ids = [(5, 0, 0)]
                    self.approver_ids = [(6, 0, [self.requested_for_id.id])]
                    _logger.info(
                        f"Assigned requested employee {self.requested_for_id.name} "
                        f"as approver for employee step '{current_step.name}'."
                    )
                    return current_step


                else:
                    # Static step
                    if current_step.cross_branch:
                        matched_users = current_step.role_id.users.filtered(
                            lambda u: u.default_branch_id == self.branch_id
                        )
                    else:
                        matched_users = current_step.role_id.users.filtered(
                            lambda u: u.default_branch_id == employee.branch_id
                        )
                        if not matched_users and fallback_branch:
                            matched_users = current_step.role_id.users.filtered(
                                lambda u: u.default_branch_id.id == fallback_branch
                            )

                    delegated_approvers = self.env['approval.delegate'].get_delegate(matched_users)
                    if not delegated_approvers and not current_step.is_final and not current_step.is_condition:
                        raise UserError(
                            f"No valid approvers found for step '{current_step.name}'. "
                            f"Ensure the role has users or active delegation rules."
                        )
                    self.approver_ids = delegated_approvers

                    return current_step

                    

            raise UserError("No valid steps found. Workflow cannot continue.")

        except Exception as e:
            _logger.error(f"Error in _check_org_chart for request {self.id}: {str(e)}", exc_info=True)
            raise UserError(f"Workflow error: {str(e)}")

    def _notify_approvers_via_activity(self, users, message=None, title=None):
        self.ensure_one()
        if not users:
            _logger.warning(f"No users to notify for approval request {self.id}")
            return
        try:
            target = self.env[self.res_model].sudo().read([self.res_id], ['display_name'])[0]
            target_name = target.get('display_name', f"{self.res_model} #{self.res_id}")
        except Exception:
            target_name = f"{self.res_model} #{self.res_id}"

        title = title or f"Approval Needed for {target_name}"
        message = message or f"Please take action on approval request for {target_name}."

        activity_type = self.env.ref('mail.mail_activity_data_todo')
        today = fields.Date.today()

        existing = self.env['mail.activity'].sudo().search([
            ('res_model', '=', 'approval.request'),
            ('res_id', '=', self.id),
            ('user_id', 'in', [u.id for u in users]),
            ('activity_type_id', '=', activity_type.id),
            ('state', '=', 'pending'),
        ])
        existing_user_ids = set(existing.mapped('user_id').ids)

        model_id = self.env['ir.model']._get('approval.request').id

        to_create = [{
            'res_model': 'approval.request',
            'res_model_id': model_id,
            'res_id': self.id,
            'activity_type_id': activity_type.id,
            'user_id': user.id,
            'summary': title,
            'note': message,
            'date_deadline': today + timedelta(days=3),
        } for user in users if user.id not in existing_user_ids]

        if to_create:
            with self.env.cr.savepoint():
                self.env['mail.activity'].sudo().create(to_create)

    def _complete_user_activity(self):
        """Marks the current user's activity as done for this request."""
        self.ensure_one()
        current_user_id = self.env.uid

        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'approval.request'),
            ('res_id', '=', self.id),
            ('user_id', '=', current_user_id),
            ('activity_type_id', '=', self.env.ref('mail.mail_activity_data_todo').id),
            ('state', '=', 'pending'),
        ])
        for activity in activities:
            activity.action_done()

    
    
    def action_approve_all(self, comment=''):
        final_approved = 0
        moved_next = 0
        skipped = 0

        HrLeave = self.env['hr.leave']
        OnDuty = self.env['onduty.report']

        for req in self:
            if req.status != 'pending':
                skipped += 1
                continue

            # Try Leave first
            leave = HrLeave.search(
                [('approval_request_id', '=', req.id)],
                limit=1
            )
            if leave:
                leave.action_approve(comment=comment)
                if leave.state == 'approved':
                    final_approved += 1
                elif req.status == 'pending':
                    moved_next += 1
                else:
                    skipped += 1
                continue

            # Try OnDuty
            onduty = OnDuty.search(
                [('approval_request_id', '=', req.id)],
                limit=1
            )
            if onduty:
                onduty.action_approve(comment=comment)
                if onduty.state == 'approved':
                    final_approved += 1
                elif onduty.state == 'pending':
                    moved_next += 1
                else:
                    skipped += 1
                continue

            skipped += 1

        message = []
        if final_approved:
            message.append(f"{final_approved} requests fully approved.")
        if moved_next:
            message.append(f"{moved_next} requests moved to next step.")
        if skipped:
            message.append(f"{skipped} requests skipped.")

        if not message:
            message.append("No requests were processed.")

        return self._open_success_message_wizard("\n".join(message))



    def _open_success_message_wizard(self, message):
        return {
            'name': 'Success',
            'type': 'ir.actions.act_window',
            'res_model': 'success.message.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref('approval_central.view_success_message_wizard').id,
            'target': 'new',
            'context': {'default_message': message},
        }



