import logging
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools.misc import format_date, format_datetime, formatLang

from .crm_ss_scoring_rule import parse_rule_domain

_logger = logging.getLogger(__name__)

SS_LEAD_STATUS = [
    ('new', 'New'),
    ('working', 'Working'),
    ('nurturing', 'Nurturing'),
    ('qualified', 'Qualified'),
    ('unqualified', 'Unqualified'),
    ('converted', 'Converted'),
]

SS_RATING = [
    ('hot', 'Hot'),
    ('warm', 'Warm'),
    ('cold', 'Cold'),
]

# Writing only those fields never changes a lead score: avoid useless recomputation.
SS_SCORE_IGNORED_FIELDS = {
    'ss_score', 'ss_rating', 'ss_status_date', 'ss_assignment_rule_id', 'color', 'date_automation_last',
    'message_main_attachment_id', 'message_follower_ids', 'message_ids', 'activity_ids',
    'date_last_stage_update', 'kanban_state', 'automated_probability', 'description',
}

ICP_PREFIX = 'crm_smart_sales.'


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------

    ss_lead_status = fields.Selection(
        SS_LEAD_STATUS, string='Lead Status', default='new', required=True, index=True,
        tracking=True, copy=False, group_expand='_ss_group_expand_status',
        help="Lead status (path). Converted is set automatically when the lead "
             "becomes an opportunity, Unqualified when a lead is marked as lost.")
    ss_status_date = fields.Datetime('Status Changed On', readonly=True, copy=False)
    ss_score = fields.Integer(
        'Lead Score', default=0, readonly=True, copy=False, aggregator='avg',
        help="Rule-based score (0-100) computed from the active Lead Scoring Rules.")
    ss_rating = fields.Selection(
        SS_RATING, string='Rating', default='cold', required=True, index=True, tracking=True, copy=False,
        help="Hot / Warm / Cold. Set from the lead score thresholds defined in the settings each time "
             "the score changes; it can be overridden manually until the score changes again.")
    ss_score_breakdown = fields.Html('Score Breakdown', compute='_compute_ss_score_breakdown', sanitize=False)
    ss_guidance = fields.Html(related='stage_id.ss_guidance', string='Guidance for Success')
    ss_key_fields_html = fields.Html('Key Fields', compute='_compute_ss_key_fields_html', sanitize=False)
    ss_has_path_info = fields.Boolean(compute='_compute_ss_key_fields_html')
    ss_last_activity_date = fields.Date('Last Activity', compute='_compute_ss_last_activity_date')
    ss_age_days = fields.Integer('Age (days)', compute='_compute_ss_age_days')
    ss_duplicate_message = fields.Char(compute='_compute_ss_duplicate_message')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    def _ss_group_expand_status(self, values, domain):
        """Kanban columns: every status, Converted only when it holds records."""
        return [key for key, _label in SS_LEAD_STATUS if key != 'converted' or key in values]

    @api.model
    def _ss_param(self, kind, key, default):
        """Typed read of a module setting (Odoo 20 ``ir.config_parameter`` API)."""
        icp = self.env['ir.config_parameter'].sudo()
        return getattr(icp, f'get_{kind}')(ICP_PREFIX + key, default)

    @api.model
    def _ss_rating_thresholds(self):
        return (self._ss_param('int', 'rating_hot_threshold', 70),
                self._ss_param('int', 'rating_warm_threshold', 40))

    def _ss_rating_for_score(self, score, thresholds=None):
        hot, warm = thresholds or self._ss_rating_thresholds()
        return 'hot' if score >= hot else 'warm' if score >= warm else 'cold'

    def _ss_reset_rating(self):
        """Re-apply the score thresholds (drops manual overrides).

        Done in SQL: a configuration change must not touch the records'
        "Last Updated" date nor flood the chatter.
        """
        if not self:
            return
        hot, warm = self._ss_rating_thresholds()
        self.env.flush_all()
        self.env.cr.execute("""
            UPDATE crm_lead
               SET ss_rating = CASE WHEN ss_score >= %(hot)s THEN 'hot'
                                    WHEN ss_score >= %(warm)s THEN 'warm'
                                    ELSE 'cold' END
             WHERE id = ANY(%(ids)s)
        """, {'hot': hot, 'warm': warm, 'ids': self.ids})
        self.invalidate_recordset(['ss_rating'])

    def _compute_ss_score_breakdown(self):
        rules = self._ss_get_scoring_rules()
        for lead in self:
            if not lead.id:
                lead.ss_score_breakdown = False
                continue
            rows = []
            for rule in rules:
                if rule.company_id and lead.company_id and rule.company_id != lead.company_id:
                    continue
                matched = bool(lead.sudo().filtered_domain(parse_rule_domain(rule.domain)))
                if not matched:
                    continue
                css = 'text-success' if rule.points >= 0 else 'text-danger'
                rows.append(Markup(
                    '<tr><td>%s</td><td class="text-end %s fw-bold">%s%s</td></tr>'
                ) % (rule.name, css, '+' if rule.points >= 0 else '', rule.points))
            if not rows:
                lead.ss_score_breakdown = Markup('<p class="text-muted mb-0">%s</p>') % _(
                    "No scoring rule matches this lead yet.")
                continue
            lead.ss_score_breakdown = Markup(
                '<table class="table table-sm o_ss_score_table mb-0"><tbody>%s</tbody>'
                '<tfoot><tr><th>%s</th><th class="text-end">%s / 100</th></tr></tfoot></table>'
            ) % (Markup('').join(rows), _("Lead Score"), lead.ss_score)

    @api.depends('stage_id', 'type')
    def _compute_ss_key_fields_html(self):
        for lead in self:
            key_fields = lead.stage_id.ss_key_field_ids if lead.type == 'opportunity' else self.env['ir.model.fields']
            lead.ss_has_path_info = bool(key_fields or (lead.type == 'opportunity' and lead.stage_id.ss_guidance))
            if not key_fields:
                lead.ss_key_fields_html = False
                continue
            items = []
            for imf in key_fields:
                if imf.name not in lead._fields:
                    continue
                value = lead._ss_display_value(imf.name)
                icon = 'check_circle' if value else 'radio_button_unchecked'
                css = 'text-success' if value else 'text-muted'
                items.append(Markup(
                    '<div class="o_ss_key_field"><i class="oi %s me-1" data-icon="%s"></i>'
                    '<span class="o_ss_key_field_label">%s</span>'
                    '<span class="o_ss_key_field_value">%s</span></div>'
                ) % (css, icon, imf.field_description, value or '—'))
            lead.ss_key_fields_html = Markup('<div class="o_ss_key_fields">%s</div>') % Markup('').join(items)

    def _ss_display_value(self, fname):
        """Human readable value of field ``fname`` (empty string when not set)."""
        self.ensure_one()
        field = self._fields[fname]
        value = self[fname]
        if field.type == 'boolean':
            return _('Yes') if value else ''
        if not value and value != 0:
            return ''
        if field.type in ('many2one', 'many2many'):
            return ', '.join(value.mapped('display_name'))
        if field.type == 'selection':
            return dict(field._description_selection(self.env)).get(value, value)
        if field.type == 'date':
            return format_date(self.env, value)
        if field.type == 'datetime':
            return format_datetime(self.env, value)
        if field.type == 'monetary':
            return (value and self.company_currency.format(value)) or ''
        if field.type == 'float':
            return value and formatLang(self.env, value) or ''
        if field.type == 'integer':
            return value and str(value) or ''
        if field.type == 'html':
            return value and _('Filled') or ''
        return str(value)

    def _compute_ss_last_activity_date(self):
        lead_ids = [lead.id for lead in self if lead.id]
        last_dates = {}
        if lead_ids:
            for res_id, date_done in self.env['mail.activity'].with_context(active_test=False).sudo()._read_group(
                    [('res_model', '=', 'crm.lead'), ('res_id', 'in', lead_ids),
                     ('active', '=', False), ('date_done', '!=', False)],
                    ['res_id'], ['date_done:max']):
                last_dates[res_id] = date_done
            for res_id, date in self.env['mail.message'].sudo()._read_group(
                    [('model', '=', 'crm.lead'), ('res_id', 'in', lead_ids),
                     ('message_type', 'in', ('email', 'comment'))],
                    ['res_id'], ['date:max']):
                if date:
                    date = date.date()
                    if not last_dates.get(res_id) or last_dates[res_id] < date:
                        last_dates[res_id] = date
        for lead in self:
            lead.ss_last_activity_date = last_dates.get(lead.id, False)

    def _compute_ss_age_days(self):
        now = fields.Datetime.now()
        for lead in self:
            lead.ss_age_days = (now - lead.create_date).days if lead.create_date else 0

    @api.depends('duplicate_lead_count')
    def _compute_ss_duplicate_message(self):
        for lead in self:
            count = lead.duplicate_lead_count
            if count:
                lead.ss_duplicate_message = _(
                    "We found %(count)s potential duplicate(s) of this %(kind)s.",
                    count=count, kind=_('lead') if lead.type == 'lead' else _('opportunity'))
            else:
                lead.ss_duplicate_message = False

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        for vals in vals_list:
            if vals.get('type') == 'opportunity' and 'ss_lead_status' not in vals:
                vals['ss_lead_status'] = 'converted'
            vals.setdefault('ss_status_date', now)
        leads = super().create(vals_list)

        if not self.env.context.get('ss_skip_score'):
            leads._ss_compute_scores()

        if (not self.env.context.get('ss_skip_assignment')
                and self._ss_param('bool', 'assignment_on_create', True)):
            # rules flagged "Reassign Owned Leads" are handled in the engine
            leads._ss_apply_assignment_rules(force=False)

        leads.filtered(lambda l: l.type == 'opportunity')._ss_schedule_stage_activity()
        leads._ss_check_duplicates_block()
        return leads

    def write(self, vals):
        if self.env.context.get('ss_skip_score') or not vals:
            return super().write(vals)

        vals = dict(vals)
        now = fields.Datetime.now()
        # converted: lead becomes an opportunity
        if vals.get('type') == 'opportunity' and 'ss_lead_status' not in vals:
            leads_to_convert = self.filtered(lambda l: l.type == 'lead')
            if leads_to_convert:
                leads_to_convert.with_context(ss_skip_score=True, ss_converting=True).write({
                    'ss_lead_status': 'converted', 'ss_status_date': now})
        if 'ss_lead_status' in vals:
            if (vals['ss_lead_status'] == 'converted' and vals.get('type') != 'opportunity'
                    and not self.env.context.get('ss_converting')
                    and any(lead.type == 'lead' for lead in self)):
                raise UserError(_("A lead becomes Converted only through the conversion. "
                                  "Use the Convert button to create the account, contact and opportunity."))
            vals['ss_status_date'] = now
        stage_changed = self.browse()
        if vals.get('stage_id'):
            stage_changed = self.filtered(lambda l: l.stage_id.id != vals['stage_id'])

        res = super().write(vals)

        if (set(vals) - SS_SCORE_IGNORED_FIELDS) & self._ss_scoring_fields():
            self._ss_compute_scores()
        if stage_changed:
            stage_changed.filtered(lambda l: l.type == 'opportunity' and l.active)._ss_schedule_stage_activity()
        return res

    def _ss_check_duplicates_block(self):
        if self._ss_param('str', 'duplicate_rule', 'alert') != 'block':
            return
        if self.env.context.get('install_mode') or self.env.context.get('ss_allow_duplicates'):
            return
        for lead in self:
            if not lead.email_normalized:
                continue
            dup = self.sudo().search([
                ('id', '!=', lead.id),
                ('email_normalized', '=', lead.email_normalized),
                ('won_status', '=', 'pending'),
                ('company_id', 'in', [lead.company_id.id, False]),
            ], limit=1)
            if dup:
                raise ValidationError(_(
                    "Duplicate rule: an open lead/opportunity with the email %(email)s already exists (%(name)s). "
                    "Merge or update the existing record instead.",
                    email=lead.email_from, name=dup.name))

    # ------------------------------------------------------------------
    # Lead scoring
    # ------------------------------------------------------------------

    @api.model
    def _ss_get_scoring_rules(self):
        return self.env['crm.ss.scoring.rule'].sudo().with_context(active_test=True).search([])

    @api.model
    @api.ormcache(cache='stable')
    def _ss_scoring_fields(self):
        """Top-level crm.lead fields used by the active scoring rules.

        Used to skip score recomputation when unrelated fields are written
        (e.g. mass assignment), keeping standard CRM flows as fast as before.
        """
        names = set()
        for rule in self._ss_get_scoring_rules():
            try:
                domain = parse_rule_domain(rule.domain)
            except Exception:  # noqa: BLE001
                continue
            for condition in domain.iter_conditions():
                names.add(condition.field_expr.split('.')[0])
        return frozenset(names)

    def _ss_score_values(self):
        """Return ``{lead_id: score}`` (0-100) for ``self`` according to the active rules."""
        leads = self.sudo()
        scores = dict.fromkeys(leads.ids, 0)
        for rule in self._ss_get_scoring_rules():
            try:
                domain = parse_rule_domain(rule.domain)
            except Exception:  # noqa: BLE001
                _logger.warning("Invalid scoring rule domain on rule %s", rule.id)
                continue
            candidates = leads
            if rule.company_id:
                candidates = leads.filtered(lambda l: not l.company_id or l.company_id == rule.company_id)
            for lead in candidates.filtered_domain(domain):
                scores[lead.id] += rule.points
        return {lead_id: max(0, min(100, score)) for lead_id, score in scores.items()}

    def _ss_changed_scores(self):
        """Group the leads whose score changes: ``{score: [ids]}``."""
        leads = self.sudo().exists()
        if not leads:
            return {}
        values = leads._ss_score_values()
        by_score = {}
        for lead in leads:
            if values[lead.id] != lead.ss_score:
                by_score.setdefault(values[lead.id], []).append(lead.id)
        return by_score

    def _ss_compute_scores(self):
        """Recompute ``ss_score`` and ``ss_rating`` for ``self`` (interactive changes, ORM)."""
        thresholds = self._ss_rating_thresholds()
        for score, ids in self._ss_changed_scores().items():
            self.browse(ids).sudo().with_context(ss_skip_score=True).write({
                'ss_score': score,
                'ss_rating': self._ss_rating_for_score(score, thresholds),
            })

    def _ss_store_scores_sql(self):
        """Batch recomputation (install, daily cron): stored directly in SQL so
        that it never changes the "Last Updated" date of the records, never
        posts chatter messages and stays fast on large databases."""
        thresholds = self._ss_rating_thresholds()
        by_score = self._ss_changed_scores()
        for score, ids in by_score.items():
            self.env.cr.execute(
                "UPDATE crm_lead SET ss_score = %s, ss_rating = %s WHERE id = ANY(%s)",
                [score, self._ss_rating_for_score(score, thresholds), ids],
            )
        if by_score:
            self.invalidate_recordset(['ss_score', 'ss_rating'])
        return sum(len(ids) for ids in by_score.values())

    @api.model
    def _ss_cron_recompute_scores(self, batch_size=5000):
        domain = [('won_status', '=', 'pending')]
        last_id = 0
        updated = 0
        while True:
            leads = self.sudo().with_context(active_test=False).search(
                Domain.AND([domain, [('id', '>', last_id)]]), order='id', limit=batch_size)
            if not leads:
                break
            self.env.flush_all()
            updated += leads._ss_store_scores_sql()
            last_id = leads[-1].id
            self.env.invalidate_all()
            if self.env.context.get('ir_cron_progress_id'):
                self.env['ir.cron']._commit_progress(len(leads))
        _logger.info("Smart Sales CRM: %s lead score(s) updated", updated)
        return updated

    # ------------------------------------------------------------------
    # Automation
    # ------------------------------------------------------------------

    def _ss_schedule_stage_activity(self):
        """Stage-based action: schedule the stage activity for the salesperson."""
        if self.env.context.get('ss_skip_stage_activity'):
            return
        today = fields.Date.context_today(self)
        for lead in self:
            stage = lead.stage_id
            if not stage.ss_activity_type_id:
                continue
            existing = lead.activity_ids.filtered(lambda a: a.activity_type_id == stage.ss_activity_type_id)
            if existing:
                continue
            lead.sudo().activity_schedule(
                activity_type_id=stage.ss_activity_type_id.id,
                summary=stage.ss_activity_summary or stage.ss_activity_type_id.summary or stage.name,
                date_deadline=fields.Date.add(today, days=stage.ss_activity_days or 0),
                user_id=(lead.user_id or self.env.user).id,
            )

    @api.model
    def _ss_cron_followup_stale_leads(self):
        """Follow-up automation: leads in New/Working status without any activity
        planned and not updated for X days get a follow-up To-Do for their owner."""
        if not self._ss_param('bool', 'followup_enabled', True):
            return
        days = max(self._ss_param('int', 'followup_days', 3), 1)
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            return
        limit_date = fields.Datetime.now() - timedelta(days=days)
        leads = self.sudo().search([
            ('type', '=', 'lead'),
            ('ss_lead_status', 'in', ('new', 'working')),
            ('activity_ids', '=', False),
            ('user_id', '!=', False),
            ('write_date', '<', limit_date),
        ], limit=1000)
        for lead in leads:
            lead.activity_schedule(
                activity_type_id=activity_type.id,
                summary=_("Follow up: no activity for %s days", days),
                user_id=lead.user_id.id,
            )
        _logger.info("Smart Sales CRM: %s follow-up activities created", len(leads))

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    def action_set_lost(self, **additional_values):
        leads = self.filtered(lambda l: l.type == 'lead' and l.ss_lead_status != 'unqualified')
        res = super().action_set_lost(**additional_values)
        if leads:
            leads.write({'ss_lead_status': 'unqualified'})
        return res

    def action_restore(self):
        res = super().action_restore()
        self.filtered(lambda l: l.type == 'lead' and l.ss_lead_status == 'unqualified').write(
            {'ss_lead_status': 'working'})
        return res

    def _ss_mark_working(self):
        """New leads become Working once the rep interacts with the prospect."""
        to_update = self.filtered(lambda l: l.type == 'lead' and l.ss_lead_status == 'new')
        if to_update:
            to_update.sudo().write({'ss_lead_status': 'working'})

    def _message_post_after_hook(self, message):
        res = super()._message_post_after_hook(message)
        if (message.message_type in ('comment', 'email_outgoing')
                and message.subtype_id == self.env.ref('mail.mt_comment', raise_if_not_found=False)
                and self.env.user._is_internal()):
            self._ss_mark_working()
        return res

    def action_ss_set_status(self):
        """Path click / button: set the status given in context."""
        status = self.env.context.get('ss_status')
        if status not in dict(SS_LEAD_STATUS) or status == 'converted':
            return False
        self.write({'ss_lead_status': status})
        return True

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_ss_open_convert_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Convert Lead'),
            'res_model': 'crm.ss.lead.convert',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'active_model': 'crm.lead', 'active_id': self.id, 'active_ids': self.ids},
        }

    def action_ss_log_call(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Log a Call'),
            'res_model': 'crm.ss.log.call',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    def action_ss_send_email(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Email'),
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_model': 'crm.lead',
                'default_res_ids': self.ids,
                'default_composition_mode': 'comment',
                'default_subtype_xmlid': 'mail.mt_comment',
                'default_partner_ids': self.partner_id.ids,
            },
        }

    def action_ss_new_task(self):
        self.ensure_one()
        todo = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Task'),
            'res_model': 'mail.activity.schedule',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'active_model': 'crm.lead',
                'active_id': self.id,
                'active_ids': self.ids,
                'default_activity_type_id': todo.id if todo else False,
            },
        }

    def _ss_mass_update_action(self, operation, name):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': 'crm.ss.mass.update',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'active_model': 'crm.lead',
                'active_ids': self.ids,
                'default_operation': operation,
            },
        }

    def action_ss_mass_change_owner(self):
        return self._ss_mass_update_action('owner', _('Change Owner'))

    def action_ss_mass_change_status(self):
        return self._ss_mass_update_action('status', _('Change Status'))

    def action_ss_recompute_score(self):
        self._ss_compute_scores()
        return True

    @api.model
    def ss_get_timeline(self, lead_id, limit=80):
        """Data for the activity timeline component.

        Returns upcoming / overdue activities (mail.activity) and past activity
        (done activities, emails, notes, meetings) for the lead, using the
        current user's access rights.
        """
        lead = self.browse(lead_id).exists()
        if not lead:
            return {'upcoming': [], 'past': []}
        lead.check_access('read')
        today = fields.Date.context_today(self)

        def user_name(user):
            return user.display_name if user else ''

        upcoming = []
        for act in lead.activity_ids.sorted(lambda a: (a.date_deadline, a.id)):
            upcoming.append({
                'id': act.id,
                'model': 'mail.activity',
                'kind': self._ss_activity_kind(act.activity_type_id),
                'type_name': act.activity_type_id.name or '',
                'title': act.summary or act.activity_type_id.name or _('Activity'),
                'note': act.note or '',
                'date': fields.Date.to_string(act.date_deadline),
                'state': act.state,
                'overdue': act.date_deadline < today,
                'user': user_name(act.user_id),
            })
        # meetings to come
        now = fields.Datetime.now()
        for event in lead.calendar_event_ids.filtered(lambda e: e.start and e.start >= now).sorted('start'):
            upcoming.append({
                'id': event.id,
                'model': 'calendar.event',
                'kind': 'meeting',
                'type_name': _('Meeting'),
                'title': event.name,
                'note': event.description or '',
                'date': fields.Datetime.to_string(event.start),
                'state': 'planned',
                'overdue': False,
                'user': user_name(event.user_id),
            })

        past = []
        done_activities = self.env['mail.activity'].with_context(active_test=False).search([
            ('res_model', '=', 'crm.lead'), ('res_id', '=', lead.id),
            ('active', '=', False), ('date_done', '!=', False),
        ], order='date_done desc, id desc', limit=limit)
        for act in done_activities:
            past.append({
                'id': act.id,
                'model': 'mail.activity',
                'kind': self._ss_activity_kind(act.activity_type_id),
                'type_name': act.activity_type_id.name or '',
                'title': act.summary or act.activity_type_id.name or _('Activity'),
                'note': act.feedback or act.note or '',
                'date': fields.Date.to_string(act.date_done),
                'user': user_name(act.user_id),
            })
        note_subtype = self.env.ref('mail.mt_note')
        messages = self.env['mail.message'].search([
            ('model', '=', 'crm.lead'), ('res_id', '=', lead.id),
            ('message_type', 'in', ('email', 'comment', 'email_outgoing')),
            ('mail_activity_type_id', '=', False),
        ], order='date desc, id desc', limit=limit)
        for msg in messages:
            if msg.message_type in ('email', 'email_outgoing') or msg.subtype_id != note_subtype:
                kind = 'email'
                type_name = _('Email')
            else:
                kind = 'note'
                type_name = _('Note')
            past.append({
                'id': msg.id,
                'model': 'mail.message',
                'kind': kind,
                'type_name': type_name,
                'title': msg.subject or msg.preview or type_name,
                'note': msg.body or '',
                'date': fields.Datetime.to_string(msg.date),
                'user': msg.author_id.display_name or msg.email_from or '',
                'incoming': msg.message_type == 'email',
            })
        for event in lead.calendar_event_ids.filtered(lambda e: e.start and e.start < now):
            past.append({
                'id': event.id,
                'model': 'calendar.event',
                'kind': 'meeting',
                'type_name': _('Meeting'),
                'title': event.name,
                'note': event.description or '',
                'date': fields.Datetime.to_string(event.start),
                'user': user_name(event.user_id),
            })
        past.sort(key=lambda item: item['date'], reverse=True)
        return {'upcoming': upcoming, 'past': past[:limit]}

    @api.model
    def _ss_activity_kind(self, activity_type):
        category = activity_type.category or ''
        xmlid = activity_type.get_external_id().get(activity_type.id, '') if activity_type else ''
        if category == 'phonecall' or xmlid.endswith('mail_activity_data_call'):
            return 'call'
        if category == 'meeting' or xmlid.endswith('mail_activity_data_meeting'):
            return 'meeting'
        if xmlid.endswith('mail_activity_data_email') or category == 'email':
            return 'email'
        return 'task'

