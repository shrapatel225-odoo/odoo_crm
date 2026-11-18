from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.fields import Domain
from odoo.tools.misc import format_date

from .crm_lead import SS_LEAD_STATUS, SS_RATING


class CrmSsDashboard(models.AbstractModel):
    """Server side of the Smart Sales CRM dashboard (client action).

    All figures are computed with the ORM in the current user's environment,
    so access rights and record rules (own documents / all documents /
    multi-company) are always respected. Nothing is cached nor stored.
    """
    _name = 'crm.ss.dashboard'
    _description = 'Smart Sales CRM Dashboard'

    # ------------------------------------------------------------------
    # Domains
    # ------------------------------------------------------------------

    @api.model
    def _ss_utc_bound(self, date_str, next_day=False):
        """Midnight of ``date_str`` in the user's timezone, as a UTC datetime string."""
        day = fields.Date.to_date(date_str)
        if next_day:
            day += timedelta(days=1)
        try:
            tz = ZoneInfo(self.env.user.tz or 'UTC')
        except Exception:  # noqa: BLE001
            tz = UTC
        local = datetime.combine(day, time.min).replace(tzinfo=tz)
        return fields.Datetime.to_string(local.astimezone(UTC).replace(tzinfo=None))

    @api.model
    def _ss_base_domain(self, filters):
        filters = filters or {}
        domain = Domain.TRUE
        if filters.get('date_from'):
            domain &= Domain('create_date', '>=', self._ss_utc_bound(filters['date_from']))
        if filters.get('date_to'):
            domain &= Domain('create_date', '<', self._ss_utc_bound(filters['date_to'], next_day=True))
        if filters.get('user_ids'):
            domain &= Domain('user_id', 'in', [int(i) for i in filters['user_ids']])
        if filters.get('team_ids'):
            domain &= Domain('team_id', 'in', [int(i) for i in filters['team_ids']])
        if filters.get('source_ids'):
            domain &= Domain('source_id', 'in', [int(i) for i in filters['source_ids']])
        if filters.get('company_ids'):
            domain &= Domain('company_id', 'in', [int(i) for i in filters['company_ids']])
        if filters.get('statuses'):
            domain &= Domain('ss_lead_status', 'in', list(filters['statuses']))
        return domain

    @api.model
    def _ss_metric_domain(self, metric, filters):
        base = self._ss_base_domain(filters)
        lead_like = Domain('type', '=', 'lead') | Domain('date_conversion', '!=', False)
        metrics = {
            'total_leads': base & lead_like,
            'new_leads': base & Domain('type', '=', 'lead') & Domain('ss_lead_status', '=', 'new'),
            'working_leads': base & Domain('type', '=', 'lead') & Domain('ss_lead_status', '=', 'working'),
            'qualified_leads': base & lead_like & Domain('ss_lead_status', '=', 'qualified'),
            'converted_leads': base & Domain('date_conversion', '!=', False),
            'lost_leads': base & Domain('type', '=', 'lead') & Domain('won_status', '=', 'lost'),
            'opportunities': base & Domain('type', '=', 'opportunity'),
            'open_pipeline': base & Domain('type', '=', 'opportunity') & Domain('won_status', '=', 'pending'),
            'won': base & Domain('type', '=', 'opportunity') & Domain('won_status', '=', 'won'),
            'lost_opportunities': base & Domain('type', '=', 'opportunity') & Domain('won_status', '=', 'lost'),
            'lost': base & Domain('won_status', '=', 'lost'),
            'hot_leads': base & Domain('type', '=', 'lead') & Domain('ss_rating', '=', 'hot')
                & Domain('won_status', '=', 'pending'),
        }
        return metrics.get(metric, base)

    # ------------------------------------------------------------------
    # Public API (called from the OWL dashboard)
    # ------------------------------------------------------------------

    @api.model
    def get_filter_options(self):
        Lead = self.env['crm.lead']
        users = self.env['res.users'].search([
            ('share', '=', False),
            ('all_group_ids', 'in', self.env.ref('sales_team.group_sale_salesman').ids),
        ], order='name')
        return {
            'users': [{'id': u.id, 'name': u.display_name} for u in users],
            'teams': [{'id': t.id, 'name': t.display_name} for t in self.env['crm.team'].search([], order='sequence, name')],
            'sources': [{'id': s.id, 'name': s.display_name}
                        for s in self.env['utm.source'].search([], order='name', limit=300)],
            'companies': [{'id': c.id, 'name': c.display_name} for c in self.env.user.company_ids],
            'statuses': [{'id': key, 'name': label}
                         for key, label in Lead._fields['ss_lead_status']._description_selection(self.env)],
            'multi_company': len(self.env.user.company_ids) > 1,
            'currency_id': self.env.company.currency_id.id,
            'is_manager': self.env.user.has_group('sales_team.group_sale_salesman_all_leads'),
        }

    @api.model
    def get_dashboard_data(self, filters=None):
        filters = filters or {}
        Lead = self.env['crm.lead'].with_context(active_test=False)
        dom = lambda metric: self._ss_metric_domain(metric, filters)  # noqa: E731

        def count(metric):
            return Lead.search_count(dom(metric))

        def total(metric, field):
            return Lead._read_group(dom(metric), [], [f'{field}:sum'])[0][0] or 0.0

        total_leads = count('total_leads')
        converted = count('converted_leads')
        won_count = count('won')
        lost_opps = count('lost_opportunities')
        avg_score = Lead._read_group(dom('total_leads') & Domain('won_status', '=', 'pending'), [], ['ss_score:avg'])[0][0]

        kpis = {
            'total_leads': total_leads,
            'new_leads': count('new_leads'),
            'working_leads': count('working_leads'),
            'qualified_leads': count('qualified_leads'),
            'converted_leads': converted,
            'lost_leads': count('lost_leads'),
            'opportunities': count('opportunities'),
            'hot_leads': count('hot_leads'),
            'conversion_rate': round(100.0 * converted / total_leads, 1) if total_leads else 0.0,
            'expected_revenue': total('open_pipeline', 'expected_revenue'),
            'weighted_revenue': total('open_pipeline', 'prorated_revenue'),
            'won_revenue': total('won', 'expected_revenue'),
            'won_count': won_count,
            'win_rate': round(100.0 * won_count / (won_count + lost_opps), 1) if (won_count + lost_opps) else 0.0,
            'avg_score': round(avg_score or 0.0, 1),
        }

        undefined = _('Undefined')

        def by_m2o(metric, field, aggregates=('__count',), limit=None, order=None):
            rows = Lead._read_group(dom(metric), [field], list(aggregates), limit=limit, order=order)
            return [{
                'id': rec.id or False,
                'label': rec.display_name if rec else undefined,
                'values': list(values),
            } for rec, *values in rows]

        def by_selection(metric, field):
            labels = dict(Lead._fields[field]._description_selection(self.env))
            rows = dict(Lead._read_group(dom(metric), [field], ['__count']))
            return [{'id': key, 'label': labels[key], 'values': [rows.get(key, 0)]}
                    for key in labels if rows.get(key)]

        # pipeline by stage, ordered by stage sequence
        pipeline_rows = Lead._read_group(
            dom('open_pipeline'), ['stage_id'], ['__count', 'expected_revenue:sum', 'prorated_revenue:sum'])
        pipeline_rows.sort(key=lambda r: (r[0].sequence, r[0].id) if r[0] else (9999, 0))
        pipeline = [{
            'id': stage.id or False,
            'label': stage.display_name if stage else undefined,
            'values': [cnt, rev or 0.0, prorated or 0.0],
        } for stage, cnt, rev, prorated in pipeline_rows]

        charts = {
            'leads_by_source': by_m2o('total_leads', 'source_id', order='__count desc', limit=12),
            'leads_by_user': by_m2o('total_leads', 'user_id', order='__count desc', limit=12),
            'leads_by_status': by_selection('total_leads', 'ss_lead_status'),
            'leads_by_rating': by_selection('total_leads', 'ss_rating'),
            'pipeline_by_stage': pipeline,
            'lost_reasons': by_m2o('lost', 'lost_reason_id', order='__count desc', limit=10),
            'monthly': self._ss_monthly_series(Lead, filters),
            'revenue_forecast': self._ss_revenue_forecast(Lead, filters),
        }
        return {
            'kpis': kpis,
            'charts': charts,
            'leaderboard': self._ss_leaderboard(Lead, filters),
            'currency_id': self.env.company.currency_id.id,
        }

    @api.model
    def _ss_month_label(self, value):
        return format_date(self.env, value, date_format='MMM yyyy') if value else _('None')

    @api.model
    def _ss_monthly_series(self, Lead, filters):
        created = dict(Lead._read_group(self._ss_metric_domain('total_leads', filters),
                                        ['create_date:month'], ['__count']))
        converted_by_created = dict(Lead._read_group(self._ss_metric_domain('converted_leads', filters),
                                                     ['create_date:month'], ['__count']))
        converted_by_date = dict(Lead._read_group(self._ss_metric_domain('converted_leads', filters),
                                                  ['date_conversion:month'], ['__count']))
        months = sorted({m for m in list(created) + list(converted_by_date) if m})
        series = []
        for month in months[-24:]:
            created_count = created.get(month, 0)
            series.append({
                'label': self._ss_month_label(month),
                'created': created_count,
                'converted': converted_by_date.get(month, 0),
                'conversion_rate': round(100.0 * converted_by_created.get(month, 0) / created_count, 1)
                if created_count else 0.0,
            })
        return series

    @api.model
    def _ss_revenue_forecast(self, Lead, filters):
        rows = Lead._read_group(self._ss_metric_domain('open_pipeline', filters),
                                ['date_deadline:month'], ['expected_revenue:sum', 'prorated_revenue:sum'])
        rows.sort(key=lambda r: (r[0] is False, r[0] or fields.Date.today()))
        return [{
            'label': self._ss_month_label(month) if month else _('No closing date'),
            'expected': expected or 0.0,
            'weighted': weighted or 0.0,
        } for month, expected, weighted in rows[:18]]

    @api.model
    def _ss_leaderboard(self, Lead, filters):
        def per_user(metric, aggregates=('__count',)):
            return {user: values for user, *values in
                    Lead._read_group(self._ss_metric_domain(metric, filters), ['user_id'], list(aggregates))}

        leads = per_user('total_leads')
        converted = per_user('converted_leads')
        opps = per_user('opportunities')
        won = per_user('won', ('__count', 'expected_revenue:sum'))
        lost = per_user('lost_opportunities')
        pipeline = per_user('open_pipeline', ('__count', 'expected_revenue:sum'))
        users = set(leads) | set(opps) | set(won) | set(pipeline)
        board = []
        for user in users:
            n_leads = leads.get(user, [0])[0]
            n_conv = converted.get(user, [0])[0]
            n_won, won_rev = won.get(user, [0, 0.0])
            n_lost = lost.get(user, [0])[0]
            board.append({
                'id': user.id or False,
                'name': user.display_name if user else _('Unassigned'),
                'leads': n_leads,
                'converted': n_conv,
                'opportunities': opps.get(user, [0])[0],
                'won': n_won,
                'won_revenue': won_rev or 0.0,
                'lost': n_lost,
                'pipeline': (pipeline.get(user, [0, 0.0])[1]) or 0.0,
                'conversion_rate': round(100.0 * n_conv / n_leads, 1) if n_leads else 0.0,
                'win_rate': round(100.0 * n_won / (n_won + n_lost), 1) if (n_won + n_lost) else 0.0,
            })
        board.sort(key=lambda r: (-r['won_revenue'], -r['pipeline'], r['name']))
        return board[:25]

    @api.model
    def get_drilldown_action(self, metric, filters=None, group_field=None, group_value=None):
        """Return a window action listing the records behind a KPI / chart bar."""
        filters = filters or {}
        domain = self._ss_metric_domain(metric, filters)
        allowed_group_fields = {'source_id', 'user_id', 'ss_lead_status', 'ss_rating', 'stage_id', 'lost_reason_id'}
        if group_field in allowed_group_fields:
            domain &= Domain(group_field, '=', group_value or False)
        is_pipeline = metric in ('opportunities', 'open_pipeline', 'won', 'lost_opportunities')
        context = {'active_test': False, 'search_default_filter_none': 1}
        if is_pipeline:
            context['default_type'] = 'opportunity'
        return {
            'type': 'ir.actions.act_window',
            'name': _('CRM Dashboard: %s', dict(self._ss_metric_labels()).get(metric, _('Records'))),
            'res_model': 'crm.lead',
            'views': [(False, 'list'), (False, 'kanban'), (False, 'form')],
            'domain': list(domain),
            'context': context,
        }

    @api.model
    def _ss_metric_labels(self):
        return [
            ('total_leads', _('Total Leads')),
            ('new_leads', _('New Leads')),
            ('working_leads', _('Working Leads')),
            ('qualified_leads', _('Qualified Leads')),
            ('converted_leads', _('Converted Leads')),
            ('lost_leads', _('Lost Leads')),
            ('opportunities', _('Opportunities')),
            ('open_pipeline', _('Open Pipeline')),
            ('won', _('Won Opportunities')),
            ('lost_opportunities', _('Lost Opportunities')),
            ('lost', _('Lost')),
            ('hot_leads', _('Hot Leads')),
        ]


# keep selections importable for other modules / tests
__all__ = ['CrmSsDashboard', 'SS_LEAD_STATUS', 'SS_RATING']
