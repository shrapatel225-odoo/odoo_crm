from ast import literal_eval

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain


def parse_rule_domain(domain_str):
    """Parse a domain stored as text (domain widget output) into a Domain.

    Rule domains are evaluated with ``literal_eval`` (same approach as the
    standard ``crm.team.member.assignment_domain``) so no code can be executed.
    """
    return Domain(literal_eval(domain_str or '[]'))


class CrmSsScoringRule(models.Model):
    """Rule-based lead scoring (fit and engagement grading).

    Each active rule adds (or removes) points when a lead matches its
    condition. The total is clamped between 0 and 100 and stored on
    ``crm.lead.ss_score``. It is complementary to Odoo's predictive lead
    scoring (``probability``), which estimates the chance to *win*; this
    score expresses how well a lead *fits* and *engages*.
    """
    _name = 'crm.ss.scoring.rule'
    _description = 'Lead Scoring Rule'
    _order = 'sequence, id'
    _clear_cache_name = 'stable'  # crm.lead._ss_scoring_fields() depends on the rules

    name = fields.Char('Rule', required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    category = fields.Selection([
        ('fit', 'Profile Fit'),
        ('engagement', 'Engagement'),
        ('value', 'Deal Value'),
        ('negative', 'Negative Signal'),
        ('other', 'Other'),
    ], default='fit', required=True)
    domain = fields.Char('Condition', required=True, default='[]',
                         help="Leads matching this condition receive the points of the rule.")
    points = fields.Integer(required=True, default=10,
                            help="Points added to the lead score when the condition matches. "
                                 "Use a negative value to penalise a lead.")
    company_id = fields.Many2one('res.company', string='Company', index=True,
                                 help="Leave empty to apply the rule to every company.")
    description = fields.Text()
    matching_count = fields.Integer('Matching Open Leads', compute='_compute_matching_count')

    _points_range = models.Constraint(
        'CHECK(points >= -100 AND points <= 100)',
        'Rule points must be between -100 and 100.',
    )

    @api.constrains('domain')
    def _check_domain(self):
        Lead = self.env['crm.lead']
        for rule in self:
            try:
                Lead.search(parse_rule_domain(rule.domain), limit=1)
            except Exception as e:  # noqa: BLE001
                raise ValidationError(_("The condition of rule '%(rule)s' is invalid: %(error)s",
                                        rule=rule.name, error=e))

    def _compute_matching_count(self):
        Lead = self.env['crm.lead']
        for rule in self:
            try:
                rule.matching_count = Lead.search_count(
                    Domain.AND([parse_rule_domain(rule.domain), [('won_status', '=', 'pending')]]))
            except Exception:  # noqa: BLE001
                rule.matching_count = 0

    def action_view_matching_leads(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Leads matching "%s"', self.name),
            'res_model': 'crm.lead',
            'view_mode': 'list,kanban,form',
            'domain': list(parse_rule_domain(self.domain)),
        }

    @api.model
    def action_recompute_all_scores(self):
        """Recompute the score of every open lead / opportunity."""
        self.env['crm.lead']._ss_cron_recompute_scores()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _('Lead scores have been recalculated.'),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
