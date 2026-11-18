{
    'name': 'Smart Sales CRM – Lead Scoring, Round Robin Lead Assignment, Lead Status & Sales Dashboard',
    'version': '20.0.1.0.0',
    'category': 'Sales/CRM',
    'sequence': 16,
    'summary': 'Modern CRM for Odoo 20: lead status path, Hot/Warm/Cold rating, lead scoring, '
               'round robin lead assignment rules, convert lead wizard, activity timeline, CRM kanban, '
               'mass update, stage guidance, follow-up automation and interactive sales dashboard.',
    'description': """
Smart Sales CRM for Odoo 20
===========================
A modern, enterprise-grade CRM experience built on top of the standard Odoo
CRM (nothing is replaced, everything is extended):

* Record page: highlights panel, lead status path, key fields &
  guidance for success per stage, duplicate alert banner
* Activity timeline (Log a Call, Email, New Task, New Event, Note,
  Upcoming & Overdue, Past Activity grouped by month)
* Lead Status (New / Working / Nurturing / Qualified / Unqualified / Converted)
* Lead Rating (Hot / Warm / Cold) and rule-based Lead Score (0-100)
* Lead Assignment Rules (ordered, first match: user, round robin, team workload)
* Convert Lead dialog (Account, Contact, Opportunity)
* Stage-based automatic activities and stale lead follow-up automation
* Mass Change Owner / Change Status / Run Assignment Rules
* Interactive CRM Sales Dashboard (KPIs, charts, leaderboard, filters)
""",
    'author': 'Donika Enterprise',
    'maintainer': 'Donika Enterprise',
    'support': 'shra.patel225@gmail.com',
    'license': 'OPL-1',
    'price': 200.0,
    'currency': 'EUR',
    'depends': [
        'crm',
        'calendar',
        'mail',
        'utm',
    ],
    'data': [
        'security/ir.access.csv',
        'data/crm_ss_data.xml',
        'data/ir_cron_data.xml',
        'wizard/crm_ss_lead_convert_views.xml',
        'wizard/crm_ss_mass_update_views.xml',
        'wizard/crm_ss_log_call_views.xml',
        'views/crm_ss_scoring_rule_views.xml',
        'views/crm_ss_assignment_rule_views.xml',
        'views/crm_stage_views.xml',
        'views/crm_lead_views.xml',
        'views/res_config_settings_views.xml',
        'views/crm_ss_dashboard_views.xml',
        'views/crm_ss_menus.xml',
    ],
    'demo': [
        'data/crm_ss_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'crm_smart_sales/static/src/scss/smart_sales.scss',
            'crm_smart_sales/static/src/components/**/*',
        ],
    },
    'images': [
        'static/description/banner.png',
    ],
    'post_init_hook': '_ss_post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
