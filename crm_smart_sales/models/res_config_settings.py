from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ss_assignment_on_create = fields.Boolean(
        'Run Assignment Rules on Creation',
        config_parameter='crm_smart_sales.assignment_on_create', default=True)
    ss_rating_hot_threshold = fields.Integer(
        'Hot from score', config_parameter='crm_smart_sales.rating_hot_threshold', default=70)
    ss_rating_warm_threshold = fields.Integer(
        'Warm from score', config_parameter='crm_smart_sales.rating_warm_threshold', default=40)
    ss_duplicate_rule = fields.Selection([
        ('alert', 'Alert (show warning on the record)'),
        ('block', 'Block (prevent creating a lead with the same email)'),
    ], string='Duplicate Rule', config_parameter='crm_smart_sales.duplicate_rule', default='alert')
    ss_followup_enabled = fields.Boolean(
        'Stale Lead Follow-up', config_parameter='crm_smart_sales.followup_enabled', default=True)
    ss_followup_days = fields.Integer(
        'Follow-up after (days)', config_parameter='crm_smart_sales.followup_days', default=3)

    @api.constrains('ss_rating_hot_threshold', 'ss_rating_warm_threshold')
    def _check_ss_thresholds(self):
        for settings in self:
            if not (0 <= settings.ss_rating_warm_threshold <= settings.ss_rating_hot_threshold <= 100):
                raise ValidationError(self.env._(
                    "Rating thresholds must satisfy 0 <= Warm <= Hot <= 100."))

    def set_values(self):
        icp = self.env['ir.config_parameter'].sudo()
        old = (icp.get_int('crm_smart_sales.rating_hot_threshold', 70),
               icp.get_int('crm_smart_sales.rating_warm_threshold', 40))
        super().set_values()
        new = (icp.get_int('crm_smart_sales.rating_hot_threshold', 70),
               icp.get_int('crm_smart_sales.rating_warm_threshold', 40))
        if old != new:
            # thresholds changed: recompute the rating of open leads
            leads = self.env['crm.lead'].sudo().search([('won_status', '=', 'pending')])
            leads._ss_reset_rating()
