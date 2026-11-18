from odoo import _, api, fields, models


class CrmSsLogCall(models.TransientModel):
    """"Log a Call" from the activity composer.

    The call is stored as a *done* activity of type Call (standard
    ``mail.activity`` + chatter message) so it appears in the chatter, the
    activity reports and the activity timeline. No parallel activity system.
    """
    _name = 'crm.ss.log.call'
    _description = 'Log a Call'

    lead_id = fields.Many2one('crm.lead', required=True, ondelete='cascade')
    summary = fields.Char('Subject', required=True, default=lambda self: _('Call'))
    outcome = fields.Selection([
        ('connected', 'Connected'),
        ('voicemail', 'Left Voicemail'),
        ('no_answer', 'No Answer'),
        ('wrong_number', 'Wrong Number'),
    ], default='connected', required=True)
    comments = fields.Text('Comments')
    schedule_follow_up = fields.Boolean('Schedule a Follow-up')
    follow_up_date = fields.Date('Follow-up Date', default=lambda self: fields.Date.add(fields.Date.context_today(self), days=2))
    follow_up_summary = fields.Char('Follow-up Subject')

    @api.model
    def _get_call_type(self):
        call = self.env.ref('mail.mail_activity_data_call', raise_if_not_found=False)
        if not call:
            call = self.env['mail.activity.type'].search([('category', '=', 'phonecall')], limit=1)
        return call

    def action_log_call(self):
        self.ensure_one()
        call_type = self._get_call_type()
        lead = self.lead_id
        outcome = dict(self._fields['outcome']._description_selection(self.env))[self.outcome]
        feedback = '%s: %s' % (outcome, self.comments) if self.comments else outcome
        activity = self.env['mail.activity'].create({
            'res_model_id': self.env['ir.model']._get_id('crm.lead'),
            'res_id': lead.id,
            'activity_type_id': call_type.id,
            'summary': self.summary,
            'user_id': self.env.user.id,
            'date_deadline': fields.Date.context_today(self),
        })
        activity.action_feedback(feedback=feedback)
        if self.schedule_follow_up:
            lead.activity_schedule(
                activity_type_id=call_type.id,
                summary=self.follow_up_summary or _('Follow-up call'),
                date_deadline=self.follow_up_date,
                user_id=self.env.user.id,
            )
        return {'type': 'ir.actions.act_window_close'}
