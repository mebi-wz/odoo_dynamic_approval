import logging

_logger = logging.getLogger(__name__)


def clear_old_rejected_requests(cr, registry):
    """Post-init hook to clear approvers from already rejected requests."""
    from odoo.api import Environment
    env = Environment(cr, 1, {})  # Use superuser

    Approvals = env['approval.request'].sudo()

    # 1️⃣ Find all rejected requests that still have approvers
    records_to_clean = Approvals.search([
        ('status', '=', 'rejected'),
        ('approver_ids', '!=', False),
    ])

    _logger.info("Found %s rejected requests with approvers.", len(records_to_clean))

    # 2️⃣ Loop and clear
    for rec in records_to_clean:
        approver_names = rec.approver_ids.mapped('name')
        _logger.info(
            "Before clearing, approval.request id=%s had approvers: %s",
            rec.id,
            ', '.join(approver_names) if approver_names else 'None'
        )
        rec.write({'approver_ids': [(5, 0, 0)]})  # clear M2M
        _logger.info("Cleared approvers for approval.request id=%s", rec.id)

    _logger.info("Rejected requests cleanup completed.")
