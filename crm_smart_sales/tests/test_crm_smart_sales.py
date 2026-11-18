from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, new_test_user, tagged
from odoo.tests.common import TransactionCase


class SsCrmCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, mail_create_nolog=True))
        # isolate tests from configuration / demo data
        cls.env['crm.ss.assignment.rule'].search([]).write({'active': False})
        cls.env['crm.stage'].search([]).write({'ss_activity_type_id': False})
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_bool('crm_smart_sales.assignment_on_create', True)
        icp.set_str('crm_smart_sales.duplicate_rule', 'alert')
        icp.set_int('crm_smart_sales.rating_hot_threshold', 70)
        icp.set_int('crm_smart_sales.rating_warm_threshold', 40)

        cls.company = cls.env.company
        cls.manager = new_test_user(cls.env, 'ss_manager', groups='sales_team.group_sale_manager')
        cls.user1 = new_test_user(cls.env, 'ss_user1', groups='sales_team.group_sale_salesman')
        cls.user2 = new_test_user(cls.env, 'ss_user2', groups='sales_team.group_sale_salesman')
        cls.team = cls.env['crm.team'].create({'name': 'SS Test Team'})
        cls.env['crm.team.member'].create([
            {'crm_team_id': cls.team.id, 'user_id': user.id} for user in (cls.user1, cls.user2)
        ])
        cls.stage_new, cls.stage_qualified = cls.env['crm.stage'].create([
            {'name': 'SS New', 'sequence': 1, 'team_ids': [(6, 0, cls.team.ids)]},
            {'name': 'SS Qualified', 'sequence': 2, 'team_ids': [(6, 0, cls.team.ids)]},
        ])
        cls.call_type = cls.env.ref('mail.mail_activity_data_call')
        cls.todo_type = cls.env.ref('mail.mail_activity_data_todo')

    def _lead(self, **vals):
        values = {'name': 'SS Lead', 'type': 'lead', 'user_id': self.user1.id, 'team_id': self.team.id}
        values.update(vals)
        return self.env['crm.lead'].create(values)


@tagged('post_install', '-at_install', 'crm_smart_sales')
class TestSsLeadStatus(SsCrmCommon):

    def test_status_lifecycle(self):
        lead = self._lead(email_from='status@example.com')
        self.assertEqual(lead.ss_lead_status, 'new')
        self.assertTrue(lead.ss_status_date)

        # rep interacts with the prospect -> Working
        lead.message_post(body='Hello', message_type='comment', subtype_xmlid='mail.mt_comment')
        self.assertEqual(lead.ss_lead_status, 'working')

        # internal notes do not change the status
        lead2 = self._lead(email_from='status2@example.com')
        lead2.message_post(body='internal', message_type='comment', subtype_xmlid='mail.mt_note')
        self.assertEqual(lead2.ss_lead_status, 'new')

        # Converted cannot be set by hand on a lead
        with self.assertRaises(UserError):
            lead.write({'ss_lead_status': 'converted'})

        lead.write({'ss_lead_status': 'qualified'})
        lead.convert_opportunity(self.env['res.partner'])
        self.assertEqual(lead.type, 'opportunity')
        self.assertEqual(lead.ss_lead_status, 'converted')
        self.assertTrue(lead.date_conversion)

    def test_lost_and_restore(self):
        lead = self._lead()
        lead.action_set_lost()
        self.assertEqual(lead.ss_lead_status, 'unqualified')
        self.assertFalse(lead.active)
        lead.action_restore()
        self.assertTrue(lead.active)
        self.assertEqual(lead.ss_lead_status, 'working')

    def test_opportunity_created_directly(self):
        opp = self._lead(type='opportunity')
        self.assertEqual(opp.ss_lead_status, 'converted')

    def test_kanban_group_expand(self):
        groups = self.env['crm.lead'].with_context(read_group_expand=True).formatted_read_group(
            [('id', '=', self._lead().id)], ['ss_lead_status'], ['__count'])
        statuses = [g['ss_lead_status'] for g in groups]
        self.assertIn('nurturing', statuses)
        self.assertNotIn('converted', statuses, "Empty Converted column must not be displayed")


