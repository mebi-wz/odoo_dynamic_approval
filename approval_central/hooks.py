from odoo import api, SUPERUSER_ID
import logging

_logger = logging.getLogger(__name__)

def create_dynamic_menus(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    approval_requests = env['approval.request'].search_read([], ['res_model'])

    model_names = set(rec['res_model'] for rec in approval_requests if rec['res_model'])
    _logger.info("Found target models: %s", model_names)

    try:
        parent_menu = env.ref('approval_central.menu_approval_root')
    except ValueError:
        _logger.error("Root menu not found. Check XML ID 'approval_central.menu_approval_root'")
        return

    for model_name in model_names:
        model = env['ir.model'].search([('model', '=', model_name)], limit=1)
        if not model:
            _logger.warning("Model not found in ir.model: %s", model_name)
            continue

        menu_name = f"{model.name} Approvals"

        # Prevent duplicate menus
        existing_menu = env['ir.ui.menu'].search([
            ('name', '=', menu_name),
            ('parent_id', '=', parent_menu.id)
        ], limit=1)
        if existing_menu:
            _logger.info("Menu already exists for model: %s", model.name)
            continue

        # Create action
        action = env['ir.actions.act_window'].create({
            'name': menu_name,
            'res_model': 'approval.request',
            'view_mode': 'tree,kanban,form',
            'domain': [('res_model', '=', model_name)],
        })

        # Register external ID
        xml_id_name = f"approval_action_{model.model.replace('.', '_')}"
        env['ir.model.data'].create({
            'name': xml_id_name,
            'model': 'ir.actions.act_window',
            'module': 'approval_central',
            'res_id': action.id,
            'noupdate': True,
        })

        # Create menu
        env['ir.ui.menu'].create({
            'name': menu_name,
            'parent_id': parent_menu.id,
            'action': f'{action._name},{action.id}',
            'sequence': 10,
        })

        _logger.info("Created menu and action for model: %s", model.name)
