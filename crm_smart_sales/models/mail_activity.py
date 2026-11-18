from odoo import api, models


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    @api.model
    def _ss_leads(self, activities):
        if 'activity_ids' not in self.env['crm.lead']._ss_scoring_fields() and not self.env.context.get('ss_force_leads'):
            lead_ids = set()
        else:
            lead_ids = {a.res_id for a in activities if a.res_model == 'crm.lead' and a.res_id}
        return self.env['crm.lead'].sudo().browse(lead_ids).exists() if lead_ids else self.env['crm.lead']

    @api.model_create_multi
    def create(self, vals_list):
        activities = super().create(vals_list)
        leads = self._ss_leads(activities)
        if leads:
            leads._ss_compute_scores()
        return activities

    def _action_done(self, feedback=False, attachment_ids=None):
        leads = self.with_context(ss_force_leads=True)._ss_leads(self)
        messages = super()._action_done(feedback=feedback, attachment_ids=attachment_ids)
        if leads:
            # interacting with the prospect: New -> Working
            leads._ss_mark_working()
            leads._ss_compute_scores()
        return messages

    def unlink(self):
        leads = self._ss_leads(self)
        res = super().unlink()
        if leads:
            leads._ss_compute_scores()
        return res