@tagged('post_install', '-at_install', 'crm_smart_sales')
class TestSsScoring(SsCrmCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # deterministic rule set
        cls.env['crm.ss.scoring.rule'].search([]).write({'active': False})
        Rule = cls.env['crm.ss.scoring.rule']
        cls.rule_email = Rule.create({'name': 'Email', 'domain': "[('email_from', '!=', False)]", 'points': 20})
        cls.rule_revenue = Rule.create({'name': 'Revenue', 'domain': "[('expected_revenue', '>=', 10000)]", 'points': 30})
        cls.rule_activity = Rule.create({'name': 'Activity', 'domain': "[('activity_ids', '!=', False)]", 'points': 25})
        cls.rule_bad = Rule.create({'name': 'Blacklisted', 'domain': "[('is_blacklisted', '=', True)]", 'points': -50})

    def test_score_and_rating(self):
        lead = self._lead()
        self.assertEqual(lead.ss_score, 0)
        self.assertEqual(lead.ss_rating, 'cold')

        lead.email_from = 'score@example.com'
        self.assertEqual(lead.ss_score, 20)
        lead.expected_revenue = 15000
        self.assertEqual(lead.ss_score, 50)
        self.assertEqual(lead.ss_rating, 'warm')

        # activities are part of the engagement score
        activity = lead.activity_schedule(activity_type_id=self.todo_type.id, user_id=self.user1.id)
        self.assertEqual(lead.ss_score, 75)
        self.assertEqual(lead.ss_rating, 'hot')
        activity.unlink()
        self.assertEqual(lead.ss_score, 50)

        # score breakdown explains the score
        self.assertIn('Revenue', lead.ss_score_breakdown)
        self.assertIn('Email', lead.ss_score_breakdown)

    def test_score_clamped(self):
        self.env['mail.blacklist'].create({'email': 'bl@example.com'})
        lead = self._lead(email_from='bl@example.com')
        self.assertEqual(lead.ss_score, 0, "20 - 50 is clamped to 0")

    def test_rating_manual_override(self):
        lead = self._lead(email_from='manual@example.com')
        lead.ss_rating = 'hot'
        lead.name = 'Renamed'  # score unchanged: manual rating kept
        self.assertEqual(lead.ss_rating, 'hot')

    def test_invalid_rule_domain(self):
        with self.assertRaises(ValidationError):
            self.env['crm.ss.scoring.rule'].create({'name': 'bad', 'domain': "[('not_a_field', '=', 1)]", 'points': 5})

    def test_cron_recompute(self):
        lead = self._lead(email_from='cron@example.com')
        self.env.cr.execute("UPDATE crm_lead SET ss_score = 0 WHERE id = %s", [lead.id])
        lead.invalidate_recordset(['ss_score'])
        self.env['crm.lead']._ss_cron_recompute_scores()
        self.assertEqual(lead.ss_score, 20)


@tagged('post_install', '-at_install', 'crm_smart_sales')
class TestSsAssignment(SsCrmCommon):

    def test_round_robin_first_match(self):
        Rule = self.env['crm.ss.assignment.rule']
        big = Rule.create({
            'name': 'Big deals', 'sequence': 1, 'domain': "[('expected_revenue', '>=', 50000)]",
            'assign_to': 'user', 'user_id': self.manager.id,
            'activity_type_id': self.call_type.id, 'activity_summary': 'Call big deal',
        })
        rr = Rule.create({
            'name': 'Round robin', 'sequence': 2, 'domain': '[]',
            'assign_to': 'round_robin', 'user_ids': [(6, 0, (self.user1 | self.user2).ids)],
            'team_id': self.team.id,
        })
        leads = self.env['crm.lead'].create([
            {'name': f'RR {i}', 'type': 'lead', 'user_id': False} for i in range(4)
        ])
        self.assertEqual(leads.mapped('user_id'), self.user1 | self.user2)
        self.assertEqual([lead.user_id for lead in leads], [self.user1, self.user2, self.user1, self.user2])
        self.assertEqual(set(leads.mapped('ss_assignment_rule_id').ids), {rr.id})
        self.assertEqual(rr.assigned_count, 4)

        deal = self.env['crm.lead'].create({'name': 'Big', 'type': 'lead', 'user_id': False, 'expected_revenue': 90000})
        self.assertEqual(deal.user_id, self.manager)
        self.assertEqual(deal.ss_assignment_rule_id, big)
        self.assertEqual(deal.activity_ids.summary, 'Call big deal')

        # owned leads are not reassigned at creation...
        owned = self._lead(user_id=self.manager.id)
        self.assertEqual(owned.user_id, self.manager)
        # ...unless the rule says so
        rr.override_owner = True
        owned2 = self._lead(user_id=self.manager.id)
        self.assertIn(owned2.user_id, self.user1 | self.user2)

    def test_team_load(self):
        self.env['crm.ss.assignment.rule'].create({
            'name': 'Team load', 'domain': '[]', 'assign_to': 'team_load', 'team_id': self.team.id,
        })
        self.env['crm.lead'].create([
            {'name': 'busy', 'type': 'opportunity', 'user_id': self.user1.id, 'team_id': self.team.id}
            for _i in range(3)
        ])
        lead = self.env['crm.lead'].create({'name': 'to assign', 'type': 'lead', 'user_id': False})
        self.assertEqual(lead.user_id, self.user2, "Least loaded member gets the lead")

    def test_manual_run_and_setting(self):
        self.env['ir.config_parameter'].sudo().set_bool('crm_smart_sales.assignment_on_create', False)
        self.env['crm.ss.assignment.rule'].create({
            'name': 'All to user2', 'domain': '[]', 'assign_to': 'user', 'user_id': self.user2.id,
        })
        lead = self.env['crm.lead'].create({'name': 'manual', 'type': 'lead', 'user_id': False})
        self.assertFalse(lead.user_id, "Rules disabled on creation")
        lead.action_ss_run_assignment_rules()
        self.assertEqual(lead.user_id, self.user2)

    def test_rule_target_constraint(self):
        with self.assertRaises(ValidationError):
            self.env['crm.ss.assignment.rule'].create({'name': 'bad', 'domain': '[]', 'assign_to': 'round_robin'})


@tagged('post_install', '-at_install', 'crm_smart_sales')
class TestSsConversion(SsCrmCommon):

    def test_convert_create_account_contact_opportunity(self):
        lead = self._lead(name='Website enquiry', partner_name='SS Acme Corp', contact_name='John Doe',
                          email_from='john.doe@ss-acme.example.com', phone='+3222222222', function='CTO')
        wizard = Form(self.env['crm.ss.lead.convert'].with_context(active_model='crm.lead', active_id=lead.id))
        self.assertEqual(wizard.account_action, 'create')
        self.assertEqual(wizard.account_name, 'SS Acme Corp')
        self.assertEqual(wizard.contact_name, 'John Doe')
        wizard.opportunity_name = 'Acme - 50 desks'
        wizard.user_id = self.user2
        action = wizard.save().action_convert()

        self.assertEqual(lead.type, 'opportunity')
        self.assertEqual(lead.name, 'Acme - 50 desks')
        self.assertEqual(lead.ss_lead_status, 'converted')
        self.assertEqual(lead.user_id, self.user2)
        self.assertEqual(lead.partner_id.name, 'John Doe')
        self.assertEqual(lead.partner_id.parent_id.name, 'SS Acme Corp')
        self.assertFalse(lead.partner_id.parent_id.parent_id)
        self.assertEqual(lead.partner_id.function, 'CTO')
        self.assertEqual(action['res_id'], lead.id)

    def test_convert_existing_account_and_merge(self):
        company = self.env['res.partner'].create({'name': 'SS Existing Inc'})
        opp = self._lead(name='Existing deal', type='opportunity', partner_id=company.id,
                         email_from='buyer@existing.example.com', expected_revenue=1000)
        lead = self._lead(name='New request', partner_name='SS Existing Inc', contact_name='Buyer',
                          email_from='buyer@existing.example.com')
        wizard = Form(self.env['crm.ss.lead.convert'].with_context(active_model='crm.lead', active_id=lead.id))
        self.assertEqual(wizard.account_action, 'existing')
        self.assertEqual(wizard.account_id, company)
        self.assertIn(opp, wizard.suggested_opportunity_ids)
        wizard.opportunity_action = 'merge'
        wizard.merge_opportunity_id = opp
        wizard.save().action_convert()
        self.assertTrue(opp.exists())
        self.assertFalse(lead.exists(), "Merged lead is removed, its data moved to the opportunity")
        self.assertEqual(opp.partner_id.commercial_partner_id, company)
        contact = self.env['res.partner'].search([('name', '=', 'Buyer'), ('parent_id', '=', company.id)])
        self.assertTrue(contact, "Contact created under the existing account")

    def test_convert_only_leads(self):
        opp = self._lead(type='opportunity')
        with self.assertRaises(UserError):
            Form(self.env['crm.ss.lead.convert'].with_context(active_model='crm.lead', active_id=opp.id))


@tagged('post_install', '-at_install', 'crm_smart_sales')
class TestSsAutomation(SsCrmCommon):

    def test_stage_activity(self):
        self.stage_qualified.write({
            'ss_activity_type_id': self.call_type.id,
            'ss_activity_summary': 'Qualification call',
            'ss_activity_days': 2,
            'ss_guidance': '<p>Ask about budget</p>',
            'ss_key_field_ids': [(6, 0, self.env['ir.model.fields'].search(
                [('model', '=', 'crm.lead'), ('name', '=', 'expected_revenue')]).ids)],
        })
        opp = self._lead(type='opportunity', stage_id=self.stage_new.id, expected_revenue=500)
        self.assertFalse(opp.activity_ids)
        opp.stage_id = self.stage_qualified
        self.assertEqual(opp.activity_ids.summary, 'Qualification call')
        self.assertEqual(opp.activity_ids.user_id, self.user1)
        self.assertEqual(opp.activity_ids.date_deadline,
                         fields.Date.add(fields.Date.context_today(opp), days=2))
        # path assistant
        self.assertTrue(opp.ss_has_path_info)
        self.assertIn('Expected Revenue', opp.ss_key_fields_html)
        # no duplicate activity when coming back to the stage
        opp.stage_id = self.stage_new
        opp.stage_id = self.stage_qualified
        self.assertEqual(len(opp.activity_ids), 1)

    def test_followup_cron(self):
        lead = self._lead(email_from='stale@example.com')
        self.env.flush_all()
        self.env.cr.execute("UPDATE crm_lead SET write_date = %s WHERE id = %s",
                            [fields.Datetime.now() - timedelta(days=10), lead.id])
        lead.invalidate_recordset()
        self.env['crm.lead']._ss_cron_followup_stale_leads()
        self.assertEqual(lead.activity_ids.activity_type_id, self.todo_type)
        self.assertEqual(lead.activity_ids.user_id, self.user1)

    def test_log_call_and_timeline(self):
        lead = self._lead(email_from='call@example.com')
        wizard = self.env['crm.ss.log.call'].create({
            'lead_id': lead.id, 'summary': 'Discovery', 'outcome': 'connected',
            'comments': 'Interested in 20 desks', 'schedule_follow_up': True,
        })
        wizard.action_log_call()
        self.assertEqual(lead.ss_lead_status, 'working', "Logging a call moves New leads to Working")
        done = self.env['mail.activity'].with_context(active_test=False).search([
            ('res_model', '=', 'crm.lead'), ('res_id', '=', lead.id), ('active', '=', False)])
        self.assertEqual(done.activity_type_id, self.call_type)
        self.assertIn('Interested in 20 desks', done.feedback)
        self.assertEqual(len(lead.activity_ids), 1, "Follow-up call scheduled")

        lead.message_post(body='Internal remark', message_type='comment', subtype_xmlid='mail.mt_note')
        timeline = self.env['crm.lead'].ss_get_timeline(lead.id)
        self.assertEqual([i['kind'] for i in timeline['upcoming']], ['call'])
        kinds = {i['kind'] for i in timeline['past']}
        self.assertIn('call', kinds)
        self.assertIn('note', kinds)
        self.assertTrue(lead.ss_last_activity_date)

    def test_duplicate_rule(self):
        self._lead(email_from='dup@example.com')
        lead2 = self._lead(email_from='dup@example.com')
        self.assertIn('duplicate', lead2.ss_duplicate_message)
        self.env['ir.config_parameter'].sudo().set_str('crm_smart_sales.duplicate_rule', 'block')
        with self.assertRaises(ValidationError):
            self._lead(email_from='dup@example.com')

    def test_mass_update(self):
        leads = self._lead(name='m1') | self._lead(name='m2')
        Wizard = self.env['crm.ss.mass.update'].with_context(active_model='crm.lead', active_ids=leads.ids)
        Wizard.create({'operation': 'owner', 'user_id': self.user2.id}).action_apply()
        self.assertEqual(leads.user_id, self.user2)
        Wizard.create({'operation': 'status', 'ss_lead_status': 'nurturing'}).action_apply()
        self.assertEqual(set(leads.mapped('ss_lead_status')), {'nurturing'})
        Wizard.create({'operation': 'rating', 'ss_rating': 'hot'}).action_apply()
        self.assertEqual(set(leads.mapped('ss_rating')), {'hot'})


@tagged('post_install', '-at_install', 'crm_smart_sales')
class TestSsDashboard(SsCrmCommon):

    def test_dashboard_figures(self):
        Lead = self.env['crm.lead']
        Dashboard = self.env['crm.ss.dashboard']
        source = self.env['utm.source'].create({'name': 'SS Test Source'})
        leads = Lead.create([
            {'name': f'D{i}', 'type': 'lead', 'user_id': self.user1.id, 'source_id': source.id}
            for i in range(4)
        ])
        leads[0].convert_opportunity(self.env['res.partner'])
        leads[1].action_set_lost()
        won_stage = self.env['crm.stage'].search([('is_won', '=', True)], limit=1)
        opp = Lead.create({'name': 'Won deal', 'type': 'opportunity', 'user_id': self.user1.id,
                           'expected_revenue': 1000, 'source_id': source.id})
        opp.stage_id = won_stage
        Lead.create({'name': 'Open deal', 'type': 'opportunity', 'user_id': self.user1.id,
                     'expected_revenue': 5000, 'source_id': source.id})

        filters = {'user_ids': [self.user1.id], 'date_from': fields.Date.to_string(fields.Date.today())}
        data = Dashboard.get_dashboard_data(filters)
        kpis = data['kpis']
        self.assertEqual(kpis['total_leads'], 4)
        self.assertEqual(kpis['converted_leads'], 1)
        self.assertEqual(kpis['lost_leads'], 1)
        self.assertEqual(kpis['opportunities'], 3)
        self.assertEqual(kpis['conversion_rate'], 25.0)
        self.assertEqual(kpis['won_count'], 1)
        self.assertEqual(kpis['won_revenue'], 1000)
        self.assertEqual(kpis['expected_revenue'], 5000)
        self.assertEqual(data['charts']['leads_by_source'][0]['label'], 'SS Test Source')
        board = {row['id']: row for row in data['leaderboard']}
        self.assertEqual(board[self.user1.id]['won'], 1)
        self.assertEqual(board[self.user1.id]['leads'], 4)

        action = Dashboard.get_drilldown_action('converted_leads', filters)
        self.assertEqual(Lead.with_context(active_test=False).search(action['domain']), leads[0])

        # a salesman only sees his own documents
        data_user2 = Dashboard.with_user(self.user2).get_dashboard_data({'user_ids': [self.user1.id]})
        self.assertEqual(data_user2['kpis']['total_leads'], 0)
        options = Dashboard.with_user(self.user2).get_filter_options()
        self.assertFalse(options['is_manager'])


@tagged('post_install', '-at_install', 'crm_smart_sales')
class TestSsSecurity(SsCrmCommon):

    def test_rules_access(self):
        with self.assertRaises(AccessError):
            self.env['crm.ss.scoring.rule'].with_user(self.user1).create({'name': 'x', 'domain': '[]', 'points': 1})
        with self.assertRaises(AccessError):
            self.env['crm.ss.assignment.rule'].with_user(self.user1).create({
                'name': 'x', 'domain': '[]', 'assign_to': 'user', 'user_id': self.user1.id})
        rule = self.env['crm.ss.scoring.rule'].with_user(self.manager).create({'name': 'ok', 'domain': '[]', 'points': 1})
        self.assertTrue(rule.with_user(self.user1).read(['name']))

    def test_salesman_flows(self):
        """A salesman (own documents) can use the Smart Sales features on his leads."""
        lead = self._lead(email_from='own@example.com').with_user(self.user1)
        lead.write({'ss_lead_status': 'working'})
        self.env['crm.ss.log.call'].with_user(self.user1).create({'lead_id': lead.id, 'summary': 'call'}).action_log_call()
        self.env['crm.lead'].with_user(self.user1).ss_get_timeline(lead.id)
        wizard = Form(self.env['crm.ss.lead.convert'].with_user(self.user1).with_context(
            active_model='crm.lead', active_id=lead.id))
        wizard.account_action = 'none'
        wizard.save().action_convert()
        self.assertEqual(lead.type, 'opportunity')
        # other salesman's lead is not visible
        other = self._lead(user_id=self.user2.id)
        with self.assertRaises(AccessError):
            self.env['crm.lead'].with_user(self.user1).ss_get_timeline(other.id)
