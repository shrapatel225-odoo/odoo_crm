from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.crm_lead import SS_LEAD_STATUS, SS_RATING


class CrmSsMassUpdate(models.TransientModel):
    """List view mass actions: Change Owner, Change Status,
    Change Rating, Change Sales Team, Run Assignment Rules."""
    _name = 'crm.ss.mass.update'
    _description = 'Mass Update Leads'

    lead_ids = fields.Many2many('crm.lead', string='Records')
    lead_count = fields.Integer(compute='_compute_lead_count')
    operation = fields.Selection([
        ('owner', 'Change Owner'),
        ('status', 'Change Lead Status'),
        ('rating', 'Change Rating'),
        ('team', 'Change Sales Team'),
        ('rules', 'Run Assignment Rules'),
    ], required=True, default='owner')
    user_id = fields.Many2one('res.users', string='New Owner', domain="[('share', '=', False)]")
    team_id = fields.Many2one('crm.team', string='Sales Team')
    ss_lead_status = fields.Selection(
        [s for s in SS_LEAD_STATUS if s[0] != 'converted'], string='New Status')
    ss_rating = fields.Selection(SS_RATING, string='New Rating')
    notify = fields.Boolean('Send Notification Email', default=True,
                            help="Send a notification email to the new owner.")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'crm.lead' and self.env.context.get('active_ids'):
            res['lead_ids'] = [(6, 0, self.env.context['active_ids'])]
        if self.env.context.get('default_operation'):
            res['operation'] = self.env.context['default_operation']
        return res

    @api.depends('lead_ids')
    def _compute_lead_count(self):
        for wizard in self:
            wizard.lead_count = len(wizard.lead_ids)

    def action_apply(self):
        self.ensure_one()
        leads = self.lead_ids
        if not leads:
            raise UserError(_("No record selected."))
        if self.operation == 'owner':
            if not self.user_id:
                raise UserError(_("Select the new owner."))
            vals = {'user_id': self.user_id.id}
            if self.team_id:
                vals['team_id'] = self.team_id.id
            leads.with_context(mail_auto_subscribe_no_notify=not self.notify).write(vals)
        elif self.operation == 'status':
            if not self.ss_lead_status:
                raise UserError(_("Select the new status."))
            leads.filtered(lambda l: l.type == 'lead').write({'ss_lead_status': self.ss_lead_status})
        elif self.operation == 'rating':
            if not self.ss_rating:
                raise UserError(_("Select the new rating."))
            leads.write({'ss_rating': self.ss_rating})
        elif self.operation == 'team':
            if not self.team_id:
                raise UserError(_("Select the sales team."))
            leads.write({'team_id': self.team_id.id})
        elif self.operation == 'rules':
            return leads.action_ss_run_assignment_rules()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _('%s record(s) updated.', len(leads)),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
