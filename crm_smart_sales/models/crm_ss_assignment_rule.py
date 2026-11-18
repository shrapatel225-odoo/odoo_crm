from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .crm_ss_scoring_rule import parse_rule_domain


class CrmSsAssignmentRule(models.Model):
    """Lead Assignment Rule entry.

    Rules are evaluated in sequence; the first rule whose condition matches a
    lead assigns it (ordered rule entries). This complements
    Odoo's periodic, capacity-based team assignment (``crm.team`` /
    ``crm.team.member``): rules run instantly at creation time (web forms,
    incoming emails, imports, API) or on demand.
    """
    _name = 'crm.ss.assignment.rule'
    _description = 'Lead Assignment Rule'
    _order = 'sequence, id'

    name = fields.Char('Rule Entry', required=True, translate=True)
    sequence = fields.Integer(default=10, help="Rules are evaluated in this order; the first match wins.")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', index=True,
                                 default=lambda self: self.env.company,
                                 help="Leave empty to apply the rule to every company.")
    lead_type = fields.Selection([
        ('lead', 'Leads'),
        ('opportunity', 'Opportunities'),
        ('both', 'Leads and Opportunities'),
    ], string='Applies To', default='lead', required=True)
    domain = fields.Char('Criteria', required=True, default='[]')
    assign_to = fields.Selection([
        ('user', 'Specific User'),
        ('round_robin', 'Round Robin (users)'),
        ('team_load', 'Sales Team Member with Lowest Workload'),
    ], string='Assign To', required=True, default='user')
    user_id = fields.Many2one('res.users', string='User', domain="[('share', '=', False)]")
    user_ids = fields.Many2many('res.users', 'crm_ss_assignment_rule_user_rel', 'rule_id', 'user_id',
                                string='Users', domain="[('share', '=', False)]")
    team_id = fields.Many2one('crm.team', string='Sales Team',
                              help="Sales team set on the lead. Mandatory for 'Lowest Workload'.")
    last_user_id = fields.Many2one('res.users', string='Last Assigned User', readonly=True, copy=False)
    override_owner = fields.Boolean(
        'Reassign Owned Leads',
        help="By default rules only assign leads created without salesperson (web forms, emails, "
             "imports, API). Enable to also reassign leads that already have an owner at creation.")
    notify_owner = fields.Boolean('Notify New Owner', default=True)
    activity_type_id = fields.Many2one('mail.activity.type', string='Follow-up Activity',
                                       domain="['|', ('res_model', '=', False), ('res_model', '=', 'crm.lead')]")
    activity_summary = fields.Char('Activity Summary')
    activity_days = fields.Integer('Due In (days)', default=1)
    assigned_count = fields.Integer('Leads Assigned', readonly=True, copy=False)

    @api.constrains('domain')
    def _check_domain(self):
        for rule in self:
            try:
                self.env['crm.lead'].search(parse_rule_domain(rule.domain), limit=1)
            except Exception as e:  # noqa: BLE001
                raise ValidationError(_("The criteria of rule '%(rule)s' are invalid: %(error)s",
                                        rule=rule.name, error=e))

    @api.constrains('assign_to', 'user_id', 'user_ids', 'team_id')
    def _check_target(self):
        for rule in self:
            if rule.assign_to == 'user' and not rule.user_id:
                raise ValidationError(_("Rule '%s': select the user to assign.", rule.name))
            if rule.assign_to == 'round_robin' and not rule.user_ids:
                raise ValidationError(_("Rule '%s': select at least one user for round robin.", rule.name))
            if rule.assign_to == 'team_load' and not rule.team_id:
                raise ValidationError(_("Rule '%s': select the sales team.", rule.name))

    # ------------------------------------------------------------------
    # Engine
    # ------------------------------------------------------------------

    def _ss_matches(self, lead):
        self.ensure_one()
        if self.company_id and lead.company_id and lead.company_id != self.company_id:
            return False
        if self.lead_type != 'both' and lead.type != self.lead_type:
            return False
        return bool(lead.filtered_domain(parse_rule_domain(self.domain)))

    def _ss_pick_user(self, lead):
        """Return the user selected by this rule for ``lead`` (may be empty)."""
        self.ensure_one()
        Users = self.env['res.users']
        if self.assign_to == 'user':
            return self.user_id
        if self.assign_to == 'round_robin':
            users = self.user_ids.filtered('active').sorted('id')
            if not users:
                return Users
            if self.last_user_id in users:
                index = (list(users).index(self.last_user_id) + 1) % len(users)
            else:
                index = 0
            return users[index]
        if self.assign_to == 'team_load':
            members = self.team_id.crm_team_member_ids.filtered(lambda m: m.active and m.user_id.active)
            users = members.user_id
            if lead.company_id:
                users = users.filtered(lambda u: lead.company_id in u.company_ids)
            if not users:
                return Users
            load = dict(self.env['crm.lead'].sudo()._read_group(
                [('user_id', 'in', users.ids), ('won_status', '=', 'pending')],
                ['user_id'], ['__count'],
            ))
            return min(users.sorted('id'), key=lambda u: load.get(u, 0))
        return Users


class CrmLeadAssignment(models.Model):
    _inherit = 'crm.lead'

    ss_assignment_rule_id = fields.Many2one(
        'crm.ss.assignment.rule', string='Assigned By Rule', readonly=True, copy=False,
        index='btree_not_null', ondelete='set null')

    def _ss_apply_assignment_rules(self, force=False):
        """Apply the first matching assignment rule to each lead of ``self``.

        :param bool force: when True (manual "Run Assignment Rules"), leads that
            already have an owner are reassigned; otherwise only leads without
            owner, or rules flagged 'Reassign Owned Leads', are applied.
        :return: recordset of assigned leads
        """
        rules = self.env['crm.ss.assignment.rule'].sudo().with_context(active_test=True).search([])
        if not rules:
            return self.browse()
        assigned = self.browse()
        for lead in self:
            for rule in rules:
                if lead.user_id and not (force or rule.override_owner):
                    continue
                if not rule._ss_matches(lead):
                    continue
                user = rule._ss_pick_user(lead)
                if not user:
                    continue
                vals = {'user_id': user.id, 'ss_assignment_rule_id': rule.id}
                if rule.team_id:
                    vals['team_id'] = rule.team_id.id
                lead.sudo().with_context(ss_skip_assignment=True, mail_auto_subscribe_no_notify=not rule.notify_owner).write(vals)
                rule.sudo().write({
                    'last_user_id': user.id,
                    'assigned_count': rule.assigned_count + 1,
                })
                if rule.activity_type_id:
                    lead.sudo().activity_schedule(
                        activity_type_id=rule.activity_type_id.id,
                        summary=rule.activity_summary or rule.activity_type_id.summary or '',
                        date_deadline=fields.Date.add(fields.Date.context_today(self), days=rule.activity_days),
                        user_id=user.id,
                    )
                lead.sudo().message_post(
                    body=_("Assigned to %(user)s by assignment rule \"%(rule)s\".", user=user.name, rule=rule.name),
                    subtype_xmlid='mail.mt_note',
                )
                assigned |= lead
                break
        return assigned

    def action_ss_run_assignment_rules(self):
        assigned = self._ss_apply_assignment_rules(force=True)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if assigned else 'warning',
                'message': _('%(count)s of %(total)s record(s) assigned by assignment rules.',
                             count=len(assigned), total=len(self)),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
