from odoo import http
from odoo.http import request

class ApprovalAPI(http.Controller):

    @http.route('/api/approve', type='json', auth='user')
    def approve(self, model_name, record_id, action, remark=None):
        approval = request.env['approval.request'].sudo().search([
            ('model_name', '=', model_name),
            ('record_id', '=', record_id)
        ], limit=1)
        if not approval:
            return {'error': 'Request not found'}

        if approval.status != 'pending':
            return {'error': 'Already processed'}

        # simulate approval logic (check roles, step etc.)
        approval.write({
            'status': 'approved' if action == 'approve' else 'rejected'
        })
        request.env['approval.action.log'].sudo().create({
            'request_id': approval.id,
            'action': action,
            'user_id': request.env.uid,
            'remark': remark,
            'step_number': approval.current_step
        })
        return {'success': True, 'new_status': approval.status}
