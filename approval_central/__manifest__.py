{
    'name': 'Centralized Approval Workflow',
    'version': '1.0',
    'summary': 'Generic approval workflow engine for any request type (Job Order, Purchase, Check Sign, etc.)',
    'description': """
        This module provides a centralized and dynamic approval workflow system
        that supports multi-company, multi-branch, condition-based and fallback approval logic.
    """,
    'category': 'Tools',
    'author': 'Hagbes',
    'website': 'https://hagbes.com',
    'depends': ['base','mail'],  # You can add 'hr', 'purchase', etc., when you integrate
    'data': [
        'views/approval_flow_views.xml',
        'views/approval_step_views.xml',
        'views/approval_condition_views.xml',
        'data/dashboard_approval_view.sql',
        'data/approval_actions.xml',
        'views/approval_dashboard_views.xml',
        'views/approval_request_views.xml',
        'views/approval_history_views.xml',
        'security/approval_group_category.xml',
        'views/approval_actions.xml',
        'views/approval_delegate.xml',
        'security/groups.xml',
        'views/menus.xml',
        'security/ir_model_access.xml',
        'security/ir.model.access.csv',
        'views/sucess_message_wizard.xml'
    ],
    # 'post_init_hook': 'clean_old_rejected_requests',
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
