from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


class ApprovalCondition(models.Model):
    _name = 'approval.condition'
    _description = 'Approval Workflow Condition'

    step_id = fields.Many2one(
        'approval.step',
        string='Step',
        required=True,
        ondelete='cascade'
    )

    field_to_check = fields.Selection([
        ('amount_total', 'Amount Total'),
        ('partner_id', 'Vendor'),
        ('user_group_id', 'User Group'),
        ('last_updator_group', 'Last Approver'),
        ('custom_field', 'Custom Field (advanced)'),
    ], string='Field to Check', required=True,
        help="Select the field to evaluate on the document.")

    custom_field_name = fields.Char(
        string="Custom Field Name",
        help="Technical field name from the document model. Use dot notation (e.g., line_ids.quantity)."
    )

    aggregation = fields.Selection([
        ('none', 'No Aggregation'),
        ('sum', 'Sum'),
        ('max', 'Max'),
        ('min', 'Min'),
        ('count', 'Count'),
    ], string="Aggregation", default='none',
        help="Only applies if the resolved field is a one2many or list-like.")

    operator = fields.Selection([
        ('=', 'Equals'),
        ('!=', 'Not Equals'),
        ('>', 'Greater Than'),
        ('<', 'Less Than'),
        ('>=', 'Greater or Equal'),
        ('<=', 'Less or Equal'),
    ], string='Operator', required=True)

    value = fields.Char(
        string='Comparison Value',
        help="Value to compare against the selected field."
    )

    group_id = fields.Many2one(
        'res.groups',
        string='User Group',
        domain="[('category_id.name', 'ilike', 'Approval')]",
        help='Used only when Field to Check is set to "User Group".'
    )

    next_step_id = fields.Many2one(
        'approval.step',
        string='Next Step',
        required=True
    )

    sequence = fields.Integer(string="Priority", default=10)

    # ----------------------------
    # UI logic: clear irrelevant fields
    # ----------------------------
    @api.onchange('field_to_check')
    def _onchange_field_to_check(self):
        if self.step_id:
            return {
                'domain': {
                    'next_step_id': [('flow_id', '=', self.step_id.flow_id.id)]
                }
            }
        if self.field_to_check in ['user_group_id', 'last_updator_group']:
            self.custom_field_name = False
            self.value = False
            self.aggregation = 'none'
        elif self.field_to_check == 'custom_field':
            self.group_id = False
        else:
            self.group_id = False
            self.custom_field_name = False
            self.aggregation = 'none'

    # ----------------------------
    # Constraint to enforce logic integrity
    # ----------------------------
    @api.constrains('field_to_check', 'value', 'group_id', 'custom_field_name')
    def _check_condition_configuration(self):
        for rec in self:
            if rec.field_to_check in ['user_group_id', 'last_updator_group'] and not rec.group_id:
                raise ValidationError("You must select a User Group when the field to check is 'User Group'.")
            elif rec.field_to_check == 'custom_field' and not rec.custom_field_name:
                raise ValidationError("You must provide a custom field name when using 'Custom Field'.")
            elif rec.field_to_check not in ['user_group_id', 'last_updator_group','custom_field'] and not rec.value:
                raise ValidationError("You must enter a comparison value for the selected field.")

    # ----------------------------
    # Helper: resolve nested field (supports dot notation and aggregation)
    # ----------------------------
    def _resolve_field_value(self, record, field_path, aggregation='none'):
        try:
            attrs = field_path.split('.')
            value = record
            for attr in attrs:
                value = getattr(value, attr, None)
                if value is None:
                    return None

            # If value is a recordset and aggregation is specified
            if isinstance(value, models.Model) and len(value) > 1:
                if aggregation == 'sum':
                    return sum(getattr(v, attrs[-1], 0) for v in value)
                elif aggregation == 'max':
                    return max(getattr(v, attrs[-1], 0) for v in value)
                elif aggregation == 'min':
                    return min(getattr(v, attrs[-1], 0) for v in value)
                elif aggregation == 'count':
                    return len(value)
            return value
        except Exception as e:
            _logger.warning("Field resolution failed for '%s': %s", field_path, e)
            return None

    # ----------------------------
    # Core method: condition evaluation
    # ----------------------------
    def _evaluate_condition(self, request):
        """Evaluate this condition against the given approval request record."""
        self.ensure_one()

        # 1. Group check
        if self.field_to_check == 'user_group_id':
            submitter = request.create_uid
            return self.group_id.id in submitter.groups_id.ids

        if self.field_to_check == 'last_updator_group':
            try:
                record = self.env[request.res_model].browse(request.res_id)
                if not record:
                    return False
            except Exception as e:
                _logger.warning("Failed to fetch record for last_updator_group: %s", e)
                return False

            last_editor = record.write_uid
            return self.group_id.id in last_editor.groups_id.ids

        # 2. Get target record
        try:
            record = self.env[request.res_model].browse(request.res_id)
            if not record:
                return False
        except Exception as e:
            _logger.warning("Failed to get record for condition: %s", e)
            return False

        # 3. Fetch the correct field
        try:
            if self.field_to_check == 'custom_field':
                field_value = self._resolve_field_value(record, self.custom_field_name, self.aggregation)
                if field_value is None:
                    raise ValidationError(
                        f"The field '{self.custom_field_name}' could not be found.\n"
                        f"Please check your configuration."
                    )
            else:
                field_value = getattr(record, self.field_to_check, None)
        except Exception as e:
            _logger.warning("Field not found or unreadable: %s", e)
            return False

        # 4. Type-safe comparison
        try:
            compare_value = self.value

            # Type coercion
            if isinstance(field_value, (int, float)):
                compare_value = float(compare_value)
            elif isinstance(field_value, bool):
                compare_value = compare_value.lower() in ['true', '1', 'yes']
            elif isinstance(field_value, (fields.Date, fields.Datetime, datetime)):
                compare_value = fields.Date.from_string(compare_value)
            else:
                field_value = str(field_value)
                compare_value = str(compare_value)

            return {
                '=': field_value == compare_value,
                '!=': field_value != compare_value,
                '>': field_value > compare_value,
                '<': field_value < compare_value,
                '>=': field_value >= compare_value,
                '<=': field_value <= compare_value,
            }.get(self.operator, False)

        except Exception as e:
            _logger.warning("Failed to compare values: %s", e)
            return False
